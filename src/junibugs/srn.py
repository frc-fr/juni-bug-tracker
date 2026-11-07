"""Service releases (-S): their "Software Release Notification" (SRN) articles.

Each service release has an SRN article on the Juniper support portal, at a
predictable address that answers 200 when it exists and 404 otherwise; the
robots.txt of the portal allows robots. The site links to the article.

The article is drawn by JavaScript: it is rendered by Lightpanda, a headless
browser, then its "List of Fixed issues" and "List of Known issues" are read.
A part marked "Confidential" is never read, nor are security entries, as the
site does not deal with security, nor descriptions that are notes between
engineers.
"""
import json
import os
import shlex
import subprocess
import time
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .versions import SYSTEMS, branch_key, branch_of, entry_key, parse_reference, train_of, version_key

log = logging.getLogger(__name__)

ARTICLE_URL = "https://supportportal.juniper.net/s/article/{name}"
SITEMAP_URL = "https://supportportal.juniper.net/s/sitemap.xml"
ARTICLE_NAME = re.compile(r"/s/article/(\d+)-(\d+)R(\d+)-S(\d+)(-EVO)?-SRN</loc>(?:<lastmod>([^<]+)</lastmod>)?")
PROBE_AHEAD = 2

USER_AGENT_SUFFIX = "juni-bug-tracker/0.1 (+https://github.com/frc-fr/juni-bug-tracker)"
SECURITY = re.compile(r"\bvulnerabilit|\bCVE-\d|/JSA\d|\bSIRT=yes\b", re.I)
STATUSES = {"Fixed": "resolved", "Known": "open"}
# Some descriptions are notes between engineers ("@name please make a release note"): never shown.
INTERNAL_NOTE = re.compile(r"(?:^|\s)@[A-Za-z]\w*")


def article_name(system: str, version: str) -> str:
    major, minor, release, service = version_key(version)
    suffix = "-EVO" if system == "evo" else ""
    return f"{major}-{minor}R{release}-S{service}{suffix}-SRN"


def article_url(system: str, version: str) -> str:
    return ARTICLE_URL.format(name=article_name(system, version))


def load_releases(path: Path) -> Dict[str, dict]:
    if not path.exists():
        return {}
    return {entry_key(e["system"], e["version"]): e for e in json.loads(path.read_text())["releases"]}


def save_releases(path: Path, releases: Dict[str, dict], missing: Dict[str, List[str]]) -> None:
    entries = sorted(releases.values(), key=lambda e: (e["system"], version_key(e["version"])))
    path.write_text(json.dumps({"releases": entries, "missing": missing}, indent=2) + "\n")


def load_missing(path: Path) -> Dict[str, List[str]]:
    return json.loads(path.read_text()).get("missing", {}) if path.exists() else {}


def sitemap_versions(client) -> List[Tuple[str, str, Optional[str]]]:
    """Service releases listed by the sitemaps of the portal, with the date of their last change.

    The lists have gaps, but their dates tell which articles changed since the last run.
    """
    index = client.request("GET", SITEMAP_URL)
    index.raise_for_status()
    found = []
    for url in re.findall(r"<loc>([^<]*topicarticle[^<]*)</loc>", index.text):
        page = client.request("GET", url)
        if page.status_code != 200:
            continue
        for major, minor, release, service, evo, changed in ARTICLE_NAME.findall(page.text):
            found.append(("evo" if evo else "junos", f"{major}.{minor}R{release}-S{service}", changed or None))
    return found


