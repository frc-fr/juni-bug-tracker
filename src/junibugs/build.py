"""Generate the static site: copy site/ and cross the extracted data into dist/data/<system>/."""
import json
import logging
import re
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .collect import load_manifest, revision_date
from .extract import read_changes
from .feed import build_feed, latest_changes
from .normalize import UNCATEGORIZED, families_in, family_of_model, models_in, normalize_category
from .srn import article_url, load_releases
from .versions import SYSTEMS, branch_key, branch_of, entry_key, train_of, version_key

log = logging.getLogger(__name__)

STATUS_CODES = {"resolved": "r", "open": "k", "limitation": "l"}
UNREAD_REASONS = {"empty for visitors": "empty", "lists in an attachment": "attachment", "holds the SRN of another release": "other"}


def load_extracted(directory: Path) -> Dict[str, dict]:
    documents = {}
    for path in directory.glob("*/*.json"):
        if path.parent.name == "srn":
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        documents[entry_key(document["system"], document["version"])] = document
    return documents


def read_schedule(path: Path) -> Optional[dict]:
    """The crons of the automatic update, read in sources/schedule.yml so the site cannot contradict it."""
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    crons = re.findall(r'cron:\s*"([^"]+)"', text)
    timezone_name = re.search(r'timezone:\s*"([^"]+)"', text)
    if not crons:
        return None
    return {"crons": crons, "timezone": timezone_name.group(1) if timezone_name else "UTC"}


def cited_hardware(documents: List[dict]) -> List[str]:
    models = set()
    for document in documents:
        models.update(document.get("models", []))
        for observation in document["observations"]:
            models.update(models_in(f"{observation['description']} {observation['workaround'] or ''}"))
    return sorted(models, key=lambda m: (re.match(r"[A-Z]+", m).group(0), int(re.search(r"\d+", m).group(0))))


def load_notices(directory: Path) -> Dict[str, dict]:
    """The SRN extractions, keyed as <system>-<version>."""
    return {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in directory.glob("*.json")}


