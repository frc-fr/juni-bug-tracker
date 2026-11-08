"use strict";
// What the site concludes from the notes, kept apart from the page so it can be tested.

/** The release as Juniper writes it: Junos OS Evolved releases end with -EVO, as 24.4R2-S5-EVO. */
function nameOf(entry) {
  return entry.name || entry.v;
}

/** Train, R number and service number of a release: 22.2R3-S7 is train 22.2R3, R 3, S 7. */
function releaseParts(version) {
  const match = version.match(/^(\d+\.\d+)R(\d+)(?:-S(\d+))?$/);
  return { branch: match[1], train: `${match[1]}R${match[2]}`, r: Number(match[2]), s: Number(match[3] || 0) };
}

/**
 * Whether a fix in one release is in another of the same branch. An R release
 * carries the fixes of the earlier R releases; a service release only carries
 * those of its own train: 22.2R3-S7 is in 22.2R3-S8, not in 22.2R2-S9 nor in 22.2R4.
 */
function covers(fix, target) {
  if (fix.branch !== target.branch) return false;
  if (fix.s === 0) return fix.r <= target.r;
  return fix.train === target.train && fix.s <= target.s;
}

/** Status of a bug on one release, from what the notes of its branch say. */
function statusAt(bug, index, versions) {
  const target = versions[index];
  const own = bug.events.filter(([v]) => versions[v].branch === target.branch);
  if (own.some(([v, status]) => v === index && status !== "r")) return { key: "affected" };

  const fixed = own.find(([v, status]) => status === "r" && covers(versions[v], target));
  if (fixed) return { key: "fixed", detail: { id: "fixedSince", version: nameOf(versions[fixed[0]]) } };

  // Open in a release this one derives from, with no fix documented on the way.
  // Only for a service release: an R note that drops an open issue may have fixed it silently.
  const inherited = target.s > 0 && [...own].reverse().find(([v, status]) => status !== "r" && v !== index && covers(versions[v], target));
  if (inherited) return { key: "potential", detail: { id: "openSince", version: nameOf(versions[inherited[0]]) } };

  const fixedLater = own.find(([v, status]) => status === "r" && v > index);
  if (fixedLater) return { key: "potential", detail: { id: "fixedIn", version: nameOf(versions[fixedLater[0]]) } };

  const knownLater = own.find(([v]) => v > index);
  if (knownLater) return { key: "potential", detail: { id: "knownIn", version: nameOf(versions[knownLater[0]]) } };

  if (own.length) {
    const last = own[own.length - 1][0];
    return { key: "unknown", detail: { id: "dropped", version: nameOf(versions[last]) } };
  }
  return { key: "unknown", detail: { id: "noMention" } };
}

/** The first fix of each train, newest first, as positions in the list of releases. */
function firstFixes(events, versions) {
  const found = new Map();
  for (const [v, status] of events) {
    if (status !== "r") continue;
    const { train } = versions[v];
    if (!found.has(train)) found.set(train, v);
  }
  // A fix in an R release already covers the later R releases of its branch.
  const kept = [...found.values()].filter((v) => ![...found.values()].some((other) => other !== v && versions[other].s === 0 && covers(versions[other], versions[v])));
  return kept.sort((a, b) => b - a);
}

function compareBranches(a, b) {
  const [majorA, minorA] = a.split(".").map(Number);
  const [majorB, minorB] = b.split(".").map(Number);
  return majorA - majorB || minorA - minorB;
}

/** Support on a date. A branch missing from the table: older ones ended, newer ones are not dated yet. */
function branchSupport(branch, branches, today) {
  const dates = branches[branch];
  if (dates) return { ...dates, supported: today <= dates.support };
  return { supported: Object.keys(branches).every((listed) => compareBranches(branch, listed) > 0) };
}

/** Branches where the notes mention a bug and which are still supported, newest first. */
function supportedBranches(events, versions) {
  const branches = new Set(events.map(([version]) => versions[version]).filter((entry) => entry.support.supported).map((entry) => entry.branch));
  return [...branches].sort(compareBranches).reverse();
}

/** "MX Series" for MX204: the letters of a model name its family. */
function modelFamily(model) {
  return `${model.match(/^[A-Z]+/)[0]} Series`;
}

/**
 * Inclusive filter. The selection is "f:<family>" or "m:<model>".
 * "cited": the text names the model. "family": the bug is in the chapter of the
 * family, or the text names it, without naming one of its models.
 */
function hardwareMatch(bug, selection, families) {
  if (!selection) return "all";
  const kind = selection.slice(0, 1);
  const name = selection.slice(2);
  const family = families.indexOf(kind === "f" ? name : modelFamily(name));
  // A PR known from a service release may name no hardware at all: it stays, as generic.
  if (!bug.families.length && !bug.models.length) return "generic";
  if (kind === "f") return bug.families.includes(family) ? "family" : null;
  if (bug.models.includes(name)) return "cited";
  if (bug.models.some((model) => families.indexOf(modelFamily(model)) === family)) return null;
  return bug.families.includes(family) ? "family" : null;
}

