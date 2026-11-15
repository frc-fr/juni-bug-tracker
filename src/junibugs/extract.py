"""Turn the cached PDFs and SRN articles into data/extracted/, log what changed, and write the processing report."""
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from . import report
from .collect import load_manifest, sort_key
from .parser import Document, parse_pdf
from .srn import Notice, article_url, load_releases, parse_article, parse_srn_pdf
from .versions import SYSTEMS, branch_of, split_key, version_key

log = logging.getLogger(__name__)


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def write_version(path: Path, system: str, version: str, document: Document) -> None:
    """One observation per line, so that a PDF revision gives a readable git diff."""
    head = {
        "system": system,
        "version": version,
        "branch": branch_of(version),
        "released": document.released,
        "revised": document.revised,
        "pages": document.pages,
        "families": document.families,
        "models": document.models,
        "notices": document.notices,
        "changes": document.changes,
    }
    lines = ",\n".join("  " + json.dumps(o, ensure_ascii=False) for o in document.observations)
    body = json.dumps(head, ensure_ascii=False)[:-1]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'{body}, "observations": [\n{lines}\n]}}\n', encoding="utf-8")


def bug_sets(observations: List[dict]) -> Tuple[Set[str], Set[str]]:
    """Return the fixed and the known PRs of a version."""
    fixed = {o["bug_id"] for o in observations if o["status"] == "resolved"}
    known = {o["bug_id"] for o in observations if o["status"] != "resolved"}
    return fixed, known


def diff_version(system: str, version: str, before: List[dict], after: List[dict], date: str) -> List[dict]:
    """Juniper keeps revising published notes: report the PRs a revision added."""
    old_fixed, old_known = bug_sets(before)
    new_fixed, new_known = bug_sets(after)
    entries = []
    for kind, added in (("known_added", new_known - old_known), ("fixed_added", new_fixed - old_fixed)):
        if added:
            entries.append({"date": date, "system": system, "version": version, "kind": kind, "bugs": sorted(added, key=int)})
    return entries


def change_key(change: dict):
    return change["date"], change["system"], version_key(change["version"]), change["kind"]


def read_changes(path: Path) -> List[dict]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def write_changes(path: Path, changes: List[dict]) -> None:
    lines = ",\n".join("  " + json.dumps(change, ensure_ascii=False) for change in sorted(changes, key=change_key))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"[\n{lines}\n]\n", encoding="utf-8")


BUCKETS = ("vendor", "read", "ruled", "failed", "unaccounted")
# Why an SRN is not read, as sources/srn.json records it: a rule of the report each.
UNREAD_RULES = {
    "empty for visitors": ("srn_empty", "the article shows no list to visitors"),
    "lists in an attachment": ("srn_attachment", "the lists are in an attachment the page does not link"),
    "holds the SRN of another release": ("srn_other_release", "the article holds the text of another release"),
}


@dataclass
class Tally:
    """What the extraction found in each document, for the processing report."""
    previous: Dict[str, dict]
    entries: List[dict] = field(default_factory=list)
    groups: Dict[str, dict] = field(default_factory=dict)
    headings: Dict[str, Dict[str, bool]] = field(default_factory=dict)
    urls: Dict[str, str] = field(default_factory=dict)
    prose: List[dict] = field(default_factory=list)
    total: int = 0

    def add(self, key: str, system: str, title: str, url: str, findings: List[dict], parsed, had: int,
            kept: Optional[str]) -> bool:
        """Count one document; return whether its last reading is kept rather than the new one.

        `parsed` is the Document or Notice read, None when nothing could be read; `had`
        the number of PRs of its last reading, `kept` the date of that reading.
        """
        self.total += 1
        group = SYSTEMS[system]
        ids: Dict[str, Set[str]] = {bucket: set() for bucket in BUCKETS}
        if parsed:
            findings = findings + parsed.findings
            ids = parsed.accounting()
            places: Dict[Tuple[str, str], List[str]] = {}
            for bug in sorted(ids["unaccounted"]):
                places.setdefault(parsed.listed[bug], []).append(bug)
            for (page, where), bugs in places.items():
                findings.append(report.finding("suspect", "unaccounted", page, where, bugs,
                                               "PR numbers the document lists that no rule of the code accounts for"))
            count = len(ids["read"])
            if had and not count:
                findings.append(report.finding("suspect", "lost_bugs", url, "", [], f"the document had {had} PRs and has none now"))
            elif had and count < (1 - report.DROP_LIMIT) * had:
                findings.append(report.finding("suspect", "drop", url, "", [], f"{count} PRs read, {had} before"))
            self.headings[key] = parsed.headings
            if parsed.prose:
                self.prose.append({"key": key, "title": title, "page": url, "count": len(parsed.prose),
                                   "ids": sorted(parsed.prose)[:report.EXAMPLES]})
        self.urls[key] = url
        keep = parsed is None or any(f["rule"] in ("lost_bugs", "drop") for f in findings)
        totals = self.groups.setdefault(group, {"name": group, "documents": 0, **{bucket: 0 for bucket in BUCKETS}})
        totals["documents"] += 1
        for bucket in BUCKETS:
            totals[bucket] += len(ids[bucket])
        if report.status_of(findings) != "read":
            self.entries.append(report.document(key, group, title, url, findings, ids, self.previous.get(key),
                                                (kept or "—") if keep and had else None))
        return keep


