"use strict";

const PAGE_SIZE = 100;
const SYSTEMS = { junos: "Junos OS", evo: "Junos OS Evolved" };
const KNOWN_LABELS = { k: t("known.k"), l: t("known.l"), r: t("status.fixed") };
const STATUSES = {
  affected: t("status.affected"),
  potential: t("status.potential"),
  fixed: t("status.fixed"),
  unknown: t("status.unknown"),
};
const SCOPES = {
  all: { label: t("scope.all"), tone: "all" },
  supported: { label: t("scope.supported"), tone: "fixed" },
  ended: { label: t("scope.ended"), tone: "unknown" },
};
// Riskiest first: what an upgrade brings or leaves matters more than what it fixes.
const UPGRADE_GROUPS = {
  all: { label: t("group.all"), tone: "all" },
  changed: { label: t("group.changed"), tone: "change" },
  introduced: { label: t("group.introduced"), tone: "affected" },
  remaining: { label: t("group.remaining"), tone: "potential" },
  gained: { label: t("group.gained"), tone: "fixed" },
};

const $ = (id) => document.getElementById(id);
const defaultFilters = () => ({
  query: "", version: "", from: "", model: "", category: "",
  hidden: new Set(["unknown"]), group: "all", scope: "all",
});
const system = (() => {
  const wanted = new URLSearchParams(location.hash.slice(1)).get("system");
  return wanted in SYSTEMS ? wanted : "junos";
})();
const systemName = SYSTEMS[system];
const state = { view: "bugs", shown: PAGE_SIZE, reading: false, ...defaultFilters() };
let versions = [];
let families = [];
let models = [];
let categories = [];
let bugs = [];
let changes = [];
let summaries = [];
let lifecycle = { source: null, branches: {} };
let notices = {};
let sources = {};
let copiedTable = () => [];
let updated = "";
let schedule = null;
let searchTimer;
const combos = {};

const escapeHtml = (text) => String(text).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const escapeRegExp = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const formatNumber = (n) => n.toLocaleString(locale);
const formatDate = (iso) => iso.split("-").reverse().join("/");

/** Text field that filters a list of options as you type. */
class Combobox {
  constructor(root, onChange) {
    this.onChange = onChange;
    this.options = [];
    this.current = "";
    this.visible = [];
    this.active = -1;
    this.input = document.createElement("input");
    this.input.id = `${root.id}-input`;
    this.input.type = "text";
    this.input.autocomplete = "off";
    this.input.spellcheck = false;
    this.input.setAttribute("role", "combobox");
    this.input.setAttribute("aria-autocomplete", "list");
    this.input.setAttribute("aria-expanded", "false");
    this.input.setAttribute("aria-controls", `${root.id}-list`);
    this.list = document.createElement("ul");
    this.list.id = `${root.id}-list`;
    this.list.className = "combo-list";
    this.list.setAttribute("role", "listbox");
    this.list.hidden = true;
    root.append(this.input, this.list);

    this.input.addEventListener("focus", () => { this.open(""); this.input.select(); });
    this.input.addEventListener("click", () => {
      if (this.list.hidden) this.open("");
      // Deferred: a click on selected text collapses the selection after this event.
      setTimeout(() => {
        if (this.input.value === this.label()) this.input.select();
      });
    });
    this.input.addEventListener("input", () => this.open(this.input.value));
    this.input.addEventListener("blur", () => this.close());
    this.input.addEventListener("keydown", (event) => this.onKey(event));
    // mousedown, not click: the field must not lose focus before the choice is made.
    this.list.addEventListener("mousedown", (event) => {
      event.preventDefault();
      const option = event.target.closest("[data-index]");
      if (option) this.choose(this.visible[Number(option.dataset.index)]);
    });
  }

  setOptions(options) {
    this.options = options;
    this.value = this.current;
  }

  get value() {
    return this.current;
  }

  set value(value) {
    this.current = value;
    this.input.value = this.label();
  }

  label() {
    const option = this.options.find((entry) => entry.value === this.current);
    return option ? option.label : "";
  }

  open(text) {
    const terms = text.toLowerCase().split(/\s+/).filter(Boolean);
    this.visible = this.options.filter((option) => {
      const label = `${option.label} ${option.group || ""}`.toLowerCase();
      return terms.every((term) => label.includes(term));
    });
    const selected = this.visible.findIndex((option) => option.value === this.current);
    this.active = terms.length ? 0 : Math.max(selected, 0);
    this.renderList();
    this.list.hidden = false;
    this.input.setAttribute("aria-expanded", "true");
    this.scrollToActive();
  }

  close() {
    this.list.hidden = true;
    this.input.setAttribute("aria-expanded", "false");
    this.input.removeAttribute("aria-activedescendant");
    this.value = this.current;
    // Still focused after Escape or a choice: typing must replace the label.
    if (document.activeElement === this.input) this.input.select();
  }

