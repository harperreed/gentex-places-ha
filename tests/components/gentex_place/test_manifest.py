# Copyright (c) 2026 Gentex
# ABOUTME: Verifies Home Assistant metadata and the immutable public SDK source.
# ABOUTME: Keeps manifest, project, and lock dependency contracts in agreement.
"""Repository metadata contract tests for the Gentex PLACE integration."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).parents[3]
_SDK_SHA = "7f9f6bb6e4f5aeaae99cae30aa40a1bb3b5005ad"
_SDK_GIT_URL = "https://github.com/harperreed/place-integration-api.git"
_SDK_REQUIREMENT = f"place-integration-api@git+{_SDK_GIT_URL}@{_SDK_SHA}"


def _load_toml(path: Path) -> dict[str, Any]:
    """Load a repository TOML document."""
    with path.open("rb") as stream:
        return tomllib.load(stream)


def test_manifest_and_project_share_the_git_sdk_requirement() -> None:
    manifest = json.loads(
        (_ROOT / "custom_components/gentex_place/manifest.json").read_text()
    )
    project = _load_toml(_ROOT / "pyproject.toml")
    sdk_dependencies = [
        dependency
        for dependency in project["dependency-groups"]["dev"]
        if dependency.partition("@")[0].strip() == "place-integration-api"
        or dependency.partition("==")[0].strip() == "place-integration-api"
    ]

    assert manifest["domain"] == "gentex_place"
    assert manifest["version"] == project["project"]["version"]
    assert manifest["requirements"] == [_SDK_REQUIREMENT]
    assert sdk_dependencies == [_SDK_REQUIREMENT]
    assert "sources" not in project.get("tool", {}).get("uv", {})


def test_lock_uses_the_approved_public_sdk_commit() -> None:
    lock = _load_toml(_ROOT / "uv.lock")
    sdk_package = next(
        package
        for package in lock["package"]
        if package["name"] == "place-integration-api"
    )

    assert sdk_package["version"] == "0.3.0"
    assert sdk_package["source"] == {"git": f"{_SDK_GIT_URL}#{_SDK_SHA}"}
    assert all(
        package.get("source", {}).get("directory") != "../place-integration-api"
        for package in lock["package"]
    )
