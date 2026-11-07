"""Helpers for Junos version strings.

A release is "<major>.<minor>R<n>", as 25.4R1, and its service releases add
"-S<n>", as 25.4R1-S3. A service release only follows its own R release: a
fix in 22.2R3-S7 is in 22.2R3-S8, not in 22.2R2-S9.
"""
import re
from typing import Optional, Tuple

VERSION = re.compile(r"^(\d+)\.(\d+)R(\d+)(?:-S(\d+))?$")
SYSTEMS = {"junos": "Junos OS", "evo": "Junos OS Evolved"}


def version_key(version: str) -> Tuple[int, ...]:
    match = VERSION.match(version)
    if not match:
        raise ValueError(f"not a Junos release: {version!r}")
    major, minor, release, service = match.groups()
    return int(major), int(minor), int(release), int(service or 0)


def is_version(version: str) -> bool:
    return bool(VERSION.match(version))


def branch_of(version: str) -> str:
    return version.split("R")[0]


def train_of(version: str) -> str:
    """The R release a service release belongs to: 22.2R3 for 22.2R3-S7."""
    return version.split("-")[0]


def branch_key(branch: str) -> Tuple[int, int]:
    major, minor = branch.split(".")
    return int(major), int(minor)


def entry_key(system: str, version: str) -> str:
    """Junos OS and Junos OS Evolved share their numbers: the system is part of the key."""
    return f"{system}-{version}"


def split_key(key: str) -> Tuple[str, str]:
    system, version = key.split("-", 1)
    return system, version


def parse_reference(token: str) -> Optional[Tuple[str, str]]:
    """"junos:22.2R3-S7" or "evo:22.3R3-S1-EVO" as (system, version); None for other trains."""
    match = re.fullmatch(r"(junos|evo):(\d+\.\d+R\d+(?:-S\d+)?)(?:-EVO)?", token)
    return (match.group(1), match.group(2)) if match else None
