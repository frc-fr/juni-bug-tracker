"""Checks on the real PDFs; skipped when .cache/pdfs is empty."""
import os
from pathlib import Path

import pytest

from junibugs.parser import parse_pdf

CACHE = Path(os.environ.get("JUNIBUGS_CACHE", ".cache/pdfs"))
PDFS = sorted(CACHE.glob("*.pdf"))
pytestmark = pytest.mark.corpus


@pytest.mark.skipif(not PDFS, reason="no cached PDF")
@pytest.mark.parametrize("pdf", PDFS, ids=lambda path: path.stem)
def test_every_pdf_parses_cleanly(pdf):
    document = parse_pdf(pdf)
    assert not document.warnings
    assert document.observations and document.families and document.released


@pytest.mark.skipif(not (CACHE / "junos-26.2R1.pdf").exists(), reason="26.2R1 not cached")
def test_known_facts_of_26_2r1():
    document = parse_pdf(CACHE / "junos-26.2R1.pdf")
    found = {(o["bug_id"], o["family"], o["status"]): o for o in document.observations}
    alg = found[("1930403", "MX Series", "resolved")]
    assert alg["category"] == "Application Layer Gateways (ALGs)"
    assert alg["description"].startswith("On MX platforms with SPC3 line-cards/ SRX platforms")
    assert ("1955888", "MX Series", "open") in found
    assert {o["release"] for o in document.observations if o.get("release")} == {"26.2R1-S1", "26.2R1"}
    assert document.released == "2026-06-29"


SRN = sorted(Path(os.environ.get("JUNIBUGS_SRN_CACHE", ".cache/srn")).glob("*.md"))


@pytest.mark.skipif(not SRN, reason="no rendered SRN")
@pytest.mark.parametrize("page", SRN, ids=lambda path: path.stem)
def test_every_srn_reads_without_security_nor_notes(page):
    from junibugs.srn import parse_article
    text = page.read_text(encoding="utf-8")
    if ("included in the attachment" in text and "List of" not in text) or "See [Attachment](" in text:
        pytest.skip("lists in an attachment")
    notice = parse_article(text)
    if f"{notice.system}-{notice.version}" != page.stem:
        pytest.skip(f"the article holds the SRN of {notice.version}")
    assert notice.items and not notice.warnings
    text = " ".join(f"{i['synopsis']} {i['description']}" for i in notice.items)
    assert "SIRT=" not in text and "CVE-" not in text and "Product-Group=" not in text


ATTACHMENTS = sorted(Path(os.environ.get("JUNIBUGS_SRN_ATTACHMENTS", ".cache/srn-attachments")).glob("*.pdf"))


@pytest.mark.skipif(not ATTACHMENTS, reason="no SRN PDF added by hand")
@pytest.mark.parametrize("pdf", ATTACHMENTS, ids=lambda path: path.stem)
def test_srn_pdf_never_reads_the_confidential_part(pdf):
    import re
    import fitz
    from junibugs.srn import parse_srn_pdf
    lines = [" ".join(line.split()) for page in fitz.open(pdf) for line in page.get_text().splitlines()]
    cut = next((i for i, line in enumerate(lines) if "List of" in line and line.lower().endswith("confidential")), len(lines))
    public = {line for line in lines[:cut] if re.fullmatch(r"\d{6,8}", line)}
    notice = parse_srn_pdf(pdf)
    assert notice.items and {item["bug_id"] for item in notice.items} <= public
    assert not any("CVE-" in item["synopsis"] for item in notice.items)
