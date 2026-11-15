"""The processing report, data/report.json: what each run could not read, and why.

Shared by the five bug trackers, word for word. A document is "read", "left_out"
(read, with parts a known rule leaves out), "suspect" (read, but the result departs
from what the vendor publishes), "unreachable" (the collection could not get it) or
"not_understood" (a layout the code does not read: the code has to be adapted).
Only what is not plainly read is detailed. The site shows the report on etat.html.
"""
import json
import logging
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional

# Below this share of documents read, the update stops and the site keeps its last version.
PUBLISH_MINIMUM = 0.75
# A document that loses more than this share of its bugs is suspect: its last reading is kept.
DROP_LIMIT = 0.5
EXAMPLES = 10
SECTIONS = 50
PROSE = 50
ERRORS = 20
STATUSES = ["not_understood", "unreachable", "suspect", "left_out", "read"]
TO_FIX = ["not_understood", "unreachable", "suspect"]


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save(path: Path, report: dict) -> None:
    """One document per line, so that a run gives a readable git diff."""
    lines = []
    for name, value in report.items():
        if isinstance(value, list) and value:
            items = ",\n".join("    " + json.dumps(item, ensure_ascii=False, sort_keys=True) for item in value)
            lines.append(f'  {json.dumps(name)}: [\n{items}\n  ]')
        else:
            lines.append(f"  {json.dumps(name)}: {json.dumps(value, ensure_ascii=False, sort_keys=True)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{\n" + ",\n".join(lines) + "\n}\n", encoding="utf-8")


