"""Keep sources/manifest.json up to date and download the Release Notes PDFs.

The PDFs live at predictable addresses on networkingdocs.hpe.com, the documentation
site of HPE, which bought Juniper. No page is crawled: known PDFs are checked with
a HEAD, and new releases are looked for at the few addresses they can take next.

An entry marked "manual" was added by hand from another address, such as
www.juniper.net whose robots.txt disallows every robot: it is downloaded once,
when it is missing from the cache, and never checked again. None is needed today.
"""
import hashlib
import json
import logging
import time
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests

from .versions import SYSTEMS, branch_of, entry_key, version_key

log = logging.getLogger(__name__)

PDF_URL = (
    "https://networkingdocs.hpe.com/documentation/us/en/software/junos/release-notes/"
    "{branch}/{prefix}-release-notes-{name}/{prefix}-release-notes-{name}.pdf"
)
PREFIXES = {"junos": "junos", "evo": "junos-evo"}
NEW_LAYOUT = (26, 2, 1)
NEW_PDF_URL = "https://networkingdocs.hpe.com/documentation/rne/us/en/release-notes/{folder}/{version}/{prefix}-release-notes-{name}.pdf"
NEW_FOLDERS = {"junos": "Junos%20OS", "evo": "Junos%20OS%20Evolved"}
NEW_PREFIXES = {"junos": "junos-os", "evo": "junos-os-evolved"}
USER_AGENT = "juni-bug-tracker/0.1 (+https://github.com/frc-fr/juni-bug-tracker)"
CRAWL_DELAY = 2.0
WATCHED_BRANCHES = 3


def pdf_url(system: str, version: str) -> str:
    """The layout changed with 26.2, the first branch published under HPE."""
    name = version.lower()
    if version_key(version) >= NEW_LAYOUT:
        return NEW_PDF_URL.format(folder=NEW_FOLDERS[system], version=version, prefix=NEW_PREFIXES[system], name=name)
    return PDF_URL.format(branch=branch_of(version), prefix=PREFIXES[system], name=name)


class Client:
    """HTTP client that spaces out requests and retries transient failures."""

    def __init__(self, delay: float = CRAWL_DELAY, retries: int = 4):
        self.delay = delay
        self.retries = retries
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self._last = 0.0

    def request(self, method: str, url: str) -> requests.Response:
        for attempt in range(self.retries):
            wait = self._last + self.delay - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                response = self.session.request(method, url, timeout=90)
            except requests.RequestException as error:
                log.warning("%s %s failed: %s", method, url, error)
            else:
                if response.status_code not in (429, 500, 502, 503, 504):
                    return response
                log.warning("%s %s returned %s", method, url, response.status_code)
            time.sleep(self.delay * 2 ** (attempt + 1))
        raise RuntimeError(f"{method} {url}: giving up after {self.retries} attempts")


def sort_key(entry: dict):
    return entry["system"], version_key(entry["version"])


def load_manifest(path: Path) -> Dict[str, dict]:
    if not path.exists():
        return {}
    return {entry_key(e["system"], e["version"]): e for e in json.loads(path.read_text())["versions"]}


def save_manifest(path: Path, manifest: Dict[str, dict]) -> None:
    entries = sorted(manifest.values(), key=sort_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"versions": entries}, indent=2) + "\n")


def object_state(client: Client, url: str) -> Optional[dict]:
    response = client.request("HEAD", url)
    if response.status_code != 200 or "pdf" not in response.headers.get("Content-Type", "pdf"):
        return None
    return {
        "etag": response.headers.get("ETag", "").strip('"'),
        "last_modified": response.headers.get("Last-Modified"),
        "size": int(response.headers.get("Content-Length", 0)),
    }


def next_branch(branch: str) -> str:
    """Junos ships two branches a year since 23.2: X.2 in June, X.4 in December."""
    major, minor = map(int, branch.split("."))
    return f"{major}.4" if minor < 4 else f"{major + 1}.2"


def candidates(manifest: Dict[str, dict], system: str) -> List[str]:
    """Releases that may come next: one more R on the newest branches, R1 of the next ones."""
    known = sorted((e["version"] for e in manifest.values() if e["system"] == system), key=version_key)
    if not known:
        return []
    branches = sorted({branch_of(v) for v in known}, key=lambda b: tuple(map(int, b.split("."))))
    found = []
    for branch in branches[-WATCHED_BRANCHES:]:
        last = max((v for v in known if branch_of(v) == branch), key=version_key)
        found.append(f"{branch}R{version_key(last)[2] + 1}")
    upcoming = next_branch(branches[-1])
    found += [f"{upcoming}R1", f"{next_branch(upcoming)}R1"]
    return [v for v in found if entry_key(system, v) not in manifest]


def update_manifest(path: Path, client: Client) -> Dict[str, dict]:
    """Refresh the state of the known PDFs and add the new releases found."""
    manifest = load_manifest(path)
    for key, entry in sorted(manifest.items(), key=lambda item: sort_key(item[1])):
        if entry.get("manual"):
            continue
        state = object_state(client, entry["pdf_url"])
        if state is None:
            log.error("%s: PDF no longer reachable", key)
            entry["unavailable"] = True
            continue
        if entry.get("etag") != state["etag"]:
            log.info("%s: new revision %s", key, state["last_modified"])
        entry.update(state)
        entry.pop("unavailable", None)
    for system in SYSTEMS:
        for version in candidates(manifest, system):
            url = pdf_url(system, version)
            state = object_state(client, url)
            if state:
                log.info("%s: new release found", entry_key(system, version))
                manifest[entry_key(system, version)] = {
                    "system": system, "version": version, "branch": branch_of(version), "pdf_url": url, **state,
                }
    save_manifest(path, manifest)
    return manifest


def download_pdfs(manifest: Dict[str, dict], cache: Path, client: Client) -> List[str]:
    """Fetch the PDFs missing from the cache or revised since; return their keys."""
    cache.mkdir(parents=True, exist_ok=True)
    downloaded = []
    for key, entry in sorted(manifest.items(), key=lambda item: sort_key(item[1])):
        if entry.get("unavailable"):
            continue
        target = cache / f"{key}.pdf"
        stamp = cache / f"{key}.etag"
        current = target.exists() and (entry.get("manual") or (stamp.exists() and stamp.read_text() == entry["etag"]))
        if current:
            entry.setdefault("sha256", hashlib.sha256(target.read_bytes()).hexdigest())
            continue
        response = client.request("GET", entry["pdf_url"])
        response.raise_for_status()
        if not response.content.startswith(b"%PDF"):
            raise RuntimeError(f"{key}: {entry['pdf_url']} is not a PDF")
        target.write_bytes(response.content)
        stamp.write_text(entry.get("etag", ""))
        entry["sha256"] = hashlib.sha256(response.content).hexdigest()
        downloaded.append(key)
        log.info("%s: downloaded %d bytes", key, len(response.content))
    return downloaded


def revision_date(entry: dict) -> Optional[str]:
    stamp = entry.get("last_modified")
    return parsedate_to_datetime(stamp).strftime("%Y-%m-%d") if stamp else None
