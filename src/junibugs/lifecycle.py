"""Support dates of the Junos branches, from Juniper's "Junos OS Dates & Milestones" page.

Read when the data is collected, never by the browser. Juniper publishes no
separate table for Junos OS Evolved on that page: the site says so where it
applies these dates to Evolved. A page that no longer parses keeps the last dates.
"""
import html
import json
import logging
import re
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

PAGE_URL = "https://support.juniper.net/support/eol/software/junos/"
MINIMUM_BRANCHES = 10

ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
BRANCH = re.compile(r"^Junos OS (\d+\.\d+)\b")


def iso(text: str) -> str:
    return datetime.strptime(text.strip(), "%m/%d/%Y").strftime("%Y-%m-%d")


def parse_lifecycle(page: str) -> dict:
    """Return {branch: {released, engineering, support, type}}; raise if the page looks wrong."""
    branches = {}
    for row in ROW.findall(page):
        cells = [html.unescape(re.sub(r"<sup.*?</sup>|<[^>]+>", "", cell, flags=re.S)).strip() for cell in CELL.findall(row)]
        match = BRANCH.match(cells[0]) if cells else None
        if not match or len(cells) < 5 or not all(cells[1:4]):
            continue
        branches[match.group(1)] = {
            "released": iso(cells[1]),
            "engineering": iso(cells[2]),
            "support": iso(cells[3]),
            "type": cells[4],
        }
    if len(branches) < MINIMUM_BRANCHES:
        raise ValueError(f"only {len(branches)} branches in the lifecycle page")
    return branches


def update_lifecycle(path: Path, client) -> None:
    """Refresh the dates; the Release Notes must not depend on this page."""
    try:
        response = client.request("GET", PAGE_URL)
        response.raise_for_status()
        branches = parse_lifecycle(response.text)
    except (RuntimeError, ValueError, OSError) as error:
        log.error("support dates kept as they were: %s", error)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"source": PAGE_URL, "branches": branches}, indent=2) + "\n")
