# Copyright (c) 2026 Gentex
# ABOUTME: Detects stable release version changes across two Git revisions.
# ABOUTME: Rejects inconsistent metadata before release automation can proceed.
# ruff: noqa: INP001 - repository scripts are importable test targets without a package
"""Detect releasable Gentex PLACE version changes between Git revisions."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

_ROOT = Path(__file__).parents[1]
_MANIFEST_PATH = "custom_components/gentex_place/manifest.json"
_STABLE_VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")


@dataclass(frozen=True)
class ReleaseDecision:
    """Describe whether matching metadata requires a release."""

    previous: str
    current: str
    required: bool


def parse_version(value: str) -> tuple[int, int, int]:
    """Parse one stable semantic version."""
    match = _STABLE_VERSION.fullmatch(value)
    if match is None:
        message = f"not a stable semantic version: {value!r}"
        raise ValueError(message)
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def decide_release(
    previous_project: str,
    previous_manifest: str,
    current_project: str,
    current_manifest: str,
) -> ReleaseDecision:
    """Validate metadata agreement and decide whether the version increased."""
    if previous_project != previous_manifest:
        message = "previous project and manifest versions differ"
        raise ValueError(message)
    if current_project != current_manifest:
        message = "current project and manifest versions differ"
        raise ValueError(message)
    previous = parse_version(previous_project)
    current = parse_version(current_project)
    if current < previous:
        message = "current version must increase or remain unchanged"
        raise ValueError(message)
    return ReleaseDecision(
        previous=previous_project,
        current=current_project,
        required=current > previous,
    )


def _show_file(commit: str, path: str, root: Path) -> bytes:
    """Read a repository file at one Git commit."""
    result = subprocess.run(  # noqa: S603 - fixed Git command, no shell
        [  # noqa: S607 - required Git lookup
            "git",
            "show",
            "--end-of-options",
            f"{commit}:{path}",
        ],
        cwd=root,
        shell=False,
        check=True,
        capture_output=True,
    )
    return result.stdout


def _read_metadata(commit: str, root: Path) -> tuple[str, str]:
    """Read matching project and manifest version sources from a Git commit."""
    try:
        project = tomllib.loads(
            _show_file(commit, "pyproject.toml", root).decode("utf-8")
        )
        manifest = json.loads(_show_file(commit, _MANIFEST_PATH, root).decode("utf-8"))
        project_version = project["project"]["version"]
        manifest_version = manifest["version"]
    except (
        json.JSONDecodeError,
        KeyError,
        OSError,
        subprocess.CalledProcessError,
        tomllib.TOMLDecodeError,
        TypeError,
        UnicodeDecodeError,
    ):
        pass
    else:
        if isinstance(project_version, str) and isinstance(manifest_version, str):
            return project_version, manifest_version
    message = f"cannot read release metadata for {commit}"
    raise ValueError(message)


def detect_release(before: str, after: str, root: Path) -> ReleaseDecision:
    """Detect a valid release transition between two Git commits."""
    previous_project, previous_manifest = _read_metadata(before, root)
    current_project, current_manifest = _read_metadata(after, root)
    return decide_release(
        previous_project,
        previous_manifest,
        current_project,
        current_manifest,
    )


def main() -> None:
    """Print the release decision and optionally write GitHub outputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", help="base Git commit")
    parser.add_argument("after", help="target Git commit")
    parser.add_argument(
        "--github-output",
        type=Path,
        help="path to the GitHub Actions output file",
    )
    parser.add_argument(
        "--require-release",
        action="store_true",
        help="reject a transition that does not increase the version",
    )
    args = parser.parse_args()
    try:
        decision = detect_release(args.before, args.after, _ROOT)
    except ValueError as error:
        parser.error(str(error))
    if args.require_release and not decision.required:
        parser.error("release version did not increase")
    print(json.dumps(asdict(decision)))  # noqa: T201 - required CLI output
    if args.github_output is not None:
        required = str(decision.required).lower()
        with args.github_output.open("a", encoding="utf-8") as output:
            output.write(f"release_required={required}\nversion={decision.current}\n")


if __name__ == "__main__":
    main()
