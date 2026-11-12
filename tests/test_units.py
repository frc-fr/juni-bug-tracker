import json

from junibugs.collect import candidates, next_branch, pdf_url
from junibugs.lifecycle import parse_lifecycle
from junibugs.normalize import canonical_family, families_in, models_in, normalize_category
from junibugs.parser import clean_description, first_sentence, parse_date, read_items, issue_starts, change_starts
from junibugs.versions import branch_of, version_key


def lines(*texts):
    return [(1, text) for text in texts]


def test_versions_sort_by_release_number():
    assert sorted(["25.4R1", "22.2R10", "22.2R3"], key=version_key) == ["22.2R3", "22.2R10", "25.4R1"]
    assert branch_of("25.4R1") == "25.4"


def test_pdf_address_follows_the_hpe_layout():
    assert pdf_url("evo", "25.4R1") == (
        "https://networkingdocs.hpe.com/documentation/us/en/software/junos/release-notes/"
        "25.4/junos-evo-release-notes-25.4r1/junos-evo-release-notes-25.4r1.pdf"
    )


def test_pdf_address_changed_with_26_2():
    assert pdf_url("junos", "26.2R1") == (
        "https://networkingdocs.hpe.com/documentation/rne/us/en/release-notes/"
        "Junos%20OS/26.2R1/junos-os-release-notes-26.2r1.pdf"
    )
    assert pdf_url("evo", "26.4R1").endswith("Junos%20OS%20Evolved/26.4R1/junos-os-evolved-release-notes-26.4r1.pdf")


def test_candidates_are_the_next_r_and_the_next_branches():
    manifest = {f"junos-{v}": {"system": "junos", "version": v} for v in ("24.4R1", "24.4R2", "25.2R1", "25.4R1")}
    assert next_branch("25.4") == "26.2" and next_branch("26.2") == "26.4"
    assert candidates(manifest, "junos") == ["24.4R3", "25.2R2", "25.4R2", "26.2R1", "26.4R1"]


def test_families_from_chapter_titles():
    assert canonical_family("MX Series") == "MX Series"
    assert canonical_family("ACX7100-32C, ACX7100-48L, and ACX7509 Devices") == "ACX Series"
    assert canonical_family("Third-Party Whitebox") == "Third-Party White Box"
    assert canonical_family("vSRX 3.0") == "vSRX"
    assert canonical_family("Something Else") is None


def test_models_are_cores_and_families_are_mentions():
    text = "On EX4400-48MP and EX4400-24T, MX204 and SRX Series devices; not in JNP10K-LC2101"
    assert models_in(text) == ["EX4400", "MX204"]
    assert families_in(text) == ["SRX Series"]


def test_categories_are_harmonized():
    assert normalize_category("Class of Service") == "Class of Service (CoS)"
    assert normalize_category("Resolved Issues: 22.1R1") == "Uncategorized"
    assert normalize_category(None) == "Uncategorized"
    assert normalize_category("EVPN") == "EVPN"


def test_description_loses_pr_and_cve_and_splits_workaround():
    text = "The rpd might crash (CVE-2022-22219). Workaround: restart it. PR1675054"
    assert clean_description(text) == ("The rpd might crash.", "restart it.")


def test_change_summary_is_its_title():
    assert first_sentence("ARP proxy default reply option—The option now replies. [See arp.]") == "ARP proxy default reply option"
    assert first_sentence("The output changed. It now shows more.") == "The output changed."


def test_dates_of_both_layouts():
    assert parse_date("27-Sep-26 - Revision 2, Junos OS Release 26.2R1.") == "2026-09-27"
    assert parse_date("09 January 2026—Revision 12", anchored=True) == "2026-01-09"
    assert parse_date("Revision 12 on 09 January 2026", anchored=True) is None


def test_items_follow_bullets_headings_and_loose_paragraphs():
    items = read_items(lines(
        "IN THIS SECTION", "EVPN | 12", "Routing Protocols | 13",
        "Learn about the issues fixed in this release.",
        "EVPN", "•", "First issue on two", "lines. PR1000001",
        "•", "Second issue with a list:", "•", "an option", "and its end. PR1000002",
        "Routing Protocols", "Constant BGP peer flaps. PR1000003",
    ), ["EVPN", "Routing Protocols"], issue_starts, loose=True)
    assert [(item.category, " ".join(item.lines)) for item in items] == [
        ("EVPN", "First issue on two lines. PR1000001"),
        ("EVPN", "Second issue with a list: an option and its end. PR1000002"),
        ("Routing Protocols", "Constant BGP peer flaps. PR1000003"),
    ]


def test_headings_are_guessed_without_contents_box():
    items = read_items(lines("Class of Service (CoS)", "•", "A fix. PR1000001", "EVPN", "•", "Another. PR1000002"),
                       [], issue_starts, loose=True)
    assert [item.category for item in items] == ["Class of Service (CoS)", "EVPN"]


def test_change_details_stay_in_their_change():
    items = read_items(lines("•", "New default—The device now", "•", "drops it", "•", "Other change—Text."),
                       [], change_starts)
    assert len(items) == 2