def update_releases(path: Path, manifest: Dict[str, dict], client) -> Dict[str, dict]:
    """Find the service releases of each R release of the manifest, by their article.

    The sitemaps give most of them, with their last change. The numbers after
    the last one known are checked on the latest R release of each branch only:
    the older ones get no new service release in practice. A number that answered
    404 below the last one known is recorded as missing and not checked again.
    """
    releases = load_releases(path)
    missing = load_missing(path)
    trains = {(e["system"], e["version"]) for e in manifest.values()}
    lowest = {system: min((branch_key(v["branch"]) for v in manifest.values() if v["system"] == system), default=(0, 0))
              for system in SYSTEMS}
    try:
        listed = sitemap_versions(client)
    except (RuntimeError, OSError) as error:
        log.error("sitemaps not read: %s", error)
        listed = []
    for system, version, changed in listed:
        if branch_key(branch_of(version)) >= lowest[system]:
            entry = releases.setdefault(entry_key(system, version), {"system": system, "version": version})
            if changed:
                entry["lastmod"] = changed
    latest = {}
    for system, train in trains:
        branch = (system, branch_of(train))
        if branch not in latest or version_key(train) > version_key(latest[branch]):
            latest[branch] = train
    for system, train in sorted(trains, key=lambda t: (t[0], version_key(t[1]))):
        if latest[(system, branch_of(train))] != train:
            continue
        known = [version_key(e["version"])[3] for e in releases.values() if e["system"] == system and train_of(e["version"]) == train]
        gone = set(missing.get(entry_key(system, train), []))
        top = max(known, default=0)
        for service in range(1, top + PROBE_AHEAD + 1):
            version = f"{train}-S{service}"
            if service in known or (service in gone and service <= top):
                continue
            response = client.request("HEAD", article_url(system, version))
            if response.status_code == 200:
                log.info("%s: service release found", entry_key(system, version))
                releases[entry_key(system, version)] = {"system": system, "version": version}
                top = max(top, service)
            elif response.status_code == 404:
                gone.add(service)
        if gone:
            missing[entry_key(system, train)] = sorted(gone)
    for entry in releases.values():
        entry["article"] = article_url(entry["system"], entry["version"])
    save_releases(path, releases, missing)
    return releases


RENDERER_ENV = "JUNIBUGS_LIGHTPANDA"
RENDER_TIMEOUT = 120
# The synopsis ends with its product group: a "|" inside a quoted command cannot shift the columns.
ROW = re.compile(r"^\| \[(\d{6,8})\]\([^)]*\)\s*(Critical|Major|Minor)?\s*\| (.*?)\s*Product-Group=\S+(?:\s+Severity=(\w+))?\s*\| (.*) \|\s*$")
SHORT_ROW = re.compile(r"^\| \[(\d{6,8})\]\([^)]*\)\s*(Critical|Major|Minor)?\s*\| (.*) \|\s*$")
# Most tables have a Synopsis column; some articles only give the description.
CATEGORY_ROW = re.compile(r"^\| PR Number \|( Synopsis \|)? Category: (.*?) \|\s*$")
TITLE = re.compile(r"^# (\d+\.\d+R\d+-S\d+(?:-EVO)?): Software Release Notification")
MAX_SYNOPSIS = 220
SECTION = re.compile(r"^## (\d+\.\d+R\d+-S\d+(?:-EVO)?) - List of (Fixed|Known) issues(.*)$", re.I)
PRODUCT = re.compile(r"\s*Product-Group=\S+(?:\s+Severity=(\w+))?\s*$")
ATTACHED = "included in the attachment"
ATTACHMENT_LINK = re.compile(r"See \[Attachment\]\(")
CREATED = re.compile(r"^Created(\d{4}-\d{2}-\d{2})$", re.M)


def renderer() -> List[str]:
    """The Lightpanda command, from JUNIBUGS_LIGHTPANDA: a path, or a wrapper running it."""
    command = os.environ.get(RENDERER_ENV, "lightpanda")
    return shlex.split(command)


def render_article(url: str) -> str:
    """The article as markdown, once its JavaScript has drawn the lists."""
    command = renderer() + [
        "fetch", "--user-agent-suffix", USER_AGENT_SUFFIX,
        "--wait-script", "document.body && document.body.innerText.includes('List of')",
        "--wait-ms", "90000", "--dump", "markdown", url,
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=RENDER_TIMEOUT)
    # Some articles leave the lists to an attached file: the wait then times out on a complete page.
    if "List of" in result.stdout or ATTACHED in result.stdout:
        return result.stdout
    raise RuntimeError(f"{url}: rendering failed ({result.returncode})")


def needs_rendering(key: str, entry: dict, extracted: Path) -> bool:
    """New, or changed since its last rendering according to the sitemap.

    The rendering is recorded in sources/srn.json and its result committed in
    data/: losing the cache of the runner never makes every article rendered again.
    """
    rendered = entry.get("rendered")
    if rendered is None:
        return True
    if entry.get("lastmod") and entry["lastmod"] != rendered:
        return True
    return not (extracted / f"{key}.json").exists() and not entry.get("unread")


