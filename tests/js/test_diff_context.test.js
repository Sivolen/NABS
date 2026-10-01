/*
 * Tests of static/js/diff_context.js ("Show changed context" by config blocks).
 * Run: node --test tests/js/*.test.js   (Node.js 18+, no dependencies)
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const jsDir = path.join(__dirname, "..", "..", "app", "static", "js");
const dc = require(path.join(jsDir, "diff_context.js"));

// real opcodes, calculated by the bundled difflib.js (the server sends the same format)
vm.runInThisContext(fs.readFileSync(path.join(jsDir, "difflib.js"), "utf8"));
const difflibJs = vm.runInThisContext("difflib");

function opcodes(oldLines, newLines) {
    return new difflibJs.SequenceMatcher(oldLines, newLines).get_opcodes();
}

const lines = (text) => text.split("\n");

// the lines of a config that fall into the resolved ranges
function shown(config, ranges) {
    const result = [];
    ranges.forEach((r) => {
        for (let i = r[0]; i <= r[1]; i++) result.push(config[i]);
    });
    return result;
}

function resolve(oldText, newText, delimiters, contextLines) {
    const oldLines = lines(oldText);
    const newLines = lines(newText);
    const result = dc.resolveChangedContext(opcodes(oldLines, newLines), oldLines, newLines, {
        delimiters: delimiters,
        contextLines: contextLines === undefined ? 3 : contextLines,
    });
    return { result, oldLines, newLines };
}

const HUAWEI = [
    "#",
    "sysname device",
    "#",
    "info-center loghost 10.0.0.41",
    "info-center loghost 10.4.15.10",
    "#",
    "vlan batch 46 50",
    "#",
    "interface GigabitEthernet0/0/1",
    " description TEST",
    "#",
].join("\n");

const CISCO = [
    "!",
    "hostname router",
    "!",
    "interface GigabitEthernet0/1",
    " description TEST",
    " ip address 10.0.0.1 255.255.255.0",
    "!",
].join("\n");

// ---------- delimiters ----------

test("normalizeDelimiters: string, list, junk, spaces, duplicates", () => {
    assert.deepEqual(dc.normalizeDelimiters("#"), ["#"]);
    assert.deepEqual(dc.normalizeDelimiters([" ## ", "#", "#", "", 5, null]), ["##", "#"]);
    assert.deepEqual(dc.normalizeDelimiters(undefined), []);
    assert.deepEqual(dc.normalizeDelimiters({}), []);
});

test("a delimiter is a line that equals it after trim, not a line that contains it", () => {
    const config = ["#", "  #  ", "description Test #", "# comment", "!"];
    assert.deepEqual(dc.findDelimiterIndexes(config, ["#"]), [0, 1]);
    assert.deepEqual(dc.findDelimiterIndexes(["!", "description Interface !"], ["!"]), [0]);
});

test("several delimiters for one vendor", () => {
    assert.deepEqual(dc.findDelimiterIndexes(["#", "a", "!", "b", "##"], ["#", "!"]), [0, 2]);
});

test("nearest delimiter above / below (strictly)", () => {
    const idx = [0, 5, 18];
    assert.equal(dc.delimiterAbove(idx, 3), 0);
    assert.equal(dc.delimiterAbove(idx, 5), 0); // strictly above
    assert.equal(dc.delimiterAbove(idx, 0), -1);
    assert.equal(dc.delimiterBelow(idx, 3), 5);
    assert.equal(dc.delimiterBelow(idx, 5), 18); // strictly below
    assert.equal(dc.delimiterBelow(idx, 18), -1);
    assert.equal(dc.delimiterAbove([], 3), -1);
});

// ---------- ranges ----------

test("mergeRanges: overlapping, touching, separate, unsorted", () => {
    assert.deepEqual(dc.mergeRanges([[15, 25], [10, 20]]), [[10, 25]]);
    assert.deepEqual(dc.mergeRanges([[10, 20], [21, 30]]), [[10, 30]]);
    assert.deepEqual(dc.mergeRanges([[10, 20], [22, 30]]), [[10, 20], [22, 30]]);
    assert.deepEqual(dc.mergeRanges([[1, 9], [2, 3]]), [[1, 9]]);
    assert.deepEqual(dc.mergeRanges([]), []);
});

test("changedLinesFromOpcodes: replace / insert / delete", () => {
    const codes = [
        ["equal", 0, 2, 0, 2],
        ["replace", 2, 4, 2, 3],
        ["insert", 4, 4, 3, 5],
        ["delete", 4, 6, 5, 5],
    ];
    assert.deepEqual(dc.changedLinesFromOpcodes(codes), {
        old: [2, 3, 4, 5],
        new: [2, 3, 4],
    });
});

// ---------- Huawei ----------

test("Huawei: a change inside info-center shows exactly that block", () => {
    const changed = HUAWEI.replace("10.4.15.10", "10.4.15.11");
    const { result, oldLines, newLines } = resolve(HUAWEI, changed, ["#"]);
    const expectedOld = ["#", "info-center loghost 10.0.0.41", "info-center loghost 10.4.15.10", "#"];
    const expectedNew = ["#", "info-center loghost 10.0.0.41", "info-center loghost 10.4.15.11", "#"];
    assert.deepEqual(shown(oldLines, result.oldRanges), expectedOld);
    assert.deepEqual(shown(newLines, result.newRanges), expectedNew);
});

test("change at the start of a block (sysname)", () => {
    const changed = HUAWEI.replace("sysname device", "sysname NEW");
    const { result, oldLines, newLines } = resolve(HUAWEI, changed, ["#"]);
    assert.deepEqual(shown(oldLines, result.oldRanges), ["#", "sysname device", "#"]);
    assert.deepEqual(shown(newLines, result.newRanges), ["#", "sysname NEW", "#"]);
});

test("change at the end of a block", () => {
    const old = "#\nundo http server enable\nhttp server-source -i MEth0/0/1\n#\nvlan batch 1\n#";
    const changed = old.replace("MEth0/0/1", "MEth0/0/2");
    const { result, oldLines } = resolve(old, changed, ["#"]);
    assert.deepEqual(shown(oldLines, result.oldRanges), [
        "#",
        "undo http server enable",
        "http server-source -i MEth0/0/1",
        "#",
    ]);
});

test("several changes in ONE block give one range (no duplicates)", () => {
    const old = "#\ninterface Gi0/0/1\n description OLD\n ip address 10.10.10.1 255.255.255.0\n undo shutdown\n#";
    const changed = old.replace("OLD", "NEW").replace("10.10.10.1", "10.10.10.2");
    const { result } = resolve(old, changed, ["#"]);
    assert.deepEqual(result.oldRanges, [[0, 5]]);
    assert.deepEqual(result.newRanges, [[0, 5]]);
});

test("several changed blocks are shown separately, once each", () => {
    const changed = HUAWEI.replace("sysname device", "sysname X").replace("vlan batch 46 50", "vlan batch 46 51");
    const { result } = resolve(HUAWEI, changed, ["#"]);
    // sysname block: lines 0-2, vlan block: lines 5-7
    assert.deepEqual(result.oldRanges, [[0, 2], [5, 7]]);
});

test("adjacent changed blocks are merged into one range", () => {
    const changed = HUAWEI.replace("sysname device", "sysname X").replace("10.0.0.41", "10.0.0.42");
    const { result } = resolve(HUAWEI, changed, ["#"]);
    // blocks 0-2 and 2-5 share the delimiter on line 2
    assert.deepEqual(result.oldRanges, [[0, 5]]);
});

// ---------- Cisco ----------

test("Cisco: the whole interface block", () => {
    const changed = CISCO.replace("10.0.0.1", "10.0.0.2");
    const { result, oldLines, newLines } = resolve(CISCO, changed, ["!"]);
    assert.deepEqual(shown(oldLines, result.oldRanges), [
        "!",
        "interface GigabitEthernet0/1",
        " description TEST",
        " ip address 10.0.0.1 255.255.255.0",
        "!",
    ]);
    assert.equal(shown(newLines, result.newRanges)[3], " ip address 10.0.0.2 255.255.255.0");
});

// ---------- added / deleted blocks ----------

test("added block: shown completely in the new config only", () => {
    const added = HUAWEI + "\ninterface GigabitEthernet0/0/10\n description NEW\n#";
    const { result, newLines } = resolve(HUAWEI, added, ["#"]);
    assert.deepEqual(shown(newLines, result.newRanges), [
        "#",
        "interface GigabitEthernet0/0/10",
        " description NEW",
        "#",
    ]);
    assert.deepEqual(result.oldRanges, []);
});

test("deleted block: shown completely in the old config only", () => {
    const removed = HUAWEI.replace("vlan batch 46 50\n#\n", "");
    const { result, oldLines } = resolve(HUAWEI, removed, ["#"]);
    const text = shown(oldLines, result.oldRanges);
    assert.ok(text.includes("vlan batch 46 50"));
    assert.equal(text[0], "#");
    assert.equal(text[text.length - 1], "#");
});

// ---------- fallback ----------

test("no delimiters configured for the vendor -> null (use N rows)", () => {
    const { result } = resolve("a\nb\nc", "a\nX\nc", []);
    assert.equal(result, null);
});

test("delimiters configured but absent in both configs -> null (use N rows)", () => {
    const plain = "line 1\nline 2\nline 3\nline 4\nline 5\nline 6\nline 7";
    const { result } = resolve(plain, plain.replace("line 4", "CHANGED"), ["#"]);
    assert.equal(result, null);
});

test("nothing changed -> null", () => {
    const { result } = resolve(HUAWEI, HUAWEI, ["#"]);
    assert.equal(result, null);
});

test("delimiter only ABOVE the change: lower side falls back to N lines / config end", () => {
    const config = ["#", "line 1", "line 2", "CHANGED", "line 4", "line 5", "line 6", "line 7", "line 8"];
    const r = dc.blockRanges(config, [3], ["#"], 2);
    assert.equal(r.hasDelimiters, true);
    assert.deepEqual(r.ranges, [[0, 5]]); // up to the delimiter, 2 lines below
    const r2 = dc.blockRanges(config, [3], ["#"], 50);
    assert.deepEqual(r2.ranges, [[0, 8]]); // never beyond the config end
});

test("delimiter only BELOW the change: upper side falls back to N lines / config start", () => {
    const config = ["line 0", "line 1", "line 2", "line 3", "CHANGED", "line 5", "#", "x"];
    assert.deepEqual(dc.blockRanges(config, [4], ["#"], 2).ranges, [[2, 6]]);
    assert.deepEqual(dc.blockRanges(config, [4], ["#"], 50).ranges, [[0, 6]]);
});

test("one config has delimiters, the other has none: no crash, both sides resolved", () => {
    const oldText = "line 1\nline 2\nline 3";
    const newText = "#\nline 1\nline 2 CHANGED\nline 3\n#";
    const { result } = resolve(oldText, newText, ["#"], 1);
    assert.notEqual(result, null);
    assert.ok(result.newRanges.length > 0);
});

// ---------- consecutive delimiters ----------

test("consecutive delimiters do not create duplicate blocks", () => {
    const config = "#\n#\ninterface Gi0/0/1\n description OLD\n#\n#";
    const { result, oldLines } = resolve(config, config.replace("OLD", "NEW"), ["#"]);
    assert.deepEqual(result.oldRanges, [[1, 4]]);
    assert.deepEqual(shown(oldLines, result.oldRanges), ["#", "interface Gi0/0/1", " description OLD", "#"]);
});

test("a changed delimiter line shows the blocks on both of its sides", () => {
    const old = "#\na\n#\nb\n#";
    const changed = "#\na\nb\n#"; // the middle "#" is removed
    const { result } = resolve(old, changed, ["#"]);
    assert.deepEqual(result.oldRanges, [[0, 4]]);
});

test("config that starts / ends with a change and has no trailing delimiter", () => {
    const old = "#\na\nb\n#\nc\nd";
    const changed = "#\na\nb\n#\nc\nD";
    const { result } = resolve(old, changed, ["#"], 1);
    assert.deepEqual(result.oldRanges, [[3, 5]]); // delimiter above + config end
});

// ---------- masks / performance ----------

test("rangesToMask marks exactly the lines of the ranges", () => {
    assert.deepEqual(Array.from(dc.rangesToMask([[1, 2], [4, 4]], 6)), [0, 1, 1, 0, 1, 0]);
    assert.deepEqual(Array.from(dc.rangesToMask([[3, 99]], 5)), [0, 0, 0, 1, 1]); // clipped
});

test("100 000 lines with many changes resolve fast (delimiters found once)", () => {
    const big = [];
    for (let block = 0; block < 20000; block++) {
        big.push("#", "interface Gi0/0/" + block, " description B" + block, " undo shutdown", " speed auto");
    }
    big.push("#");
    const changedLines = [];
    for (let i = 2; i < big.length; i += 250) changedLines.push(i);

    const started = Date.now();
    const r = dc.blockRanges(big, changedLines, ["#"], 3);
    const elapsed = Date.now() - started;
    assert.ok(r.ranges.length > 0);
    assert.ok(elapsed < 1000, "took " + elapsed + " ms");
});

// ---------- diff_page.js glue ----------

require(path.join(jsDir, "diff_page.js"));
const page = globalThis.diffPage;

test("contextRowsFrom: DIFF_CONTEXT_LINES from the page data or the default 3", () => {
    assert.equal(page.contextRowsFrom({ context_lines: 5 }), 5);
    assert.equal(page.contextRowsFrom({ context_lines: 0 }), 0);
    assert.equal(page.contextRowsFrom({ context_lines: "x" }), 3);
    assert.equal(page.contextRowsFrom({ context_lines: -1 }), 3);
    assert.equal(page.contextRowsFrom(undefined), 3);
});

test("visibleRowsByBlocks: a row is shown if its old OR new line is in a range", () => {
    const context = {
        oldMask: Uint8Array.from([1, 1, 0, 0]),
        newMask: Uint8Array.from([0, 0, 0, 1, 1]),
    };
    const rows = [
        [0, 0], // equal row, old line is in a range      -> shown
        [1, null], // deleted line in an old block        -> shown
        [2, 2], // equal row, outside of both ranges      -> hidden
        [3, null], // deleted line outside of old ranges  -> hidden
        [null, 3], // inserted line in a new block        -> shown
        [null, null], // "..." separator                  -> hidden
    ];
    assert.deepEqual(Array.from(page.visibleRowsByBlocks(rows, context)).sort(), [0, 1, 4]);
});

// ---------- changed delimiter (added / removed / replaced) ----------

// Builds the rows of the diff table like diff_table.js does (equal / replace /
// insert / delete -> [oldIndex|null, newIndex|null]) and returns the lines that
// the block context shows on each side. This is the path "opcodes -> ranges ->
// masks -> rows" that both Side by Side and Inline use.
function shownRows(oldText, newText, delimiters, contextLines) {
    const oldLines = lines(oldText);
    const newLines = lines(newText);
    const codes = opcodes(oldLines, newLines);
    const context = dc.resolveChangedContext(codes, oldLines, newLines, {
        delimiters: delimiters,
        contextLines: contextLines === undefined ? 3 : contextLines,
    });
    const rows = [];
    codes.forEach((code) => {
        const oldCount = code[2] - code[1];
        const newCount = code[4] - code[3];
        if (code[0] === "equal") {
            for (let k = 0; k < oldCount; k++) rows.push([code[1] + k, code[3] + k]);
        } else {
            for (let k = 0; k < oldCount; k++) rows.push([code[1] + k, null]);
            for (let k = 0; k < newCount; k++) rows.push([null, code[3] + k]);
        }
    });
    const visible = page.visibleRowsByBlocks(rows, context);
    return { context, rows, visible, oldLines, newLines };
}

test("delimiter REMOVED: both neighbouring blocks are shown (whole range)", () => {
    const old = "#\ninterface Gi0/0/1\n description TEST\n#\ninterface Gi0/0/2\n description TEST2\n#";
    const changed = "#\ninterface Gi0/0/1\n description TEST\ninterface Gi0/0/2\n description TEST2\n#";
    const { result, oldLines } = resolve(old, changed, ["#"]);
    assert.deepEqual(result.oldRanges, [[0, 6]]); // not just the "#" line
    assert.deepEqual(shown(oldLines, result.oldRanges), oldLines);
    assert.deepEqual(result.newRanges, []); // nothing on the new side is changed
});

test("delimiter ADDED: the block that was split is shown completely", () => {
    const old = "#\nblock A\nblock B\n#";
    const changed = "#\nblock A\n#\nblock B\n#";
    const { result, newLines } = resolve(old, changed, ["#"]);
    assert.deepEqual(result.newRanges, [[0, 4]]);
    assert.deepEqual(shown(newLines, result.newRanges), newLines);

    // and the table rows: every row of the diff is visible (old side has no changed lines)
    const t = shownRows(old, changed, ["#"]);
    assert.equal(t.visible.size, t.rows.length);
});

test("delimiter REPLACED (# -> !) for Huawei: the change is in the context", () => {
    const old = "#\nsysname A\n#\nvlan batch 1\n#\ninterface Gi0/0/1\n#";
    const changed = "#\nsysname A\n!\nvlan batch 1\n#\ninterface Gi0/0/1\n#";
    const t = shownRows(old, changed, ["#"]);
    // old side: the replaced "#" is a delimiter -> blocks on both sides (lines 0..4)
    assert.deepEqual(t.context.oldRanges, [[0, 4]]);
    // new side: "!" is an ordinary line of the merged block between "#" (0) and "#" (4)
    assert.deepEqual(t.context.newRanges, [[0, 4]]);
    // the changed rows are visible, the untouched last block is not
    const changedRows = t.rows
        .map((r, i) => [r, i])
        .filter(([r]) => r[0] === 2 || r[1] === 2)
        .map(([, i]) => i);
    changedRows.forEach((i) => assert.ok(t.visible.has(i)));
    const lastRow = t.rows.findIndex((r) => r[0] === 5);
    assert.ok(!t.visible.has(lastRow));
});

test("delimiter replaced with ANOTHER configured delimiter (# -> !, both configured)", () => {
    const old = "#\na\n#\nb\n#";
    const changed = "#\na\n!\nb\n#";
    const { result } = resolve(old, changed, ["#", "!"]);
    assert.deepEqual(result.oldRanges, [[0, 4]]);
    assert.deepEqual(result.newRanges, [[0, 4]]);
});

test("changed delimiter at the config edge does not crash", () => {
    const old = "#\na\nb";
    const changed = "a\nb"; // the first "#" removed
    const { result } = resolve(old, changed, ["#"], 1);
    assert.notEqual(result, null);
    assert.deepEqual(result.oldRanges, [[0, 1]]); // no delimiter above: N lines below
    const old2 = "a\nb\n#";
    const { result: r2 } = resolve(old2, "a\nb", ["#"], 1);
    assert.deepEqual(r2.oldRanges, [[1, 2]]); // no delimiter below: N lines above
});

// ---------- delimiter must be a separate line (both vendors) ----------

test("Huawei '#': 'description Test #' is an ordinary line", () => {
    const config = ["#", "description Test #", "#"];
    assert.deepEqual(dc.findDelimiterIndexes(config, ["#"]), [0, 2]);
});

test("Cisco '!': 'description Test !' is an ordinary line", () => {
    const config = ["!", "description Test !", "!", " ! indented comment", "  !  "];
    assert.deepEqual(dc.findDelimiterIndexes(config, ["!"]), [0, 2, 4]);
});

test("a change in 'description Test !' stays inside its block", () => {
    const old = "!\ninterface Gi0/1\n description Test !\n!\nhostname r1\n!";
    const { result, oldLines } = resolve(old, old.replace("Test !", "Test 2 !"), ["!"]);
    assert.deepEqual(shown(oldLines, result.oldRanges), [
        "!",
        "interface Gi0/1",
        " description Test !",
        "!",
    ]);
});

// ---------- consecutive delimiters ----------

test("consecutive delimiters: one range, no empty or duplicated blocks", () => {
    const config = "#\n#\ninterface Gi0/0/1\n description TEST\n#\n#";
    const t = shownRows(config, config.replace("TEST", "PROD"), ["#"]);
    assert.deepEqual(t.context.oldRanges, [[1, 4]]);
    assert.deepEqual(t.context.newRanges, [[1, 4]]);
    // every row is shown once: visible rows are unique row indexes of lines 1..4
    const shownOld = t.rows.filter((r, i) => t.visible.has(i)).map((r) => r[0]).filter((x) => x !== null);
    assert.deepEqual(shownOld, [1, 2, 3, 4]);
});

test("changed delimiter among consecutive delimiters", () => {
    const old = "#\n#\n#\na\n#";
    const changed = "#\n#\na\n#"; // one of the repeated "#" removed
    const { result } = resolve(old, changed, ["#"]);
    assert.ok(result.oldRanges.length === 1);
    // never a zero-length or inverted range
    result.oldRanges.forEach((r) => assert.ok(r[0] <= r[1]));
});

// ---------- Side by Side and Inline use the SAME resolver result ----------

test("the same masks drive both views: old/new lines shown do not depend on the view", () => {
    const changed = HUAWEI.replace("10.4.15.10", "10.4.15.11").replace("vlan batch 46 50", "vlan batch 46 51");
    const t = shownRows(HUAWEI, changed, ["#"]);
    // One resolver call gives one pair of masks; the renderers only read them.
    // Re-resolving must give the identical result (pure, no hidden state).
    const again = shownRows(HUAWEI, changed, ["#"]);
    assert.deepEqual(Array.from(t.context.oldMask), Array.from(again.context.oldMask));
    assert.deepEqual(Array.from(t.context.newMask), Array.from(again.context.newMask));
    assert.deepEqual(Array.from(t.visible), Array.from(again.visible));
});

// ---------- fallback is still there ----------

test("fallback: unknown vendor (no delimiters) and plain config -> null, N rows mode", () => {
    assert.equal(resolve("a\nb\nc\nd", "a\nb\nX\nd", []).result, null);
    const plain = "l1\nl2\nl3\nl4\nl5\nl6\nl7";
    assert.equal(resolve(plain, plain.replace("l4", "CHANGED"), ["#"]).result, null);
    // the N rows helper used by the page
    const visible = page.expandWithContext([3], 7, 2, 2);
    assert.deepEqual(Array.from(visible).sort(), [1, 2, 3, 4, 5]);
});

// ---------- very long blocks are cut around the change ----------

// 0 "#", 1 "sysname r", 2 "#", 3 "bgp 65000", 4 " router-id", 5 " ipv4-family vpn-instance X",
// 6..6+n-1 "  peer 10.0.0.<i> enable", 6+n "#", 7+n "return"
function bgpBlock(n) {
    const result = ["#", "sysname r", "#", "bgp 65000", " router-id 1.1.1.1", " ipv4-family vpn-instance X"];
    for (let i = 0; i < n; i++) result.push("  peer 10.0.0." + i + " enable");
    result.push("#", "return");
    return result;
}

function cut(oldLines, newLines, maxBlockLines, contextLines) {
    return dc.resolveChangedContext(opcodes(oldLines, newLines), oldLines, newLines, {
        delimiters: ["#"],
        contextLines: contextLines === undefined ? 3 : contextLines,
        maxBlockLines: maxBlockLines,
    });
}

function changeAt(config, index, text) {
    const copy = config.slice();
    copy[index] = text === undefined ? copy[index] + " CHANGED" : text;
    return copy;
}

test("block within the limit is shown completely", () => {
    const old = bgpBlock(10); // block 2..16 = 15 lines
    const result = cut(old, changeAt(old, 10), 30);
    assert.deepEqual(result.oldRanges, [[2, 16]]);
});

test("block exactly at the limit is whole, one line more is cut", () => {
    const old = bgpBlock(100); // block 2..106 = 105 lines
    const changed = changeAt(old, 56);
    assert.deepEqual(cut(old, changed, 105).oldRanges, [[2, 106]]);
    assert.deepEqual(cut(old, changed, 104).oldRanges, [[2, 5], [53, 59], [106, 106]]);
});

test("limit 0 / absent never cuts", () => {
    const old = bgpBlock(500);
    const changed = changeAt(old, 250);
    assert.deepEqual(cut(old, changed, 0).oldRanges, [[2, 506]]);
    assert.deepEqual(cut(old, changed, undefined).oldRanges, [[2, 506]]);
});

test("cut block: delimiters, header, parent lines, window", () => {
    const old = bgpBlock(100);
    const changed = changeAt(old, 56);
    const result = cut(old, changed, 30);
    // "#"(2) + "bgp 65000"(3) + " ipv4-family ..."(5, the parent; 1 line gap joined)
    // + 3 lines around the change + closing "#"(106)
    assert.deepEqual(result.oldRanges, [[2, 5], [53, 59], [106, 106]]);
    assert.deepEqual(shown(old, result.oldRanges).slice(0, 4), [
        "#",
        "bgp 65000",
        " router-id 1.1.1.1",
        " ipv4-family vpn-instance X",
    ]);
    assert.equal(old[106], "#");
});

test("cut block: the parent chain follows the indentation", () => {
    const old = [
        "#",
        "bgp 65000",
        " ipv4-family vpn-instance A",
        "  peer 1.1.1.1 enable",
        " ipv4-family vpn-instance B",
        "  peer 2.2.2.2 enable",
        "  peer 2.2.2.3 enable",
    ];
    for (let i = 0; i < 60; i++) old.push("  peer 3.3.3." + i + " enable");
    old.push("#");
    const changed = changeAt(old, 6); // "  peer 2.2.2.3 enable" inside family B
    const result = cut(old, changed, 20, 1);
    const lines = shown(old, result.oldRanges);
    assert.ok(lines.includes(" ipv4-family vpn-instance B")); // parent
    assert.ok(lines.includes("bgp 65000")); // grand parent / header
    assert.ok(!lines.includes(" ipv4-family vpn-instance A")); // a sibling section
    assert.ok(!lines.includes("  peer 1.1.1.1 enable"));
});

test("cut block: a top-level change in the block has no parents, only header", () => {
    const old = bgpBlock(100);
    const changed = changeAt(old, 3, "bgp 65001");
    const result = cut(old, changed, 30);
    assert.deepEqual(result.oldRanges, [[2, 6], [106, 106]]);
});

test("cut block: several changes share the header and closing delimiter", () => {
    const old = bgpBlock(100);
    const changed = changeAt(changeAt(old, 20), 80);
    const result = cut(old, changed, 30);
    assert.deepEqual(result.oldRanges, [[2, 5], [17, 23], [77, 83], [106, 106]]);
});

test("cut block: a skipped gap of ONE line is shown instead of a '1 hidden line' row", () => {
    const old = bgpBlock(100);
    // windows of 3 around lines 20 and 28: 17..23 and 25..31 -> one line (24) between
    const changed = changeAt(changeAt(old, 20), 28);
    const result = cut(old, changed, 30);
    assert.deepEqual(result.oldRanges, [[2, 5], [17, 31], [106, 106]]);
    // two lines between are still a gap
    const changed2 = changeAt(changeAt(old, 20), 29);
    assert.deepEqual(cut(old, changed2, 30).oldRanges, [[2, 5], [17, 23], [26, 32], [106, 106]]);
});

test("cut block: a change near the header merges with it", () => {
    const old = bgpBlock(100);
    const result = cut(old, changeAt(old, 7), 30);
    assert.deepEqual(result.oldRanges, [[2, 10], [106, 106]]);
});

test("cut block: header skips blank lines", () => {
    const old = ["#", "", "  ", "interface Gi0/0/1"];
    for (let i = 0; i < 60; i++) old.push(" ip address 10.0.0." + i);
    old.push("#");
    const result = cut(old, changeAt(old, 40), 20);
    assert.ok(shown(old, result.oldRanges).includes("interface Gi0/0/1"));
});

test("cut block: only the upper delimiter exists - window plus the header, no crash", () => {
    const old = ["#", "interface Gi0/0/1"];
    for (let i = 0; i < 80; i++) old.push(" ip address 10.0.0." + i);
    const result = cut(old, changeAt(old, 50), 20);
    assert.deepEqual(result.oldRanges, [[0, 1], [47, 53]]);
});

test("cut block: a changed delimiter inside a long range still gets its window", () => {
    const old = ["#", "a"];
    for (let i = 0; i < 40; i++) old.push(" x" + i);
    old.push("#", "b");
    for (let i = 0; i < 40; i++) old.push(" y" + i);
    old.push("#");
    const changed = old.filter((line, i) => i !== 42); // the middle "#" is removed
    const result = cut(old, changed, 30);
    const lines = shown(old, result.oldRanges);
    assert.ok(lines.includes("b"));
    assert.ok(result.oldRanges.some((r) => r[0] <= 42 && 42 <= r[1]));
});

test("an added huge block is shown completely (all of its lines are changed)", () => {
    const old = bgpBlock(5);
    const added = ["#", "interface Vlanif100"];
    for (let i = 0; i < 200; i++) added.push(" ip address 10.9.9." + i);
    added.push("#");
    const grown = old.concat(added);
    const result = cut(old, grown, 30);
    const covered = new Set();
    result.newRanges.forEach((r) => {
        for (let i = r[0]; i <= r[1]; i++) covered.add(i);
    });
    for (let i = old.length; i < grown.length; i++) assert.ok(covered.has(i), "line " + i);
    assert.deepEqual(result.oldRanges, []);
});

test("table rows: a cut block hides the middle rows of Side by Side / Inline rows", () => {
    const old = bgpBlock(100);
    const changed = changeAt(old, 56);
    const codes = opcodes(old, changed);
    const context = dc.resolveChangedContext(codes, old, changed, {
        delimiters: ["#"],
        contextLines: 3,
        maxBlockLines: 30,
    });
    // equal rows carry both indexes, the changed pair is one "replace" row
    const rows = old.map((_, i) => [i, i]);
    const visible = page.visibleRowsByBlocks(rows, context);
    assert.deepEqual(Array.from(visible).sort((a, b) => a - b), [2, 3, 4, 5, 53, 54, 55, 56, 57, 58, 59, 106]);
});

// ---------- performance of the cut path ----------

// The opcodes come from the server in the real page, so only the resolver is timed.
function timedCut(oldLines, newLines) {
    const codes = opcodes(oldLines, newLines);
    const started = Date.now();
    const result = dc.resolveChangedContext(codes, oldLines, newLines, {
        delimiters: ["#"],
        contextLines: 3,
        maxBlockLines: 30,
    });
    return { result, elapsed: Date.now() - started };
}

test("a block of 100 000 lines with scattered changes is cut fast", () => {
    const old = bgpBlock(100000);
    const changed = old.slice();
    for (let i = 500; i < 99000; i += 997) changed[i] += " X";
    const { result, elapsed } = timedCut(old, changed);
    assert.ok(result.oldRanges.length > 50);
    assert.ok(elapsed < 500, "took " + elapsed + " ms");
});

test("a block of 50 000 changed lines (every line differs) is not quadratic", () => {
    const old = bgpBlock(50000);
    const changed = old.map((line, i) => (i >= 6 && i < 50006 ? line + " X" : line));
    const { result, elapsed } = timedCut(old, changed);
    assert.deepEqual(result.oldRanges, [[2, 50006]]);
    assert.ok(elapsed < 1000, "took " + elapsed + " ms");
});

// ---------- "hidden lines" row: helpers of diff_page.js ----------

test("maxBlockLinesFrom: server value, 0 allowed, default 30", () => {
    assert.equal(page.maxBlockLinesFrom({ max_block_lines: 50 }), 50);
    assert.equal(page.maxBlockLinesFrom({ max_block_lines: 0 }), 0);
    assert.equal(page.maxBlockLinesFrom({}), 30);
    assert.equal(page.maxBlockLinesFrom({ max_block_lines: -3 }), 30);
    assert.equal(page.maxBlockLinesFrom({ max_block_lines: "x" }), 30);
    assert.equal(page.maxBlockLinesFrom(undefined), 30);
});

test("hiddenLabel: singular and plural", () => {
    assert.equal(page.hiddenLabel(1), "1 hidden line");
    assert.equal(page.hiddenLabel(120), "120 hidden lines");
});

test("gapRowsToReveal: top / bottom / all, never beyond the gap", () => {
    assert.deepEqual(page.gapRowsToReveal(10, 100, "top", 3), [10, 11, 12]);
    assert.deepEqual(page.gapRowsToReveal(10, 100, "bottom", 3), [98, 99, 100]);
    assert.deepEqual(page.gapRowsToReveal(10, 12, "all", 25), [10, 11, 12]);
    assert.deepEqual(page.gapRowsToReveal(10, 12, "top", 25), [10, 11, 12]);
    assert.deepEqual(page.gapRowsToReveal(10, 12, "bottom", 25), [10, 11, 12]);
    assert.deepEqual(page.gapRowsToReveal(5, 5, "all", 25), [5]);
});
