"""Command line entry point."""
import argparse
import logging
import sys
from pathlib import Path

from . import build, collect, extract, hardware, lifecycle, report, srn


def main() -> None:
    parser = argparse.ArgumentParser(prog="junibugs")
    parser.add_argument("--manifest", type=Path, default=Path("sources/manifest.json"))
    parser.add_argument("--lifecycle", type=Path, default=Path("sources/lifecycle.json"))
    parser.add_argument("--schedule", type=Path, default=Path("sources/schedule.yml"))
    parser.add_argument("--srn", type=Path, default=Path("sources/srn.json"))
    parser.add_argument("--hardware", type=Path, default=Path("sources/hardware.json"))
    parser.add_argument("--recommended", type=Path, default=Path("sources/recommended.json"))
    parser.add_argument("--cache", type=Path, default=Path(".cache/pdfs"))
    parser.add_argument("--srn-cache", type=Path, default=Path(".cache/srn"))
    parser.add_argument("--srn-attachments", type=Path, default=Path(".cache/srn-attachments"))
    parser.add_argument("--output", type=Path, default=Path("data/extracted"))
    parser.add_argument("--changes", type=Path, default=Path("data/changes.json"))
    parser.add_argument("--report", type=Path, default=Path("data/report.json"))
    parser.add_argument("--site", type=Path, default=Path("site"))
    parser.add_argument("--base-url", default="https://frc-fr.github.io/juni-bug-tracker/")
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("collect", help="update the manifest and download new or revised PDFs")
    commands.add_parser("extract", help="parse the cached PDFs and SRN; fails only when too few are read")
    commands.add_parser("build", help="generate the static site from the extracted data")
    commands.add_parser("check", help="fail when the processing report lists something to fix")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.command == "collect":
        client = collect.Client()
        with report.source(args.report, "notes"):
            manifest = collect.update_manifest(args.manifest, client)
            downloaded = collect.download_pdfs(manifest, args.cache, client)
            collect.save_manifest(args.manifest, manifest)
        with report.source(args.report, "lifecycle"):
            lifecycle.update_lifecycle(args.lifecycle, client)
        with report.source(args.report, "hardware"):
            hardware.update_eol(args.hardware, client)
        with report.source(args.report, "recommended"):
            hardware.update_suggested(args.recommended)
        with report.source(args.report, "srn"):
            releases = srn.update_releases(args.srn, manifest, client)
            srn.fetch_articles(releases, args.srn_cache, args.output / "srn")
            srn.save_releases(args.srn, releases, srn.load_missing(args.srn))
        logging.info("%d releases, %d PDFs downloaded", len(manifest), len(downloaded))
    elif args.command == "extract":
        stops = extract.extract_all(args.manifest, args.cache, args.output, args.changes, args.report,
                                    args.srn, args.srn_cache, args.srn_attachments)
        for reason in stops:
            logging.error("%s", reason)
        sys.exit(1 if stops else 0)
    elif args.command == "check":
        left = report.check(report.load(args.report))
        for line in left:
            print(line)
        sys.exit(1 if left else 0)
    elif args.command == "build":
        summary = build.build_site(
            args.output, args.manifest, args.changes, args.lifecycle, args.schedule, args.site, args.dist, args.base_url,
            args.srn, args.hardware, args.recommended, args.report,
        )
        logging.info("%s", summary)
