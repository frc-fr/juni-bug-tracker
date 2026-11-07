"""Extract the problem reports of a Junos OS or Junos OS Evolved Release Notes PDF.

The PDFs have a real text layer and bookmarks: one top-level bookmark per product
family ("Junos OS Release Notes for MX Series"), with "Open Issues", "Resolved
Issues", "Known Limitations" and "What's Changed" under it. Each issue is a bullet
ending with its PR number. Anything that does not fit is reported in `warnings`
rather than dropped.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import fitz

from .normalize import canonical_family, models_in

PR = re.compile(r"\bPR\s?(\d{6,8})\b")
ENDS_WITH_PR = re.compile(r"\bPR\s?\d{6,8}\s*[.,;)]*\s*$")
VULNERABILITY = re.compile(r"\bvulnerabilit(?:y|ies)\b", re.I)
CVE_REFERENCE = re.compile(r"[\s(,;]*\bCVE-\d{4}-\d{4,}\b[)]?", re.I)
WORKAROUND = re.compile(r"\b(?:As a )?workaround\s*[:,]\s*", re.I)
RELEASE = re.compile(r"(\d+\.\d+R\d+(?:-S\d+)?)")
TOC_ENTRY = re.compile(r"^(.*?)\s+\|\s+\d+$")
BULLET = "•"
FAMILY_CHAPTER = re.compile(r"Release Notes for (.+)$")
SECTIONS = [
    (r"^open issues", "open"),
    (r"^resolved issues", "resolved"),
    (r"^known limitations", "limitation"),
    (r"^what.s changed", "changed"),
]
UPGRADE_CHAPTER = re.compile(r"upgrade|migration", re.I)
MAX_SUMMARY = 220
DASH = "—"


@dataclass
class Section:
    family: str
    title: str
    kind: str
    release: Optional[str]
    first_page: int
    last_page: int
    next_title: Optional[str]
    categories: List[str]


@dataclass
class Item:
    page: int
    category: Optional[str]
    lines: List[str] = field(default_factory=list)
    closed: bool = False


@dataclass
class Document:
    released: Optional[str]
    revised: Optional[str]
    families: List[list]
    models: List[str]
    observations: List[dict]
    changes: List[list]
    notices: List[list]
    warnings: List[str]
    pages: Dict[str, Optional[int]] = field(default_factory=dict)


def normalize_title(text: str) -> str:
    return re.sub(r"\W+", "", text.replace("’", "'")).lower()


def section_kind(title: str) -> Optional[str]:
    name = " ".join(title.split()).replace("’", "'").lower()
    return next((kind for pattern, kind in SECTIONS if re.match(pattern, name)), None)


def find_sections(doc: fitz.Document, warnings: List[str]) -> Tuple[List[Section], List[list]]:
    """Return the sections to read and the [family, page] of each family chapter."""
    toc = [(level, " ".join(title.split()), page) for level, title, page in doc.get_toc()]
    sections: List[Section] = []
    families: List[list] = []
    family = None
    for index, (level, title, page) in enumerate(toc):
        if level == 1:
            match = FAMILY_CHAPTER.search(title)
            family = canonical_family(match.group(1)) if match else None
            if match and not family:
                warnings.append(f"unknown family {match.group(1)!r}")
            if family and family not in [name for name, _ in families]:
                families.append([family, page])
            continue
        if level != 2 or not family:
            continue
        kind = section_kind(title)
        if not kind:
            continue
        following = next((entry for entry in toc[index + 1:] if entry[0] <= 2), None)
        children = []
        for entry in toc[index + 1:]:
            if entry[0] <= 2:
                break
            if entry[0] == 3:
                children.append(entry[1])
        release = RELEASE.search(title)
        sections.append(Section(
            family=family,
            title=title,
            kind=kind,
            release=release.group(1) if release else None,
            first_page=page,
            last_page=following[2] if following else len(doc),
            next_title=following[1] if following else None,
            categories=children,
        ))
    return sections, families


def find_title(lines: List[Tuple[int, str]], title: str, start: int = 0) -> Optional[Tuple[int, int]]:
    """Index of the first and last line holding a title, which may wrap over lines."""
    wanted = normalize_title(title)
    for first in range(start, len(lines)):
        text = normalize_title(lines[first][1])
        if not text or not wanted.startswith(text):
            continue
        last = first
        while len(text) < len(wanted) and last + 1 < len(lines):
            last += 1
            text += normalize_title(lines[last][1])
        if text == wanted:
            return first, last
    return None


def section_lines(doc: fitz.Document, section: Section) -> List[Tuple[int, str]]:
    """Lines of a section, as (page, text), without the page numbers."""
    lines = []
    for number in range(section.first_page, section.last_page + 1):
        for line in doc[number - 1].get_text().splitlines():
            text = " ".join(line.replace("\xa0", " ").split())
            if text and not text.isdigit():
                lines.append((number, text))
    start = find_title(lines, section.title)
    if start:
        lines = lines[start[1] + 1:]
    if section.next_title:
        end = find_title(lines, section.next_title)
        if end:
            lines = lines[:end[0]]
    return lines


def contents_categories(lines: List[Tuple[int, str]]) -> List[str]:
    """The "IN THIS SECTION" box lists the categories: "EVPN | 117"."""
    names = []
    for _, text in lines:
        match = TOC_ENTRY.match(text)
        if match:
            names.append(match.group(1).strip())
    return names


def looks_like_heading(lines: List[Tuple[int, str]], index: int) -> bool:
    """Notes without contents box: a short title line right before a bullet."""
    text = lines[index][1]
    following = lines[index + 1][1] if index + 1 < len(lines) else ""
    return (
        following.startswith(BULLET) and len(text) <= 60 and text[:1].isupper()
        and not re.search(r"[.,;:\]]$", text) and not PR.search(text) and DASH not in text
    )


def read_items(lines: List[Tuple[int, str]], categories: List[str], starts_item, loose: bool = False) -> List[Item]:
    """Split a section into bullets, following the category headings between them.

    With `loose`, a paragraph ending with a PR number outside any bullet is an
    issue too: some notes forget the bullet.
    """
    known = {normalize_title(name): name for name in categories}
    items: List[Item] = []
    category = None
    item: Optional[Item] = None
    paragraph: List[Tuple[int, str]] = []
    for index, (page, text) in enumerate(lines):
        if TOC_ENTRY.match(text):
            continue
        idle = item is None or item.closed or not item.lines or has_pr(item)
        heading = known.get(normalize_title(text))
        # The contents box, when there is one, is the only reliable list of categories.
        if not heading and not known and (idle or not loose) and looks_like_heading(lines, index):
            heading = text
        if heading and (idle or not loose):
            category, item, paragraph = heading, None, []
            continue
        if text.startswith(BULLET):
            paragraph = []
            rest = text[1:].strip()
            # The bullet usually stands alone on its line: the text follows on the next one.
            opening = rest or (lines[index + 1][1] if index + 1 < len(lines) else "")
            if starts_item(item, opening):
                item = Item(page, category)
                items.append(item)
                if rest:
                    item.lines.append(rest)
            elif item is not None:
                item.closed = False
                if rest:
                    item.lines.append(rest)
            continue
        if item is None or item.closed:
            if loose:
                paragraph.append((page, text))
                if ENDS_WITH_PR.search(text):
                    item = Item(paragraph[0][0], category, [line for _, line in paragraph], closed=True)
                    items.append(item)
                    paragraph = []
                elif text.endswith("."):
                    paragraph = []
            continue
        item.lines.append(text)
        if ENDS_WITH_PR.search(text):
            item.closed = True
    return items


def join_lines(lines: List[str]) -> str:
    """Join wrapped lines; a line broken after a hyphen is one word: "rate-" + "limit"."""
    text = ""
    for line in lines:
        glued = text.endswith("-") and len(text) > 1 and text[-2] != " "
        text += line if glued or not text else f" {line}"
    return text


def clean_description(text: str) -> Tuple[str, Optional[str]]:
    """Remove the PR numbers and CVE references, and split the workaround out."""
    text = PR.sub("", text)
    text = CVE_REFERENCE.sub("", " ".join(text.split())).strip(" ,;")
    text = re.sub(r"\s+([.,;:])", r"\1", text)
    parts = WORKAROUND.split(text, maxsplit=1)
    workaround = parts[1].strip() if len(parts) > 1 else None
    return parts[0].strip(), workaround or None


def first_sentence(text: str) -> str:
    """The summary of a change: its title when it has one, else its first sentence."""
    text = " ".join(text.split())
    head = text.split(DASH, 1)[0] if DASH in text[:MAX_SUMMARY] else re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)[0]
    head = re.sub(r"\s*\[See [^\]]*\]?\s*$", "", head).strip()
    if len(head) <= MAX_SUMMARY:
        return head
    return head[:MAX_SUMMARY].rsplit(" ", 1)[0] + "…"


def has_pr(item: Item) -> bool:
    return any(PR.search(line) for line in item.lines)


def issue_starts(item: Optional[Item], rest: str) -> bool:
    """A bullet inside an issue that has no PR yet is a list within that issue."""
    return item is None or item.closed or not item.lines or has_pr(item)


def change_starts(item: Optional[Item], rest: str) -> bool:
    """A change opens with its title and a dash; other bullets list its details."""
    return item is None or not item.lines or DASH in rest[:150] or not any(DASH in line for line in item.lines[:3])


def parse_issues(doc: fitz.Document, section: Section, warnings: List[str]) -> List[dict]:
    lines = section_lines(doc, section)
    categories = section.categories + contents_categories(lines)
    observations = []
    found = set()
    skipped = set()
    for item in read_items(lines, categories, issue_starts, loose=True):
        raw = join_lines(item.lines)
        ids = list(dict.fromkeys(PR.findall(raw)))
        if not ids:
            # Mostly limitations without PR: nothing to follow from a version to the next.
            continue
        if VULNERABILITY.search(raw):
            skipped.update(ids)
            continue
        description, workaround = clean_description(raw)
        for bug_id in ids:
            found.add(bug_id)
            observation = {
                "bug_id": bug_id,
                "status": section.kind,
                "family": section.family,
                "category": item.category,
                "description": description,
                "workaround": workaround,
                "page": item.page,
            }
            if section.release:
                observation["release"] = section.release
            observations.append(observation)
    expected = set(PR.findall("\n".join(text for _, text in lines)))
    missing = sorted(expected - found - skipped)
    if missing:
        warnings.append(f"{section.family} {section.title}: {len(missing)} PRs not parsed: {missing[:5]}")
    return observations


def parse_changes(doc: fitz.Document, section: Section) -> List[list]:
    lines = section_lines(doc, section)
    categories = section.categories + contents_categories(lines)
    rows = []
    for item in read_items(lines, categories, change_starts):
        text = join_lines(item.lines)
        if len(text) < 20:
            continue
        rows.append([section.family, item.category, first_sentence(text), item.page])
    return rows


def parse_date(text: str, anchored: bool = False) -> Optional[str]:
    for pattern, layout in ((r"\d{1,2} [A-Z][a-z]+ \d{4}", "%d %B %Y"), (r"\d{1,2}-[A-Z][a-z]{2}-\d{2}", "%d-%b-%y")):
        match = re.match(rf"\s*{pattern}", text) if anchored else re.search(pattern, text)
        if match:
            try:
                return datetime.strptime(match.group(0).strip(), layout).strftime("%Y-%m-%d")
            except ValueError:
                return None
    return None


def revision_dates(doc: fitz.Document) -> Tuple[Optional[str], Optional[str], Optional[int]]:
    """First and last dates of the "Revision History" chapter, and its page."""
    page = next((page for level, title, page in doc.get_toc() if title.strip() == "Revision History"), None)
    if not page:
        return None, None, None
    text = "\n".join(doc[number].get_text() for number in range(page - 1, len(doc)))
    text = text.split("Revision History", 1)[-1]
    # Newest first, one line per revision opening with its date. Order beats the
    # values: the notes hold typos, as a revision dated a year before the previous one.
    today = datetime.now().strftime("%Y-%m-%d")
    dates = [date for date in (parse_date(line, anchored=True) for line in text.splitlines()) if date and date <= today]
    if not dates:
        return None, None, page
    return dates[-1], dates[0], page


def extract_notices(doc: fitz.Document) -> List[list]:
    """The [family, title, page] of the upgrade chapters, worth reading before an upgrade."""
    notices = []
    family = None
    for level, title, page in doc.get_toc():
        title = " ".join(title.split())
        if level == 1:
            match = FAMILY_CHAPTER.search(title)
            family = canonical_family(match.group(1)) if match else None
            if not match and UPGRADE_CHAPTER.search(title):
                notices.append([None, title, page])
        elif level == 2 and UPGRADE_CHAPTER.search(title):
            notices.append([family, title, page])
    return notices


def chapter_models(doc: fitz.Document) -> List[str]:
    """Old Evolved notes name their chapters after models: "ACX7100-32C and ACX7509 Devices"."""
    titles = [title for level, title, _ in doc.get_toc() if level == 1 and FAMILY_CHAPTER.search(title)]
    return sorted({model for title in titles for model in models_in(title)})


def parse_pdf(path: Path) -> Document:
    doc = fitz.open(path)
    warnings: List[str] = []
    sections, families = find_sections(doc, warnings)
    if not families:
        warnings.append("no product family chapter")
    observations: List[dict] = []
    changes: List[list] = []
    for section in sections:
        if section.kind == "changed":
            changes.extend(parse_changes(doc, section))
        else:
            observations.extend(parse_issues(doc, section, warnings))
    if not observations:
        warnings.append("no issue at all")
    released, revised, page = revision_dates(doc)
    if not released:
        warnings.append("no revision history")
    return Document(
        released=released,
        revised=revised,
        families=families,
        models=chapter_models(doc),
        observations=observations,
        changes=changes,
        notices=extract_notices(doc),
        warnings=warnings,
        pages={"revisions": page},
    )
