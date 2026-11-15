"""Service releases (-S): their "Software Release Notification" (SRN) articles.

Each service release has an SRN article on the Juniper support portal, at a
predictable address that answers 200 when it exists and 404 otherwise; the
robots.txt of the portal allows robots. The site links to the article.

The article is drawn by JavaScript: it is rendered by Lightpanda, a headless
browser, then its "List of Fixed issues" and "List of Known issues" are read.
A part marked "Confidential" is never read, nor are security entries, as the
site does not deal with security, nor descriptions that are notes between
engineers.

Every PR number of a table row of the article ends in one bucket of the processing
report: read, left out by a known rule (security), or not understood (a row the code
cannot split). A row found in none of them, as a table under a title the code does
not know, is "unaccounted": the report calls the article suspect.
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
from typing import Dict, List, Optional, Set, Tuple

from .report import accounting, finding
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
# A row opens with its PR number, a link or a bare number, and may give its severity.
PR_CELL = r"^\| (?:\[(\d{6,8})\]\([^)]*\)|(\d{6,8}))\s*(Critical|Major|Minor)?\s*\| "
# The synopsis ends with its product group: a "|" inside a quoted command cannot shift the columns.
ROW = re.compile(PR_CELL + r"(.*?)\s*Product-Group=\S+(?:\s+Severity=(\w+))?\s*\| (.*) \|\s*$")
# Some rows lack the product group, their text cut short: read only when no "|" can shift the columns.
PLAIN_ROW = re.compile(PR_CELL + r"([^|]*?)\s*\| ([^|]*?)\s*\|\s*$")
SHORT_ROW = re.compile(PR_CELL + r"(.*) \|\s*$")
# A list without category nor description: the synopsis only.
SYNOPSIS_ROW = re.compile(PR_CELL + r"(?:(.*?)\s*Product-Group=\S+(?:\s+Severity=(\w+))?|([^|]*?))\s*\|\s*$")
# Most tables have a Synopsis column and a category; some articles only give the description,
# one gives the synopsis only, without category.
CATEGORY_ROW = re.compile(r"^\| (?:PR )?Number \|( Synopsis \|)? Category: (.*?) \|\s*$")
SYNOPSIS_HEADER = re.compile(r"^\| (?:PR )?Number \| Synopsis \|\s*$")
TITLE = re.compile(r"^# (\d+\.\d+R\d+-S\d+(?:-EVO)?): Software Release Notification")
MAX_SYNOPSIS = 220
SECTION = re.compile(r"^## (\d+\.\d+R\d+-S\d+(?:-EVO)?) - List of (Fixed|Known) issues(.*)$", re.I)
PRODUCT = re.compile(r"\s*Product-Group=\S+(?:\s+Severity=(\w+))?\s*$")
ATTACHED = "included in the attachment"
ATTACHMENT_LINK = re.compile(r"See \[Attachment\]\(")
CREATED = re.compile(r"^Created(\d{4}-\d{2}-\d{2})$", re.M)
# A table row that opens with a PR number: what the article lists, even in a form the code does not read.
LISTED_ROW = re.compile(r"^\|\s*\[?(\d{6,8})\b")
CITED = re.compile(r"\bPR\s?#?(\d{6,8})\b")
# The frame of every SRN article, not its content: never reported as content left unread.
FRAME = re.compile(
    r"^(alert type|product affected|alert description|download junos software service release:?|call to action|solution|"
    r"affected product series / features|\d+\.\d+R\d+-S\d+(-EVO)?: Software Release Notification.*|[\W_]*)$", re.I)


def renderer() -> List[str]:
    """The Lightpanda command, from JUNIBUGS_LIGHTPANDA: a path, or a wrapper running it."""
    command = os.environ.get(RENDERER_ENV, "lightpanda")
    return shlex.split(command)


# The frame Juniper draws around the text of every article: once it is in the output,
# the article is drawn, with or without lists.
ARTICLE_FRAME = re.compile(r"^## Alert Type\s*$", re.M)


class EmptyArticle(Exception):
    """The article is drawn, without any list for visitors."""


def check_rendering(url: str, output: str, returncode: int) -> str:
    """The output of Lightpanda when it holds the lists of the article.

    Raise EmptyArticle when the article is drawn without its lists, RuntimeError when
    the rendering failed: an empty output, or a page without the frame of the article.
    """
    # Some articles leave the lists to an attachment: the wait then times out on a complete page.
    if "List of" in output or ATTACHED in output:
        return output
    if ARTICLE_FRAME.search(output):
        raise EmptyArticle(f"{url}: the article shows no list to visitors")
    raise RuntimeError(f"{url}: rendering failed (exit {returncode}, {len(output.strip())} characters"
                       f"{'' if output.strip() else ', empty output'})")


def render_article(url: str) -> str:
    """The article as markdown, once its JavaScript has drawn the lists."""
    command = renderer() + [
        "fetch", "--user-agent-suffix", USER_AGENT_SUFFIX,
        "--wait-script", "document.body && document.body.innerText.includes('List of')",
        "--wait-ms", "90000", "--dump", "markdown", url,
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=RENDER_TIMEOUT)
    return check_rendering(url, result.stdout, result.returncode)


def needs_rendering(key: str, entry: dict, extracted: Path) -> bool:
    """New, or changed since its last rendering according to the sitemap.

    The rendering is recorded in sources/srn.json and its result committed in
    data/: losing the cache of the runner never makes every article rendered again.
    A failed rendering is not recorded: the article is rendered again on the next run.
    """
    rendered_on = entry.get("rendered")
    if rendered_on is None:
        return True
    if entry.get("lastmod") and entry["lastmod"] != rendered_on:
        return True
    return not (extracted / f"{key}.json").exists() and not entry.get("unread")


def fetch_articles(releases: Dict[str, dict], cache: Path, extracted: Path, delay: float = 2.0,
                   render=None) -> List[str]:
    """Render the new and changed articles into the cache; `render` stands for render_article in tests."""
    render = render or render_article
    cache.mkdir(parents=True, exist_ok=True)
    fetched = []
    for key, entry in sorted(releases.items()):
        if not needs_rendering(key, entry, extracted):
            continue
        try:
            text = render(entry["article"])
        except EmptyArticle as empty:
            # An article drawn empty for visitors is kept as unread until it changes.
            log.warning("%s", empty)
            entry["rendered"] = entry.get("lastmod") or "unknown"
            entry["unread"] = "empty for visitors"
            entry.pop("render_failed", None)
            continue
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
            # Not recorded as rendered: tried again on the next run; the report calls it unreachable.
            log.warning("%s: %s", key, error)
            entry.pop("rendered", None)
            entry.pop("unread", None)
            entry["render_failed"] = str(error) or type(error).__name__
            continue
        (cache / f"{key}.md").write_text(text, encoding="utf-8")
        entry["rendered"] = entry.get("lastmod") or "unknown"
        entry.pop("unread", None)
        entry.pop("render_failed", None)
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
    internal: int = 0
    # What is not read, and why: a known rule ("left_out"), or a layout to adapt the code to.
    findings: List[dict] = field(default_factory=list)
    # PR number: (page, place) where the article lists it.
    listed: Dict[str, Tuple[str, str]] = field(default_factory=dict)
    # Each section title, and whether the site reads something under it.
    headings: Dict[str, bool] = field(default_factory=dict)
    # PR numbers cited outside the lists.
    prose: Set[str] = field(default_factory=set)

    @property
    def warnings(self) -> List[str]:
        """What the code cannot read: it has to be adapted."""
        return [f"{f['where'] or 'article'}: {f['detail']}" for f in self.findings if f["kind"] == "not_understood"]

    @property
    def skipped(self) -> int:
        """The security entries left out."""
        return sum(f["count"] for f in self.findings if f["rule"] == "security")

    def accounting(self) -> Dict[str, Set[str]]:
        """Each PR number the article lists, in one bucket: read, ruled out, failed, or unaccounted."""
        return accounting(set(self.listed), {i["bug_id"] for i in self.items}, self.findings)


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


def parse_row(line: str, category: Optional[str], columns: str = "synopsis") -> Optional[dict]:
    """One row of a list; `columns` says its layout: "synopsis" (synopsis and description),
    "description" (the description only) or "two" (the synopsis only, without category)."""
    if columns == "synopsis":
        match = ROW.match(line)
        if match:
            linked, bare, severity, synopsis, stated, description = match.groups()
            severity = severity or stated
        else:
            match = PLAIN_ROW.match(line)
            if not match:
                return None
            linked, bare, severity, synopsis, description = match.groups()
    elif columns == "two":
        match = SYNOPSIS_ROW.match(line)
        if not match:
            return None
        linked, bare, severity, synopsis, stated, plain = match.groups()
        severity = severity or stated
        synopsis = synopsis if synopsis is not None else plain
        # Nothing but the synopsis: the site shows it as the description, without detail.
        description = synopsis
    else:
        match = SHORT_ROW.match(line)
        if not match:
            return None
        linked, bare, severity, description = match.groups()
        synopsis = first_sentence(description.split("Resolved In:")[0].replace("*", " "))
    bug_id = linked or bare
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


def parse_article(text: str, url: str = "") -> Notice:
    """Read the "List of Fixed issues" and "List of Known issues" of a rendered SRN; `url` is the article."""
    text = unescape(text)
    notice: Optional[Notice] = None
    status = None
    category = None
    columns = "synopsis"
    title = None
    heading = ""
    confidential = False
    findings: List[dict] = []
    listed: Dict[str, Tuple[str, str]] = {}
    headings: Dict[str, bool] = {}
    prose: Set[str] = set()
    for line in text.splitlines():
        heading_title = TITLE.match(line.strip())
        if heading_title:
            title = heading_title.group(1)
        if line.startswith("#"):
            heading = line.lstrip("#").replace("*", "").strip()
            if not FRAME.match(heading):
                headings.setdefault(heading, False)
        # Without "List of" titles, the fixed issues follow the Solution section.
        if line.strip() == "## Solution" and title and not re.search(r"- List of", text, re.I) and ATTACHED not in text:
            notice = notice or Notice("evo" if title.endswith("-EVO") else "junos", title.replace("-EVO", ""))
            status, confidential = "resolved", False
            continue
        section = SECTION.match(line.strip())
        if section:
            version = section.group(1)
            if "confidential" in section.group(3).lower():
                status, confidential = None, True
                headings.pop(heading, None)
                findings.append(finding("left_out", "confidential", url, heading, [], "a part marked Confidential, never read"))
                continue
            notice = notice or Notice("evo" if version.endswith("-EVO") else "junos", version.replace("-EVO", ""))
            status, confidential = STATUSES[section.group(2).capitalize()], False
            # Each list states its own columns: no category is carried from the list before.
            category, columns = None, "synopsis"
            headings[heading] = True
            continue
        if line.startswith("## "):
            status, confidential = None, False
            continue
        listing = LISTED_ROW.match(line)
        if not listing:
            prose.update(CITED.findall(line))
        elif not confidential:
            listed.setdefault(listing.group(1), (url, heading))
        if status is None:
            continue
        header = line.replace("**", "")  # bold headers; a lone "*" belongs to the category
        row_heading = CATEGORY_ROW.match(header)
        if row_heading:
            columns = "synopsis" if row_heading.group(1) else "description"
            category = row_heading.group(2).strip()
            continue
        if SYNOPSIS_HEADER.match(header):
            columns, category = "two", None
            continue
        row = parse_row(line, category, columns)
        if not row:
            if listing:
                findings.append(finding("not_understood", "row_unknown", url, heading, [listing.group(1)],
                                        "a row the code cannot split into synopsis and description"))
            continue
        if SECURITY.search(line):
            findings.append(finding("left_out", "security", url, heading, [row["bug_id"]], "a security entry"))
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
        findings.append(finding("not_understood", "no_issue", url, "", [], "no issue read in the article"))
    notice.findings, notice.listed, notice.headings = findings, listed, headings
    notice.prose = prose - set(listed)
    return notice


# PDF copies of the articles whose lists Lightpanda cannot read, downloaded by hand
# from the support portal and dropped in .cache/srn-attachments; never fetched by a robot.
PDF_LIST_TITLE = re.compile(r"^(\d+\.\d+R\d+-S\d+(?:-EVO)?) - List of (Fixed|Known) issues(.*)$", re.I)
PDF_ID = re.compile(r"^(\d{6,8})$")
PDF_SEVERITY = re.compile(r"^(Critical|Major|Minor)$")
PDF_HEADER = {"PR", "Number", "Synopsis"}
# Older copies print the date, the page number and a local path on top of each page.
PDF_FURNITURE = re.compile(r"^(\d{1,2}/\d{1,2}/\d{2}, \d{1,2}:\d{2} [AP]M|Page \d+ of \d+|file:///.*|jtac-web\.\S+)$")


def parse_srn_pdf(path: Path, url: str = "") -> Notice:
    """Read the lists of a PDF copy of an SRN; `url` is the article it copies.

    Its description column is cut at the right margin, words missing: only the
    synopsis, complete, and the short "Resolved In" lines are kept.
    """
    import fitz

    lines = [" ".join(line.split()) for page in fitz.open(path) for line in page.get_text().splitlines()]
    lines = [line for line in lines if line and not PDF_FURNITURE.match(line)]
    notice: Optional[Notice] = None
    status = None
    category = None
    entries: List[dict] = []
    current: Optional[dict] = None
    part = None
    heading = ""
    findings: List[dict] = []
    listed: Dict[str, Tuple[str, str]] = {}
    headings: Dict[str, bool] = {}
    for index, line in enumerate(lines):
        title = PDF_LIST_TITLE.match(line)
        if title:
            heading = line
            if "confidential" in title.group(3).lower():
                status = None
                findings.append(finding("left_out", "confidential", url, heading, [], "a part marked Confidential, never read"))
                continue
            headings[heading] = True
            version = title.group(1)
            notice = notice or Notice("evo" if version.endswith("-EVO") else "junos", version.replace("-EVO", ""))
            status = STATUSES[title.group(2).capitalize()]
            current = None
            continue
        if status is None:
            continue
        if line.startswith("Category:"):
            category, current = line[len("Category:"):].strip(), None
            continue
        if line in PDF_HEADER:
            continue
        following = lines[index + 1] if index + 1 < len(lines) else ""
        if PDF_ID.match(line):
            listed.setdefault(line, (url, heading))
        # A PR number opens an entry, followed by its severity or its synopsis.
        if PDF_ID.match(line) and (part in (None, "description", "resolved") or PDF_SEVERITY.match(following)):
            current = {"bug_id": line, "category": category, "severity": None, "synopsis": [], "description": [],
                       "resolved": [], "status": status, "raw": [line], "where": heading}
            entries.append(current)
            part = "synopsis"
            continue
        if current is None:
            continue
        current["raw"].append(line)
        if part == "synopsis" and PDF_SEVERITY.match(line) and not current["synopsis"]:
            current["severity"] = line
        elif line.startswith("Product-Group="):
            part = "description"
        elif line.startswith("Severity="):
            current["severity"] = current["severity"] or line.split("=", 1)[1]
        elif line.startswith("Resolved In:"):
            part = "resolved"
            current["resolved"].append(line[len("Resolved In:"):])
        elif part in ("synopsis", "description", "resolved"):
            current[part].append(line)
    if notice is None:
        raise ValueError("no list of fixed issues")
    for entry in entries:
        if SECURITY.search(" ".join(entry["raw"])):
            findings.append(finding("left_out", "security", url, entry["where"], [entry["bug_id"]], "a security entry"))
            continue
        notice.items.append({
            "bug_id": entry["bug_id"],
            "category": entry["category"],
            "severity": entry["severity"],
            "synopsis": " ".join(" ".join(entry["synopsis"]).split()),
            "description": "",
            "resolved_in": references(" ".join(entry["resolved"])),
            "status": entry["status"],
        })
    if not notice.items:
        findings.append(finding("not_understood", "no_issue", url, "", [], "no issue read in the PDF copy"))
    notice.findings, notice.listed, notice.headings = findings, listed, headings
    return notice
