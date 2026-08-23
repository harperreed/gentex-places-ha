# Copyright (c) 2026 Gentex
# ABOUTME: Verifies stable release decisions across repository metadata revisions.
# ABOUTME: Keeps release automation tied to matching, increasing semantic versions.
"""Tests for release-change detection and artifact packaging."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import zipfile
from pathlib import Path

import pytest

from scripts.check_release import (
    ReleaseDecision,
    decide_release,
    detect_release,
    parse_version,
)

_ROOT = Path(__file__).parents[1]


def _write_metadata(root: Path, *, project_version: str, manifest_version: str) -> None:
    """Write minimal project and integration release metadata."""
    pyproject = root / "pyproject.toml"
    manifest = root / "custom_components/gentex_place/manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    pyproject.write_text(
        f'[project]\nname = "example"\nversion = "{project_version}"\n'
    )
    manifest.write_text(json.dumps({"version": manifest_version}))


def _git(repo: Path, *args: str) -> str:
    """Run Git in a disposable test repository and return standard output."""
    result = subprocess.run(  # noqa: S603 - fixed Git executable and test arguments
        ["git", *args],  # noqa: S607 - test exercises Git itself
        cwd=repo,
        shell=False,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.mark.parametrize("value", ["v1.0.0", "1.0", "1.0.0-rc1", "1.0.0+1", "01.0.0"])
def test_parse_version_rejects_non_stable_semver(value: str) -> None:
    with pytest.raises(ValueError, match="stable semantic version"):
        parse_version(value)


def test_decide_release_returns_noop_for_unchanged_matching_versions() -> None:
    assert decide_release("0.1.0", "0.1.0", "0.1.0", "0.1.0") == ReleaseDecision(
        previous="0.1.0", current="0.1.0", required=False
    )


def test_decide_release_requests_strict_increase() -> None:
    assert decide_release("0.1.0", "0.1.0", "1.0.0", "1.0.0") == ReleaseDecision(
        previous="0.1.0", current="1.0.0", required=True
    )


@pytest.mark.parametrize(
    ("versions", "message"),
    [
        (("0.1.0", "0.2.0", "1.0.0", "1.0.0"), "previous"),
        (("0.1.0", "0.1.0", "1.0.0", "1.0.1"), "current"),
        (("1.0.0", "1.0.0", "0.9.0", "0.9.0"), "increase"),
    ],
)
def test_decide_release_rejects_invalid_transition(
    versions: tuple[str, str, str, str], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        decide_release(*versions)


def test_detect_release_reads_metadata_from_real_git_commits(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "release-test@example.com")
    _git(repo, "config", "user.name", "Release Test")
    _write_metadata(repo, project_version="0.1.0", manifest_version="0.1.0")
    _git(repo, "add", "pyproject.toml", "custom_components/gentex_place/manifest.json")
    _git(repo, "commit", "-m", "initial metadata")
    first_sha = _git(repo, "rev-parse", "HEAD")

    _write_metadata(repo, project_version="1.0.0", manifest_version="1.0.0")
    _git(repo, "add", "pyproject.toml", "custom_components/gentex_place/manifest.json")
    _git(repo, "commit", "-m", "release metadata")
    second_sha = _git(repo, "rev-parse", "HEAD")

    assert detect_release(first_sha, second_sha, repo) == ReleaseDecision(
        previous="0.1.0", current="1.0.0", required=True
    )

    with pytest.raises(ValueError, match="cannot read release metadata"):
        detect_release("0" * 40, second_sha, repo)


def test_workflow_archive_contains_integration_and_full_license() -> None:
    workflow = (_ROOT / ".github/workflows/release.yml").read_text()
    archive_block = re.search(
        r"      - name: Build integration archive\n"
        r"        run: >-\n"
        r"(?P<command>(?:          .+\n)+)",
        workflow,
    )
    assert archive_block is not None
    command = " ".join(
        line.strip() for line in archive_block.group("command").splitlines()
    )
    archive_path = _ROOT / "gentex_place.zip"
    assert not archive_path.exists()
    try:
        subprocess.run(  # noqa: S603 - exact checked repository workflow command
            shlex.split(command),
            cwd=_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        with zipfile.ZipFile(archive_path) as archive:
            names = set(archive.namelist())
            assert names
            assert all(name.startswith("gentex_place/") for name in names)
            assert "gentex_place/manifest.json" in names
            assert "gentex_place/LICENSE" in names
            assert (
                archive.read("gentex_place/LICENSE") == (_ROOT / "LICENSE").read_bytes()
            )
    finally:
        archive_path.unlink(missing_ok=True)
