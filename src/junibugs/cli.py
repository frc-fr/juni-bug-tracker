"""Command line entry point."""
import argparse
import logging
import sys
from pathlib import Path

from . import build, collect, extract, hardware, lifecycle, srn


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
    parser.add_argument("--site", type=Path, default=Path("site"))
    parser.add_argument("--base-url", default="https://frc-fr.github.io/juni-bug-tracker/")
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("collect", help="update the manifest and download new or revised PDFs")
    commands.add_parser("extract", help="parse the cached PDFs; fails on any warning")
    commands.add_parser("build", help="generate the static site from the extracted data")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.command == "collect":
        client = collect.Client()
        manifest = collect.update_manifest(args.manifest, client)
        downloaded = collect.download_pdfs(manifest, args.cache, client)
        collect.save_manifest(args.manifest, manifest)
        lifecycle.update_lifecycle(args.lifecycle, client)
        hardware.update_eol(args.hardware, client)
        hardware.update_suggested(args.recommended)
        releases = srn.update_releases(args.srn, manifest, client)
        srn.fetch_articles(releases, args.srn_cache, args.output / "srn")
        srn.save_releases(args.srn, releases, srn.load_missing(args.srn))
        logging.info("%d releases, %d PDFs downloaded", len(manifest), len(downloaded))
    elif args.command == "extract":
        problems = extract.extract_all(args.cache, args.output, args.changes)
        problems.update(extract.extract_srn(args.srn_cache, args.output / "srn", args.srn_attachments))
        for key, warnings in problems.items():
            for warning in warnings:
                logging.error("%s: %s", key, warning)
        sys.exit(1 if problems else 0)
    elif args.command == "build":
        summary = build.build_site(
            args.output, args.manifest, args.changes, args.lifecycle, args.schedule, args.site, args.dist, args.base_url,
            args.srn, args.hardware, args.recommended,
        )
        logging.info("%s", summary)