def test_lifecycle_table():
    rows = "".join(
        f"<tr><td>Junos OS {b}<sup><a href='#1'>1</a></sup></td><td>06/23/2023</td><td>06/23/2028</td>"
        f"<td>12/23/2028</td><td>EEOL</td></tr>" for b in ("23.2", "23.4", "24.2", "24.4", "25.2", "25.4", "26.2", "22.4", "22.2", "21.4")
    )
    branches = parse_lifecycle(f"<table><tr><th>Product</th></tr>{rows}<tr><td>Junos OS 4.4</td><td>04/30/2001</td><td></td><td></td><td></td></tr></table>")
    assert branches["23.2"] == {"released": "2023-06-23", "engineering": "2028-06-23", "support": "2028-12-23", "type": "EEOL"}
    assert "4.4" not in branches


from junibugs.srn import article_name, parse_article, references
from junibugs.versions import parse_reference, train_of


def test_service_releases_sort_after_their_r_release():
    assert sorted(["22.2R3-S10", "22.2R3", "22.2R3-S7", "22.2R2-S1"], key=version_key) == ["22.2R2-S1", "22.2R3", "22.2R3-S7", "22.2R3-S10"]
    assert train_of("22.2R3-S7") == "22.2R3" and branch_of("22.2R3-S7") == "22.2"


def test_srn_article_names():
    assert article_name("junos", "22.2R3-S7") == "22-2R3-S7-SRN"
    assert article_name("evo", "22.4R3-S1") == "22-4R3-S1-EVO-SRN"


def test_resolved_in_keeps_r_trains_only():
    assert parse_reference("evo:22.3R3-S1-EVO") == ("evo", "22.3R3-S1")
    assert parse_reference("junos:22.3X80-D35") is None
    assert parse_reference("junos:21.4R3-S2-J16") is None
    assert references("evo:22.3R2-S2-EVO junos:22.4R3 junos:23.1R2-S1") == [
        ("evo", "22.3R2-S2"), ("junos", "22.4R3"), ("junos", "23.1R2-S1")]


ARTICLE = r"""Created2025\-06\-24
## 22.2R3\-S7 \- List of Fixed issues 

| PR Number | Synopsis | Category: Border Gateway Protocol |
|---|---|---|
| [1793435](https://prsearch.juniper.net/PR1793435) Major | Route learning degrades Product\-Group=junos Severity=Major | BGP learning is slow.  *Resolved In:* junos:22.4R3\-S1 evo:23.2R1\-EVO junos:21.4R3\-S2\-J16 |
| [1700001](https://prsearch.juniper.net/PR1700001) Critical | A vulnerability Product\-Group=junos | See JSA70000 and CVE\-2024\-1. |
| [1700002](https://prsearch.juniper.net/PR1700002) Minor | Something Product\-Group=junos | @someone please add a release note |
## 22.2R3\-S7 \- List of Fixed issues Confidential
| [1700003](https://prsearch.juniper.net/PR1700003) Minor | Internal Product\-Group=junos | Never read |
## 22.2R3\-S7 \- List of Known issues 
| PR Number | Synopsis | Category: MPLS |
| [1700004](https://prsearch.juniper.net/PR1700004) Major | Open one Product\-Group=junos | Still open. |
## Modification History
| [1700005](https://prsearch.juniper.net/PR1700005) Major | After Product\-Group=junos | Not a list. |
"""


def test_srn_article():
    notice = parse_article(ARTICLE)
    assert (notice.system, notice.version, notice.created, notice.skipped, notice.internal) == ("junos", "22.2R3-S7", "2025-06-24", 1, 1)
    assert [(i["bug_id"], i["status"], i["category"]) for i in notice.items] == [
        ("1793435", "resolved", "Border Gateway Protocol"), ("1700002", "resolved", "Border Gateway Protocol"), ("1700004", "open", "MPLS")]
    first = notice.items[0]
    assert first["synopsis"] == "Route learning degrades" and first["severity"] == "Major"
    assert first["description"] == "BGP learning is slow."
    assert first["resolved_in"] == [("junos", "22.4R3-S1"), ("evo", "23.2R1")]
    assert notice.items[1]["description"] == ""


def test_an_article_is_rendered_again_only_when_it_changed(tmp_path):
    from junibugs.srn import needs_rendering
    (tmp_path / "junos-22.2R3-S7.json").write_text("{}")
    assert needs_rendering("junos-22.2R3-S8", {"lastmod": "2026-10-16"}, tmp_path)
    assert not needs_rendering("junos-22.2R3-S7", {"lastmod": "2026-10-16", "rendered": "2026-10-16"}, tmp_path)
    assert needs_rendering("junos-22.2R3-S7", {"lastmod": "2026-11-02", "rendered": "2026-10-16"}, tmp_path)
    # Unread pages wait for a change; a lost result of a read page is rendered again.
    assert not needs_rendering("junos-22.1R3-S4", {"lastmod": "2026-10-16", "rendered": "2026-10-16", "unread": "empty for visitors"}, tmp_path)
    assert needs_rendering("junos-24.2R2-S1", {"lastmod": "2026-10-16", "rendered": "2026-10-16"}, tmp_path)


