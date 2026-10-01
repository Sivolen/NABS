/*
 * diff_align.js - pairs the lines of a "replace" block by similarity.
 *
 * The line-level diff says "these old lines became those new lines" for a whole
 * block, but not which old line became which new one. The table used to pair
 * them by position: when a command was added above a changed line, every line
 * of the block was compared with its neighbour (storm-control ... against
 * port-security ...) and the character-level highlight showed noise.
 *
 * refineOpcodes() splits every replace block into
 *   equal    - identical lines (a block that only shifted down)
 *   replace  - two similar lines, shown with a character/word-level diff
 *   insert / delete - a line that has no similar counterpart
 *   replace + "plain" (6th element) - unrelated old and new lines that stay on the
 *              same rows, but are NOT compared inside the line
 * Only the opcodes change: the backend diff is not touched, and every line of the
 * old and the new config is still covered exactly once.
 *
 * Everything here is pure (no DOM); tests: tests/js/test_diff_align.test.js
 * Exposes the global `diffAlign` (and module.exports under Node).
 */
(function (root) {
    "use strict";

    // two lines are "the same line, edited" from this similarity (0..1) on
    const SIMILARITY_CUTOFF = 0.45;
    // blocks up to old*new lines are aligned exhaustively (best pair, then both halves)
    const FULL_ALIGN_LIMIT = 10000;
    // bigger blocks: every old line is compared with this many following new lines only
    const ALIGN_WINDOW = 40;
    // a block with more lines than this on one side is not aligned at all
    const ALIGN_MAX_LINES = 3000;

    // overlapping character pairs of a line with counts; indentation does not matter
    function bigrams(text) {
        const trimmed = text.trim();
        const counts = new Map();
        for (let i = 0; i < trimmed.length - 1; i++) {
            const gram = trimmed.substr(i, 2);
            counts.set(gram, (counts.get(gram) || 0) + 1);
        }
        return { counts: counts, total: Math.max(0, trimmed.length - 1) };
    }

    /**
     * Dice coefficient of the character pairs: 1 = same line, 0 = nothing in common.
     * "storm-control ... percent 3" vs "... percent 5" -> 0.98,
     * "storm-control ..." vs "port-security aging-time 1" -> 0.12.
     */
    function similarity(a, b, gramsA, gramsB) {
        if (a.trim() === b.trim()) return 1;
        const x = gramsA || bigrams(a);
        const y = gramsB || bigrams(b);
        if (!x.total || !y.total) return 0;
        const small = x.counts.size <= y.counts.size ? x.counts : y.counts;
        const large = small === x.counts ? y.counts : x.counts;
        let common = 0;
        small.forEach(function (count, gram) {
            const other = large.get(gram);
            if (other) common += Math.min(count, other);
        });
        return (2 * common) / (x.total + y.total);
    }

    // similarity(i, j) of old line i and new line j; the bigrams of a line are built once
    function createScorer(oldLines, newLines) {
        const oldGrams = new Map();
        const newGrams = new Map();
        function grams(cache, lines, index) {
            let value = cache.get(index);
            if (value === undefined) {
                value = bigrams(lines[index]);
                cache.set(index, value);
            }
            return value;
        }
        return function (i, j) {
            const a = oldLines[i];
            const b = newLines[j];
            if (a === b) return 1;
            return similarity(a, b, grams(oldGrams, oldLines, i), grams(newGrams, newLines, j));
        };
    }

    /**
     * Pairs [oldIndex, newIndex] (ascending in both) of the lines that are the same or
     * similar. Like difflib's own "fancy replace": take the most similar pair, then
     * align what is left of it and what is right of it the same way.
     */
    function pairBlock(score, i1, i2, j1, j2, cutoff) {
        const pairs = [];

        function exhaustive(alo, ahi, blo, bhi) {
            if (alo >= ahi || blo >= bhi) return;
            let best = -1;
            let bestI = -1;
            let bestJ = -1;
            search: for (let i = alo; i < ahi; i++) {
                for (let j = blo; j < bhi; j++) {
                    const value = score(i, j);
                    if (value > best) {
                        best = value;
                        bestI = i;
                        bestJ = j;
                        if (value === 1) break search;
                    }
                }
            }
            if (best < cutoff) return;
            exhaustive(alo, bestI, blo, bestJ);
            pairs.push([bestI, bestJ]);
            exhaustive(bestI + 1, ahi, bestJ + 1, bhi);
        }

        function windowed() {
            let from = j1;
            for (let i = i1; i < i2 && from < j2; i++) {
                let best = -1;
                let bestJ = -1;
                const to = Math.min(j2, from + ALIGN_WINDOW);
                for (let j = from; j < to; j++) {
                    const value = score(i, j);
                    if (value > best) {
                        best = value;
                        bestJ = j;
                        if (value === 1) break;
                    }
                }
                if (best >= cutoff) {
                    pairs.push([i, bestJ]);
                    from = bestJ + 1;
                }
            }
        }

        const oldCount = i2 - i1;
        const newCount = j2 - j1;
        if (oldCount * newCount <= FULL_ALIGN_LIMIT) exhaustive(i1, i2, j1, j2);
        else if (Math.max(oldCount, newCount) <= ALIGN_MAX_LINES) windowed();
        return pairs;
    }

    // joins neighbouring ops of the same kind: equal+equal, replace+replace (not "plain")
    function mergeOps(ops) {
        const merged = [];
        ops.forEach(function (op) {
            const last = merged[merged.length - 1];
            const mergeable =
                last &&
                last.length === 5 &&
                op.length === 5 &&
                last[0] === op[0] &&
                (op[0] === "equal" || op[0] === "replace" || op[0] === "delete" || op[0] === "insert") &&
                last[2] === op[1] &&
                last[4] === op[3];
            if (mergeable) {
                last[2] = op[2];
                last[4] = op[4];
            } else {
                merged.push(op.slice()); // a copy: the caller's opcodes are never modified
            }
        });
        return merged;
    }

    /**
     * Opcodes of one replace block [i1, i2) x [j1, j2) after alignment.
     * Lines between two pairs that have no counterpart stay on the same rows
     * ("plain" replace) when both sides have some, otherwise they are delete / insert.
     */
    function alignReplace(oldLines, newLines, i1, i2, j1, j2, options) {
        const cutoff = options && options.cutoff !== undefined ? options.cutoff : SIMILARITY_CUTOFF;
        const score = createScorer(oldLines, newLines);
        const pairs = pairBlock(score, i1, i2, j1, j2, cutoff);
        const ops = [];
        let i = i1;
        let j = j1;

        function gap(oldEnd, newEnd) {
            if (i < oldEnd && j < newEnd) ops.push(["replace", i, oldEnd, j, newEnd, "plain"]);
            else if (i < oldEnd) ops.push(["delete", i, oldEnd, j, j]);
            else if (j < newEnd) ops.push(["insert", i, i, j, newEnd]);
        }

        pairs.forEach(function (pair) {
            gap(pair[0], pair[1]);
            // identical text = the line only moved (a shifted block); anything else is an edit
            const same = oldLines[pair[0]] === newLines[pair[1]];
            ops.push([same ? "equal" : "replace", pair[0], pair[0] + 1, pair[1], pair[1] + 1]);
            i = pair[0] + 1;
            j = pair[1] + 1;
        });
        gap(i2, j2);
        return mergeOps(ops);
    }

    /**
     * Refines the server opcodes: every replace block is aligned by similarity.
     *   opcodes    - [[tag, i1, i2, j1, j2], ...] from difflib.SequenceMatcher
     *   oldLines, newLines - the two configs split into lines
     * Other opcodes are returned as they are. Never throws on bad input: the original
     * opcodes are returned instead.
     */
    function refineOpcodes(opcodes, oldLines, newLines, options) {
        if (!Array.isArray(opcodes) || !Array.isArray(oldLines) || !Array.isArray(newLines)) return opcodes;
        const result = [];
        for (let k = 0; k < opcodes.length; k++) {
            const code = opcodes[k];
            if (code[0] !== "replace") {
                result.push(code);
                continue;
            }
            if (code[2] > oldLines.length || code[4] > newLines.length) return opcodes;
            alignReplace(oldLines, newLines, code[1], code[2], code[3], code[4], options).forEach(function (op) {
                result.push(op);
            });
        }
        return mergeOps(result);
    }

    const api = {
        SIMILARITY_CUTOFF: SIMILARITY_CUTOFF,
        similarity: similarity,
        pairBlock: pairBlock,
        createScorer: createScorer,
        alignReplace: alignReplace,
        refineOpcodes: refineOpcodes,
    };

    root.diffAlign = api;
    if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