def build_system(system: str, documents: Dict[str, dict], manifest: Dict[str, dict], lifecycle: dict,
                 releases: Dict[str, dict], notices_srn: Dict[str, dict]) -> dict:
    """Index and bugs of one system; the PR numbers are shared, the facts are not.

    The Release Notes give the R releases. The service releases come from their
    SRN articles, and their fixes from the SRN PDFs: those of the release itself,
    and the other releases each PR is "Resolved In", on any branch.
    """
    own = {doc["version"]: doc for doc in documents.values() if doc["system"] == system}
    entries = {e["version"]: e for e in manifest.values() if e["system"] == system}
    trains = set(own) | set(entries)
    lowest = min(branch_key(branch_of(v)) for v in trains)
    in_scope = lambda version: train_of(version) in trains and branch_key(branch_of(version)) >= lowest
    articles = {e["version"]: e for e in releases.values() if e["system"] == system}
    # "Resolved In" also names releases without article: planned ones, as 23.4R2-S10
    # while 23.4R2-S8 is the latest out, and numbers Juniper published no article for.
    referenced = {
        version for notice in notices_srn.values() for item in notice["items"]
        for item_system, version in item["resolved_in"] if item_system == system
    }
    services = {v for v in set(articles) | referenced if in_scope(v)}
    latest_train = {}
    for train in trains:
        if version_key(train) > version_key(latest_train.get(branch_of(train), "0.0R0")):
            latest_train[branch_of(train)] = train
    latest_service = {}
    for version in articles:
        train = train_of(version)
        latest_service[train] = max(latest_service.get(train, 0), version_key(version)[3])
    versions = sorted(trains | services, key=version_key)
    positions = {version: i for i, version in enumerate(versions)}

    models = cited_hardware(list(own.values()))
    names = {name for doc in own.values() for name, _ in doc["families"]}
    names |= {family_of_model(model) for model in models}
    families = sorted(names, key=str.lower)
    family_positions = {name: i for i, name in enumerate(families)}

    bugs: Dict[str, dict] = {}

    def add_event(bug: dict, version: str, code: str, page=None, family=None, release=None, source=None):
        event = bug["events"].setdefault((version, code), [positions[version], code, page, [], release, source])
        if family is not None:
            event[3] = sorted(set(event[3]) | {family_positions[family]})
        if page is not None and event[2] is None:
            event[2] = page

    for version in sorted(own, key=version_key):
        for o in own[version]["observations"]:
            bug = bugs.setdefault(o["bug_id"], {"events": {}, "families": set()})
            bug["category"] = normalize_category(o["category"])
            if o["description"]:
                bug["description"] = o["description"]
            bug["workaround"] = o["workaround"] or bug.get("workaround")
            bug["families"].add(o["family"])
            # A release can list a PR as fixed in one family and open in another: both facts are kept.
            add_event(bug, version, STATUS_CODES[o["status"]], o["page"], o["family"], o.get("release"))

    for key, notice in sorted(notices_srn.items(), key=lambda item: version_key(item[1]["version"])):
        source_system, source = notice["system"], notice["version"]
        for item in notice["items"]:
            facts = [(system, source, STATUS_CODES[item["status"]])] if source_system == system else []
            facts += [(s, v, "r") for s, v in item["resolved_in"] if s == system]
            facts = [(v, code) for s, v, code in facts if v in positions]
            if not facts:
                continue
            bug = bugs.setdefault(item["bug_id"], {"events": {}, "families": set()})
            bug.setdefault("category", UNCATEGORIZED)
            bug.setdefault("description", item["synopsis"])
            bug.setdefault("workaround", None)
            bug["severity"] = item["severity"] or bug.get("severity")
            if item["description"] and item["description"] != item["synopsis"]:
                bug["detail"] = item["description"]
            if item["category"]:
                bug["srn_category"] = item["category"]
            for version, code in facts:
                origin = None if version == source else key
                add_event(bug, version, code, source=origin)

    categories = sorted({bug["category"] for bug in bugs.values()}, key=str.lower)
    category_positions = {name: i for i, name in enumerate(categories)}
    rows = []
    for bug_id, bug in sorted(bugs.items(), key=lambda item: -int(item[0])):
        text = f"{bug.get('description', '')} {bug['workaround'] or ''} {bug.get('srn_category', '')}"
        cited_models = models_in(text)
        cited = (set(families_in(text)) | {family_of_model(m) for m in cited_models}) & set(family_positions)
        rows.append([
            bug_id,
            category_positions[bug["category"]],
            bug.get("description", ""),
            bug["workaround"],
            cited_models,
            sorted(family_positions[name] for name in bug["families"] | cited),
            sorted(bug["events"].values(), key=lambda event: (event[0], event[1])),
            bug.get("severity"),
            bug.get("srn_category"),
            bug.get("detail"),
        ])

    index_versions = []
    for version in versions:
        doc = own.get(version, {})
        entry = entries.get(version, {})
        service = "-S" in version
        index_versions.append({
            "v": version,
            "branch": branch_of(version),
            "released": doc.get("released") or notices_srn.get(f"{system}-{version}", {}).get("created"),
            "revised": doc.get("revised") or revision_date(entry),
            "pages": doc.get("pages", {}),
            "pdf": None if entry.get("unavailable") else entry.get("pdf_url"),
            "article": articles.get(version, {}).get("article"),
            "service": service,
            # Without article: "pending" when it comes after the latest article of the latest R
            # release of its branch, the only train still getting service releases; else "none".
            "publication": None if not service or version in articles
            else "pending" if train_of(version) == latest_train[branch_of(version)]
            and version_key(version)[3] > latest_service.get(train_of(version), 0) else "none",
            "read": (f"{system}-{version}" in notices_srn) if service else version in own,
            # Why an article was not read: "empty" for visitors, lists in an "attachment", or the text of an "other" release.
            "unread": None if f"{system}-{version}" in notices_srn else UNREAD_REASONS.get(articles.get(version, {}).get("unread")),
            "unavailable": not service and version not in own,
            "families": sorted(family_positions[name] for name, _ in doc.get("families", [])),
            "changes": [[family_positions[f], c, text, page] for f, c, text, page in doc.get("changes", [])],
        })
    sources = {key: articles.get(n["version"], {}).get("article") or article_url(n["system"], n["version"])
               for key, n in notices_srn.items()}
    index = {
        "system": system,
        "name": SYSTEMS[system],
        "families": families,
        "models": models,
        "versions": index_versions,
        "sources": {key: {"version": notices_srn[key]["version"], "system": notices_srn[key]["system"], "article": url}
                    for key, url in sources.items()},
        "lifecycle": {**lifecycle, "shared": system == "evo"},
    }
    notices = {
        version: [[None if f is None else family_positions.get(f), title, page] for f, title, page in doc.get("notices", [])]
        for version, doc in own.items()
    }
    return {"index": index, "bugs": {"categories": categories, "bugs": rows, "annotations": {"bugs": {}, "versions": {}}},
            "notices": notices}


def build_site(
    extracted: Path, manifest_path: Path, changes_path: Path, lifecycle_path: Path, schedule_path: Path,
    sources: Path, dist: Path, base_url: str, srn_path: Path = Path("sources/srn.json"),
) -> dict:
    documents = load_extracted(extracted)
    manifest = load_manifest(manifest_path)
    lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8")) if lifecycle_path.exists() else {"source": None, "branches": {}}
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    schedule = read_schedule(schedule_path)
    all_changes = read_changes(changes_path)
    releases = load_releases(srn_path)
    notices_srn = load_notices(extracted / "srn")

    if dist.exists():
        shutil.rmtree(dist)
    shutil.copytree(sources, dist)
    summary = {}
    descriptions: Dict[str, str] = {}
    for system in SYSTEMS:
        data = build_system(system, documents, manifest, lifecycle, releases, notices_srn)
        data["index"].update({"updated": updated, "schedule": schedule})
        changes = latest_changes([c for c in all_changes if c["system"] == system], documents)
        folder = dist / "data" / system
        folder.mkdir(parents=True)
        for name, content in (("index.json", data["index"]), ("bugs.json", data["bugs"]),
                              ("changes.json", changes), ("notices.json", data["notices"])):
            (folder / name).write_text(json.dumps(content, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        descriptions.update({row[0]: row[2] for row in data["bugs"]["bugs"]})
        rows = data["bugs"]["bugs"]
        summary[system] = {
            "versions": len(data["index"]["versions"]),
            "families": len(data["index"]["families"]),
            "models": len(data["index"]["models"]),
            "categories": len(data["bugs"]["categories"]),
            "bugs": len(rows),
            "with model": sum(1 for row in rows if row[4]),
            "service releases": sum(1 for v in data["index"]["versions"] if v["service"]),
            "with severity": sum(1 for row in rows if row[7]),
        }
    (dist / "feed.xml").write_bytes(build_feed(latest_changes(all_changes, documents), descriptions, base_url))
    return summary
