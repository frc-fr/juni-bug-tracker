"""Hardware status: Juniper's end of life tables and its suggested releases.

Two public pages of Juniper, read when the data is collected, never by the browser:

- the "Hardware Dates & Milestones" page of each product series, on
  support.juniper.net: one row per announcement, with the SKUs it covers, the
  last software version that supports them and their end of support. Only the
  chassis SKUs are kept (EX4300-48MP, MX2010-BASE-AC), named after the model
  the site uses (EX4300) and their variant (EX4300-48MP): a power supply or a
  fan reaching its end of life says nothing of the switch it goes into.
- the article KB21476 "Junos Software Versions - Suggested Releases to Consider
  and Evaluate", on the support portal, drawn by JavaScript and rendered by
  Lightpanda like the SRN articles: one row per platform, with the suggested
  release, "(LSV)" when it is the last one the platform supports, and its date.

A page that no longer parses keeps the last values.
"""
import html
import json
import logging
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .normalize import PREFIXES, models_in
from .srn import USER_AGENT_SUFFIX, renderer

log = logging.getLogger(__name__)

SERIES_URL = "https://support.juniper.net/support/eol/product/{series}_series/"
# The series of the families the notes cover; the MX Series is on the "M Series" page.
SERIES = ["acx", "ex", "m", "nfx", "ptx", "qfx", "srx"]
MINIMUM_ANNOUNCEMENTS = 60
SUGGESTED_URL = "https://supportportal.juniper.net/s/article/Junos-Software-Versions-Suggested-Releases-to-Consider-and-Evaluate"
MINIMUM_PLATFORMS = 60
RENDER_TIMEOUT = 150

TABLE = re.compile(r"<table.*?</table>", re.S)
ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
# A renamed or transformed SKU is no end of life.
NOT_AN_END = re.compile(r"renaming|transformation", re.I)
# A chassis SKU: the model, then its port layout (EX4300-48MP) or a system bundle (MX2010-BASE-AC).
CHASSIS = re.compile(rf"^((?:{'|'.join(PREFIXES)})\d{{2,5}}[A-Z]?)(?:-(\d+[A-Z0-9]*)|-(?:BASE|PREMIUM\d?|SYS|CHAS|AC|DC|JB|JE)\b)")
BRANCH = re.compile(r"^(\d+\.\d+)")


def write_lines(path: Path, head: dict, key: str, items: List[dict]) -> None:
    """One item per line, for readable diffs."""
    lines = ",\n".join("  " + json.dumps(item, ensure_ascii=False) for item in items)
    body = json.dumps(head, ensure_ascii=False)[:-1]
    path.write_text(f'{body}, "{key}": [\n{lines}\n]}}\n', encoding="utf-8")


