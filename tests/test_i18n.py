"""Every text key used by the page exists in both languages."""
import re
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"


def keys(language: str) -> set:
    text = (SITE / "i18n.js").read_text(encoding="utf-8")
    start = text.index(f"  {language}: {{")
    end = text.index("\n  },", start)
    return set(re.findall(r'^\s+"([\w.]+)":', text[start:end], re.M))


def test_both_languages_have_the_same_keys():
    assert keys("fr") == keys("en")


def test_used_keys_exist():
    used = set(re.findall(r'\bt\("([\w.]+)"', (SITE / "app.js").read_text(encoding="utf-8")))
    used |= set(re.findall(r'data-(?:text|html|label|placeholder)="([\w.]+)"', (SITE / "index.html").read_text(encoding="utf-8")))
    dynamic = {"help.bugs", "help.upgrade", "help.news", "help.hardware", "detail.fixedSince", "detail.fixedIn",
               "detail.knownIn", "detail.openSince", "publication.pending", "publication.none", "notice.pending", "notice.none", "notice.unread.empty", "notice.unread.attachment", "notice.unread.other", "notice.unread.pending", "detail.dropped", "detail.noMention", "hardware.model", "hardware.family",
               "hardware.count", "hardware.first", "hardware.last", "support.noteEvo"}
    assert used - keys("fr") == set()
    assert dynamic - keys("fr") == set()


def test_csp_forbids_inline_and_third_parties():
    for page in SITE.glob("*.html"):
        html = page.read_text(encoding="utf-8")
        assert "default-src 'none'; script-src 'self';" in html, page.name
        assert not re.search(r"<script>(?!</script>)|<style>|\son\w+=", html), page.name