def read_json(path: Path) -> Optional[dict]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def extract_pdfs(manifest_path: Path, cache: Path, output: Path, changes: List[dict], baseline: bool, date: str,
                 tally: Tally) -> None:
    """Parse every cached PDF of the manifest; write what is read, and the PRs a revision added."""
    manifest = load_manifest(manifest_path)
    for key, entry in sorted(manifest.items(), key=lambda item: sort_key(item[1])):
        pdf = cache / f"{key}.pdf"
        if not pdf.exists() and not entry.get("unavailable"):
            continue
        system, version = entry["system"], entry["version"]
        url = entry["pdf_url"]
        target = output / system / f"{version}.json"
        previous = read_json(target)
        findings: List[dict] = []
        document = None
        if pdf.exists():
            try:
                document = parse_pdf(pdf, url)
            except Exception as error:  # A PDF that breaks the parser must not pass silently.
                findings.append(report.finding("not_understood", "parse_error", url, "", [], f"the parser stops: {error!r}"))
        if entry.get("unavailable"):
            findings.append(report.finding("unreachable", "http", url, "", [],
                                           "the PDF no longer answers at its address: its last reading stays"))
        had = len({o["bug_id"] for o in previous["observations"]}) if previous else 0
        title = f"{SYSTEMS[system]} {version} Release Notes"
        keep = tally.add(key, system, title, url, findings, document, had, (previous or {}).get("revised"))
        if keep:
            continue
        if previous is None or baseline:
            released = document.released or (None if baseline else date)
            if released:
                changes.append({"date": released, "system": system, "version": version, "kind": "version", "bugs": []})
        else:
            changes.extend(diff_version(system, version, previous["observations"], document.observations, date))
        write_version(target, system, version, document)
        log.info("%s: %d observations, %d security entries left out", key, len(document.observations), document.skipped)


def read_srn(path: Path, url: str = "") -> Notice:
    if path.suffix == ".pdf":
        return parse_srn_pdf(path, url)
    return parse_article(path.read_text(encoding="utf-8"), url)


def write_notice(path: Path, notice: Notice, source: str) -> None:
    head = {"system": notice.system, "version": notice.version, "created": notice.created, "skipped": notice.skipped,
            "source": source}
    lines = ",\n".join("  " + json.dumps(item, ensure_ascii=False) for item in notice.items)
    body = json.dumps(head, ensure_ascii=False)[:-1]
    path.write_text(f'{body}, "items": [\n{lines}\n]}}\n', encoding="utf-8")