def cell_text(cell: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", cell)).split())


def iso(text: str) -> Optional[str]:
    try:
        return datetime.strptime(text.strip(), "%m/%d/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def chassis_of(sku: str) -> Optional[tuple]:
    """(model, variant) of a chassis SKU, None for a part: EX4300-48MP-TAA is ("EX4300", "EX4300-48MP")."""
    match = CHASSIS.match(sku.strip())
    if not match or sku.startswith("B-"):
        return None
    model = match.group(1)
    if not models_in(model):
        return None
    return models_in(model)[0], f"{model}-{match.group(2)}" if match.group(2) else model


def parse_series(page: str, url: str) -> List[dict]:
    """The announcements of a series page that cover chassis, with their variants.

    The page has two tables: the recent announcements, with their technical
    bulletin and last software version, and the older ones, without either.
    """
    found = []
    for table in TABLE.findall(page):
        for row in ROW.findall(table)[1:]:
            cells = [cell_text(cell) for cell in CELL.findall(row)]
            if len(cells) == 8:
                title, skus, announced, last_software, end = cells[0], cells[1], cells[2], cells[6], cells[7]
            elif len(cells) == 7:
                title, skus, announced, last_software, end = None, cells[0], cells[1], None, cells[6]
            else:
                continue
            if NOT_AN_END.search(title or skus):
                continue
            variants: Dict[str, set] = {}
            for sku in skus.split(","):
                named = chassis_of(sku)
                if named:
                    variants.setdefault(named[0], set()).add(named[1])
            branch = BRANCH.match(last_software or "")
            for model, names in variants.items():
                found.append({
                    "model": model,
                    "variants": sorted(names),
                    "bulletin": title.split(" - ")[0] if title else None,
                    "announced": iso(announced),
                    "last_software": branch.group(1) if branch else None,
                    "end_of_support": iso(end),
                    "page": url,
                })
    return found


def update_eol(path: Path, client) -> None:
    """Refresh the end of life announcements; one series failing keeps them all as they were."""
    announcements = []
    try:
        for series in SERIES:
            url = SERIES_URL.format(series=series)
            response = client.request("GET", url)
            response.raise_for_status()
            announcements += parse_series(response.text, url)
        if len(announcements) < MINIMUM_ANNOUNCEMENTS:
            raise ValueError(f"only {len(announcements)} chassis announcements")
    except (RuntimeError, ValueError, OSError) as error:
        log.error("hardware end of life kept as it was: %s", error)
        return
    # A bulletin repeats its dates on several rows of SKUs: one fact is kept once.
    unique = {json.dumps(a, sort_keys=True): a for a in announcements}
    announcements = sorted(unique.values(), key=lambda a: (a["model"], a["announced"] or "", a["variants"]))
    write_lines(path, {"source": "https://support.juniper.net/support/eol/"}, "announcements", announcements)


# | [EX4300 ](https://...) | Latest Junos 21.4R3\-Sx | 2025\-2\-28 | notes |
PLATFORM_ROW = re.compile(r"^\| \[([^\]]+?)\s*\](?:\([^)]*\))? \| (.*?) \| (\d{4}\\?-\d{1,2}\\?-\d{1,2}) \|(.*)\|\s*$")
RELEASE = re.compile(r"(\d{2}\.\d)(?:(R\d+)(?:-S(\d+|x))?|(X\d+-D\d+))?(?:-EVO)?", re.I)


def unescape(text: str) -> str:
    return re.sub(r"\\(.)", r"\1", text)


def parse_suggested(markdown: str) -> List[dict]:
    """The platforms of KB21476, with the releases suggested for them."""
    platforms = []
    for line in markdown.splitlines():
        match = PLATFORM_ROW.match(line)
        if not match:
            continue
        name, text, updated, notes = (unescape(part).strip() for part in match.groups())
        text = " ".join(text.split())
        releases = []
        for branch, train, service, special in RELEASE.findall(text):
            release = branch + (train or special or "")
            if train and service:
                release += "-S" + service.lower()
            if release not in releases:
                releases.append(release)
        year, month, day = (int(part) for part in updated.split("-"))
        platforms.append({
            "platform": " ".join(name.split()),
            "models": models_in(name),
            "text": text,
            "releases": releases,
            "system": "evo" if re.search(r"EVO|Evolved", text) else "junos",
            "last": bool(re.search(r"\bLSV\b", text)),
            "updated": f"{year:04d}-{month:02d}-{day:02d}",
        })
    return platforms


def render_suggested() -> str:
    command = renderer() + [
        "fetch", "--user-agent-suffix", USER_AGENT_SUFFIX,
        "--wait-script", "document.body && document.body.innerText.includes('Junos Software by Platform')",
        "--wait-ms", "90000", "--dump", "markdown", SUGGESTED_URL,
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=RENDER_TIMEOUT)
    if "Junos Software by Platform" not in result.stdout:
        raise RuntimeError(f"{SUGGESTED_URL}: rendering failed ({result.returncode})")
    return result.stdout


def update_suggested(path: Path) -> None:
    """Refresh the suggested releases; a failed rendering keeps them as they were."""
    try:
        platforms = parse_suggested(render_suggested())
        if len(platforms) < MINIMUM_PLATFORMS:
            raise ValueError(f"only {len(platforms)} platforms in KB21476")
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as error:
        log.error("suggested releases kept as they were: %s", error)
        return
    write_lines(path, {"source": SUGGESTED_URL, "as_of": max(p["updated"] for p in platforms)}, "platforms", platforms)


def load(path: Path) -> Optional[dict]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def hardware_index(system: str, cited: List[str], eol: Optional[dict], suggested: Optional[dict]) -> dict:
    """The models of the Hardware tab of a system, with what Juniper says of their end of life.

    The tab lists the models the notes cite, those KB21476 suggests a release of
    this system for, and, for Junos OS, the models of an end of life announcement:
    the announcements do not say which system runs on the hardware, and the old
    models they hold all run Junos OS. The browser decides the status, as it
    depends on the latest branch and on the day.
    """
    platforms = [p for p in (suggested or {}).get("platforms", []) if p["system"] == system]
    announcements = (eol or {}).get("announcements", [])
    models = set(cited) | {model for p in platforms for model in p["models"]}
    if system == "junos":
        evo_only = {model for p in (suggested or {}).get("platforms", []) if p["system"] == "evo" for model in p["models"]}
        models |= {a["model"] for a in announcements} - (evo_only - {m for p in platforms for m in p["models"]})
    entries = {}
    for model in models:
        entries[model] = {
            "cited": model in cited,
            "eol": [[a["variants"], a["bulletin"], a["last_software"], a["end_of_support"], a["page"]]
                    for a in announcements if a["model"] == model],
            "suggested": [[p["platform"], p["text"], p["releases"], p["last"], p["updated"]]
                          for p in platforms if model in p["models"]],
        }
    return {
        "eol_source": (eol or {}).get("source"),
        "suggested_source": (suggested or {}).get("source"),
        "as_of": max((p["updated"] for p in platforms), default=None),
        # Rows of KB21476 naming a whole series or a design, as "MX Series" or "IP-Fabric": shown in the news.
        "general": [[p["platform"], p["text"], p["releases"], p["updated"]] for p in platforms if not p["models"]],
        "models": dict(sorted(entries.items())),
    }
