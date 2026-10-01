/*
 * Tests of static/js/diff_align.js (pairing of the lines of a "replace" block by similarity).
 * Run: node --test tests/js/*.test.js   (Node.js 18+, no dependencies)
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const jsDir = path.join(__dirname, "..", "..", "app", "static", "js");
const align = require(path.join(jsDir, "diff_align.js"));

vm.runInThisContext(fs.readFileSync(path.join(jsDir, "difflib.js"), "utf8"));
const difflibJs = vm.runInThisContext("difflib");
const serverOpcodes = (a, b) => new difflibJs.SequenceMatcher(a, b).get_opcodes();

const STORM3 = " storm-control multicast min-rate percent 1 max-rate percent 3";
const STORM5 = " storm-control multicast min-rate percent 1 max-rate percent 5";

// every old and every new line of [i1,i2) x [j1,j2) is covered exactly once, in order
function assertCoverage(ops, i1, i2, j1, j2) {
    let i = i1;
    let j = j1;
    ops.forEach((op) => {
        assert.equal(op[1], i, "old side must continue where the previous op ended: " + JSON.stringify(op));
        assert.equal(op[3], j, "new side must continue where the previous op ended: " + JSON.stringify(op));
        assert.ok(op[2] >= op[1] && op[4] >= op[3]);
        if (op[0] === "equal") assert.equal(op[2] - op[1], op[4] - op[3]);
        if (op[0] === "delete") assert.equal(op[4], op[3]);
        if (op[0] === "insert") assert.equal(op[2], op[1]);
        i = op[2];
        j = op[4];
    });
    assert.equal(i, i2);
    assert.equal(j, j2);
}

const pairsOf = (ops) =>
    ops.filter((op) => op[0] === "replace" && op[5] !== "plain").map((op) => [op[1], op[3]]);

// ---------- similarity ----------

test("similarity: the same command edited is similar, unrelated commands are not", () => {
    assert.ok(align.similarity(STORM3, STORM5) > 0.9);
    assert.ok(align.similarity(STORM3, " port-security aging-time 1") < 0.3);
    assert.ok(align.similarity(STORM3, " port-security enable") < 0.3);
    assert.ok(align.similarity(" description OLD", " description NEW") > align.SIMILARITY_CUTOFF);
    assert.ok(align.similarity(" info-center loghost 10.0.0.41", " snmp-agent community read cipher X") < 0.3);
});

test("similarity: identical = 1, indentation is ignored, nothing in common = 0", () => {
    assert.equal(align.similarity("sysname A", "sysname A"), 1);
    assert.equal(align.similarity("  sysname A", "sysname A"), 1);
    assert.equal(align.similarity("quit", "return"), 0);
    assert.equal(align.similarity("", "x"), 0);
    assert.equal(align.similarity("#", "#"), 1);
});

// ---------- the reported artifact ----------

test("a command added above a changed line: the changed line is paired with ITS new version", () => {
    const old = ["interface Gi0/0/5", STORM3, " undo shutdown"];
    const changed = [
        "interface Gi0/0/5",
        " port-security enable",
        " port-security max-mac-num 1",
        " port-security aging-time 1",
        STORM5,
        " undo shutdown",
    ];
    const raw = serverOpcodes(old, changed);
    // the server says: one block replaced by four lines (positional pairing used to
    // compare STORM3 with "port-security enable")
    assert.deepEqual(raw[1].slice(0, 5), ["replace", 1, 2, 1, 5]);

    const ops = align.refineOpcodes(raw, old, changed);
    assertCoverage(ops, 0, old.length, 0, changed.length);
    assert.deepEqual(pairsOf(ops), [[1, 4]]); // STORM3 <-> STORM5, nothing else is compared
    assert.deepEqual(ops.find((op) => op[0] === "insert").slice(0, 5), ["insert", 1, 1, 1, 4]);
});

test("a block that only moved down is shown as an insert, the moved lines are equal", () => {
    const tail = [" port link-type access", " port default vlan 100", STORM3, " storm-control action block", " undo shutdown", "#"];
    const old = ["interface Gi0/0/5"].concat(tail);
    const changed = ["interface Gi0/0/5", " port-security enable", " port-security max-mac-num 1", " port-security aging-time 1"].concat(tail);
    // what difflib's "popular line" heuristic can return for a big config: one replace block
    const raw = [
        ["equal", 0, 1, 0, 1],
        ["replace", 1, old.length, 1, changed.length],
    ];
    const ops = align.refineOpcodes(raw, old, changed);
    assertCoverage(ops, 0, old.length, 0, changed.length);
    assert.deepEqual(ops, [
        ["equal", 0, 1, 0, 1],
        ["insert", 1, 1, 1, 4],
        ["equal", 1, old.length, 4, changed.length],
    ]);
});

test("unrelated old and new lines stay on the same rows but are not compared inside", () => {
    const old = [STORM3];
    const changed = [" port-security aging-time 1"];
    const ops = align.refineOpcodes([["replace", 0, 1, 0, 1]], old, changed);
    assert.deepEqual(ops, [["replace", 0, 1, 0, 1, "plain"]]);
});

test("unequal unrelated blocks: one plain replace block (rows are paired, the surplus is empty)", () => {
    const old = [" snmp-agent community read cipher X", " snmp-agent sys-info version v2c"];
    const changed = [" ntp-service unicast-server 10.0.0.1"];
    const ops = align.refineOpcodes([["replace", 0, 2, 0, 1]], old, changed);
    assert.deepEqual(ops, [["replace", 0, 2, 0, 1, "plain"]]);
});

test("a mixed block: similar lines are paired, the new line between them is an insert", () => {
    const old = [" description OLD", " speed 100"];
    const changed = [" description NEW", " duplex full", " speed 1000"];
    const ops = align.refineOpcodes([["replace", 0, 2, 0, 3]], old, changed);
    assertCoverage(ops, 0, 2, 0, 3);
    assert.deepEqual(pairsOf(ops), [[0, 0], [1, 2]]);
    assert.deepEqual(ops.filter((op) => op[0] === "insert").map((op) => [op[3], op[4]]), [[1, 2]]);
});

test("a removed line above a changed line: the deleted line is a delete, the rest is paired", () => {
    const old = [" port-security enable", " port-security aging-time 1", STORM3];
    const changed = [STORM5];
    const ops = align.refineOpcodes([["replace", 0, 3, 0, 1]], old, changed);
    assertCoverage(ops, 0, 3, 0, 1);
    assert.deepEqual(pairsOf(ops), [[2, 0]]);
    assert.equal(ops[0][0], "delete");
});

test("an indentation-only change is an edit (replace), not an equal line", () => {
    const ops = align.refineOpcodes([["replace", 0, 1, 0, 1]], ["sysname A"], ["  sysname A"]);
    assert.deepEqual(ops, [["replace", 0, 1, 0, 1]]);
});

// ---------- the rest of the opcodes ----------

test("equal / insert / delete from the server pass through, the input is not modified", () => {
    const old = ["a", "b", "c"];
    const changed = ["a", "x", "c", "d"];
    const raw = [
        ["equal", 0, 1, 0, 1],
        ["replace", 1, 2, 1, 2],
        ["equal", 2, 3, 2, 3],
        ["insert", 3, 3, 3, 4],
    ];
    const copy = JSON.parse(JSON.stringify(raw));
    const ops = align.refineOpcodes(raw, old, changed);
    assert.deepEqual(raw, copy);
    assertCoverage(ops, 0, 3, 0, 4);
    assert.deepEqual(ops[ops.length - 1], ["insert", 3, 3, 3, 4]);
});

test("neighbouring equal ops are joined (a refined equal next to a server equal)", () => {
    const old = ["a", "b", "c"];
    const changed = ["a", "b", "c"];
    const raw = [["equal", 0, 1, 0, 1], ["replace", 1, 3, 1, 3]];
    assert.deepEqual(align.refineOpcodes(raw, old, changed), [["equal", 0, 3, 0, 3]]);
});

test("bad input returns the original opcodes", () => {
    const raw = [["replace", 0, 5, 0, 5]];
    assert.equal(align.refineOpcodes(raw, ["a"], ["b"]), raw); // indexes beyond the configs
    assert.equal(align.refineOpcodes(null, [], []), null);
    assert.equal(align.refineOpcodes(raw, null, []), raw);
});

// ---------- invariants on random blocks ----------

test("random replace blocks: every line is covered exactly once, in order", () => {
    let seed = 12345;
    const random = () => {
        seed = (seed * 1103515245 + 12345) & 0x7fffffff;
        return seed / 0x7fffffff;
    };
    const pool = [
        " description user", " description core", STORM3, STORM5, " undo shutdown", " shutdown",
        " port-security enable", " port-security aging-time 1", " speed 100", " speed 1000", "#", "quit",
        " ip address 10.0.0.1 255.255.255.0", " ip address 10.0.0.2 255.255.255.0",
    ];
    for (let trial = 0; trial < 400; trial++) {
        const m = 1 + Math.floor(random() * 12);
        const n = 1 + Math.floor(random() * 12);
        const old = Array.from({ length: m }, () => pool[Math.floor(random() * pool.length)]);
        const changed = Array.from({ length: n }, () => pool[Math.floor(random() * pool.length)]);
        const ops = align.alignReplace(old, changed, 0, m, 0, n);
        assertCoverage(ops, 0, m, 0, n);
        // paired lines are always at least as similar as the cutoff (or identical)
        pairsOf(ops).forEach(([i, j]) => {
            assert.ok(align.similarity(old[i], changed[j]) >= align.SIMILARITY_CUTOFF);
        });
    }
});

// ---------- big blocks ----------

function bigLines(count, tag) {
    return Array.from({ length: count }, (_, k) => " ip address 10." + tag + "." + (k % 250) + "." + k + " mask " + (k % 7));
}

test("a 100 x 100 block is aligned exhaustively and fast", () => {
    const old = bigLines(100, 1);
    const changed = bigLines(100, 2);
    const started = Date.now();
    const ops = align.alignReplace(old, changed, 0, 100, 0, 100);
    const elapsed = Date.now() - started;
    assertCoverage(ops, 0, 100, 0, 100);
    assert.ok(elapsed < 1000, "took " + elapsed + " ms");
});

test("a 2000-line block with 5 lines inserted on top keeps its alignment (windowed)", () => {
    const old = bigLines(2000, 1);
    const changed = [" snmp-agent a", " snmp-agent b", " snmp-agent c", " snmp-agent d", " snmp-agent e"].concat(
        old.map((line) => line + " x")
    );
    const started = Date.now();
    const ops = align.alignReplace(old, changed, 0, 2000, 0, 2005);
    const elapsed = Date.now() - started;
    assertCoverage(ops, 0, 2000, 0, 2005);
    // all the old lines are paired with their own edited copy (5 lines lower)
    const paired = ops.filter((op) => op[0] === "replace" && op[5] !== "plain").reduce((sum, op) => sum + (op[2] - op[1]), 0);
    assert.ok(paired > 1990, "paired " + paired);
    assert.ok(elapsed < 1500, "took " + elapsed + " ms");
});

test("a block bigger than the limit is not aligned: one plain replace", () => {
    const old = bigLines(3500, 1);
    const changed = bigLines(3500, 2);
    const ops = align.alignReplace(old, changed, 0, 3500, 0, 3500);
    assert.deepEqual(ops, [["replace", 0, 3500, 0, 3500, "plain"]]);
});