  choose(option) {
    const changed = option.value !== this.current;
    this.current = option.value;
    this.close();
    if (changed) this.onChange(option.value);
  }

  onKey(event) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (this.list.hidden) {
        this.open("");
      } else if (this.visible.length) {
        const step = event.key === "ArrowDown" ? 1 : -1;
        this.active = (this.active + step + this.visible.length) % this.visible.length;
        this.renderList();
        this.scrollToActive();
      }
    } else if (event.key === "Enter" && !this.list.hidden) {
      event.preventDefault();
      if (this.visible[this.active]) this.choose(this.visible[this.active]);
    } else if (event.key === "Escape") {
      this.close();
    }
  }

  renderList() {
    let group = null;
    const items = [];
    this.visible.forEach((option, index) => {
      const tone = option.tone ? ` ${option.tone}` : "";
      if (option.group && option.group !== group) {
        group = option.group;
        items.push(`<li class="combo-group${tone}" role="presentation">${escapeHtml(group)}</li>`);
      }
      const classes = `combo-option${tone}${index === this.active ? " active" : ""}`;
      items.push(`<li id="${this.list.id}-${index}" class="${classes}" role="option" data-index="${index}" aria-selected="${option.value === this.current}">${escapeHtml(option.label)}</li>`);
    });
    this.list.innerHTML = items.join("") || `<li class="combo-empty">${t("filter.noResult")}</li>`;
  }

  scrollToActive() {
    const option = this.list.querySelector(".active");
    if (!option) return;
    option.scrollIntoView({ block: "nearest" });
    this.input.setAttribute("aria-activedescendant", option.id);
  }
}

function hydrate(row) {
  const [id, category, description, workaround, cited, familyList, events, severity, srnCategory, detail] = row;
  const fixes = firstFixes(events, versions);
  const text = `pr${id} ${description} ${workaround || ""} ${detail || ""} ${srnCategory || ""} ${cited.join(" ")}`.toLowerCase();
  const supported = supportedBranches(events, versions);
  return { id, category, description, workaround, models: cited, families: familyList, events, fixes, text, supported, severity, srnCategory, detail };
}

/** The branch filter only makes sense on a search across all the releases. */
function scopeApplies() {
  return state.view === "bugs" && !state.version && Object.keys(lifecycle.branches).length > 0;
}

function versionIndex(value) {
  return value === "" ? -1 : versions.findIndex((entry) => entry.v === value);
}

function compute() {
  const terms = searchTerms(state.query);
  const version = versionIndex(state.version);
  const from = versionIndex(state.from);
  const upgrade = state.view === "upgrade" && version >= 0 && from >= 0;
  const scoped = scopeApplies();
  const category = state.category === "" ? -1 : Number(state.category);
  const family = selectedFamily(state.model, families);
  const counts = {};
  const rows = [];

  if (state.view === "upgrade" && !upgrade) return { rows, counts };
  if (upgrade && category < 0) {
    for (const change of versionChanges(versions, from, version, family)) {
      const text = `${change.text} ${change.category || ""}`.toLowerCase();
      if (!terms.every((term) => text.includes(term))) continue;
      counts.changed = (counts.changed || 0) + 1;
      counts.all = (counts.all || 0) + 1;
      if (state.group === "all" || state.group === "changed") rows.push({ change, group: "changed" });
    }
  }
  for (const bug of bugs) {
    if (category >= 0 && bug.category !== category) continue;
    if (!matchesTerms(bug, terms)) continue;
    const hardware = hardwareMatch(bug, state.model, families);
    if (!hardware) continue;

    if (scoped) {
      const scope = bug.supported.length ? "supported" : "ended";
      counts[scope] = (counts[scope] || 0) + 1;
      counts.all = (counts.all || 0) + 1;
      if (state.scope !== "all" && scope !== state.scope) continue;
    }
    const status = version >= 0 ? statusAt(bug, version, versions) : null;
    if (upgrade) {
      const group = upgradeGroup(bug, from, version, versions);
      if (!group) continue;
      counts[group] = (counts[group] || 0) + 1;
      counts.all = (counts.all || 0) + 1;
      if (state.group !== "all" && group !== state.group) continue;
      rows.push({ bug, status, hardware, group });
      continue;
    } else if (status) {
      counts[status.key] = (counts[status.key] || 0) + 1;
      if (state.hidden.has(status.key)) continue;
    }
    rows.push({ bug, status, hardware });
  }
  const risk = Object.keys(UPGRADE_GROUPS);
  const cited = (row) => (row.hardware === "cited" ? 0 : 1);
  const ended = (row) => (scoped && !row.bug.supported.length ? 1 : 0);
  rows.sort((a, b) => risk.indexOf(a.group) - risk.indexOf(b.group)
    || (a.change || b.change ? 0 : (state.model ? cited(a) - cited(b) : 0) || ended(a) - ended(b)));
  return { rows, counts };
}