from junibugs.hardware import chassis_of, hardware_index, parse_series, parse_suggested


def test_chassis_skus_name_their_model_and_parts_are_left_out():
    assert chassis_of("EX4300-48MP-TAA") == ("EX4300", "EX4300-48MP")
    assert chassis_of("MX2010-BASE-AC") == ("MX2010", "MX2010")
    assert chassis_of("SRX345-SYS-JB") == ("SRX345", "SRX345")
    assert chassis_of("EX4300-FAN") is None
    assert chassis_of("B-EX4300-48MP-EDU") is None
    assert chassis_of("JPSU-1400-AC-A") is None


def test_series_page_keeps_chassis_announcements_only():
    head = "<tr><th>Technical Support Bulletin (TSB)</th><th>SKU Description</th></tr>"
    recent = (
        "<tr><td>TSB109284 - End of Life Announcement: EX4300-48MP</td><td>EX4300-48MP, EX4300-48MP-TAA, JPSU-1400-AC-A</td>"
        "<td>06/29/2026</td><td>12/29/2026</td><td>12/29/2027</td><td>12/29/2029</td><td>25.4</td><td>12/29/2031</td></tr>"
        "<tr><td>TSB107601 - SKU Renaming Announcement: EX4300-48T</td><td>EX4300-48T</td>"
        "<td>05/15/2026</td><td>11/15/2026</td><td>N/A</td><td>N/A</td><td>N/A</td><td>06/30/2027</td></tr>"
        "<tr><td>TSB98158 - End of Life Announcement: Power Supply SKU</td><td>JPSU-1100-AC-AFO</td>"
        "<td>06/02/2025</td><td>06/02/2025</td><td>06/02/2026</td><td>06/02/2028</td><td>N/A</td><td>03/31/2029</td></tr>"
    )
    old = (
        "<tr><td>EX2200-24T-4G, EX2200-48T-4G</td><td>02/01/2019</td><td>06/30/2019</td><td>06/30/2020</td>"
        "<td>06/30/2024</td><td>06/30/2024</td><td>06/30/2024</td></tr>"
    )
    found = parse_series(f"<table>{head}{recent}</table><table><tr><th>Product</th></tr>{old}</table>", "u")
    assert found == [
        {"model": "EX4300", "variants": ["EX4300-48MP"], "bulletin": "TSB109284", "announced": "2026-06-29",
         "last_software": "25.4", "end_of_support": "2031-12-29", "page": "u"},
        {"model": "EX2200", "variants": ["EX2200-24T", "EX2200-48T"], "bulletin": None, "announced": "2019-02-01",
         "last_software": None, "end_of_support": "2024-06-30", "page": "u"},
    ]


def test_suggested_releases_of_kb21476():
    markdown = "\n".join([
        "| Platform | Junos Software by Platform | Last  Updated | Notes |",
        "| [EX4300 ](https://x) | Latest Junos 21.4R3\\-Sx | 2025\\-2\\-28 |  |",
        "| [ACX500 ](https://x) | Latest Junos 20.4 \\(LSV Outdoor\\)  Latest Junos 21.2 \\(LSV Indoor\\) | 2024\\-3\\-19 |  |",
        "| [PTX10003 ](https://x) | Latest Junos Evolved 24.4R2\\-Sx\\-EVO | 2024\\-11\\-26 | EVO Platform |",
        "| [MX Series ](https://x) | Latest Junos 23.4R2\\-Sx | 2025\\-6\\-17 |  |",
    ])
    platforms = parse_suggested(markdown)
    assert [(p["platform"], p["releases"], p["system"], p["last"], p["updated"]) for p in platforms] == [
        ("EX4300", ["21.4R3-Sx"], "junos", False, "2025-02-28"),
        ("ACX500", ["20.4", "21.2"], "junos", True, "2024-03-19"),
        ("PTX10003", ["24.4R2-Sx"], "evo", False, "2024-11-26"),
        ("MX Series", ["23.4R2-Sx"], "junos", False, "2025-06-17"),
    ]
    index = hardware_index("evo", ["PTX10001"], {"announcements": []}, {"source": "s", "platforms": platforms})
    assert sorted(index["models"]) == ["PTX10001", "PTX10003"]
    assert index["general"] == [] and index["as_of"] == "2024-11-26"
    junos = hardware_index("junos", [], {"announcements": [{"model": "EX2200", "variants": ["EX2200-24T"], "bulletin": None,
                                                            "last_software": None, "end_of_support": "2024-06-30", "page": "u"}]},
                           {"source": "s", "platforms": platforms})
    assert sorted(junos["models"]) == ["ACX500", "EX2200", "EX4300"]
    assert junos["general"] == [["MX Series", "Latest Junos 23.4R2-Sx", ["23.4R2-Sx"], "2025-06-17"]]