def extract_srn(srn_path: Path, cache: Path, output: Path, attachments: Path, tally: Tally) -> None:
    """Read the rendered SRN articles, or the PDF copies added by hand, into data/extracted/srn/.

    A PDF copy replaces the article of the same release, which may be shown empty to
    visitors. An article without file in the cache keeps its committed reading, uncounted.
    """
    output.mkdir(parents=True, exist_ok=True)
    releases = load_releases(srn_path)
    copies: Dict[str, Path] = {}
    for path in sorted(attachments.glob("*.pdf")):
        try:
            notice = parse_srn_pdf(path)
        except Exception as error:  # The file names do not say the release: it is only logged.
            log.error("%s: PDF copy not read: %r", path.name, error)
            continue
        copies[f"{notice.system}-{notice.version}"] = path
    articles = {path.stem: path for path in cache.glob("*.md")}
    for key in sorted(set(releases) | set(articles) | set(copies), key=lambda k: (split_key(k)[0], version_key(split_key(k)[1]))):
        system, version = split_key(key)
        entry = releases.get(key, {})
        url = entry.get("article") or article_url(system, version)
        target = output / f"{key}.json"
        previous = read_json(target)
        findings: List[dict] = []
        notice = None
        source = key in copies and copies[key] or articles.get(key)
        if source:
            try:
                notice = read_srn(source, url)
            except ValueError as error:
                if "attachment" in str(error):
                    findings.append(report.finding("left_out", "srn_attachment", url, "", [], UNREAD_RULES["lists in an attachment"][1]))
                else:
                    findings.append(report.finding("not_understood", "no_issue", url, "", [], str(error)))
            except Exception as error:  # An article that breaks the parser must not pass silently.
                findings.append(report.finding("not_understood", "parse_error", url, "", [], f"the parser stops: {error!r}"))
            if notice and f"{notice.system}-{notice.version}" != key:
                # Juniper published the text of another release under this address: not trusted.
                findings.append(report.finding("left_out", "srn_other_release", url, "", [],
                                               f"the article holds the SRN of {notice.version}"))
                notice = None
        elif entry.get("unread") in UNREAD_RULES:
            rule, detail = UNREAD_RULES[entry["unread"]]
            findings.append(report.finding("left_out", rule, url, "", [], detail))
        else:
            continue
        had = len({item["bug_id"] for item in previous["items"]}) if previous else 0
        title = f"{SYSTEMS[system]} {version} Software Release Notification"
        if tally.add(key, system, title, url, findings, notice, had, (previous or {}).get("created")):
            continue
        write_notice(target, notice, "pdf" if source.suffix == ".pdf" else "article")
        log.info("%s: %d PRs, %d security entries left out", key, len(notice.items), notice.skipped)


def extract_all(manifest_path: Path, cache: Path, output: Path, changes_path: Path, report_path: Path,
                srn_path: Path, srn_cache: Path, srn_attachments: Path, date: Optional[str] = None) -> List[str]:
    """Parse every cached PDF and SRN, write what is read and the processing report; return why the update stops.

    A document is published for what the code reads of it; what it does not read is in
    the report. A document that no longer parses, or loses most of its PRs, keeps its
    last reading. The update stops only when too few documents are read
    (report.PUBLISH_MINIMUM): the site then keeps its last version rather than an empty one.

    Without a change log the data is a baseline: published releases are recorded
    with their release date, as nothing tells which PRs were added when.
    """
    date = date or today()
    baseline = not changes_path.exists()
    changes = read_changes(changes_path)
    tally = Tally({d["key"]: d for d in report.load(report_path).get("documents", [])})
    extract_pdfs(manifest_path, cache, output, changes, baseline, date, tally)
    extract_srn(srn_path, srn_cache, output / "srn", srn_attachments, tally)
    for found in tally.entries:
        if found["status"] in report.TO_FIX:
            log.warning("%s: %s %s", found["key"], found["status"], ", ".join(sorted({f["rule"] for f in found["findings"]})))
    order = list(SYSTEMS.values())
    summary = report.build(report_path, tally.entries, tally.total,
                           sorted(tally.groups.values(), key=lambda g: order.index(g["name"])),
                           report.unused_sections(tally.headings, tally.urls), tally.prose)
    publication = summary["publication"]
    if not publication["published"]:
        return [f"only {publication['read_share']:.0%} of the documents read, under {publication['minimum']:.0%}: "
                "the site keeps its last version"]
    # A stopped extraction must not leave a log describing data that is not published.
    write_changes(changes_path, changes)
    return []
