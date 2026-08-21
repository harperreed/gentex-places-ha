# Copyright (c) 2026 Gentex
# ABOUTME: Validates one release version across workflow and repository metadata.
# ABOUTME: Fails artifact builds before packaging when version sources disagree.
# ruff: noqa: INP001 - repository scripts are importable test targets without a package
"""Check release version agreement for the Gentex PLACE artifact workflow."""

from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).parents[1]


def _load_toml(path: Path) -> dict[str, Any]:
    """Load one TOML document."""
    with path.open("rb") as stream:
        return tomllib.load(stream)


def check_release_version(requested: str, pyproject: Path, manifest: Path) -> str:
    """Return the shared version or name every source when they disagree."""
    project_version = _load_toml(pyproject)["project"]["version"]
    manifest_version = json.loads(manifest.read_text())["version"]
    versions = {
        "requested": requested,
        "project": project_version,
        "manifest": manifest_version,
    }
    if len(set(versions.values())) != 1:
        details = ", ".join(f"{source}={value!r}" for source, value in versions.items())
        message = f"release version mismatch: {details}"
        raise ValueError(message)
    return requested


def main() -> None:
    """Validate command-line release metadata."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("requested", help="workflow release version")
    parser.add_argument(
        "--pyproject",
        type=Path,
        default=_ROOT / "pyproject.toml",
        help="project metadata path",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=_ROOT / "custom_components/gentex_place/manifest.json",
        help="integration manifest path",
    )
    args = parser.parse_args()
    try:
        check_release_version(
            args.requested,
            args.pyproject,
            args.manifest,
        )
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