function officialLink(entry, page, label) {
  const url = officialUrl(entry, page);
  return url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener">${label}</a>` : label;
}

function highlight(text, terms) {
  const words = terms.filter((term) => !isPrTerm(term)).map(escapeRegExp);
  const safe = escapeHtml(text);
  if (!words.length) return safe;
  return safe.replace(new RegExp(`(${words.map((w) => escapeHtml(w)).join("|")})`, "gi"), "<mark>$1</mark>");
}

/** "23.4R2-S10 (pas encore publiée)": a release named by an SRN without article of its own. */
function releaseLabel(entry) {
  return entry.publication ? `${entry.v} (${t(`publication.${entry.publication}`)})` : entry.v;
}

function fixesLabel(bug) {
  const labels = bug.fixes.map((version) => releaseLabel(versions.find((entry) => entry.v === version)));
  return labels.length ? t("bug.fixedIn", { versions: labels.join(", ") }) : t("bug.noFix");
}

function hardwareTags(bug, hardware) {
  const tags = bug.models.map((name) => `<span class="tag hw">${escapeHtml(name)}</span>`);
  tags.push(...bug.families.map((position) => `<span class="tag">${escapeHtml(families[position])}</span>`));
  if (hardware === "family") tags.push(`<span class="tag">${t("bug.familyOnly")}</span>`);
  if (hardware === "generic") tags.push(`<span class="tag">${t("bug.generic")}</span>`);
  return tags.join("");
}

/** First mention per branch: Juniper does not publish the release that introduced a bug. */
function renderAppearance(bug) {
  const first = new Map();
  for (const [version, status] of bug.events) {
    const branch = versions[version].branch;
    if (status !== "r" && !first.has(branch)) first.set(branch, [version, status]);
  }
  if (!first.size) return `<p>${t("bug.neverKnown")}</p>`;
  const lines = [...first].reverse().map(([branch, [version, status]]) => {
    const text = t(status === "l" ? "bug.firstLimitation" : "bug.firstKnown", { version: versions[version].v });
    return `<dt>${escapeHtml(branch)}</dt><dd>${escapeHtml(text)}</dd>`;
  });
  return `<dl class="history">${lines.join("")}</dl><p class="note">${t("bug.appearanceNote")}</p>`;
}

function renderHistory(bug) {
  const lines = [...bug.events].reverse().map(([version, status, page, familyList, release, source]) => {
    const entry = versions[version];
    const parts = [release ? `${KNOWN_LABELS[status]} (${escapeHtml(release)})` : KNOWN_LABELS[status]];
    if (familyList.length) parts.push(escapeHtml(familyList.map((position) => families[position]).join(", ")));
    if (source) {
      // Stated by the SRN of another release, in its "Resolved In" field.
      const origin = sources[source];
      const via = `<a href="${escapeHtml(origin.article)}" target="_blank" rel="noopener">${t("bug.via", { version: escapeHtml(origin.version) })}</a>`;
      parts.push(entry.article ? `${officialLink(entry, null, t("bug.srnArticle"))}, ${via}` : via);
    } else if (entry.service) {
      parts.push(officialLink(entry, null, t("bug.srnArticle")));
    } else {
      parts.push(officialLink(entry, page, t("bug.officialPage", { page })));
    }
    return `<dt>${escapeHtml(releaseLabel(entry))}</dt><dd>${parts.join(", ")}</dd>`;
  });
  return `<dl class="history">${lines.join("")}</dl>`;
}

function statusDetail(detail) {
  return detail ? `<span>${escapeHtml(t(`detail.${detail.id}`, detail))}</span>` : "";
}

function supportTag(bug) {
  if (!scopeApplies()) return "";
  return bug.supported.length
    ? `<span class="tag supported">${t("bug.supported", { branches: escapeHtml(bug.supported.join(", ")) })}</span>`
    : `<span class="tag">${t("scope.ended")}</span>`;
}

function renderChange({ family, category, text, page, entry }, terms) {
  const link = officialLink(entry, page, t("change.page", { version: escapeHtml(entry.v), page }));
  return `<div class="bug"><div class="bug-row">
    <span class="bug-id">${escapeHtml(entry.v)}</span>
    <span class="bug-text">${highlight(text, terms)}</span>
    <span class="bug-meta"><span class="badge change">${t("change.label")}</span><span>${escapeHtml(families[family])}</span>${category ? `<span>${escapeHtml(category)}</span>` : ""}${link}</span>
  </div></div>`;
}