/** Family of a selection, as a position in the list of families, or -1. */
function selectedFamily(selection, families) {
  if (!selection) return -1;
  const name = selection.slice(2);
  return families.indexOf(selection.startsWith("f:") ? name : modelFamily(name));
}

function searchTerms(query) {
  return query.toLowerCase().split(/[\s,;]+/).filter(Boolean);
}

const PR_TERM = /^(?:pr)?(\d{6,8})$/;

function isPrTerm(term) {
  return PR_TERM.test(term);
}

function matchesTerms(bug, terms) {
  return terms.every((term) => {
    const number = term.match(PR_TERM);
    return number ? bug.id === number[1] : bug.text.includes(term);
  });
}

function upgradeGroup(bug, from, to, versions) {
  const before = statusAt(bug, from, versions).key;
  const after = statusAt(bug, to, versions).key;
  if (after === "fixed" && before !== "fixed") return "gained";
  if (after === "affected") return before === "affected" ? "remaining" : "introduced";
  return null;
}

/**
 * Releases crossed by an upgrade: the R1 of each later branch up to the target
 * branch, then the releases of the target branch up to the target.
 */
function upgradePath(versions, from, to) {
  if (from >= to) return [];
  const target = versions[to].branch;
  const start = versions[from].branch;
  const firsts = new Map();
  versions.forEach((entry, index) => {
    if (!firsts.has(entry.branch)) firsts.set(entry.branch, index);
  });
  const path = [];
  for (let index = from + 1; index <= to; index += 1) {
    const branch = versions[index].branch;
    if (branch === target || (branch !== start && firsts.get(branch) === index)) path.push(index);
  }
  return path;
}

/** Changes of behavior met on the way, for the selected family when there is one. */
function versionChanges(versions, from, to, family = -1) {
  const found = new Map();
  for (const index of upgradePath(versions, from, to)) {
    const entry = versions[index];
    for (const [changeFamily, category, text, page] of entry.changes) {
      if (family >= 0 && changeFamily !== family) continue;
      // The same change is written once per family chapter: keep its first occurrence.
      const key = `${entry.v} ${text}`;
      if (!found.has(key)) found.set(key, { family: changeFamily, category, text, page, entry });
    }
  }
  return [...found.values()];
}

/** Upgrade chapters of the target release, for the selected family or common to all. */
function upgradeNotices(notices, versions, to, family = -1) {
  const seen = new Set();
  return (notices[versions[to].v] || [])
    .filter(([noticeFamily]) => noticeFamily === null || family < 0 || noticeFamily === family)
    .filter(([, title]) => {
      const key = title.toLowerCase();
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .map(([noticeFamily, title, page]) => ({ family: noticeFamily, title, page }));
}

/** Per model: the bugs whose text names it, and the first and last releases where they appear. */
function modelSummaries(models, bugs, versions) {
  const summaries = new Map(models.map((model) => [model, { model, count: 0, first: Infinity, last: -1 }]));
  for (const bug of bugs) {
    for (const model of bug.models) {
      const summary = summaries.get(model);
      if (!summary) continue;
      summary.count += 1;
      for (const [version] of bug.events) {
        if (!isPublished(versions[version])) continue;
        summary.first = Math.min(summary.first, version);
        summary.last = Math.max(summary.last, version);
      }
    }
  }
  return [...summaries.values()].filter((summary) => summary.count && summary.last >= 0).map((summary) => ({
    ...summary, family: modelFamily(summary.model), first: nameOf(versions[summary.first]), last: nameOf(versions[summary.last]),
  }));
}

/** A release one can download: its notes exist, and it is no planned or article-less service release. */
function isPublished(entry) {
  return !entry.unavailable && !entry.publication;
}

/** Link to the page of the PDF holding a fact, or to the SRN article of a service release. */
function officialUrl(entry, page) {
  if (entry.pdf) return page ? `${entry.pdf}#page=${page}` : entry.pdf;
  return entry.article || null;
}

/** Tab-separated text, which spreadsheets and mail clients paste as a table. */
function tableText(rows) {
  return rows.map((row) => row.map((cell) => String(cell ?? "").replace(/\s+/g, " ").trim()).join("\t")).join("\n");
}

if (typeof module !== "undefined") {
  module.exports = {
    nameOf, releaseParts, covers, isPublished, firstFixes, statusAt, branchSupport, supportedBranches, modelFamily, hardwareMatch, selectedFamily, searchTerms, isPrTerm,
    matchesTerms, upgradeGroup, upgradePath, versionChanges, upgradeNotices, modelSummaries, officialUrl, tableText,
  };
}
