"""The processing report and its page, the same on the five bug trackers."""
import json
import logging
import re
from pathlib import Path

import pytest

from junibugs import report

SITE = Path(__file__).resolve().parent.parent / "site"


def texts(language: str) -> dict:
    text = (SITE / "i18n.js").read_text(encoding="utf-8")
    start = text.index(f"  {language}: {{")
    return dict(re.findall(r'^\s+"([\w.]+)": "(.*)",?$', text[start:text.index("\n  },", start)], re.M))


def test_every_id_lands_in_one_bucket():
    findings = [report.finding("left_out", "security", "p", "s", ["A", "B"], ""),
                report.finding("not_understood", "status_unknown", "p", "s", ["C"], "")]
    buckets = report.accounting({"A", "B", "C", "D", "E"}, {"B", "D"}, findings)
    assert buckets["read"] == {"B", "D"}
    assert buckets["ruled"] == {"A"}
    assert buckets["failed"] == {"C"}
    assert buckets["unaccounted"] == {"E"}


def test_status_and_since():
    findings = [report.finding("left_out", "security", "p", "", ["A"], ""), report.finding("suspect", "drop", "p", "", [], "")]
    ids = {"vendor": {"A"}, "read": set(), "ruled": {"A"}, "failed": set(), "unaccounted": set()}
    entry = report.document("k", "G", "T", "u", findings, ids, {"status": "suspect", "since": "2026-01-02"})
    assert entry["status"] == "suspect" and entry["since"] == "2026-01-02"
    assert report.document("k", "G", "T", "u", findings[:1], ids, {"status": "suspect", "since": "2026-01-02"})["since"] != "2026-01-02"


def test_publication_threshold():
    docs = [{"status": "not_understood", "kept": None}] * 2 + [{"status": "suspect", "kept": "2026-01-01"}]
    assert report.publication(docs, 12)["published"]
    assert not report.publication(docs + [{"status": "not_understood", "kept": None}], 12)["published"]
    assert report.publication([{"status": "unreachable", "kept": None}] * 10, 12)["published"]


def test_unused_sections_hide_releases():
    assert report.shape("New Features in Cisco IOS XE 17.12.1a and 17.12.2") == "New Features in Cisco IOS XE X and X"
    sections = report.unused_sections({"a": {"New Features in 17.1": False, "Open Bugs": True}, "b": {"New Features in 17.2": False}},
                                      {"a": "ua", "b": "ub"})
    assert sections == [{"heading": "New Features in X", "documents": 2, "example": "ua"}]


def test_a_source_records_its_errors(tmp_path):
    path = tmp_path / "report.json"
    with report.source(path, "notes", "https://example.com"):
        logging.getLogger("x").error("https://example.com/a returned 404")
    with report.source(path, "lifecycle"):
        pass
    sources = {s["name"]: s for s in report.load(path)["sources"]}
    assert sources["notes"]["status"] == "error" and sources["notes"]["errors"] == ["https://example.com/a returned 404"]
    assert sources["lifecycle"]["status"] == "ok" and sources["lifecycle"]["last_success"]
    assert report.check(report.load(path)) == ["source in error: notes: https://example.com/a returned 404"]


def test_status_page_texts_exist():
    french, english = texts("fr"), texts("en")
    code = (SITE / "status.js").read_text(encoding="utf-8")
    used = set(re.findall(r'\bt\("([\w.]+)"', code))
    used |= set(re.findall(r'data-(?:text|html|label)="([\w.]+)"', (SITE / "etat.html").read_text(encoding="utf-8")))
    used |= {f"status.{s}" for s in report.STATUSES} | {f"status.{s}.help" for s in report.TO_FIX + ["left_out"]}
    used |= {f"status.ids.{b}" for b in ("vendor", "read", "ruled", "failed", "unaccounted")}
    assert used - french.keys() == set()
    assert french.keys() == english.keys()
    assert "etat.html" in french["footer.credit"] and "etat.html" in english["footer.credit"]


@pytest.mark.parametrize("rule", ["parse_error", "status_unknown", "release_unknown", "lost_bugs", "drop", "unaccounted", "http",
                                  "security", "out_of_scope"])
def test_common_rules_have_a_label(rule):
    assert f"rule.{rule}" in texts("fr") and f"rule.{rule}.help" in texts("fr")


def test_report_rules_have_a_label():
    path = Path("data/report.json")
    if not path.exists():
        pytest.skip("no report yet")
    rules = {f["rule"] for d in json.loads(path.read_text(encoding="utf-8")).get("documents", []) for f in d["findings"]}
    assert {r for r in rules if f"rule.{r}" not in texts("fr")} == set()