function renderBug({ bug, status, hardware, group, change }, terms) {
  if (change) return renderChange(change, terms);
  const badge = group
    ? `<span class="badge ${UPGRADE_GROUPS[group].tone}">${UPGRADE_GROUPS[group].label}</span>`
    : status
      ? `<span class="badge ${status.key}">${STATUSES[status.key]}</span>${statusDetail(status.detail)}`
      : "";
  const workaround = bug.workaround
    ? `<h3>${t("bug.workaround")}</h3><p>${highlight(bug.workaround, terms)}</p>`
    : "";
  const description = bug.description ? highlight(bug.description, terms) : `<em>${t("bug.noDescription")}</em>`;
  const severity = bug.severity ? `<span class="tag severity">${t("bug.severity", { severity: escapeHtml(bug.severity) })}</span>` : "";
  const detail = bug.detail ? `<h3>${t("bug.srnDetail")}</h3><p>${highlight(bug.detail, terms)}</p>` : "";
  return `<details class="bug" data-id="${bug.id}">
    <summary>
      <span class="bug-id">PR${bug.id}</span>
      <span class="bug-text">${description}</span>
      <span class="bug-meta">${badge}<span>${escapeHtml(bug.srnCategory && categories[bug.category] === "Uncategorized" ? bug.srnCategory : categories[bug.category])}</span><span>${escapeHtml(fixesLabel(bug))}</span>${severity}${supportTag(bug)}${hardwareTags(bug, hardware)}</span>
    </summary>
    <div class="bug-detail">${detail}<h3>${t("bug.appearance")}</h3>${renderAppearance(bug)}${workaround}<h3>${t("bug.history")}</h3>${renderHistory(bug)}
      <p class="note"><a href="https://prsearch.juniper.net/PR${bug.id}" target="_blank" rel="noopener">${t("bug.prsearch", { id: bug.id })}</a> ${t("bug.prsearchNote")}</p></div>
  </details>`;
}

function tile(data, key, label, tone, count, pressed) {
  return `<button type="button" class="summary-card ${tone}" data-${data}="${key}" aria-pressed="${pressed}"><strong>${formatNumber(count || 0)}</strong><span>${label}</span></button>`;
}

function renderChips(counts) {
  const version = versionIndex(state.version);
  if (state.view === "upgrade") {
    const compared = version >= 0 && versionIndex(state.from) >= 0;
    $("chips").innerHTML = compared
      ? Object.entries(UPGRADE_GROUPS)
        // The order of the tiles helps finding one; the list keeps the riskiest first.
        .sort(([a, { label: first }], [b, { label: second }]) => (b === "all") - (a === "all") || first.localeCompare(second, locale))
        .map(([key, { label, tone }]) => tile("group", key, label, tone, counts[key], state.group === key)).join("")
      : "";
  } else if (scopeApplies()) {
    $("chips").innerHTML = Object.entries(SCOPES).map(([key, { label, tone }]) => tile("scope", key, label, tone, counts[key], state.scope === key)).join("");
  } else if (version >= 0) {
    $("chips").innerHTML = Object.entries(STATUSES).map(([key, label]) => tile("status", key, label, key, counts[key], !state.hidden.has(key))).join("");
  } else {
    $("chips").innerHTML = "";
  }
}

function renderNotices() {
  const messages = [];
  const selected = [versionIndex(state.version), state.view === "upgrade" ? versionIndex(state.from) : -1];
  for (const index of selected) {
    if (index >= 0 && versions[index].unavailable) messages.push(t("notice.unavailable", { version: versions[index].v }));
    const selected = index >= 0 ? versions[index] : null;
    if (selected && selected.publication) messages.push(t(`notice.${selected.publication}`, { version: selected.v }));
    else if (selected && selected.service && !selected.read) messages.push(t("notice.srnNotRead", { version: selected.v }));
  }
  const version = selected[0];
  const family = selectedFamily(state.model, families);
  if (version >= 0 && family >= 0 && !versions[version].unavailable && !versions[version].service && !versions[version].families.includes(family)) {
    messages.push(t("notice.notListed", { family: families[family], version: versions[version].v }));
  }
  if (state.view === "upgrade" && versionIndex(state.from) >= 0 && version >= 0 && versionIndex(state.from) >= version) {
    messages.push(t("notice.order"));
  }
  if (state.view === "upgrade" && versionIndex(state.from) >= 0 && version >= 0 && versionIndex(state.from) < version) {
    messages.push(t("notice.path", { path: upgradePath(versions, versionIndex(state.from), version).map((index) => versions[index].v).join(", ") }));
  }
  $("notices").innerHTML = messages.map((text) => `<p class="notice">${escapeHtml(text)}</p>`).join("");
}

