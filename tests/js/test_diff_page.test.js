/*
 * Frontend tests for the pure helpers of app/static/js/diff_page.js
 * (history timeline grouping, line splitting, search regexp, context rows).
 *
 * Run: node --test tests/js/*.test.js
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const file = path.join(__dirname, "..", "..", "app", "static", "js", "diff_page.js");
const context = vm.createContext({ console });
vm.runInContext(fs.readFileSync(file, "utf8"), context, { filename: "diff_page.js" });
const page = context.diffPage;
const plain = (value) => JSON.parse(JSON.stringify(value));

// ---------------------------------------------------------------------------
test("parseStamp: formats the stored timestamp", () => {
    assert.deepStrictEqual(plain(page.parseStamp("2026-09-29 14:32")), {
        day: "2026-09-29",
        year: "2026",
        dateLabel: "29.09",
        time: "14:32",
        full: "29.09.2026 14:32",
    });
});

test("parseStamp: unknown format gives null", () => {
    assert.strictEqual(page.parseStamp("unknown"), null);
    assert.strictEqual(page.parseStamp(""), null);
    assert.strictEqual(page.parseStamp(null), null);
});

// ---------------------------------------------------------------------------
test("groupByDay: versions are grouped by date, newest first", () => {
    const groups = plain(
        page.groupByDay([
            "2026-09-29 14:32",
            "2026-09-29 12:18",
            "2026-09-28 18:45",
            "2026-09-27 09:12",
        ])
    );
    assert.deepStrictEqual(
        groups.map((g) => [g.label, g.items.map((i) => i.time)]),
        [
            ["29.09", ["14:32", "12:18"]],
            ["28.09", ["18:45"]],
            ["27.09", ["09:12"]],
        ]
    );
    // ordinal numbers: 1 = the oldest version
    assert.deepStrictEqual(
        groups.flatMap((g) => g.items.map((i) => i.version)),
        [4, 3, 2, 1]
    );
    assert.strictEqual(groups[0].items[0].full, "29.09.2026 14:32");
    assert.strictEqual(groups[0].items[0].ts, "2026-09-29 14:32");
});

test("groupByDay: the year is shown for the first day and when it changes", () => {
    const groups = plain(
        page.groupByDay(["2026-01-02 10:00", "2026-01-01 10:00", "2025-12-31 10:00", "2025-12-30 10:00"])
    );
    assert.deepStrictEqual(
        groups.map((g) => g.showYear),
        [true, false, true, false]
    );
});

test("groupByDay: duplicated timestamps are collapsed", () => {
    const groups = plain(page.groupByDay(["2026-09-29 14:32", "2026-09-29 14:32", "2026-09-29 10:00"]));
    assert.strictEqual(groups[0].items.length, 2);
    assert.deepStrictEqual(
        groups[0].items.map((i) => i.version),
        [2, 1]
    );
});

test("groupByDay: broken timestamps do not break the timeline", () => {
    const groups = plain(page.groupByDay(["2026-09-29 14:32", "unknown"]));
    assert.strictEqual(groups.length, 2);
    assert.strictEqual(groups[1].label, "?");
    assert.strictEqual(groups[1].items[0].ts, "unknown");
});

test("groupByDay: 5 / 50 / 500 versions - only the newest are labelled", () => {
    // n versions, one every 5 hours, newest first
    const many = (n) =>
        Array.from({ length: n }, (_, i) => {
            const d = new Date(Date.UTC(2026, 8, 29, 23, 59) - i * 3600 * 1000 * 5);
            const p = (x) => String(x).padStart(2, "0");
            return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;
        });

    for (const n of [5, 50, 500]) {
        const items = plain(page.groupByDay(many(n))).flatMap((g) => g.items);
        assert.strictEqual(items.length, n);
        assert.strictEqual(items.filter((i) => !i.compact).length, Math.min(n, page.TIMELINE_LABELED_LIMIT));
        assert.strictEqual(items[0].version, n);
        assert.strictEqual(items[n - 1].version, 1);
    }
});

test("groupByDay: empty history", () => {
    assert.deepStrictEqual(plain(page.groupByDay([])), []);
});

// ---------------------------------------------------------------------------
test("splitLines: identical to Python str.splitlines()", () => {
    const cases = [
        ["", []],
        ["a", ["a"]],
        ["a\nb", ["a", "b"]],
        ["a\nb\n", ["a", "b"]],
        ["a\n\n", ["a", ""]],
        ["\n", [""]],
        ["\na", ["", "a"]],
        ["a\r\nb", ["a", "b"]],
        ["a\rb", ["a", "b"]],
        ["a\x0cb", ["a", "b"]], // form feed: Python splits here, a plain split("\n") does not
        ["a\x0bb", ["a", "b"]],
        ["a\u2028b", ["a", "b"]],
    ];
    for (const [text, expected] of cases) {
        assert.deepStrictEqual(plain(page.splitLines(text)), expected, JSON.stringify(text));
    }
});

// ---------------------------------------------------------------------------
test("buildSearchRegex: case-insensitive, invalid regexp falls back to plain text", () => {
    assert.ok(page.buildSearchRegex("server").test("description SERVER-01"));
    assert.ok(page.buildSearchRegex("ser.er-0[12]").test("SERVER-02"));
    assert.doesNotThrow(() => page.buildSearchRegex("(unclosed"));
    assert.ok(page.buildSearchRegex("(unclosed").test("text (unclosed paren"));
    assert.ok(page.buildSearchRegex("a[").test("array a[ ]"));
});

test("expandWithContext: rows around the found rows, clamped to the table", () => {
    assert.deepStrictEqual([...page.expandWithContext([5], 100, 2, 2)].sort((a, b) => a - b), [3, 4, 5, 6, 7]);
    assert.deepStrictEqual([...page.expandWithContext([0], 10, 3, 3)].sort((a, b) => a - b), [0, 1, 2, 3]);
    assert.deepStrictEqual([...page.expandWithContext([9], 10, 3, 3)].sort((a, b) => a - b), [6, 7, 8, 9]);
    // overlapping ranges are merged
    // 10 -> 7..13, 12 -> 9..15: union is 7..15
    assert.strictEqual(page.expandWithContext([10, 12], 100, 3, 3).size, 9);
    assert.strictEqual(page.expandWithContext([], 100, 3, 3).size, 0);
});

// ---------------------------------------------------------------------------
test("scrollTargetLeft: a visible dot does not move the timeline", () => {
    // view 800px wide, scrolled to 3000, dot at 3400 (well inside)
    assert.strictEqual(page.scrollTargetLeft(3400, 46, 3000, 800), null);
});

test("scrollTargetLeft: a dot outside the view is centred, never reset to the start", () => {
    // dot far to the right of the view
    assert.strictEqual(page.scrollTargetLeft(5000, 46, 3000, 800), 5000 - (800 - 46) / 2);
    // dot to the left of the view (keyboard / older-newer buttons)
    assert.strictEqual(page.scrollTargetLeft(2500, 46, 3000, 800), 2500 - (800 - 46) / 2);
    // a dot at the very edge counts as not visible (margin)
    assert.notStrictEqual(page.scrollTargetLeft(3003, 46, 3000, 800), null);
});

test("scrollTargetLeft: never negative", () => {
    assert.strictEqual(page.scrollTargetLeft(10, 46, 5000, 800), 0);
});
