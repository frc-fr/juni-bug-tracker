"""Turn the cached PDFs into data/extracted/<system>/<version>.json and log what changed."""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .parser import Document, parse_pdf
from .srn import parse_article
from .versions import branch_of, split_key, version_key

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


def cached_keys(cache: Path) -> List[str]:
    keys = [pdf.stem for pdf in cache.glob("*.pdf")]
    return sorted(keys, key=lambda key: (split_key(key)[0], version_key(split_key(key)[1])))


def extract_all(cache: Path, output: Path, changes_path: Path, date: Optional[str] = None) -> Dict[str, List[str]]:
    """Parse every cached PDF and return the warnings per release.

    Without a change log the data is a baseline: published releases are recorded
    with their release date, as nothing tells which PRs were added when.
    """
    date = date or today()
    baseline = not changes_path.exists()
    changes = read_changes(changes_path)
    problems = {}
    for key in cached_keys(cache):
        system, version = split_key(key)
        document = parse_pdf(cache / f"{key}.pdf")
        target = output / system / f"{version}.json"
        previous = json.loads(target.read_text(encoding="utf-8")) if target.exists() else None
        if previous is None or baseline:
            released = document.released or (None if baseline else date)
            if released:
                changes.append({"date": released, "system": system, "version": version, "kind": "version", "bugs": []})
        else:
            changes.extend(diff_version(system, version, previous["observations"], document.observations, date))
        write_version(target, system, version, document)
        log.info("%s: %d observations", key, len(document.observations))
        if document.warnings:
            problems[key] = document.warnings
    # A failed extraction must not leave a log describing data that is not published.
    if not problems:
        write_changes(changes_path, changes)
    return problems


def extract_srn(cache: Path, output: Path) -> Dict[str, List[str]]:
    """Read the rendered SRN articles into data/extracted/srn/<system>-<version>.json."""
    output.mkdir(parents=True, exist_ok=True)
    problems = {}
    for page in sorted(cache.glob("*.md")):
        try:
            notice = parse_article(page.read_text(encoding="utf-8"))
        except ValueError as error:
            # An article whose lists are attached is known, only its fixes are missing.
            if "attachment" not in str(error):
                problems[page.stem] = [str(error)]
            continue
        key = f"{notice.system}-{notice.version}"
        if key != page.stem:
            # Juniper published the text of another release under this address: not trusted.
            log.warning("%s: the article holds the SRN of %s, left out", page.stem, key)
            continue
        head = {"system": notice.system, "version": notice.version, "created": notice.created, "skipped": notice.skipped}
        lines = ",\n".join("  " + json.dumps(item, ensure_ascii=False) for item in notice.items)
        body = json.dumps(head, ensure_ascii=False)[:-1]
        (output / f"{key}.json").write_text(f'{body}, "items": [\n{lines}\n]}}\n', encoding="utf-8")
        log.info("%s: %d PRs, %d security entries left out", key, len(notice.items), notice.skipped)
        if notice.warnings:
            problems[key] = notice.warnings
    return problems