function supportBadge(support) {
  if (!Object.keys(lifecycle.branches).length) return "";
  if (!support.support && support.supported) return "";
  const date = support.support && formatDate(support.support);
  const [tone, text] = !support.support ? ["unknown", t("support.ended")]
    : support.supported ? ["fixed", t("support.until", { date })] : ["unknown", t("support.endedOn", { date })];
  return `<a class="badge ${tone}" href="${escapeHtml(lifecycle.source)}" target="_blank" rel="noopener">${text}</a>`;
}

/** Shortcuts to the latest release of each supported branch. */
function renderSupport() {
  const latest = new Map(versions.filter(isPublished).map((entry) => [entry.branch, entry]));
  const branches = [...latest.values()].filter((entry) => entry.support.supported).reverse();
  const shown = ["bugs", "upgrade"].includes(state.view) && Object.keys(lifecycle.branches).length > 0;
  $("support").hidden = !shown;
  if (!shown) return;
  const links = branches.map((entry) => {
    const params = stateParams();
    params.set("version", entry.v);
    const date = entry.support.support ? `<small>${t("support.date", { date: formatDate(entry.support.support) })}</small>` : "";
    const current = entry.v === state.version ? ' aria-current="true"' : "";
    return `<a class="support-branch" href="#${escapeHtml(params.toString())}"${current}><strong>${escapeHtml(entry.v)}</strong>${date}</a>`;
  });
  const note = t(lifecycle.shared ? "support.noteEvo" : "support.note", { url: escapeHtml(lifecycle.source) });
  $("support").innerHTML = `<h2>${t("support.title")}</h2><div class="support-list">${links.join("")}</div><p class="muted">${note}</p>`;
}

function renderVersionInfo() {
  const entry = versions[versionIndex(state.version)];
  const parts = [];
  if (entry && entry.service) {
    parts.push(`${systemName} ${escapeHtml(releaseLabel(entry))}`, t("version.service"));
    const support = supportBadge(entry.support);
    if (support) parts.push(support);
    if (entry.article) parts.push(officialLink(entry, null, t("version.article")));
  } else if (entry && !entry.unavailable) {
    parts.push(`${systemName} ${escapeHtml(entry.v)}`);
    const page = entry.pages.revisions;
    if (entry.released) parts.push(officialLink(entry, page, t("version.released", { date: formatDate(entry.released) })));
    if (entry.revised) parts.push(officialLink(entry, page, t("version.revised", { date: formatDate(entry.revised) })));
    const support = supportBadge(entry.support);
    if (support) parts.push(support);
    parts.push(officialLink(entry, page, t("version.official")));
  }
  $("version-info").innerHTML = parts.map((part) => `<span>${part}</span>`).join("");
}

function renderUpgradeNotices() {
  const from = versionIndex(state.from);
  const to = versionIndex(state.version);
  const family = selectedFamily(state.model, families);
  const items = state.view === "upgrade" && from >= 0 && to > from ? upgradeNotices(notices, versions, to, family) : [];
  if (!items.length) {
    $("upgrade-notices").innerHTML = "";
    return;
  }
  const entry = versions[to];
  const list = items.map((item) => {
    const where = item.family === null ? "" : ` <span class="muted">${escapeHtml(families[item.family])}</span>`;
    return `<li>${officialLink(entry, item.page, escapeHtml(item.title))}${where}</li>`;
  }).join("");
  $("upgrade-notices").innerHTML = `<details class="reading"${state.reading ? " open" : ""}><summary>${t("reading.title", { count: items.length })}</summary>
    <p class="muted">${t("reading.help", { version: escapeHtml(entry.v) })}</p><ul>${list}</ul></details>`;
}

/** Releases holding the most recent value of a date field, newest release first. */
function latestBy(field) {
  const dated = versions.filter((entry) => entry[field] && isPublished(entry));
  const date = dated.reduce((latest, entry) => (entry[field] > latest ? entry[field] : latest), "");
  return { date, entries: dated.filter((entry) => entry[field] === date).reverse() };
}

function newsCard(title, date, releases) {
  const links = releases.map((release) => `<a href="#${escapeHtml(new URLSearchParams({ system, version: release }).toString())}">${escapeHtml(release)}</a>`);
  return `<section class="news-card"><h2>${title}</h2><strong>${date}</strong><p>${systemName} ${links.join(", ")}</p></section>`;
}

function latestCard(title, field) {
  const { date, entries } = latestBy(field);
  return date ? newsCard(title, formatDate(date), entries.map((entry) => entry.v)) : "";
}

function pdfLine(version) {
  const entry = versions.find((candidate) => candidate.v === version);
  if (!entry || !entry.pdf || !entry.revised) return "";
  return `<p class="news-pdf version-info"><span>${t("news.revised", { date: formatDate(entry.revised) })}</span> ${officialLink(entry, entry.pages.revisions, t("version.official"))}</p>`;
}

