/*
 * Frontend tests for app/static/js/diff_table.js (character-level diff in
 * Side by Side, word-level diff in Inline, protection for huge lines).
 *
 * Run (Node.js 18+, no dependencies):
 *     node --test tests/js/*.test.js
 *
 * difflib.js and diff_table.js are loaded into a vm context together with a
 * tiny fake DOM, so no browser / jsdom is needed.
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const JS_DIR = path.join(__dirname, "..", "..", "app", "static", "js");

// ---------------------------------------------------------------------------
// Minimal fake DOM (enough for diffview.buildView)
// ---------------------------------------------------------------------------
class FakeNode {
    constructor(tagName, text) {
        this.tagName = tagName ? tagName.toUpperCase() : "#text";
        this.children = [];
        this.className = "";
        this.id = "";
        this.style = {};
        // Every real HTMLElement has a dataset (diff_table.js tags rows with it)
        this.dataset = {};
        this.text = text || "";
        const owner = this;
        this.classList = {
            add(name) {
                const names = owner.className.split(/\s+/).filter(Boolean);
                if (!names.includes(name)) names.push(name);
                owner.className = names.join(" ");
            },
            remove(name) {
                owner.className = owner.className
                    .split(/\s+/)
                    .filter((n) => n && n !== name)
                    .join(" ");
            },
        };
    }
    appendChild(child) {
        this.children.push(child);
        return child;
    }
    setAttribute(name, value) {
        this[name] = value;
    }
    set innerHTML(_value) {}
    get textContent() {
        return this.tagName === "#text"
            ? this.text
            : this.children.map((c) => c.textContent).join("");
    }
    hasClass(name) {
        return this.className.split(/\s+/).includes(name);
    }
    find(predicate, found = []) {
        if (predicate(this)) found.push(this);
        this.children.forEach((c) => c.find(predicate, found));
        return found;
    }
}

function loadDiffview() {
    const context = vm.createContext({
        console,
        document: {
            createElement: (name) => new FakeNode(name),
            createTextNode: (text) => new FakeNode(null, text),
        },
    });
    for (const file of ["difflib.js", "diff_table.js"]) {
        const code = fs.readFileSync(path.join(JS_DIR, file), "utf8");
        vm.runInContext(code, context, { filename: file });
    }
    return vm.runInContext("diffview", context);
}

const diffview = loadDiffview();

// Arrays created inside the vm context belong to another realm, and
// assert.deepStrictEqual compares prototypes -> normalise through JSON.
const plain = (value) => JSON.parse(JSON.stringify(value));
const charDiff = (...args) => plain(diffview.charDiffSegments(...args));
const wordDiff = (...args) => plain(diffview.wordDiffSegments(...args));

// Line-level opcodes the way the server (Python SequenceMatcher) returns them
function lineOpcodes(oldLines, newLines) {
    const context = vm.createContext({});
    vm.runInContext(
        fs.readFileSync(path.join(JS_DIR, "difflib.js"), "utf8"),
        context
    );
    return vm.runInContext(
        "new difflib.SequenceMatcher(a, b).get_opcodes()",
        Object.assign(context, { a: oldLines, b: newLines })
    );
}

function build(oldLines, newLines, viewType, extra) {
    return diffview.buildView(
        Object.assign(
            {
                baseTextLines: oldLines,
                newTextLines: newLines,
                opcodes: lineOpcodes(oldLines, newLines),
                baseTextName: "Previous config",
                newTextName: "Last config",
                viewType: viewType,
            },
            extra
        )
    );
}

const bodyRows = (table) =>
    table.children[1].children; // tbody -> rows
const tags = (node, tag) => node.find((n) => n.tagName === tag);
const textOf = (nodes) => nodes.map((n) => n.textContent);

// ---------------------------------------------------------------------------
// charDiffSegments (pure function)
// ---------------------------------------------------------------------------
test("charDiffSegments: only the changed characters are marked", () => {
    const r = charDiff("description SERVER-01", "description SERVER-02");
    assert.deepStrictEqual(r.oldSide, [
        ["equal", "description SERVER-0"],
        ["delete", "1"],
    ]);
    assert.deepStrictEqual(r.newSide, [
        ["equal", "description SERVER-0"],
        ["insert", "2"],
    ]);
});

test("charDiffSegments: change in the middle keeps prefix and suffix", () => {
    const r = charDiff(
        " description OLD-SERVER uplink",
        " description NEW-SERVER uplink"
    );
    assert.deepStrictEqual(r.oldSide, [
        ["equal", " description "],
        ["delete", "OLD"],
        ["equal", "-SERVER uplink"],
    ]);
    assert.deepStrictEqual(r.newSide, [
        ["equal", " description "],
        ["insert", "NEW"],
        ["equal", "-SERVER uplink"],
    ]);
});

test("charDiffSegments: pure insertion and pure deletion inside a line", () => {
    const added = charDiff("ip address 10.0.0.1", "ip address 10.0.0.12");
    assert.deepStrictEqual(added.oldSide, [["equal", "ip address 10.0.0.1"]]);
    assert.deepStrictEqual(added.newSide, [
        ["equal", "ip address 10.0.0.1"],
        ["insert", "2"],
    ]);
    const removed = charDiff("ip address 10.0.0.12", "ip address 10.0.0.1");
    assert.deepStrictEqual(removed.oldSide, [
        ["equal", "ip address 10.0.0.1"],
        ["delete", "2"],
    ]);
    assert.deepStrictEqual(removed.newSide, [["equal", "ip address 10.0.0.1"]]);
});

test("charDiffSegments: segments always rebuild the original lines", () => {
    const pairs = [
        ["switchport trunk allowed vlan 10,20,30", "switchport trunk allowed vlan 10,25,30,40"],
        ["a", "b"],
        ["abcabcabc", "abcXabcYabc"],
        ["  ", "   x"],
        ["snmp-server community public RO", "snmp-server community private RW"],
        ["", "new line"],
        ["old line", ""],
    ];
    for (const [oldLine, newLine] of pairs) {
        const r = charDiff(oldLine, newLine);
        assert.strictEqual(r.oldSide.map((s) => s[1]).join(""), oldLine);
        assert.strictEqual(r.newSide.map((s) => s[1]).join(""), newLine);
        assert.ok(r.oldSide.every((s) => s[0] !== "insert"));
        assert.ok(r.newSide.every((s) => s[0] !== "delete"));
    }
});

test("charDiffSegments: emoji / non-BMP characters are not split", () => {
    const r = charDiff("descr \u{1F600}", "descr \u{1F601}");
    assert.deepStrictEqual(r.oldSide, [
        ["equal", "descr "],
        ["delete", "\u{1F600}"],
    ]);
    assert.deepStrictEqual(r.newSide, [
        ["equal", "descr "],
        ["insert", "\u{1F601}"],
    ]);
});

test("charDiffSegments: works with cyrillic text", () => {
    const r = charDiff("description Сервер-1", "description Сервер-2");
    assert.deepStrictEqual(r.oldSide[1], ["delete", "1"]);
    assert.deepStrictEqual(r.newSide[1], ["insert", "2"]);
});

test("charDiffSegments: a too long line is not compared", () => {
    const long = "x".repeat(diffview.MAX_INLINE_DIFF_LENGTH + 1);
    assert.strictEqual(charDiff(long, "short"), null);
    assert.strictEqual(charDiff("short", long), null);
    // exactly at the limit is still compared
    const atLimit = "x".repeat(diffview.MAX_INLINE_DIFF_LENGTH);
    assert.notStrictEqual(charDiff(atLimit, atLimit.slice(0, -1) + "y"), null);
});

test("charDiffSegments: long line with a small change stays precise and fast", () => {
    const base = "certificate ".repeat(500); // 6000 chars, > 200 (difflib 'popular' limit)
    const started = Date.now();
    const r = charDiff(base + "AAA tail", base + "BBB tail");
    assert.ok(Date.now() - started < 1000, "must not hang");
    assert.deepStrictEqual(r.oldSide.slice(-2), [
        ["delete", "AAA"],
        ["equal", " tail"],
    ]);
    assert.deepStrictEqual(r.newSide.slice(-2), [
        ["insert", "BBB"],
        ["equal", " tail"],
    ]);
});

// ---------------------------------------------------------------------------
// wordDiffSegments (Inline)
// ---------------------------------------------------------------------------
test("wordDiffSegments: whole words are marked", () => {
    const r = wordDiff("description SERVER-01", "description SERVER-02");
    assert.deepStrictEqual(r.oldSide, [
        ["equal", "description "],
        ["delete", "SERVER-01"],
    ]);
    assert.deepStrictEqual(r.newSide, [
        ["equal", "description "],
        ["insert", "SERVER-02"],
    ]);
});

// ---------------------------------------------------------------------------
// Side by Side table
// ---------------------------------------------------------------------------
test("Side by Side: replaced line is highlighted on both sides, rows stay in sync", () => {
    const oldLines = [
        "interface GigabitEthernet0/1",
        " description OLD-SERVER",
        " ip address 10.10.10.1",
    ];
    const newLines = [
        "interface GigabitEthernet0/1",
        " description NEW-SERVER",
        " ip address 10.10.10.1",
    ];
    const table = build(oldLines, newLines, 0);
    const rows = bodyRows(table);
    assert.strictEqual(rows.length, 3);

    // one row: [th n][td old][th n][td new]
    const changed = rows[1];
    assert.strictEqual(changed.children.length, 4);
    const [thOld, tdOld, thNew, tdNew] = changed.children;
    assert.strictEqual(thOld.textContent, "2");
    assert.strictEqual(thNew.textContent, "2");
    assert.ok(tdOld.hasClass("replace") && tdNew.hasClass("replace"));

    assert.deepStrictEqual(textOf(tags(tdOld, "DEL")), ["OLD"]);
    assert.deepStrictEqual(textOf(tags(tdNew, "INS")), ["NEW"]);
    assert.strictEqual(tags(tdOld, "INS").length, 0);
    assert.strictEqual(tags(tdNew, "DEL").length, 0);
    // full text of the cells is intact
    assert.strictEqual(tdOld.textContent, " description OLD-SERVER");
    assert.strictEqual(tdNew.textContent, " description NEW-SERVER");
    // unchanged parts are plain spans
    assert.ok(tags(tdOld, "SPAN").some((s) => s.hasClass("equal")));

    // equal lines have no character-level markup
    assert.strictEqual(tags(rows[0], "INS").length + tags(rows[0], "DEL").length, 0);
});

test("Side by Side: inserted and deleted lines are whole-line, opposite cell is empty", () => {
    const table = build(["a", "b", "c"], ["a", "c", "d"], 0);
    const rows = bodyRows(table);
    const marked = rows.filter((r) => tags(r, "INS").length + tags(r, "DEL").length > 0);
    assert.strictEqual(marked.length, 0, "insert/delete lines are not compared inside");

    const deleteRow = rows.find((r) => r.children[1].hasClass("delete"));
    assert.ok(deleteRow.children[3].hasClass("empty"));
    assert.strictEqual(deleteRow.children[0].textContent, "2");
    assert.strictEqual(deleteRow.children[2].textContent, "");

    const insertRow = rows.find((r) => r.children[3].hasClass("insert"));
    assert.ok(insertRow.children[1].hasClass("empty"));
    assert.strictEqual(insertRow.children[2].textContent, "3");
});

test("Side by Side: line numbers are correct after a changed block", () => {
    const oldLines = ["a", "b OLD", "c", "d"];
    const newLines = ["a", "b NEW", "c", "d"];
    const rows = bodyRows(build(oldLines, newLines, 0));
    assert.deepStrictEqual(
        rows.map((r) => [r.children[0].textContent, r.children[2].textContent]),
        [["1", "1"], ["2", "2"], ["3", "3"], ["4", "4"]]
    );
});

test("Side by Side: replace block with different line counts", () => {
    const oldLines = ["start", "one OLD", "two OLD", "three OLD", "end"];
    const newLines = ["start", "one NEW", "end"];
    const table = build(oldLines, newLines, 0, {
        // force a single replace opcode for the block
        opcodes: [
            ["equal", 0, 1, 0, 1],
            ["replace", 1, 4, 1, 2],
            ["equal", 4, 5, 2, 3],
        ],
    });
    const rows = bodyRows(table);
    assert.strictEqual(rows.length, 5);
    // first pair is compared character by character
    assert.deepStrictEqual(textOf(tags(rows[1], "DEL")), ["OLD"]);
    assert.deepStrictEqual(textOf(tags(rows[1], "INS")), ["NEW"]);
    // surplus old lines: plain text on the left, empty placeholder on the right
    for (const i of [2, 3]) {
        assert.strictEqual(tags(rows[i], "DEL").length, 0);
        assert.ok(rows[i].children[3].hasClass("empty"));
        assert.strictEqual(rows[i].children[2].textContent, "");
    }
    assert.strictEqual(rows[2].children[0].textContent, "3");
    assert.strictEqual(rows[3].children[0].textContent, "4");
});

test("Side by Side: replace block that ends the file does not create phantom lines", () => {
    const oldLines = ["a", "b OLD", "c OLD"];
    const newLines = ["a", "b NEW"];
    const rows = bodyRows(
        build(oldLines, newLines, 0, {
            opcodes: [
                ["equal", 0, 1, 0, 1],
                ["replace", 1, 3, 1, 2],
            ],
        })
    );
    assert.strictEqual(rows.length, 3);
    const last = rows[2];
    assert.strictEqual(last.children[0].textContent, "3");
    // right side: no line number, empty cell (used to be a phantom line "3")
    assert.strictEqual(last.children[2].textContent, "");
    assert.ok(last.children[3].hasClass("empty"));
});

test("Side by Side: huge line falls back to a plain changed line", () => {
    const hugeOld = "key " + "A".repeat(diffview.MAX_INLINE_DIFF_LENGTH + 10);
    const hugeNew = "key " + "B".repeat(diffview.MAX_INLINE_DIFF_LENGTH + 10);
    const table = build(["x", hugeOld], ["x", hugeNew], 0);
    const row = bodyRows(table)[1];
    assert.strictEqual(tags(row, "INS").length + tags(row, "DEL").length, 0);
    assert.ok(row.children[1].hasClass("replace") && row.children[3].hasClass("replace"));
    assert.strictEqual(row.children[1].textContent, hugeOld);
    assert.strictEqual(row.children[3].textContent, hugeNew);
});

test("Side by Side: tabs are rendered as spaces in highlighted lines", () => {
    const table = build(["\tdescr OLD"], ["\tdescr NEW"], 0);
    const row = bodyRows(table)[0];
    assert.ok(row.children[1].textContent.startsWith("\u00a0\u00a0\u00a0\u00a0descr "));
});

test("Side by Side: table has one id and the copy buttons in the header", () => {
    const table = build(["a"], ["b"], 0);
    assert.strictEqual(table.id, "diff_table");
    const withId = table.find((n) => n.id === "diff_table");
    assert.strictEqual(withId.length, 1, "ids must be unique");
    const buttons = tags(table.children[0], "BUTTON");
    assert.deepStrictEqual(
        buttons.map((b) => b.title),
        ["Copy previous config", "Copy last config"]
    );
});

// ---------------------------------------------------------------------------
// Inline table
// ---------------------------------------------------------------------------
test("Inline: replaced line becomes a delete row and an insert row with word diff", () => {
    const table = build(["description SERVER-01"], ["description SERVER-02"], 2);
    const rows = bodyRows(table);
    assert.strictEqual(rows.length, 2);
    assert.ok(rows[0].children[2].hasClass("delete"));
    assert.ok(rows[1].children[2].hasClass("insert"));
    assert.deepStrictEqual(textOf(tags(rows[0], "DEL")), ["SERVER-01"]);
    assert.deepStrictEqual(textOf(tags(rows[1], "INS")), ["SERVER-02"]);
});

test("Inline: replace block with different line counts does not throw", () => {
    const opcodes = [
        ["equal", 0, 1, 0, 1],
        ["replace", 1, 3, 1, 2],
    ];
    const rows = bodyRows(
        build(["a", "b OLD", "c OLD"], ["a", "b NEW"], 2, { opcodes })
    );
    // equal + 2 deleted lines + 1 inserted line, no empty rows
    assert.strictEqual(rows.length, 4);
    assert.ok(rows.every((r) => r.children.length > 0));

    const opcodes2 = [
        ["equal", 0, 1, 0, 1],
        ["replace", 1, 2, 1, 3],
    ];
    const rows2 = bodyRows(
        build(["a", "b OLD"], ["a", "b NEW", "c NEW"], 2, { opcodes: opcodes2 })
    );
    assert.strictEqual(rows2.length, 4);
    assert.ok(rows2.every((r) => r.children.length > 0));
});

test("Inline (viewType 1): plain lines without inner highlighting", () => {
    const table = build(["description SERVER-01"], ["description SERVER-02"], 1);
    assert.strictEqual(tags(table, "INS").length + tags(table, "DEL").length, 0);
});

test("Switching views needs only the same opcodes (no server call)", () => {
    const oldLines = ["a", "b OLD", "c"];
    const newLines = ["a", "b NEW", "c"];
    const opcodes = lineOpcodes(oldLines, newLines);
    const sideBySide = diffview.buildView({
        baseTextLines: oldLines,
        newTextLines: newLines,
        opcodes,
        viewType: 0,
    });
    const inline = diffview.buildView({
        baseTextLines: oldLines,
        newTextLines: newLines,
        opcodes,
        viewType: 2,
    });
    assert.strictEqual(bodyRows(sideBySide).length, 3);
    assert.strictEqual(bodyRows(inline).length, 4);
});
