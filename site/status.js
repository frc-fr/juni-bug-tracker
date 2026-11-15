"use strict";
// The processing status page, the same on the five bug trackers: what the last automatic
// run read in the vendor's documents, what a known rule left out, and what the code has
// to be adapted to. Reads data/report.json, written by the collection and the extraction.

const TO_FIX = ["not_understood", "unreachable", "suspect"];
const $ = (id) => document.getElementById(id);
const escapeHtml = (text) => String(text ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const formatDate = (iso) => (iso ? iso.slice(0, 10).split("-").reverse().join("/") : t("status.never"));
const formatNumber = (n) => Number(n).toLocaleString(locale);
const formatShare = (share) => `${Math.round(share * 100)} %`;
const has = (key) => key in TEXTS[language];
const ruleLabel = (rule) => (has(`rule.${rule}`) ? t(`rule.${rule}`) : rule);
const ruleHelp = (rule) => (has(`rule.${rule}.help`) ? t(`rule.${rule}.help`) : "");
const sourceLabel = (name) => (has(`source.${name}`) ? t(`source.${name}`) : name);
const link = (url, text) => `<a href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(text)}</a>`;

function table(headers, rows) {
  if (!rows.length) return "";
  return `<div class="report-scroll"><table class="report-table"><thead><tr>${headers.map((h) => `<th scope="col">${h}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((cells) => `<tr>${cells.map((c, i) => (i ? `<td>${c}</td>` : `<th scope="row">${c}</th>`)).join("")}</tr>`).join("")}</tbody></table></div>`;
}

function section(id, title, help, body) {
  return `<section id="${id}"><h3>${title}</h3>${help ? `<p class="muted">${help}</p>` : ""}${body}</section>`;
}

function summary(report) {
  const moment = new Date(report.generated);
  const { publication, totals } = report;
  const lines = [t("status.generated", { date: moment.toLocaleDateString(locale), time: moment.toLocaleTimeString(locale, { timeStyle: "short" }) })];
  const values = { share: formatShare(publication.read_share), minimum: formatShare(publication.minimum) };
  lines.push(t(publication.published ? "status.published" : "status.blocked", values));
  const counts = ["documents", "read", "left_out", "suspect", "not_understood", "unreachable"];
  const totalsTable = table(counts.map((key) => t(`status.${key}`)), [counts.map((key) => formatNumber(totals[key] || 0))]);
  const buckets = ["vendor", "read", "ruled", "failed", "unaccounted"];
  const gap = table([t("status.group"), t("status.documents"), ...buckets.map((key) => t(`status.ids.${key}`))],
    report.groups.map((group) => [escapeHtml(group.name), formatNumber(group.documents), ...buckets.map((key) => formatNumber(group[key]))]));
  return section("status-summary", t("status.summary"), "", `<p>${lines.join(" ")}</p>${totalsTable}`)
    + section("status-gap", t("status.gap"), t("status.gapHelp"), gap);
}

function findingRows(findings) {
  return findings.map((f) => [
    `${escapeHtml(ruleLabel(f.rule))}${ruleHelp(f.rule) ? `<small class="report-help">${escapeHtml(ruleHelp(f.rule))}</small>` : ""}`,
    `${link(f.page, f.where || t("status.wholeDocument"))}`,
    f.count ? formatNumber(f.count) : "—",
    f.ids.length ? `<span class="report-ids">${f.ids.map(escapeHtml).join(", ")}${f.count > f.ids.length ? " …" : ""}</span>` : "—",
    escapeHtml(f.detail),
  ]);
}

function documentCard(doc, kinds) {
  const ids = doc.ids;
  const facts = [escapeHtml(doc.group), t("status.since", { date: formatDate(doc.since) })];
  if (doc.kept) facts.push(t("status.kept", { date: escapeHtml(doc.kept) }));
  const counts = t("status.idsLine", {
    vendor: formatNumber(ids.vendor), read: formatNumber(ids.read), ruled: formatNumber(ids.ruled),
    failed: formatNumber(ids.failed), unaccounted: formatNumber(ids.unaccounted.length),
  });
  const findings = doc.findings.filter((f) => kinds.includes(f.kind));
  return `<details class="report-doc" open><summary>${link(doc.url, doc.title)} <span class="muted">${facts.join(" · ")}</span></summary>
    ${ids.vendor ? `<p class="muted">${counts}</p>` : ""}
    ${table([t("status.finding"), t("status.where"), t("status.count"), t("status.examples"), t("status.detail")], findingRows(findings))}</details>`;
}

function toFix(report) {
  const parts = TO_FIX.map((status) => {
    const docs = report.documents.filter((doc) => doc.status === status);
    if (!docs.length) return "";
    return `<h4>${t(`status.${status}`)} (${formatNumber(docs.length)})</h4><p class="muted">${t(`status.${status}.help`)}</p>
      ${docs.map((doc) => documentCard(doc, [status, ...TO_FIX])).join("")}`;
  }).join("");
  const sources = report.sources.filter((source) => source.status === "error");
  const body = parts || sources.length ? parts : `<p>${t("status.nothingToFix")}</p>`;
  return section("status-fix", t("status.toFix"), t("status.toFixHelp"), body);
}

function rules(report) {
  const byRule = new Map();
  for (const doc of report.documents) {
    for (const f of doc.findings.filter((found) => found.kind === "left_out")) {
      const entry = byRule.get(f.rule) || { count: 0, docs: [] };
      entry.count += f.count;
      entry.docs.push({ doc, f });
      byRule.set(f.rule, entry);
    }
  }
  const blocks = [...byRule.entries()].sort((a, b) => b[1].count - a[1].count).map(([rule, { count, docs }]) => {
    const documents = new Set(docs.map(({ doc }) => doc.key)).size;
    const rows = docs.map(({ doc, f }) => [link(doc.url, doc.title), link(f.page, f.where || t("status.wholeDocument")), formatNumber(f.count),
      f.ids.length ? `<span class="report-ids">${f.ids.map(escapeHtml).join(", ")}${f.count > f.ids.length ? " …" : ""}</span>` : "—"]);
    return `<details class="report-rule"><summary><strong>${escapeHtml(ruleLabel(rule))}</strong> <span class="muted">${t("status.ruleCounts", { documents: formatNumber(documents), count: formatNumber(count) })}</span></summary>
      ${ruleHelp(rule) ? `<p class="muted">${escapeHtml(ruleHelp(rule))}</p>` : ""}
      ${table([t("status.document"), t("status.where"), t("status.count"), t("status.examples")], rows)}</details>`;
  });
  return section("status-rules", t("status.left_out"), t("status.left_out.help"), blocks.join("") || `<p>${t("status.none")}</p>`);
}

function unused(report) {
  const sections = table([t("status.section"), t("status.documents"), t("status.example")],
    report.unused.sections.map((s) => [escapeHtml(s.heading), formatNumber(s.documents), link(s.example, t("status.open"))]));
  const prose = table([t("status.document"), t("status.count"), t("status.examples")],
    report.unused.prose.map((p) => [link(p.page, p.title), formatNumber(p.count), `<span class="report-ids">${p.ids.map(escapeHtml).join(", ")}</span>`]));
  return section("status-unused", t("status.unused"), t("status.unusedHelp"),
    `<h4>${t("status.sections")}</h4><p class="muted">${t("status.sectionsHelp")}</p>${sections || `<p>${t("status.none")}</p>`}
     <h4>${t("status.prose")}</h4><p class="muted">${t("status.proseHelp")}</p>${prose || `<p>${t("status.none")}</p>`}`);
}

function sources(report) {
  const rows = report.sources.map((source) => [
    source.url ? link(source.url, sourceLabel(source.name)) : escapeHtml(sourceLabel(source.name)),
    source.status === "error"
      ? `<span class="badge potential">${t("status.failing", { date: formatDate(source.since) })}</span>`
      : `<span class="badge fixed">${t("status.ok")}</span>`,
    formatDate(source.last_success),
    source.errors.length ? `<ul class="report-errors">${source.errors.map((e) => `<li>${escapeHtml(e)}</li>`).join("")}</ul>` : "—",
  ]);
  return section("status-sources", t("status.sources"), t("status.sourcesHelp"),
    table([t("status.source"), t("status.state"), t("status.lastSuccess"), t("status.errors")], rows) || `<p>${t("status.noSource")}</p>`);
}

async function main() {
  $("language").addEventListener("click", () => {
    try { localStorage.setItem("language", language === "fr" ? "en" : "fr"); } catch { /* private window: the hash still works */ }
    location.hash = `lang=${language === "fr" ? "en" : "fr"}`;
    location.reload();
  });
  try {
    const response = await fetch("data/report.json");
    if (!response.ok) throw new Error(String(response.status));
    const report = await response.json();
    report.sources = report.sources || [];
    report.documents = report.documents || [];
    $("report").innerHTML = report.generated
      ? summary(report) + toFix(report) + rules(report) + unused(report) + sources(report)
      : `<p>${t("status.empty")}</p>${sources(report)}`;
  } catch {
    $("report").innerHTML = `<p>${t("status.failed")}</p>`;
  }
}

main();