function bugTable(rows) {
  const header = ["copy.bug", "copy.status", "copy.category", "copy.description", "copy.workaround", "copy.fix"].map((key) => t(key));
  return [header, ...rows.map(({ bug, status, group, change }) => (change ? [
    change.entry.v, UPGRADE_GROUPS[group].label, families[change.family], change.text, "", "",
  ] : [
    `PR${bug.id}`,
    group ? UPGRADE_GROUPS[group].label : status ? STATUSES[status.key] : "",
    categories[bug.category],
    bug.description,
    bug.workaround,
    fixesLabel(bug),
  ]))];
}

/** The Clipboard API needs HTTPS: a local preview over HTTP falls back on the old command. */
async function copyText(text) {
  if (navigator.clipboard) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const field = document.createElement("textarea");
  field.value = text;
  document.body.append(field);
  field.select();
  document.execCommand("copy");
  field.remove();
}

function clearPanels() {
  $("notices").innerHTML = "";
  $("version-info").innerHTML = "";
  $("upgrade-notices").innerHTML = "";
  $("more").hidden = true;
}

function renderHardware() {
  const terms = searchTerms($("hardware-query").value);
  const listed = summaries
    .filter(({ model, family }) => terms.every((term) => `${model} ${family}`.toLowerCase().includes(term)))
    .sort((a, b) => a.model.localeCompare(b.model, "fr", { numeric: true }));
  const columns = ["model", "family", "count", "first", "last"];
  copiedTable = () => [columns.map((key) => t(`hardware.${key}`)), ...listed.map((entry) => [entry.model, entry.family, entry.count, entry.first, entry.last])];
  $("copy").hidden = !listed.length;
  $("copy").textContent = t("list.copy");
  $("chips").innerHTML = "";
  const rows = listed.map((entry) => {
    const filter = new URLSearchParams({ system, model: `m:${entry.model}` });
    const family = new URLSearchParams({ system, model: `f:${entry.family}` });
    return `<tr><th scope="row"><a href="#${escapeHtml(filter.toString())}">${escapeHtml(entry.model)}</a></th>
      <td><a href="#${escapeHtml(family.toString())}">${escapeHtml(entry.family)}</a></td><td>${formatNumber(entry.count)}</td>
      <td>${escapeHtml(entry.first)}</td><td>${escapeHtml(entry.last)}</td></tr>`;
  });
  $("results").innerHTML = rows.length
    ? `<table class="hardware-table"><thead><tr>${columns.map((key) => `<th scope="col">${t(`hardware.${key}`)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table>`
    : "";
  $("count").textContent = rows.length ? t("hardware.listed", { count: formatNumber(rows.length) }) : t("hardware.none");
  clearPanels();
  $("news-summary").innerHTML = "";
  writeHash();
}

function renderNews() {
  $("news-summary").innerHTML = latestCard(t("news.latestRelease"), "released") + latestCard(t("news.latestPdf"), "revised");
  const byId = new Map(bugs.map((bug) => [bug.id, bug]));
  const entries = changes.map((change) => {
    const items = change.bugs.slice(0, 20).map((id) => {
      const bug = byId.get(id);
      const link = new URLSearchParams({ system, query: `PR${id}` });
      return `<li><a href="#${escapeHtml(link.toString())}">PR${id}</a> ${bug ? escapeHtml(bug.description) : ""}</li>`;
    });
    const hidden = change.bugs.length - items.length;
    if (hidden > 0) items.push(`<li class="muted">${t("news.more", { count: formatNumber(hidden) })}</li>`);
    const link = new URLSearchParams({ system, version: change.version });
    return `<article class="news">
      <time datetime="${change.date}">${formatDate(change.date)}</time>
      <h2><a href="#${escapeHtml(link.toString())}">${escapeHtml(change.titles[language])}</a></h2>
      ${pdfLine(change.version)}
      ${items.length ? `<ul>${items.join("")}</ul>` : ""}
    </article>`;
  });
  $("results").innerHTML = entries.join("");
  $("count").textContent = "";
  $("copy").hidden = true;
  $("chips").innerHTML = "";
  clearPanels();
  writeHash();
}

function render() {
  renderSupport();
  if (state.view === "news") {
    renderNews();
    return;
  }
  if (state.view === "hardware") {
    renderHardware();
    return;
  }
  $("news-summary").innerHTML = "";
  const { rows, counts } = compute();
  const terms = searchTerms(state.query);
  renderChips(counts);
  renderNotices();
  renderVersionInfo();
  renderUpgradeNotices();

  const waiting = state.view === "upgrade" && (!state.from || !state.version);
  $("count").textContent = waiting
    ? t("count.choose")
    : rows.length > state.shown ? t("count.partial", { count: formatNumber(rows.length), shown: formatNumber(state.shown) })
      : rows.length > 1 ? t("count.many", { count: formatNumber(rows.length) }) : t(rows.length ? "count.one" : "count.none");
  $("results").innerHTML = rows.slice(0, state.shown).map((row) => renderBug(row, terms)).join("");
  $("more").hidden = rows.length <= state.shown;
  $("more").textContent = t("list.more", { count: formatNumber(rows.length - state.shown) });
  copiedTable = () => bugTable(rows);
  $("copy").hidden = !rows.length;
  $("copy").textContent = t("list.copy");
  writeHash();
}

function stateParams(shown = language) {
  const params = new URLSearchParams();
  if (shown === "en") params.set("lang", "en");
  if (system !== "junos") params.set("system", system);
  if (state.view !== "bugs") params.set("view", state.view);
  for (const key of ["query", "version", "from", "model", "category"]) {
    if (state[key]) params.set(key, state[key]);
  }
  if (state.scope !== "all") params.set("scope", state.scope);
  return params;
}

function writeHash() {
  history.replaceState(null, "", `#${stateParams()}`);
}

function readHash() {
  const params = new URLSearchParams(location.hash.slice(1));
  state.view = ["upgrade", "news", "hardware"].includes(params.get("view")) ? params.get("view") : "bugs";
  for (const key of ["query", "version", "from", "model", "category"]) {
    state[key] = params.get(key) || "";
  }
  state.scope = ["supported", "ended"].includes(params.get("scope")) ? params.get("scope") : "all";
}

function syncControls() {
  const upgrade = state.view === "upgrade";
  const news = state.view === "news";
  const hardware = state.view === "hardware";
  $("tab-bugs").setAttribute("aria-pressed", String(state.view === "bugs"));
  $("tab-upgrade").setAttribute("aria-pressed", String(upgrade));
  $("tab-news").setAttribute("aria-pressed", String(news));
  $("tab-hardware").setAttribute("aria-pressed", String(hardware));
  $("filters").hidden = news || hardware;
  $("legend").hidden = news || hardware;
  $("hardware-tools").hidden = !hardware;
  $("subscribe").hidden = !news;
  $("field-from").hidden = !upgrade;
  $("version-label").textContent = t(upgrade ? "filter.target" : "filter.version", { system: systemName });
  $("view-help").textContent = t(`help.${state.view}`, { system: systemName });
  for (const key of ["version", "from", "model", "category"]) combos[key].value = state[key];
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  $("theme").textContent = t(theme === "dark" ? "theme.light" : "theme.dark");
}

function branchLabel({ branch, support }) {
  if (!Object.keys(lifecycle.branches).length) return `${systemName} ${branch}`;
  if (!support.supported) return t("option.branchEnded", { system: systemName, branch });
  return support.support ? t("option.branchUntil", { system: systemName, branch, date: formatDate(support.support) }) : `${systemName} ${branch}`;
}

function versionOptions(placeholder) {
  const options = [...versions].reverse().map((entry) => ({
    value: entry.v,
    label: `${releaseLabel(entry)}${entry.unavailable ? t("option.unavailable") : ""}`,
    group: branchLabel(entry),
    tone: entry.support.supported ? "" : "ended",
  }));
  return [{ value: "", label: placeholder }, ...options];
}

/** A family first, for its bugs without model, then the models its bugs name. */
function modelOptions() {
  const options = families.flatMap((family) => [
    { value: `f:${family}`, label: t("option.family", { family }), group: family },
    ...models.filter((model) => modelFamily(model) === family)
      .map((model) => ({ value: `m:${model}`, label: model, group: family })),
  ]);
  return [{ value: "", label: t("filter.allModels") }, ...options];
}

function update(next) {
  clearTimeout(searchTimer);
  // The field is the reference: a filter can change while a search is debounced.
  Object.assign(state, { query: $("query").value }, next, { shown: PAGE_SIZE });
  syncControls();
  render();
}

function switchTo(next) {
  if (next === system) return;
  const params = new URLSearchParams({ system: next });
  if (state.view !== "bugs") params.set("view", state.view);
  if (state.query) params.set("query", state.query);
  if (language === "en") params.set("lang", "en");
  history.replaceState(null, "", `#${params}`);
  location.reload();
}

function bindEvents() {
  $("query").addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => update({}), 150);
  });
  $("theme").addEventListener("click", () => {
    const theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    localStorage.setItem("theme", theme);
    applyTheme(theme);
  });
  $("reset").addEventListener("click", () => {
    $("query").value = "";
    update(defaultFilters());
  });
  $("language").addEventListener("click", () => {
    const next = language === "fr" ? "en" : "fr";
    localStorage.setItem("language", next);
    history.replaceState(null, "", `#${stateParams(next)}`);
    location.reload();
  });
  $("system-junos").addEventListener("click", () => switchTo("junos"));
  $("system-evo").addEventListener("click", () => switchTo("evo"));
  $("tab-bugs").addEventListener("click", () => update({ view: "bugs" }));
  $("tab-upgrade").addEventListener("click", () => update({ view: "upgrade" }));
  $("tab-news").addEventListener("click", () => update({ view: "news" }));
  $("tab-hardware").addEventListener("click", () => update({ view: "hardware" }));
  $("hardware-query").addEventListener("input", () => render());
  $("more").addEventListener("click", () => {
    state.shown = Infinity;
    render();
  });
  $("chips").addEventListener("click", (event) => {
    const chip = event.target.closest("button");
    if (!chip) return;
    if (chip.dataset.scope) {
      update({ scope: chip.dataset.scope });
    } else if (chip.dataset.group) {
      update({ group: chip.dataset.group });
    } else {
      const key = chip.dataset.status;
      if (state.hidden.has(key)) state.hidden.delete(key); else state.hidden.add(key);
      update({});
    }
  });
  // toggle does not bubble, and a new render must not fold what the reader opened.
  $("upgrade-notices").addEventListener("toggle", (event) => {
    if (event.target.classList.contains("reading")) state.reading = event.target.open;
  }, true);
  $("copy").addEventListener("click", async () => {
    const table = copiedTable();
    await copyText(tableText(table));
    $("copy").textContent = t("list.copied", { count: formatNumber(table.length - 1) });
  });
  $("to-top").addEventListener("click", () => window.scrollTo({ top: 0, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" }));
  window.addEventListener("scroll", () => {
    $("to-top").hidden = window.scrollY < 500;
  }, { passive: true });
  // Selecting text in a bug must not fold or unfold it.
  $("results").addEventListener("click", (event) => {
    if (event.target.closest("summary") && !getSelection().isCollapsed) event.preventDefault();
  });
  window.addEventListener("hashchange", () => {
    const wanted = new URLSearchParams(location.hash.slice(1)).get("system") || "junos";
    if (wanted !== system && wanted in SYSTEMS) {
      location.reload();
      return;
    }
    readHash();
    $("query").value = state.query;
    update({});
  });
}

async function start() {
  const [index, data, news, chapters] = await Promise.all(
    ["index.json", "bugs.json", "changes.json", "notices.json"].map((name) => fetch(`data/${system}/${name}`).then((response) => {
      if (!response.ok) throw new Error(`${name}: ${response.status}`);
      return response.json();
    })),
  );
  lifecycle = index.lifecycle;
  const today = new Date().toISOString().slice(0, 10);
  versions = index.versions.map((entry) => ({ ...entry, ...releaseParts(entry.v), support: branchSupport(entry.branch, lifecycle.branches, today) }));
  sources = index.sources;
  families = index.families;
  models = index.models;
  categories = data.categories;
  changes = news;
  notices = chapters;
  updated = index.updated;
  schedule = index.schedule;
  bugs = data.bugs.map(hydrate);
  summaries = modelSummaries(models, bugs, versions);

  for (const key of ["version", "from", "model", "category"]) {
    combos[key] = new Combobox($(key), (value) => update({ [key]: value }));
  }
  combos.version.setOptions(versionOptions(t("filter.allVersions")));
  combos.from.setOptions(versionOptions(t("filter.choose")));
  combos.model.setOptions(modelOptions());
  combos.category.setOptions([
    { value: "", label: t("filter.allCategories") },
    ...categories.map((name, position) => ({ value: String(position), label: name })),
  ]);

  const latest = [...versions].reverse().find(isPublished);
  $("scope").textContent = t("page.scopeRange", { system: systemName, first: versions[0].v, last: latest.v });
  $("stats").textContent = t("page.stats", { bugs: formatNumber(bugs.length), versions: formatNumber(versions.length), latest: latest.v });
  const moment = new Date(updated);
  $("updated").textContent = t("page.updated", {
    date: moment.toLocaleDateString(locale),
    time: moment.toLocaleTimeString(locale, { timeStyle: "short" }),
  });
  if (schedule) $("schedule").textContent = t("page.schedule", { crons: schedule.crons.join(t("page.and")), zone: schedule.timezone });
  readHash();
  $("query").value = state.query;
  bindEvents();
  update({});
}

$(`system-${system}`).setAttribute("aria-pressed", "true");
applyTheme(document.documentElement.dataset.theme);
start().catch((error) => {
  $("stats").textContent = t("page.failed");
  console.error(error);
});