def fetch_articles(releases: Dict[str, dict], cache: Path, extracted: Path, delay: float = 2.0) -> List[str]:
    cache.mkdir(parents=True, exist_ok=True)
    fetched = []
    for key, entry in sorted(releases.items()):
        if not needs_rendering(key, entry, extracted):
            continue
        try:
            text = render_article(entry["article"])
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
            # An article drawn empty for visitors is kept as unread until it changes.
            log.error("%s: %s", key, error)
            entry["rendered"] = entry.get("lastmod") or "unknown"
            entry["unread"] = "empty for visitors"
            continue
        (cache / f"{key}.md").write_text(text, encoding="utf-8")
        entry["rendered"] = entry.get("lastmod") or "unknown"
        entry.pop("unread", None)
        if (ATTACHED in text and "List of" not in text) or ATTACHMENT_LINK.search(text):
            entry["unread"] = "lists in an attachment"
            log.warning("%s: the lists are in an attachment the page does not link", key)
        created = CREATED.search(unescape(text))
        if created:
            entry["created"] = created.group(1)
        fetched.append(key)
        log.info("%s: article rendered", key)
        time.sleep(delay)
    return fetched


@dataclass
class Notice:
    system: str
    version: str
    created: Optional[str] = None
    items: List[dict] = field(default_factory=list)
    skipped: int = 0
    internal: int = 0
    warnings: List[str] = field(default_factory=list)


def unescape(text: str) -> str:
    return re.sub(r"\\([-()\[\]_*#.!+{}`>|\\])", r"\1", text)


def references(text: str) -> List[Tuple[str, str]]:
    found = []
    for token in text.split():
        reference = parse_reference(token)
        if reference and reference not in found:
            found.append(reference)
    return found


def first_sentence(text: str) -> str:
    sentence = re.split(r"(?<=[.!?])\s+(?=[A-Z])", " ".join(text.split()))[0]
    return sentence if len(sentence) <= MAX_SYNOPSIS else sentence[:MAX_SYNOPSIS].rsplit(" ", 1)[0] + "…"


def parse_row(line: str, category: Optional[str], synopsis_column: bool = True) -> Optional[dict]:
    if synopsis_column:
        match = ROW.match(line)
        if not match:
            return None
        bug_id, severity, synopsis, stated, description = match.groups()
        severity = severity or stated
    else:
        match = SHORT_ROW.match(line)
        if not match:
            return None
        bug_id, severity, description = match.groups()
        synopsis = first_sentence(description.split("Resolved In:")[0].replace("*", " "))
    product = PRODUCT.search(synopsis)
    if product:
        severity = severity or product.group(1)
        synopsis = synopsis[:product.start()]
    description = PRODUCT.sub("", description)
    resolved = []
    if "Resolved In:" in description:
        description, tokens = description.split("Resolved In:", 1)
        resolved = references(tokens.replace("*", " "))
    return {
        "bug_id": bug_id,
        "category": category,
        "severity": severity,
        "synopsis": " ".join(synopsis.split()),
        "description": " ".join(description.replace("*", " ").split()),
        "resolved_in": resolved,
    }


def parse_article(text: str) -> Notice:
    """Read the "List of Fixed issues" and "List of Known issues" of a rendered SRN."""
    text = unescape(text)
    notice: Optional[Notice] = None
    status = None
    category = None
    synopsis_column = True
    title = None
    for line in text.splitlines():
        heading_title = TITLE.match(line.strip())
        if heading_title:
            title = heading_title.group(1)
        # Without "List of" titles, the fixed issues follow the Solution section.
        if line.strip() == "## Solution" and title and not re.search(r"- List of", text, re.I) and ATTACHED not in text:
            notice = notice or Notice("evo" if title.endswith("-EVO") else "junos", title.replace("-EVO", ""))
            status = "resolved"
            continue
        section = SECTION.match(line.strip())
        if section:
            version = section.group(1)
            if "confidential" in section.group(3).lower():
                status = None
                continue
            notice = notice or Notice("evo" if version.endswith("-EVO") else "junos", version.replace("-EVO", ""))
            status = STATUSES[section.group(2).capitalize()]
            continue
        if line.startswith("## "):
            status = None
            continue
        if status is None:
            continue
        heading = CATEGORY_ROW.match(line)
        if heading:
            synopsis_column = bool(heading.group(1))
            category = heading.group(2).strip()
            continue
        row = parse_row(line, category, synopsis_column)
        if not row:
            continue
        if SECURITY.search(line):
            notice.skipped += 1
            continue
        if INTERNAL_NOTE.search(row["description"]):
            row["description"] = ""
            notice.internal += 1
        notice.items.append({**row, "status": status})
    if notice is None:
        raise ValueError("lists in an attachment" if ATTACHED in text else "no list of fixed issues")
    if not notice.items and ATTACHMENT_LINK.search(text):
        raise ValueError("lists in an attachment")
    created = CREATED.search(text)
    notice.created = created.group(1) if created else None
    if not notice.items:
        notice.warnings.append("no issue read")
    return notice
