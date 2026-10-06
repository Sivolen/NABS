/*
 * diff_context.js - "Show changed context" by logical config blocks.
 *
 * Network configs are split into blocks by delimiter lines ("#" for Huawei,
 * "!" for Cisco ...). Instead of a fixed number of lines around a change, the
 * whole block that contains the change is shown (delimiters included).
 *
 * Pipeline (the backend diff is not touched):
 *   line-level opcodes  ->  changed lines (per side)  ->  block ranges (per side)
 *   ->  masks  ->  the renderer shows the rows whose old/new line is in a range.
 *
 * A very long block (more than maxBlockLines) is not shown completely: it is cut to
 * the opening delimiter, the block header (its first line), the parent lines of the
 * change (by indentation), a window of N lines around the change and the closing
 * delimiter. The renderer draws a clickable "hidden lines" row for what is skipped.
 *
 * Old and new configs are resolved separately: a changed block is shown in both
 * versions, an added block only in the new one, a deleted block only in the old one.
 *
 * Everything here is pure (no DOM); tests: tests/js/test_diff_context.test.js
 * Exposes the global `diffContext` (and module.exports under Node).
 */
(function (root) {
    "use strict";

    // ["#", " ## ", "", 5] -> ["#", "##"]; a plain string is accepted as well
    function normalizeDelimiters(value) {
        const list = typeof value === "string" ? [value] : Array.isArray(value) ? value : [];
        const result = [];
        list.forEach(function (item) {
            if (typeof item !== "string") return;
            const trimmed = item.trim();
            if (trimmed && result.indexOf(trimmed) === -1) result.push(trimmed);
        });
        return result;
    }

    /**
     * Indexes of the delimiter lines, ascending. ONE pass over the config:
     * a line is a delimiter only if line.trim() equals a delimiter exactly.
     */
    function findDelimiterIndexes(lines, delimiters) {
        const wanted = new Set(normalizeDelimiters(delimiters));
        const indexes = [];
        if (!wanted.size) return indexes;
        for (let i = 0; i < lines.length; i++) {
            if (wanted.has(lines[i].trim())) indexes.push(i);
        }
        return indexes;
    }

    // index of the first element of the sorted array that is >= value (binary search)
    function lowerBound(sorted, value) {
        let lo = 0;
        let hi = sorted.length;
        while (lo < hi) {
            const mid = (lo + hi) >> 1;
            if (sorted[mid] < value) lo = mid + 1;
            else hi = mid;
        }
        return lo;
    }

    // nearest delimiter strictly above the line, or -1
    function delimiterAbove(indexes, line) {
        const pos = lowerBound(indexes, line); // first delimiter >= line
        return pos > 0 ? indexes[pos - 1] : -1;
    }

    // nearest delimiter strictly below the line, or -1
    function delimiterBelow(indexes, line) {
        const pos = lowerBound(indexes, line + 1); // first delimiter > line
        return pos < indexes.length ? indexes[pos] : -1;
    }

    /**
     * Sorts inclusive [start, end] ranges and merges the ones that overlap
     * (10-20 + 15-25 -> 10-25) or touch (10-20 + 21-30 -> 10-30).
     * `slack` also merges ranges with up to `slack` skipped lines between them
     * (a "1 hidden line" gap takes as much room as the line itself).
     */
    function mergeRanges(ranges, slack) {
        const join = slack > 0 ? slack | 0 : 0;
        const sorted = ranges
            .map(function (r) {
                return [r[0], r[1]];
            })
            .sort(function (a, b) {
                return a[0] - b[0] || a[1] - b[1];
            });
        const merged = [];
        sorted.forEach(function (range) {
            const last = merged[merged.length - 1];
            if (last && range[0] <= last[1] + 1 + join) {
                if (range[1] > last[1]) last[1] = range[1];
            } else {
                merged.push(range);
            }
        });
        return merged;
    }

    // leading whitespace of a line; -1 for a blank line (blank lines carry no structure)
    function indentOf(line) {
        if (line.trim() === "") return -1;
        return /^[ \t]*/.exec(line)[0].length;
    }

    // how far up the parent lines of one change are searched
    const PARENT_SCAN_LIMIT = 500;
    // skipped gaps of at most this many lines between the pieces of a cut block are shown
    const PIECE_JOIN_GAP = 1;

    /**
     * Context ranges of one config.
     *   lines         - config lines
     *   changedLines  - indexes of the changed lines
     *   delimiters    - delimiter lines of the vendor
     *   contextLines  - N: window around a change for a side without a delimiter
     *                   and inside a cut block
     *   options.maxBlockLines     - blocks longer than this are cut (0 / absent = never)
     *   options.delimiterIndexes  - precomputed findDelimiterIndexes(), optional
     *
     * 1. Changed line is an ordinary line: from the nearest delimiter above to the
     *    nearest delimiter below (both included).
     * 2. Changed line IS a delimiter (added / removed / replaced separator - in
     *    this version of the config): it is the border of two blocks, so both
     *    neighbouring blocks are taken: previous delimiter .. next delimiter.
     *    The nearest delimiters are searched strictly above / below the line,
     *    so the changed delimiter itself lies inside the range.
     * 3. The range is longer than maxBlockLines: it is cut to the pieces
     *    - opening delimiter and the block header (first non-blank line after it),
     *    - parent lines of the change (lines with a smaller indent going up),
     *    - N lines around the change,
     *    - closing delimiter.
     *    A block where many lines changed is still shown completely, because the
     *    windows of the neighbouring changes join.
     * If a delimiter is missing on one side, that side is N lines (or the
     * config edge). If the config has no delimiter at all, hasDelimiters is
     * false and the caller should use the plain N-lines mode.
     *
     * Returns {ranges: [[start, end], ...] merged and sorted, hasDelimiters}
     */
    function blockRanges(lines, changedLines, delimiters, contextLines, options) {
        const opts = options || {};
        const count = lines.length;
        const around = Math.max(0, contextLines | 0);
        const maxLines = opts.maxBlockLines > 0 ? opts.maxBlockLines | 0 : 0;
        const indexes = opts.delimiterIndexes || findDelimiterIndexes(lines, delimiters);
        const wholeBlocks = [];
        const pieces = [];
        let indents = null; // lazy cache: only a cut block needs the indentation

        function indentAt(i) {
            if (indents === null) indents = new Int32Array(count).fill(-2);
            if (indents[i] === -2) indents[i] = indentOf(lines[i]);
            return indents[i];
        }

        // parent lines of `line` by indentation, nearest first; never above `floor`
        function parentLines(line, floor) {
            const parents = [];
            let current = indentAt(line);
            if (current <= 0) return parents;
            const stop = Math.max(floor, line - PARENT_SCAN_LIMIT);
            for (let j = line - 1; j >= stop && current > 0; j--) {
                const indent = indentAt(j);
                if (indent >= 0 && indent < current) {
                    parents.push(j);
                    current = indent;
                }
            }
            return parents;
        }

        // The previous cut change: a run of consecutive changed lines (a whole new
        // section) must not search the parents again for every line.
        let last = null; // {line, above, below, parents}

        changedLines.forEach(function (line) {
            if (line < 0 || line >= count) return;
            // Ordinary line: its own block. Changed delimiter: both neighbouring
            // blocks. One formula covers both, because the delimiters are searched
            // strictly above / below `line` - a delimiter on `line` is never its own
            // border (locked by the "changed delimiter" tests).
            const above = delimiterAbove(indexes, line);
            const below = delimiterBelow(indexes, line);
            const start = above >= 0 ? above : Math.max(0, line - around);
            const end = below >= 0 ? below : Math.min(count - 1, line + around);

            if (!maxLines || end - start + 1 <= maxLines) {
                wholeBlocks.push([start, end]);
                return;
            }

            // the block is too long: cut it
            const window = [Math.max(start, line - around), Math.min(end, line + around)];

            if (last && last.line === line - 1 && last.above === above && last.below === below) {
                // the line right after the previous change, same block: same or deeper
                // indent means the parents are the previous ones (+ the previous line),
                // and all of them are already among the pieces
                const indent = indentAt(line);
                const lastIndent = indentAt(last.line);
                if (lastIndent >= 0 && indent >= lastIndent) {
                    pieces.push(window);
                    last = {
                        line: line,
                        above: above,
                        below: below,
                        parents: indent === lastIndent ? last.parents : [last.line].concat(last.parents),
                    };
                    return;
                }
            }

            const floor = above >= 0 ? above + 1 : 0;
            if (above >= 0) {
                pieces.push([above, above]);
                let header = above + 1;
                while (header < line && lines[header].trim() === "") header++;
                if (header < count) pieces.push([header, header]);
            }
            if (below >= 0) pieces.push([below, below]);
            const parents = parentLines(line, floor);
            parents.forEach(function (parent) {
                pieces.push([parent, parent]);
            });
            pieces.push(window);
            last = { line: line, above: above, below: below, parents: parents };
        });

        return {
            ranges: mergeRanges(wholeBlocks.concat(mergeRanges(pieces, PIECE_JOIN_GAP))),
            hasDelimiters: indexes.length > 0,
        };
    }

    /**
     * Changed line indexes of both sides from line-level opcodes
     * ([tag, i1, i2, j1, j2] - the difflib / SequenceMatcher format).
     */
    function changedLinesFromOpcodes(opcodes) {
        const oldLines = [];
        const newLines = [];
        (opcodes || []).forEach(function (code) {
            if (code[0] === "equal") return;
            for (let i = code[1]; i < code[2]; i++) oldLines.push(i);
            for (let j = code[3]; j < code[4]; j++) newLines.push(j);
        });
        return { old: oldLines, new: newLines };
    }

    // ranges -> Uint8Array mask (1 = the line is shown): O(lines), O(1) lookup per row
    function rangesToMask(ranges, length) {
        const mask = new Uint8Array(length);
        ranges.forEach(function (range) {
            const end = Math.min(range[1], length - 1);
            for (let i = Math.max(0, range[0]); i <= end; i++) mask[i] = 1;
        });
        return mask;
    }

    /**
     * Main entry point.
     *   opcodes                 - line-level opcodes from the server
     *   oldLines, newLines      - the two configs split into lines
     *   options.delimiters      - delimiter lines of the device vendor
     *   options.contextLines    - N for the fallback and for a window in a cut block
     *   options.maxBlockLines   - blocks longer than this are cut (0 / absent = never)
     *
     * Returns {oldRanges, newRanges, oldMask, newMask}, or null when the block
     * mode is not applicable (no delimiters configured / none present in either
     * config / nothing changed): the caller must then use the N-lines mode.
     */
    function resolveChangedContext(opcodes, oldLines, newLines, options) {
        const opts = options || {};
        const delimiters = normalizeDelimiters(opts.delimiters);
        if (!delimiters.length) return null;

        const changed = changedLinesFromOpcodes(opcodes);
        if (!changed.old.length && !changed.new.length) return null;

        const contextLines = opts.contextLines === undefined ? 3 : opts.contextLines;
        const rangeOptions = { maxBlockLines: opts.maxBlockLines };
        const oldResult = blockRanges(oldLines, changed.old, delimiters, contextLines, rangeOptions);
        const newResult = blockRanges(newLines, changed.new, delimiters, contextLines, rangeOptions);
        if (!oldResult.hasDelimiters && !newResult.hasDelimiters) return null;

        return {
            oldRanges: oldResult.ranges,
            newRanges: newResult.ranges,
            oldMask: rangesToMask(oldResult.ranges, oldLines.length),
            newMask: rangesToMask(newResult.ranges, newLines.length),
        };
    }

    const api = {
        normalizeDelimiters: normalizeDelimiters,
        findDelimiterIndexes: findDelimiterIndexes,
        delimiterAbove: delimiterAbove,
        delimiterBelow: delimiterBelow,
        mergeRanges: mergeRanges,
        blockRanges: blockRanges,
        changedLinesFromOpcodes: changedLinesFromOpcodes,
        rangesToMask: rangesToMask,
        resolveChangedContext: resolveChangedContext,
    };

    root.diffContext = api;
    if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
