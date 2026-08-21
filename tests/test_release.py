# Copyright (c) 2026 Gentex
# ABOUTME: Verifies release input, project metadata, and manifest version agreement.
# ABOUTME: Keeps release artifact naming tied to one checked version source.
"""Tests for the release-version validation helper."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from scripts.check_release import check_release_version

if TYPE_CHECKING:
    from pathlib import Path


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