class _Catcher(logging.Handler):
    def __init__(self):
        super().__init__(logging.ERROR)
        self.messages: List[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@contextmanager
def source(path: Path, name: str, url: Optional[str] = None) -> Iterator[None]:
    """Run one step of the collection: the errors it logs go to the report, or its success."""
    catcher = _Catcher()
    root = logging.getLogger()
    root.addHandler(catcher)
    try:
        yield
    except Exception as error:
        catcher.messages.append(f"{type(error).__name__}: {error}")
        raise
    finally:
        root.removeHandler(catcher)
        report = load(path)
        sources = {s["name"]: s for s in report.get("sources", [])}
        entry = sources.get(name, {"name": name, "last_success": None, "since": None})
        entry["url"] = url
        if catcher.messages:
            entry["since"] = entry.get("since") if entry.get("status") == "error" else now()
            entry.update(status="error", errors=catcher.messages[:ERRORS], count=len(catcher.messages))
        else:
            entry.update(status="ok", errors=[], count=0, since=None, last_success=now())
        sources[name] = entry
        report["sources"] = sorted(sources.values(), key=lambda s: s["name"])
        save(path, report)


def finding(kind: str, rule: str, page: str, where: str, ids: List[str], detail: str) -> dict:
    return {"kind": kind, "rule": rule, "page": page, "where": where, "count": len(ids), "ids": ids, "detail": detail}


def merged(findings: List[dict]) -> List[dict]:
    """The findings of one document, one per kind, rule, page and place, with a few IDs each."""
    found: Dict[tuple, dict] = {}
    for f in findings:
        key = (f["kind"], f["rule"], f["page"], f["where"])
        if key in found:
            found[key]["ids"] = list(dict.fromkeys(found[key]["ids"] + f["ids"]))
            found[key]["count"] += f["count"]
        else:
            found[key] = {**f, "ids": list(f["ids"])}
    for f in found.values():
        f["ids"] = f["ids"][:EXAMPLES]
    return sorted(found.values(), key=lambda f: (STATUSES.index(f["kind"]), f["rule"], f["page"], f["where"]))


def status_of(findings: List[dict]) -> str:
    return min((f["kind"] for f in findings), key=STATUSES.index, default="read")


def document(key: str, group: str, title: str, url: str, findings: List[dict], ids: Dict[str, list],
             previous: Optional[dict], kept: Optional[str] = None) -> dict:
    """The report entry of one document; `since` is kept while its status stays the same."""
    status = status_of(findings)
    same = previous and previous.get("status") == status
    return {
        "key": key, "group": group, "title": title, "url": url, "status": status,
        "since": previous["since"] if same else now()[:10], "kept": kept,
        "ids": {"vendor": len(ids["vendor"]), "read": len(ids["read"]), "ruled": len(ids["ruled"]),
                "failed": len(ids["failed"]), "unaccounted": sorted(ids["unaccounted"])[:EXAMPLES]},
        "findings": merged(findings),
    }


def accounting(listed: set, read: set, findings: List[dict]) -> Dict[str, set]:
    """Each bug ID the vendor lists, in one bucket: read, ruled out, failed, or unaccounted."""
    failed = {i for f in findings if f["kind"] == "not_understood" for i in f["ids"]} - read
    ruled = {i for f in findings if f["kind"] == "left_out" for i in f["ids"]} - read - failed
    vendor = listed | read | ruled | failed
    return {"vendor": vendor, "read": read, "ruled": ruled, "failed": failed, "unaccounted": listed - read - ruled - failed}


def shape(heading: str) -> str:
    """A section title without its releases and numbers: "Open Bugs in Release X"."""
    text = re.sub(r"\S*\d\S*", "X", heading)
    return re.sub(r"(X[\s,/-]*)+X", "X", " ".join(text.split()))


def unused_sections(headings: Dict[str, Dict[str, bool]], urls: Dict[str, str]) -> List[dict]:
    """Section titles the site never reads anything under, by number of documents."""
    seen: Dict[str, dict] = {}
    for key, titles in headings.items():
        for title, used in titles.items():
            if used or not title.strip():
                continue
            entry = seen.setdefault(shape(title), {"heading": shape(title), "documents": set(), "example": urls[key]})
            entry["documents"].add(key)
    ranked = sorted(seen.values(), key=lambda e: (-len(e["documents"]), e["heading"]))[:SECTIONS]
    return [{**e, "documents": len(e["documents"])} for e in ranked]


def publication(documents: List[dict], total: int) -> dict:
    """Whether to publish: enough documents must be read; an unreachable one keeps its last reading."""
    reachable = total - sum(d["status"] == "unreachable" for d in documents)
    failing = sum(d["status"] == "not_understood" or bool(d["kept"]) for d in documents if d["status"] != "unreachable")
    share = round(1 - failing / reachable, 3) if reachable else 1.0
    return {"published": share >= PUBLISH_MINIMUM, "read_share": share, "minimum": PUBLISH_MINIMUM}


def build(path: Path, documents: List[dict], total: int, groups: List[dict], sections: List[dict], prose: List[dict]) -> dict:
    """The report of an extraction, with the sources the collection recorded; saved, and returned."""
    report = load(path)
    totals = {status: 0 for status in STATUSES}
    for d in documents:
        totals[d["status"]] += 1
    totals["read"] = total - sum(totals[s] for s in STATUSES if s != "read")
    report.update({
        "generated": now(),
        "publication": publication(documents, total),
        "totals": {"documents": total, **totals},
        "groups": groups,
        "documents": sorted(documents, key=lambda d: (STATUSES.index(d["status"]), d["group"], d["title"])),
        "unused": {"sections": sections, "prose": sorted(prose, key=lambda p: (-p["count"], p["title"]))[:PROSE]},
    })
    report.setdefault("sources", [])
    save(path, report)
    return report


def check(report: dict) -> List[str]:
    """What is left to fix: one line per document or source."""
    lines = [f"{d['status']}: {d['group']} {d['title']} ({', '.join(sorted({f['rule'] for f in d['findings']}))}) {d['url']}"
             for d in report.get("documents", []) if d["status"] in TO_FIX]
    lines += [f"source in error: {s['name']}: {s['errors'][0] if s['errors'] else ''}"
              for s in report.get("sources", []) if s.get("status") == "error"]
    return lines
