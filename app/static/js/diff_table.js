/*
 * diff_table.js - builds the config diff table (Side by Side / Inline).
 *
 * The server (/diff_configs/) returns only line-level opcodes. Everything that
 * happens *inside* a changed line is calculated here, in the browser, with the
 * bundled difflib.js:
 *   - Side by Side: character-level highlighting (<del> on the old side,
 *     <ins> on the new side, unchanged text in <span>);
 *   - Inline: word-level highlighting.
 * Switching between the two views therefore never needs the server.
 *
 * Exposes the global `diffview` (diffview.buildView(params)).
 * The pure helpers (charDiffSegments / wordDiffSegments) do not touch the DOM
 * and are covered by tests/js/test_diff_table.test.js.
 */
(function (root) {
    "use strict";

    // Lines longer than this are NOT compared inside the line (certificates,
    // keys, huge ACLs, long encoded strings ...): they are shown as a plain
    // changed line. This keeps the DOM small and the browser responsive.
    const MAX_INLINE_DIFF_LENGTH = 10000;

    const TAB_AS_SPACES = "\u00a0\u00a0\u00a0\u00a0";
    const WORD_RULE = /(\s+|[\p{L}\p{N}_-]+|.)/u;

    // ------------------------------------------------------------------
    // Pure helpers: line -> highlighted segments
    // ------------------------------------------------------------------

    // [["equal","a"],["equal","b"],["delete","c"]] -> [["equal","ab"],["delete","c"]]
    function mergeRuns(segments) {
        const merged = [];
        segments.forEach(function (segment) {
            const last = merged[merged.length - 1];
            if (last && last[0] === segment[0]) {
                last[1] += segment[1];
            } else {
                merged.push([segment[0], segment[1]]);
            }
        });
        return merged;
    }

    /**
     * Compares two token arrays (characters or words).
     * The common prefix and suffix are cut off first (cheap, and it is what
     * makes long lines with a small change fast and precise); only the middle
     * part goes to difflib.SequenceMatcher.
     *
     * Returns {oldSide: [[kind, text], ...], newSide: [[kind, text], ...]},
     * where kind is "equal" | "delete" (old side only) | "insert" (new side only).
     */
    function compareTokens(a, b) {
        const minLength = Math.min(a.length, b.length);
        let start = 0;
        while (start < minLength && a[start] === b[start]) {
            start++;
        }
        let endA = a.length;
        let endB = b.length;
        while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) {
            endA--;
            endB--;
        }

        const oldSide = [];
        const newSide = [];

        if (start > 0) {
            const prefix = a.slice(0, start).join("");
            oldSide.push(["equal", prefix]);
            newSide.push(["equal", prefix]);
        }

        const midA = a.slice(start, endA);
        const midB = b.slice(start, endB);
        if (midA.length && midB.length) {
            const opcodes = new difflib.SequenceMatcher(midA, midB).get_opcodes();
            opcodes.forEach(function (code) {
                const tag = code[0];
                const oldText = midA.slice(code[1], code[2]).join("");
                const newText = midB.slice(code[3], code[4]).join("");
                if (tag === "equal") {
                    oldSide.push(["equal", oldText]);
                    newSide.push(["equal", newText]);
                    return;
                }
                if (oldText) oldSide.push(["delete", oldText]);
                if (newText) newSide.push(["insert", newText]);
            });
        } else {
            if (midA.length) oldSide.push(["delete", midA.join("")]);
            if (midB.length) newSide.push(["insert", midB.join("")]);
        }

        if (endA < a.length) {
            const suffix = a.slice(endA).join("");
            oldSide.push(["equal", suffix]);
            newSide.push(["equal", suffix]);
        }

        return { oldSide: mergeRuns(oldSide), newSide: mergeRuns(newSide) };
    }

    function tooLong(oldLine, newLine, maxLength) {
        const limit = maxLength || MAX_INLINE_DIFF_LENGTH;
        return oldLine.length > limit || newLine.length > limit;
    }

    // Character-level diff of two lines. Returns null if a line is too long.
    function charDiffSegments(oldLine, newLine, maxLength) {
        if (tooLong(oldLine, newLine, maxLength)) return null;
        // Array.from splits by code points, so emoji / surrogate pairs stay whole
        return compareTokens(Array.from(oldLine), Array.from(newLine));
    }

    // Word-level diff of two lines. Returns null if a line is too long.
    function wordDiffSegments(oldLine, newLine, maxLength) {
        if (tooLong(oldLine, newLine, maxLength)) return null;
        return compareTokens(
            oldLine.split(WORD_RULE).filter(Boolean),
            newLine.split(WORD_RULE).filter(Boolean)
        );
    }

    // ------------------------------------------------------------------
    // DOM helpers
    // ------------------------------------------------------------------

    function telt(name, text) {
        const e = document.createElement(name);
        e.appendChild(document.createTextNode(text));
        return e;
    }

    function ctelt(name, clazz, text) {
        const e = document.createElement(name);
        e.className = clazz;
        e.appendChild(document.createTextNode(text));
        return e;
    }

    function ctel(name, clazz, node) {
        const e = document.createElement(name);
        e.className = clazz;
        e.appendChild(node);
        return e;
    }

    function showTabs(text) {
        return (text || "").replace(/\t/g, TAB_AS_SPACES);
    }

    // [["equal","x"],["delete","y"]] -> <span><span class="equal">x</span><del class="table">y</del></span>
    function segmentsToNode(segments) {
        const node = document.createElement("span");
        segments.forEach(function (segment) {
            const kind = segment[0];
            const text = showTabs(segment[1]);
            if (kind === "delete") {
                node.appendChild(ctelt("del", "table", text));
            } else if (kind === "insert") {
                node.appendChild(ctelt("ins", "table", text));
            } else {
                node.appendChild(ctelt("span", "equal", text));
            }
        });
        return node;
    }

    // ------------------------------------------------------------------
    // Copy buttons (they copy the ORIGINAL text from the hidden textareas,
    // never the highlighted HTML)
    // ------------------------------------------------------------------

    function showSuccess(btn) {
        const originalHtml = btn.innerHTML;
        btn.innerHTML =
            '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="currentColor" class="bi bi-check-lg" viewBox="0 0 16 16"><path d="M12.736 3.97a.733.733 0 0 1 1.047 0c.286.289.29.756.01 1.05L7.88 12.01a.733.733 0 0 1-1.065.02L3.217 8.384a.757.757 0 0 1 0-1.06.733.733 0 0 1 1.047 0l3.052 3.093 5.4-6.425a.247.247 0 0 1 .02-.022Z"/></svg>';
        btn.classList.add("btn-success");
        setTimeout(function () {
            btn.innerHTML = originalHtml;
            btn.classList.remove("btn-success");
        }, 2000);
    }

    function fallbackCopy(text, btn) {
        const textarea = document.createElement("textarea");
        textarea.value = text;
        document.body.appendChild(textarea);
        textarea.select();
        let success = false;
        try {
            success = document.execCommand("copy");
        } catch (err) {
            console.error("Fallback copy failed:", err);
        }
        document.body.removeChild(textarea);
        if (success) {
            showSuccess(btn);
        } else {
            btn.classList.add("btn-outline-danger");
            setTimeout(function () {
                btn.classList.remove("btn-outline-danger");
            }, 2000);
        }
    }

    function setupCopyButton(btn, configType) {
        btn.onclick = function (e) {
            e.stopPropagation();
            const textarea = document.getElementById(
                configType === "prev" ? "previousConfig" : "lastConfig"
            );
            if (!textarea) return;
            const text = textarea.value;
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard
                    .writeText(text)
                    .then(function () {
                        showSuccess(btn);
                    })
                    .catch(function (err) {
                        console.error("Clipboard write failed:", err);
                        fallbackCopy(text, btn);
                    });
            } else {
                fallbackCopy(text, btn);
            }
        };
    }

    function createCopyButton(configType, title) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "btn btn-sm btn-outline-secondary ms-2 copy-diff-btn";
        btn.title = title;
        btn.innerHTML =
            '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="currentColor" class="bi bi-clipboard" viewBox="0 0 16 16"><path d="M4 1.5H3a2 2 0 0 0-2 2V14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V3.5a2 2 0 0 0-2-2h-1v1h1a1 1 0 0 1 1 1V14a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3.5a1 1 0 0 1 1-1h1v-1z"/><path d="M9.5 1a.5.5 0 0 1 .5.5v1a.5.5 0 0 1-.5.5h-3a.5.5 0 0 1-.5-.5v-1a.5.5 0 0 1 .5-.5h3zm-3-1A1.5 1.5 0 0 0 5 1.5v1A1.5 1.5 0 0 0 6.5 4h3A1.5 1.5 0 0 0 11 2.5v-1A1.5 1.5 0 0 0 9.5 0h-3z"/></svg>';
        setupCopyButton(btn, configType);
        return btn;
    }

    // ------------------------------------------------------------------
    // The table
    // ------------------------------------------------------------------

    /**
     * params:
     *   baseTextLines, newTextLines - arrays of lines
     *   opcodes                     - line-level opcodes from the server
     *   baseTextName, newTextName   - column titles
     *   contextSize                 - (optional) collapse long equal blocks
     *   viewType                    - 0: Side by Side, 1: Inline, 2: Inline with
     *                                 word-level highlighting
     *   maxInlineDiffLength         - (optional) override MAX_INLINE_DIFF_LENGTH
     */
    function buildView(params) {
        const baseTextLines = params.baseTextLines;
        const newTextLines = params.newTextLines;
        const opcodes = params.opcodes;
        const baseTextName = params.baseTextName ? params.baseTextName : "Base Text";
        const newTextName = params.newTextName ? params.newTextName : "New Text";
        const contextSize = params.contextSize;
        const inline = params.viewType == 0 || params.viewType >= 1 ? params.viewType : 0;
        const wordlevel = params.viewType > 1;
        const maxLength = params.maxInlineDiffLength;

        if (baseTextLines == null) throw "Cannot build diff view; baseTextLines is not defined.";
        if (newTextLines == null) throw "Cannot build diff view; newTextLines is not defined.";
        if (!opcodes) throw "Cannot build diff view; opcodes is not defined.";

        // ----- Header -----
        const thead = document.createElement("thead");
        const headRow = document.createElement("tr");
        thead.appendChild(headRow);

        // Title on the left, copy button(s) on the right
        function createAlignedHeaderCell(text, button) {
            const th = document.createElement("th");
            th.className = inline ? "row" : "col";
            const wrapper = document.createElement("div");
            wrapper.style.display = "flex";
            wrapper.style.justifyContent = "space-between";
            wrapper.style.alignItems = "center";
            wrapper.style.width = "100%";
            wrapper.appendChild(document.createTextNode(text));
            if (button) wrapper.appendChild(button);
            th.appendChild(wrapper);
            return th;
        }

        if (inline) {
            headRow.appendChild(document.createElement("th"));
            headRow.appendChild(document.createElement("th"));
            const btnGroup = document.createElement("span");
            btnGroup.className = "copy-buttons-group ms-2";
            btnGroup.appendChild(createCopyButton("prev", "Copy previous config"));
            btnGroup.appendChild(createCopyButton("last", "Copy last config"));
            headRow.appendChild(createAlignedHeaderCell(baseTextName + " vs. " + newTextName, btnGroup));
        } else {
            headRow.appendChild(document.createElement("th"));
            headRow.appendChild(
                createAlignedHeaderCell(baseTextName, createCopyButton("prev", "Copy previous config"))
            );
            headRow.appendChild(document.createElement("th"));
            headRow.appendChild(
                createAlignedHeaderCell(newTextName, createCopyButton("last", "Copy last config"))
            );
        }

        // ----- Row cells -----

        // Side by Side: line number + text of one side. A missing line
        // (tidx >= tend) gives an empty placeholder cell.
        function addCells(row, tidx, tend, textLines, change) {
            if (tidx < tend) {
                const text = textLines[tidx];
                row.appendChild(telt("th", (tidx + 1).toString()));
                row.appendChild(ctelt("td", change, text ? showTabs(text) : " "));
                return tidx + 1;
            }
            row.appendChild(document.createElement("th"));
            row.appendChild(ctelt("td", "empty", ""));
            return tidx;
        }

        // Side by Side: line number + already highlighted content of one side
        function addCellNode(row, tidx, node, change) {
            row.appendChild(telt("th", (tidx + 1).toString()));
            row.appendChild(ctel("td", change, node));
        }

        function addCellsInline(row, tidx, tidx2, textLines, change) {
            row.appendChild(telt("th", tidx == null ? "" : (tidx + 1).toString()));
            row.appendChild(telt("th", tidx2 == null ? "" : (tidx2 + 1).toString()));
            row.appendChild(ctelt("td", change, showTabs(textLines[tidx != null ? tidx : tidx2])));
        }

        function addCellsInlineNode(row, tidx, tidx2, node, change) {
            row.appendChild(telt("th", tidx == null ? "" : (tidx + 1).toString()));
            row.appendChild(telt("th", tidx2 == null ? "" : (tidx2 + 1).toString()));
            row.appendChild(ctel("td", change, node));
        }

        // ----- Rows -----
        const rows = [];
        let node2;
        let node3;

        for (let idx = 0; idx < opcodes.length; idx++) {
            const code = opcodes[idx];
            const change = code[0];
            let b = code[1];
            const be = code[2];
            let n = code[3];
            const ne = code[4];
            const rowcnt = Math.max(be - b, ne - n);
            const toprows = [];
            const botrows = [];

            for (let i = 0; i < rowcnt; i++) {
                // Collapse long "equal" blocks when contextSize is given
                if (
                    contextSize &&
                    opcodes.length > 1 &&
                    ((idx > 0 && i == contextSize) || (idx == 0 && i == 0)) &&
                    change == "equal"
                ) {
                    const jump = rowcnt - (idx == 0 ? 1 : 2) * contextSize;
                    if (jump > 1) {
                        toprows.push((node2 = document.createElement("tr")));
                        b += jump;
                        n += jump;
                        i += jump - 1;
                        node2.appendChild(telt("th", "..."));
                        if (!inline) node2.appendChild(ctelt("td", "skip", ""));
                        node2.appendChild(telt("th", "..."));
                        node2.appendChild(ctelt("td", "skip", ""));
                        if (idx + 1 == opcodes.length) {
                            break;
                        } else {
                            continue;
                        }
                    }
                }

                toprows.push((node2 = document.createElement("tr")));

                if (inline) {
                    if (change == "insert") {
                        addCellsInline(node2, null, n++, newTextLines, change);
                    } else if (change == "replace") {
                        // The old and the new block can have different length:
                        // the surplus lines are plain deleted / inserted lines
                        const hasOld = b < be;
                        const hasNew = n < ne;
                        let oldNode = null;
                        let newNode = null;
                        if (wordlevel && hasOld && hasNew) {
                            const pair = wordDiffSegments(baseTextLines[b], newTextLines[n], maxLength);
                            if (pair) {
                                oldNode = segmentsToNode(pair.oldSide);
                                newNode = segmentsToNode(pair.newSide);
                            }
                        }
                        if (hasOld) {
                            if (oldNode) addCellsInlineNode(node2, b++, null, oldNode, "delete");
                            else addCellsInline(node2, b++, null, baseTextLines, "delete");
                        } else {
                            toprows.pop();
                        }
                        if (hasNew) {
                            botrows.push((node3 = document.createElement("tr")));
                            if (newNode) addCellsInlineNode(node3, null, n++, newNode, "insert");
                            else addCellsInline(node3, null, n++, newTextLines, "insert");
                        }
                    } else if (change == "delete") {
                        addCellsInline(node2, b++, null, baseTextLines, change);
                    } else {
                        addCellsInline(node2, b++, n++, baseTextLines, change);
                    }
                } else if (change == "replace" && b < be && n < ne) {
                    // Side by Side, replaced line: compare the pair character by character
                    const pair = charDiffSegments(baseTextLines[b], newTextLines[n], maxLength);
                    if (pair) {
                        addCellNode(node2, b++, segmentsToNode(pair.oldSide), change);
                        addCellNode(node2, n++, segmentsToNode(pair.newSide), change);
                    } else {
                        // too long line: plain changed line
                        b = addCells(node2, b, be, baseTextLines, change);
                        n = addCells(node2, n, ne, newTextLines, change);
                    }
                } else {
                    // equal / insert / delete, or the surplus lines of a replace block
                    b = addCells(node2, b, be, baseTextLines, change);
                    n = addCells(node2, n, ne, newTextLines, change);
                }
            }
            toprows.forEach(function (row) {
                rows.push(row);
            });
            botrows.forEach(function (row) {
                rows.push(row);
            });
        }

        const tbody = document.createElement("tbody");
        rows.forEach(function (row) {
            tbody.appendChild(row);
        });
        tbody.classList.add("table-group-divider");

        const table = document.createElement("table");
        table.id = "diff_table";
        table.className = "table table-striped table-hover" + (inline ? " inlinediff" : "");
        table.appendChild(thead);
        table.appendChild(tbody);
        return table;
    }

    root.diffview = {
        buildView: buildView,
        charDiffSegments: charDiffSegments,
        wordDiffSegments: wordDiffSegments,
        MAX_INLINE_DIFF_LENGTH: MAX_INLINE_DIFF_LENGTH,
    };
})(typeof window !== "undefined" ? window : globalThis);
