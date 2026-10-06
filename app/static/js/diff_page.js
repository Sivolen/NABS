/*
 * diff_page.js - controller of the config compare page (templates/diff_page.html).
 *
 *  - configuration history timeline (choose the previous version);
 *  - loading of the previous config and of the line-level opcodes
 *    (/previous_config/ and /diff_configs/, both unchanged);
 *  - Side by Side / Inline switching (from the cached opcodes, no server call);
 *  - "Search in diff..." and "Show changed context" (the whole config block
 *    between delimiter lines when the vendor has them - see diff_context.js -
 *    otherwise N rows around every change).
 *
 * The table itself is built by diff_table.js (global `diffview`).
 * Page data comes from <script type="application/json" id="diff-page-data">.
 * The pure helpers are exposed as `diffPage` and covered by
 * tests/js/test_diff_page.test.js.
 */
(function (root) {
    "use strict";

    // Only the newest N versions get a time label under the dot, the rest are
    // narrower and without a label (their time is available in the tooltip).
    // The dot size is the same everywhere.
    const TIMELINE_LABELED_LIMIT = 200;
    // Rows shown around a changed row by "Show changed context" when there is no
    // block delimiter (the server overrides it with DIFF_CONTEXT_LINES from config.py)
    const CONTEXT_ROWS = 3;
    // Rows shown around a found row by "Search in diff..."
    const SEARCH_CONTEXT_ROWS = 5;
    // "Show changed context": a block longer than this is cut (server value MAX_BLOCK_CONTEXT_LINES)
    const MAX_BLOCK_LINES = 30;
    // rows revealed by one click on the "hidden lines" row
    const EXPAND_STEP = 25;
    const SEARCH_DEBOUNCE_MS = 150;

    // Configs.timestamp is stored as "YYYY-MM-DD HH:MM"
    const TIMESTAMP_RE = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})/;

    // ------------------------------------------------------------------
    // Pure helpers
    // ------------------------------------------------------------------

    function escapeHtml(text) {
        return String(text).replace(/[&<>"']/g, function (ch) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
        });
    }

    function escapeRegExp(text) {
        return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    }

    // "2026-09-29 14:32" -> {day, year, dateLabel: "29.09", time: "14:32", full: "29.09.2026 14:32"}
    // Returns null for a timestamp in an unknown format.
    function parseStamp(timestamp) {
        const m = TIMESTAMP_RE.exec(String(timestamp));
        if (!m) return null;
        return {
            day: m[1] + "-" + m[2] + "-" + m[3],
            year: m[1],
            dateLabel: m[3] + "." + m[2],
            time: m[4] + ":" + m[5],
            full: m[3] + "." + m[2] + "." + m[1] + " " + m[4] + ":" + m[5],
        };
    }

    /**
     * Groups the timestamps (newest first, as the server sends them) by day.
     * Duplicated timestamps are collapsed: both would open the same config.
     *
     * Returns [{day, label, year, showYear, items: [{ts, index, version, time, full, compact}]}]
     *   index   - position from the newest (0 = newest previous config)
     *   version - number from the oldest (1 = the oldest config)
     */
    function groupByDay(timestamps, labeledLimit) {
        const limit = labeledLimit === undefined ? TIMELINE_LABELED_LIMIT : labeledLimit;
        const seen = new Set();
        const groups = [];
        let index = 0;

        timestamps.forEach(function (ts) {
            if (seen.has(ts)) return;
            seen.add(ts);
            const info = parseStamp(ts) || {
                day: "unknown",
                year: "",
                dateLabel: "?",
                time: String(ts).slice(0, 8),
                full: String(ts),
            };
            let group = groups[groups.length - 1];
            if (!group || group.day !== info.day) {
                group = { day: info.day, label: info.dateLabel, year: info.year, showYear: false, items: [] };
                groups.push(group);
            }
            group.items.push({ ts: ts, index: index, time: info.time, full: info.full });
            index++;
        });

        const total = index;
        groups.forEach(function (group, i) {
            group.showYear = i === 0 || group.year !== groups[i - 1].year;
            group.items.forEach(function (item) {
                item.version = total - item.index;
                item.compact = item.index >= limit;
            });
        });
        return groups;
    }

    /**
     * Splits a config into lines exactly like Python's str.splitlines(), which the
     * server uses to calculate the opcodes - the line indexes must be identical.
     */
    function splitLines(text) {
        if (!text) return [];
        const lines = text.split(/\r\n|[\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029]/);
        if (lines[lines.length - 1] === "") lines.pop();
        return lines;
    }

    // A case-insensitive regexp; text that is not a valid regexp ("(", "[a") is
    // searched as a plain string instead of breaking the search.
    function buildSearchRegex(value) {
        try {
            return new RegExp(value, "i");
        } catch (e) {
            return new RegExp(escapeRegExp(value), "i");
        }
    }

    /**
     * New scrollLeft for the timeline so that a dot becomes visible, or null if the
     * dot is already fully visible (then the timeline must not move at all: a click
     * on a visible dot should not shift the scrollbar under the mouse).
     *   dotLeft    - dot position inside the scrollable content (not the viewport!)
     *   scrollLeft - current scroll position, viewWidth - visible width
     */
    function scrollTargetLeft(dotLeft, dotWidth, scrollLeft, viewWidth, margin) {
        const gap = margin === undefined ? 12 : margin;
        const inView = dotLeft >= scrollLeft + gap && dotLeft + dotWidth <= scrollLeft + viewWidth - gap;
        if (inView) return null;
        return Math.max(0, dotLeft - (viewWidth - dotWidth) / 2);
    }

    // Set of row indexes: every index of `indexes` plus `before`/`after` rows around it
    function expandWithContext(indexes, rowCount, before, after) {
        const visible = new Set();
        indexes.forEach(function (index) {
            const from = Math.max(0, index - before);
            const to = Math.min(rowCount - 1, index + after);
            for (let i = from; i <= to; i++) visible.add(i);
        });
        return visible;
    }

    // Valid DIFF_CONTEXT_LINES from the page data, else the default
    function contextRowsFrom(settings) {
        const value = settings && Number(settings.context_lines);
        return Number.isInteger(value) && value >= 0 ? value : CONTEXT_ROWS;
    }

    /**
     * Set of row indexes shown by the block context. A row is shown if its old
     * line is inside an old-config range OR its new line is inside a new-config
     * range. `rowLines` is [[oldIndex|null, newIndex|null], ...] (see tagRow in
     * diff_table.js). Rows without any line (the "..." separators) stay hidden.
     */
    function visibleRowsByBlocks(rowLines, context) {
        const visible = new Set();
        rowLines.forEach(function (pair, i) {
            const inOld = pair[0] !== null && context.oldMask[pair[0]] === 1;
            const inNew = pair[1] !== null && context.newMask[pair[1]] === 1;
            if (inOld || inNew) visible.add(i);
        });
        return visible;
    }

    // MAX_BLOCK_CONTEXT_LINES from the page data (0 = never cut), else the default
    function maxBlockLinesFrom(settings) {
        const value = settings && Number(settings.max_block_lines);
        return settings && settings.max_block_lines !== undefined && Number.isInteger(value) && value >= 0
            ? value
            : MAX_BLOCK_LINES;
    }

    // "1 hidden line" / "120 hidden lines"
    function hiddenLabel(count) {
        return count + (count === 1 ? " hidden line" : " hidden lines");
    }

    /**
     * Row indexes revealed by a click on a gap of hidden rows from..to (inclusive):
     *   "top"    - `step` rows right after the shown block above the gap
     *   "bottom" - `step` rows right before the shown block below the gap
     *   "all"    - the whole gap
     */
    function gapRowsToReveal(from, to, mode, step) {
        let first = from;
        let last = to;
        if (mode === "top") last = Math.min(to, from + step - 1);
        else if (mode === "bottom") first = Math.max(from, to - step + 1);
        const result = [];
        for (let i = first; i <= last; i++) result.push(i);
        return result;
    }

    // Identity of a table row that is the same in Side by Side and in Inline: the hidden rows
    // are unchanged rows, they carry both line numbers (see tagRow in diff_table.js)
    function rowKey(row) {
        const old = row.dataset.old === undefined ? "" : row.dataset.old;
        const now = row.dataset.new === undefined ? "" : row.dataset.new;
        return old + ":" + now;
    }

    // ------------------------------------------------------------------
    // Page
    // ------------------------------------------------------------------

    function init() {
        const dataElement = document.getElementById("diff-page-data");
        if (!dataElement) return;
        const pageData = JSON.parse(dataElement.textContent);

        const el = {
            output: document.getElementById("diffoutput"),
            previousConfig: document.getElementById("previousConfig"),
            lastConfig: document.getElementById("lastConfig"),
            search: document.getElementById("search-table"),
            contextBtn: document.getElementById("showContextBtn"),
            viewTypes: document.querySelectorAll('input[name="viewtype"]'),
            track: document.getElementById("timeline-track"),
            scroller: document.getElementById("timeline-scroller"),
            label: document.getElementById("previous_config_label"),
            count: document.getElementById("timeline-count"),
            newerBtn: document.getElementById("timeline-newer"),
            olderBtn: document.getElementById("timeline-older"),
        };
        if (!el.output || !el.previousConfig || !el.lastConfig || !el.track || !el.search) {
            console.error("diff_page: required elements are missing");
            return;
        }

        const state = {
            groups: groupByDay(pageData.timestamps || []),
            dots: [], // dot buttons, newest first
            selected: null, // selected timestamp
            opcodes: null, // line-level opcodes for the selected version
            blockContext: null, // block ranges/masks of the selected version, or null (N rows mode)
            contextOnly: false,
            revealed: new Set(), // rows opened by the user in the "hidden lines" rows (rowKey)
            requestSeq: 0,
            abort: null,
        };

        // ---------------- helpers ----------------
        function csrfHeaders() {
            const meta = document.querySelector('meta[name="csrf-token"]');
            const token = meta ? meta.getAttribute("content") : "";
            return {
                "Content-Type": "application/json",
                "X-CSRFToken": token,
                "X-CSRF-Token": token,
            };
        }

        function showToast(title, message) {
            const toastElement = document.getElementById("liveToast");
            if (!toastElement || !root.bootstrap) return;
            document.getElementById("toasts_strong").textContent = title;
            document.getElementById("number-of-changes").textContent = message;
            root.bootstrap.Toast.getOrCreateInstance(toastElement).show();
        }

        function currentViewType() {
            const inline = document.getElementById("inline");
            return inline && inline.checked ? 2 : 0;
        }

        function postJson(url, payload, signal) {
            return fetch(url, {
                method: "POST",
                headers: csrfHeaders(),
                body: JSON.stringify(payload),
                signal: signal,
            }).then(function (response) {
                if (!response.ok) throw new Error(response.status + " " + response.statusText);
                return response.json();
            });
        }

        // ---------------- timeline ----------------
        function tooltipHtml(item, total) {
            return (
                "<strong>Configuration</strong><br>" +
                escapeHtml(item.full) +
                "<br><small>Version " +
                item.version +
                " of " +
                total +
                "</small>"
            );
        }

        function renderTimeline() {
            const total = state.groups.reduce(function (sum, g) {
                return sum + g.items.length;
            }, 0);
            el.track.textContent = "";
            state.dots = [];
            if (el.count) el.count.textContent = total ? "(" + total + ")" : "";

            if (!total) {
                const empty = document.createElement("span");
                empty.className = "text-muted small";
                empty.textContent = "No previous configurations";
                el.track.appendChild(empty);
                return;
            }

            const fragment = document.createDocumentFragment();
            state.groups.forEach(function (group) {
                const dayNode = document.createElement("div");
                dayNode.className = "cfg-day";
                dayNode.setAttribute("role", "group");

                const label = document.createElement("div");
                label.className = "cfg-day__label";
                label.textContent = group.label;
                if (group.showYear && group.year) {
                    const year = document.createElement("span");
                    year.className = "cfg-day__year";
                    year.textContent = group.year;
                    label.appendChild(year);
                }
                dayNode.appendChild(label);

                const points = document.createElement("div");
                points.className = "cfg-day__points";
                group.items.forEach(function (item) {
                    const dot = document.createElement("button");
                    dot.type = "button";
                    dot.className = "cfg-dot" + (item.compact ? " is-compact" : "");
                    dot.setAttribute("role", "option");
                    dot.setAttribute("aria-selected", "false");
                    dot.setAttribute("aria-label", "Configuration " + item.full);
                    dot.tabIndex = -1;
                    dot.dataset.ts = item.ts;
                    dot.dataset.tooltip = tooltipHtml(item, total);

                    const mark = document.createElement("span");
                    mark.className = "cfg-dot__mark";
                    dot.appendChild(mark);
                    if (!item.compact) {
                        const time = document.createElement("span");
                        time.className = "cfg-dot__time";
                        time.textContent = item.time;
                        dot.appendChild(time);
                    }
                    points.appendChild(dot);
                    state.dots.push(dot);
                });
                dayNode.appendChild(points);
                fragment.appendChild(dayNode);
            });
            el.track.appendChild(fragment);
        }

        function dotIndex(ts) {
            return state.dots.findIndex(function (dot) {
                return dot.dataset.ts === ts;
            });
        }

        function markActiveDot(ts) {
            state.dots.forEach(function (dot) {
                const active = dot.dataset.ts === ts;
                dot.classList.toggle("is-active", active);
                dot.setAttribute("aria-selected", active ? "true" : "false");
                dot.tabIndex = active ? 0 : -1;
            });
            const activeIndex = dotIndex(ts);
            if (activeIndex < 0 && state.dots.length) state.dots[0].tabIndex = 0;
            if (el.olderBtn) el.olderBtn.disabled = activeIndex < 0 || activeIndex >= state.dots.length - 1;
            if (el.newerBtn) el.newerBtn.disabled = activeIndex <= 0;
        }

        function scrollToDot(dot) {
            if (!dot || !el.scroller) return;
            // offsetLeft is relative to the nearest positioned ancestor (.cfg-day__points),
            // not to the scroller, so the position is taken from the bounding rectangles
            const scrollerRect = el.scroller.getBoundingClientRect();
            const dotRect = dot.getBoundingClientRect();
            const dotLeft = dotRect.left - scrollerRect.left + el.scroller.scrollLeft;
            const target = scrollTargetLeft(dotLeft, dotRect.width, el.scroller.scrollLeft, el.scroller.clientWidth);
            if (target !== null) el.scroller.scrollTo({ left: target, behavior: "smooth" });
        }

        function initTimelineInteraction() {
            // click on a dot
            el.track.addEventListener("click", function (event) {
                const dot = event.target.closest(".cfg-dot");
                if (dot) selectVersion(dot.dataset.ts);
            });

            // arrows / Home / End move the focus (Enter / Space select)
            el.track.addEventListener("keydown", function (event) {
                const current = event.target.closest(".cfg-dot");
                if (!current) return;
                const index = state.dots.indexOf(current);
                let target = null;
                if (event.key === "ArrowRight") target = state.dots[index + 1];
                else if (event.key === "ArrowLeft") target = state.dots[index - 1];
                else if (event.key === "Home") target = state.dots[0];
                else if (event.key === "End") target = state.dots[state.dots.length - 1];
                if (!target) return;
                event.preventDefault();
                state.dots.forEach(function (dot) {
                    dot.tabIndex = dot === target ? 0 : -1;
                });
                target.focus();
                scrollToDot(target);
            });

            // tooltips are created lazily: there can be 500+ dots
            function showTooltip(event) {
                const dot = event.target.closest && event.target.closest(".cfg-dot");
                if (!dot || !root.bootstrap || root.bootstrap.Tooltip.getInstance(dot)) return;
                const tooltip = new root.bootstrap.Tooltip(dot, {
                    html: true,
                    title: dot.dataset.tooltip,
                    container: "body",
                    placement: "top",
                    trigger: "hover focus",
                });
                tooltip.show();
            }
            el.track.addEventListener("mouseover", showTooltip);
            el.track.addEventListener("focusin", showTooltip);

            // vertical mouse wheel scrolls the timeline sideways, unless it is at its edge
            el.scroller.addEventListener(
                "wheel",
                function (event) {
                    const s = el.scroller;
                    if (s.scrollWidth <= s.clientWidth) return;
                    if (Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return;
                    const atStart = s.scrollLeft <= 0 && event.deltaY < 0;
                    const atEnd = s.scrollLeft >= s.scrollWidth - s.clientWidth - 1 && event.deltaY > 0;
                    if (atStart || atEnd) return;
                    event.preventDefault();
                    s.scrollLeft += event.deltaY;
                },
                { passive: false }
            );

            // newer (left) / older (right) buttons
            function step(delta) {
                const index = dotIndex(state.selected);
                const target = state.dots[index + delta];
                if (target) selectVersion(target.dataset.ts);
            }
            if (el.newerBtn) el.newerBtn.addEventListener("click", function () { step(-1); });
            if (el.olderBtn) el.olderBtn.addEventListener("click", function () { step(1); });
        }

        // ---------------- loading & rendering ----------------
        function selectVersion(ts) {
            if (!ts || ts === state.selected) return;
            state.selected = ts;
            markActiveDot(ts);
            scrollToDot(state.dots[dotIndex(ts)]);

            const info = parseStamp(ts);
            if (el.label) el.label.textContent = "Previous config: " + (info ? info.full : ts);

            el.search.value = "";
            loadVersion(ts);
        }

        function loadVersion(ts) {
            // a newer click cancels the previous unfinished requests
            if (state.abort) state.abort.abort();
            state.abort = new AbortController();
            const seq = ++state.requestSeq;
            const signal = state.abort.signal;
            const payload = { device_id: pageData.device_id, date: ts };

            state.opcodes = null;
            state.blockContext = null;
            state.revealed.clear();
            el.previousConfig.value = "";
            el.output.innerHTML = '<div class="spinner-border text-primary" role="status"></div>';

            Promise.all([
                postJson("/previous_config/", payload, signal),
                postJson("/diff_configs/", payload, signal),
            ])
                .then(function (results) {
                    if (seq !== state.requestSeq) return;
                    const previous = results[0];
                    const diff = results[1];
                    if (previous.status === "none" || diff.status !== "ok") {
                        el.output.textContent = "";
                        showToast("Config", "none");
                        return;
                    }
                    el.previousConfig.value = previous.previous_config_file;
                    state.opcodes = refineOpcodes(diff.opcodes);
                    state.blockContext = resolveBlockContext();
                    renderDiff();
                })
                .catch(function (error) {
                    if (error.name === "AbortError" || seq !== state.requestSeq) return;
                    console.error("Diff request failed:", error);
                    el.output.innerHTML = "";
                    const alert = document.createElement("div");
                    alert.className = "alert alert-danger";
                    alert.textContent = "Error: " + error.message;
                    el.output.appendChild(alert);
                });
        }

        // Pairs the lines of every replace block by similarity (diff_align.js), so a line that
        // only moved down is not compared with an unrelated new line. On any problem the
        // server opcodes are used as they are.
        function refineOpcodes(opcodes) {
            if (!root.diffAlign) return opcodes;
            try {
                return root.diffAlign.refineOpcodes(
                    opcodes,
                    splitLines(el.previousConfig.value),
                    splitLines(el.lastConfig.value)
                );
            } catch (error) {
                console.error("Line alignment failed, using the server diff:", error);
                return opcodes;
            }
        }

        // Block ranges for "Show changed context"; null = use the N rows mode.
        // Any error here must never break the page: fall back to N rows.
        function resolveBlockContext() {
            const settings = pageData.context;
            if (!settings || !settings.enabled || !root.diffContext) return null;
            try {
                return root.diffContext.resolveChangedContext(
                    state.opcodes,
                    splitLines(el.previousConfig.value),
                    splitLines(el.lastConfig.value),
                    {
                        delimiters: settings.delimiters,
                        contextLines: contextRowsFrom(settings),
                        maxBlockLines: maxBlockLinesFrom(settings),
                    }
                );
            } catch (error) {
                console.error("Block context failed, using N rows:", error);
                return null;
            }
        }

        // Builds the table from the cached opcodes - used for a new version and for
        // Side by Side <-> Inline switching (no request to the server)
        function renderDiff() {
            if (!state.opcodes) return;
            const table = diffview.buildView({
                baseTextLines: splitLines(el.previousConfig.value),
                newTextLines: splitLines(el.lastConfig.value),
                opcodes: state.opcodes,
                baseTextName: "Previous config",
                newTextName: "Last config",
                viewType: currentViewType(),
            });
            el.output.textContent = "";
            el.output.appendChild(table);
            applyRowVisibility();
        }

        // ---------------- search & changed context ----------------
        function rowText(row) {
            // textContent of the text cells only (not the line numbers): it also
            // finds text that is split between <ins>/<del>/<span> nodes
            let text = "";
            for (let i = 0; i < row.cells.length; i++) {
                if (row.cells[i].tagName === "TD") text += row.cells[i].textContent + "\n";
            }
            return text;
        }

        // The row that stands for skipped rows: "⋮ 120 hidden lines" with buttons that
        // show 25 more rows from the top / bottom of the gap or all of it. `kind` tells
        // which neighbours the gap has: "head" (shown block only below), "tail" (only
        // above) or "mid" (between two shown blocks).
        // It is created by applyRowVisibility and never takes part in search / context
        // calculations.
        function createGapRow(columns, rows, from, to, kind) {
            const count = to - from + 1;
            const row = document.createElement("tr");
            row.className = "ctx-sep";
            const cell = document.createElement("td");
            cell.colSpan = columns;
            cell.className = "ctx-sep__cell";

            const label = document.createElement("span");
            label.className = "ctx-sep__label";
            label.textContent = "\u22EE  " + hiddenLabel(count);
            cell.appendChild(label);

            function addButton(text, title, mode) {
                const button = document.createElement("button");
                button.type = "button";
                button.className = "ctx-sep__btn";
                button.textContent = text;
                button.title = title;
                button.addEventListener("click", function () {
                    gapRowsToReveal(from, to, mode, EXPAND_STEP).forEach(function (i) {
                        state.revealed.add(rowKey(rows[i]));
                    });
                    applyRowVisibility();
                });
                cell.appendChild(button);
            }

            if (count > EXPAND_STEP) {
                const step = String(EXPAND_STEP);
                if (kind !== "head") addButton("\u2193 " + step, "Show the next " + step + " lines", "top");
                if (kind !== "tail") addButton("\u2191 " + step, "Show the previous " + step + " lines", "bottom");
            }
            addButton("all", "Show all " + count + " hidden lines", "all");

            row.appendChild(cell);
            return row;
        }

        function applyRowVisibility() {
            const table = document.getElementById("diff_table");
            if (!table || !table.tBodies.length) return;
            const body = table.tBodies[0];
            // remove the separators of the previous pass first
            Array.from(body.querySelectorAll("tr.ctx-sep")).forEach(function (row) {
                row.remove();
            });
            const rows = Array.from(body.rows);
            const query = el.search.value;
            let visible = null; // null = show everything

            if (query) {
                const regexp = buildSearchRegex(query);
                const found = [];
                rows.forEach(function (row, i) {
                    if (regexp.test(rowText(row))) found.push(i);
                });
                visible = expandWithContext(found, rows.length, SEARCH_CONTEXT_ROWS, SEARCH_CONTEXT_ROWS);
            } else if (state.contextOnly) {
                const changed = [];
                rows.forEach(function (row, i) {
                    if (row.querySelector("td.replace, td.insert, td.empty, td.delete")) changed.push(i);
                });
                // nothing changed: leave the full table
                if (changed.length) {
                    if (state.blockContext) {
                        const rowLines = rows.map(function (row) {
                            return [
                                row.dataset.old === undefined ? null : Number(row.dataset.old),
                                row.dataset.new === undefined ? null : Number(row.dataset.new),
                            ];
                        });
                        visible = visibleRowsByBlocks(rowLines, state.blockContext);
                    } else {
                        const around = contextRowsFrom(pageData.context);
                        visible = expandWithContext(changed, rows.length, around, around);
                    }
                    // rows the user opened with the buttons of a "hidden lines" row
                    if (state.revealed.size) {
                        rows.forEach(function (row, i) {
                            if (state.revealed.has(rowKey(row))) visible.add(i);
                        });
                    }
                }
            }

            const columns = table.tHead && table.tHead.rows.length ? table.tHead.rows[0].cells.length : 4;
            const showGaps = state.contextOnly && !query && visible !== null;
            let lastShown = -1;
            rows.forEach(function (row, i) {
                const shown = visible === null || visible.has(i);
                row.style.display = shown ? "" : "none";
                if (!shown) return;
                if (showGaps && lastShown + 1 < i) {
                    const kind = lastShown === -1 ? "head" : "mid";
                    body.insertBefore(createGapRow(columns, rows, lastShown + 1, i - 1, kind), row);
                }
                lastShown = i;
            });
            // rows hidden after the last shown one
            if (showGaps && lastShown !== -1 && lastShown < rows.length - 1) {
                body.appendChild(createGapRow(columns, rows, lastShown + 1, rows.length - 1, "tail"));
            }
        }

        function initControls() {
            // Side by Side / Inline
            Array.prototype.forEach.call(el.viewTypes, function (radio) {
                radio.addEventListener("change", renderDiff);
            });

            // search (debounced: big configs have thousands of rows)
            let searchTimer = null;
            el.search.addEventListener("input", function () {
                clearTimeout(searchTimer);
                searchTimer = setTimeout(applyRowVisibility, SEARCH_DEBOUNCE_MS);
            });

            // Show changed context (toggle)
            if (el.contextBtn) {
                el.contextBtn.addEventListener("click", function () {
                    state.contextOnly = !state.contextOnly;
                    state.revealed.clear();
                    el.contextBtn.classList.toggle("active", state.contextOnly);
                    el.contextBtn.setAttribute("aria-pressed", state.contextOnly ? "true" : "false");
                    const text = el.contextBtn.querySelector(".js--context-text");
                    if (text) text.textContent = state.contextOnly ? "Show all lines" : "Show changed context";
                    applyRowVisibility();
                });
            }
        }

        // ---------------- start ----------------
        renderTimeline();
        initTimelineInteraction();
        initControls();
        markActiveDot(null);
        if (state.dots.length) selectVersion(state.dots[0].dataset.ts);
    }

    root.diffPage = {
        parseStamp: parseStamp,
        groupByDay: groupByDay,
        splitLines: splitLines,
        buildSearchRegex: buildSearchRegex,
        expandWithContext: expandWithContext,
        contextRowsFrom: contextRowsFrom,
        visibleRowsByBlocks: visibleRowsByBlocks,
        maxBlockLinesFrom: maxBlockLinesFrom,
        hiddenLabel: hiddenLabel,
        gapRowsToReveal: gapRowsToReveal,
        scrollTargetLeft: scrollTargetLeft,
        TIMELINE_LABELED_LIMIT: TIMELINE_LABELED_LIMIT,
    };

    if (typeof document !== "undefined") {
        if (document.readyState === "loading") {
            document.addEventListener("DOMContentLoaded", init);
        } else {
            init();
        }
    }
})(typeof window !== "undefined" ? window : globalThis);
