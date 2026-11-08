"use strict";
const test = require("node:test");
const assert = require("node:assert");
const logic = require("../../site/logic.js");

const versions = ["24.4R1", "24.4R2", "25.2R1", "25.2R2", "25.4R1"].map((v) => ({ v, ...logic.releaseParts(v), changes: [], support: { supported: true } }));
const families = ["EX Series", "MX Series", "SRX Series"];

test("status follows the notes of the branch", () => {
  const bug = { events: [[0, "k"], [1, "r"], [2, "k"]] };
  assert.strictEqual(logic.statusAt(bug, 0, versions).key, "affected");
  assert.strictEqual(logic.statusAt(bug, 1, versions).key, "fixed");
  assert.strictEqual(logic.statusAt(bug, 2, versions).key, "affected");
  assert.strictEqual(logic.statusAt(bug, 3, versions).key, "unknown");
  assert.strictEqual(logic.statusAt({ events: [[3, "r"]] }, 2, versions).key, "potential");
});

test("hardware filter keeps the family bugs naming no model", () => {
  const cited = { models: ["MX204"], families: [1] };
  const other = { models: ["MX10003"], families: [1] };
  const family = { models: [], families: [1] };
  const elsewhere = { models: [], families: [0] };
  assert.strictEqual(logic.hardwareMatch(cited, "m:MX204", families), "cited");
  assert.strictEqual(logic.hardwareMatch(other, "m:MX204", families), null);
  assert.strictEqual(logic.hardwareMatch(family, "m:MX204", families), "family");
  assert.strictEqual(logic.hardwareMatch(elsewhere, "m:MX204", families), null);
  assert.strictEqual(logic.hardwareMatch(other, "f:MX Series", families), "family");
  assert.strictEqual(logic.selectedFamily("m:SRX4600", families), 2);
});

test("a PR number is found with or without its prefix", () => {
  const bug = { id: "1927951", text: "pr1927951 bgp flap" };
  assert.ok(logic.matchesTerms(bug, logic.searchTerms("PR1927951")));
  assert.ok(logic.matchesTerms(bug, logic.searchTerms("1927951, BGP")));
  assert.ok(!logic.matchesTerms(bug, logic.searchTerms("1927952")));
});

test("an upgrade crosses the R1 of each branch, then the target branch", () => {
  assert.deepStrictEqual(logic.upgradePath(versions, 0, 4).map((i) => versions[i].v), ["25.2R1", "25.4R1"]);
  assert.deepStrictEqual(logic.upgradePath(versions, 0, 3).map((i) => versions[i].v), ["25.2R1", "25.2R2"]);
  assert.deepStrictEqual(logic.upgradePath(versions, 0, 1).map((i) => versions[i].v), ["24.4R2"]);
  assert.deepStrictEqual(logic.upgradePath(versions, 2, 1), []);
});

test("changes are filtered by family and kept once per release", () => {
  const withChanges = versions.map((entry) => ({ ...entry, changes: entry.v === "25.2R1" ? [[1, "EVPN", "A", 3], [0, "EVPN", "A", 9], [0, "MPLS", "B", 10]] : [] }));
  assert.strictEqual(logic.versionChanges(withChanges, 0, 2).length, 2);
  assert.deepStrictEqual(logic.versionChanges(withChanges, 0, 2, 0).map((c) => c.text), ["A", "B"]);
});

test("support of a branch missing from the table", () => {
  const branches = { "25.4": { support: "2031-06-22" }, "24.4": { support: "2030-06-29" } };
  assert.ok(logic.branchSupport("26.2", branches, "2026-11-07").supported);
  assert.ok(!logic.branchSupport("23.3", branches, "2026-11-07").supported);
  assert.ok(logic.branchSupport("24.4", branches, "2026-11-07").supported);
});

test("a service release only carries the fixes of its own train", () => {
  const list = ["22.2R2", "22.2R2-S9", "22.2R3", "22.2R3-S6", "22.2R3-S7", "22.2R3-S8"].map((v) => ({ v, ...logic.releaseParts(v) }));
  const bug = { events: [[2, "k"], [4, "r"]] };
  assert.strictEqual(logic.statusAt(bug, 5, list).key, "fixed");
  assert.strictEqual(logic.statusAt(bug, 3, list).key, "potential");
  assert.strictEqual(logic.statusAt(bug, 3, list).detail.id, "openSince");
  assert.strictEqual(logic.statusAt(bug, 1, list).key, "potential");
  assert.strictEqual(logic.statusAt({ events: [[0, "r"]] }, 4, list).key, "fixed");
  assert.deepStrictEqual(logic.firstFixes([[0, "r"], [1, "r"], [4, "r"]], list), [0]);
  assert.deepStrictEqual(logic.firstFixes([[1, "r"], [4, "r"]], list), [4, 1]);
});

test("planned and article-less releases are not the latest one, nor a model's last release", () => {
  const list = ["24.4R2-S4", "24.4R2-S5", "24.4R2-S6", "24.4R2-S7"].map((v) => ({ v, ...logic.releaseParts(v), publication: null }));
  list[2].publication = "pending";
  list[3].publication = "pending";
  assert.strictEqual([...list].reverse().find(logic.isPublished).v, "24.4R2-S5");
  const summaries = logic.modelSummaries(["MX204"], [{ models: ["MX204"], events: [[0, "k"], [3, "r"]] }], list);
  assert.deepStrictEqual([summaries[0].first, summaries[0].last], ["24.4R2-S4", "24.4R2-S4"]);
});

test("Evolved releases are named with -EVO", () => {
  const list = ["24.4R2-S5", "24.4R2-S6"].map((v) => ({ v, name: `${v}-EVO`, ...logic.releaseParts(v) }));
  assert.strictEqual(logic.nameOf(list[0]), "24.4R2-S5-EVO");
  assert.strictEqual(logic.statusAt({ events: [[0, "r"]] }, 1, list).detail.version, "24.4R2-S5-EVO");
  assert.strictEqual(logic.nameOf({ v: "24.4R2-S5" }), "24.4R2-S5");
});
