# Copyright (c) 2026 Gentex
# ABOUTME: Verifies release input, project metadata, and manifest version agreement.
# ABOUTME: Keeps release artifact naming tied to one checked version source.
"""Tests for the release-version validation helper."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import zipfile
from pathlib import Path

import pytest

from scripts.check_release import check_release_version

_ROOT = Path(__file__).parents[1]


def _write_metadata(
    root: Path, *, project_version: str, manifest_version: str
) -> tuple[Path, Path]:
    """Write minimal project and integration release metadata."""
    pyproject = root / "pyproject.toml"
    manifest = root / "manifest.json"
    pyproject.write_text(
        f'[project]\nname = "example"\nversion = "{project_version}"\n'
    )
    manifest.write_text(json.dumps({"version": manifest_version}))
    return pyproject, manifest


def test_check_release_version_returns_shared_version(tmp_path: Path) -> None:
    pyproject, manifest = _write_metadata(
        tmp_path, project_version="0.1.0", manifest_version="0.1.0"
    )

    assert check_release_version("0.1.0", pyproject, manifest) == "0.1.0"


def test_check_release_version_names_project_manifest_mismatch(
    tmp_path: Path,
) -> None:
    pyproject, manifest = _write_metadata(
        tmp_path, project_version="0.1.0", manifest_version="0.2.0"
    )

    with pytest.raises(ValueError, match=r"project.*manifest"):
        check_release_version("0.1.0", pyproject, manifest)


def test_check_release_version_names_requested_project_mismatch(
    tmp_path: Path,
) -> None:
    pyproject, manifest = _write_metadata(
        tmp_path, project_version="0.1.0", manifest_version="0.1.0"
    )

    with pytest.raises(ValueError, match=r"requested.*project"):
        check_release_version("0.2.0", pyproject, manifest)


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
