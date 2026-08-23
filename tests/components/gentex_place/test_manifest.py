# Copyright (c) 2026 Gentex
# ABOUTME: Verifies Home Assistant metadata and the immutable public SDK source.
# ABOUTME: Keeps manifest, project, and lock dependency contracts in agreement.
"""Repository metadata contract tests for the Gentex PLACE integration."""

from __future__ import annotations

import json
import stat
import tomllib
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).parents[3]
_SDK_SHA = "d92f07ecc9b7e66162d60d4a66cc07366543b631"
_SDK_GIT_URL = "https://github.com/harperreed/place-integration-api.git"
_SDK_REQUIREMENT = f"place-integration-api@git+{_SDK_GIT_URL}@{_SDK_SHA}"
_WORKFLOW_JOB_COUNT = 3
_RELEASE_CHECKOUT_COUNT = 2
_DEPENDABOT_UPDATE_COUNT = 2
_CHECKOUT_ACTION = "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"
_EXPECTED_RELEASE_WORKFLOW = (
    """name: Release

on:
  push:
    branches:
      - main

permissions:
  contents: read

jobs:
  detect:
    runs-on: ubuntu-latest
    outputs:
      release_required: ${{ steps.version.outputs.release_required }}
      version: ${{ steps.version.outputs.version }}
    steps:
      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0
        with:
          fetch-depth: 0
          persist-credentials: false
      - uses: astral-sh/setup-uv@ae62891fec2bb8e7d6c99fc78c9fec3a63790f8d
      - run: uv python install 3.14.2
      - name: Detect version change
        id: version
        env:
          BEFORE_SHA: ${{ github.event.before }}
          AFTER_SHA: ${{ github.sha }}
        run: uv run python scripts/check_release.py "$BEFORE_SHA" "$AFTER_SHA" """
    '--github-output "$GITHUB_OUTPUT"'
    """
      - name: Refuse an existing tag or published release
        if: steps.version.outputs.release_required == 'true'
        env:
          GH_TOKEN: ${{ github.token }}
          RELEASE_VERSION: ${{ steps.version.outputs.version }}
        run: scripts/check_release_absent "$RELEASE_VERSION"

  publish:
    needs: detect
    if: needs.detect.outputs.release_required == 'true'
    permissions:
      contents: write
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0
        with:
          fetch-depth: 0
          persist-credentials: false
      - uses: astral-sh/setup-uv@ae62891fec2bb8e7d6c99fc78c9fec3a63790f8d
      - run: uv python install 3.14.2
      - run: scripts/check
      - name: Recheck release decision
        env:
          BEFORE_SHA: ${{ github.event.before }}
          AFTER_SHA: ${{ github.sha }}
        run: uv run python scripts/check_release.py "$BEFORE_SHA" "$AFTER_SHA" """
    "--require-release"
    """
      - name: Refuse a raced tag or any release
        env:
          GH_TOKEN: ${{ github.token }}
          RELEASE_VERSION: ${{ needs.detect.outputs.version }}
        run: scripts/check_release_absent "$RELEASE_VERSION" --include-drafts
      - name: Build release assets
        run: uv run python scripts/build_release.py --output dist/gentex_place.zip
      - name: Create draft release
        env:
          GH_TOKEN: ${{ github.token }}
          RELEASE_VERSION: ${{ needs.detect.outputs.version }}
        run: gh release create "v$RELEASE_VERSION" dist/gentex_place.zip """
    'dist/gentex_place.zip.sha256 --draft --target "$GITHUB_SHA" '
    '--title "v$RELEASE_VERSION" --notes-file '
    '"docs/releases/v$RELEASE_VERSION.md"'
    """
      - name: Verify uploaded draft
        env:
          GH_TOKEN: ${{ github.token }}
          RELEASE_VERSION: ${{ needs.detect.outputs.version }}
        run: scripts/verify_draft_release "$RELEASE_VERSION" "$GITHUB_SHA"
      - name: Publish verified release
        env:
          GH_TOKEN: ${{ github.token }}
          RELEASE_VERSION: ${{ needs.detect.outputs.version }}
        run: gh release edit "v$RELEASE_VERSION" --draft=false --latest
"""
)


def _load_toml(path: Path) -> dict[str, Any]:
    """Load a repository TOML document."""
    with path.open("rb") as stream:
        return tomllib.load(stream)


def test_manifest_and_project_share_the_git_sdk_requirement() -> None:
    manifest = json.loads(
        (_ROOT / "custom_components/gentex_place/manifest.json").read_text()
    )
    hacs = json.loads((_ROOT / "hacs.json").read_text())
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
    assert manifest["config_flow"] is True
    assert manifest["iot_class"] == "cloud_push"
    assert manifest["loggers"] == ["place"]
    assert hacs["homeassistant"] == "2026.8.1"
    assert hacs["zip_release"] is True
    assert hacs["filename"] == "gentex_place.zip"
    assert (
        len([path for path in (_ROOT / "custom_components").iterdir() if path.is_dir()])
        == 1
    )
    assert sdk_dependencies == [_SDK_REQUIREMENT]
    assert "sources" not in project.get("tool", {}).get("uv", {})
    for install_gate in (
        _ROOT / "scripts/check_sdk_dependency",
        _ROOT / "tests/system/run.sh",
    ):
        assert install_gate.read_text().count(_SDK_REQUIREMENT) == 1


def test_lock_uses_the_approved_public_sdk_commit() -> None:
    lock = _load_toml(_ROOT / "uv.lock")
    sdk_package = next(
        package
        for package in lock["package"]
        if package["name"] == "place-integration-api"
    )

    assert sdk_package["version"] == "0.3.0"
    assert sdk_package["source"] == {"git": f"{_SDK_GIT_URL}?rev={_SDK_SHA}#{_SDK_SHA}"}
    assert all(
        package.get("source", {}).get("directory") != "../place-integration-api"
        for package in lock["package"]
    )


def test_canonical_check_runs_every_local_gate() -> None:
    check_path = _ROOT / "scripts/check"
    check = check_path.read_text()

    assert check.splitlines()[:4] == [
        "#!/bin/sh",
        "# ABOUTME: Runs every local Gentex PLACE integration quality gate.",
        (
            "# ABOUTME: CI calls this before Home Assistant and HACS repository "
            "validators."
        ),
        "set -eu",
    ]
    assert check_path.stat().st_mode & stat.S_IXUSR
    assert "uv sync --locked" in check
    assert "uv run ruff format --check custom_components tests scripts" in check
    assert "uv run ruff check custom_components tests scripts" in check
    assert "uv run basedpyright" in check
    assert (
        "uv run pytest -W error --cov=custom_components.gentex_place "
        "--cov-report=term-missing --cov-fail-under=100"
    ) in check
    assert "uv run python scripts/check_dependency_audit.py" in check
    assert "git diff --check" in check


def test_validation_workflow_uses_pinned_official_actions() -> None:
    workflow = (_ROOT / ".github/workflows/validate.yml").read_text()

    assert "permissions:\n  contents: read" in workflow
    assert workflow.count("runs-on: ubuntu-latest") == _WORKFLOW_JOB_COUNT
    assert workflow.count(_CHECKOUT_ACTION) == _WORKFLOW_JOB_COUNT
    assert "astral-sh/setup-uv@ae62891fec2bb8e7d6c99fc78c9fec3a63790f8d" in workflow
    assert "run: uv python install 3.14.2" in workflow
    assert "run: scripts/check" in workflow
    assert (
        "home-assistant/actions/hassfest@f4ca6f671bd429efb108c0f2fa0ae8af0215986c"
    ) in workflow
    assert "hacs/action@d556e736723344f83838d08488c983a15381059a" in workflow
    assert "category: integration" in workflow


def _assert_release_workflow_contract(workflow: str) -> None:
    """Require the complete release workflow instead of a permissive denylist."""
    assert workflow == _EXPECTED_RELEASE_WORKFLOW


def test_release_workflow_publishes_only_a_verified_version_change() -> None:
    workflow = (_ROOT / ".github/workflows/release.yml").read_text()

    _assert_release_workflow_contract(workflow)
    assert "push:\n    branches:\n      - main" in workflow
    assert "workflow_dispatch" not in workflow
    assert "permissions:\n  contents: read" in workflow
    assert workflow.count("contents: write") == 1
    assert "if: needs.detect.outputs.release_required == 'true'" in workflow
    assert workflow.count("persist-credentials: false") == _RELEASE_CHECKOUT_COUNT
    assert "scripts/check" in workflow
    assert "scripts/build_release.py" in workflow
    assert "--draft" in workflow
    assert "scripts/verify_draft_release" in workflow
    detect, publish = workflow.split("  publish:\n", maxsplit=1)
    assert "--include-drafts" not in detect
    assert publish.count("--include-drafts") == 1
    assert "--draft=false" in workflow
    assert "gh release delete" not in workflow
    assert "gh release upload --clobber" not in workflow


@pytest.mark.parametrize(
    ("anchor", "unsafe_replacement"),
    [
        (
            "permissions:\n  contents: read",
            "permissions:\n  contents: read\n  issues: write",
        ),
        (
            f"      - uses: {_CHECKOUT_ACTION}",
            "      - uses: actions/checkout@main",
        ),
        (
            "    if: needs.detect.outputs.release_required == 'true'\n",
            "",
        ),
        (
            "    permissions:\n      contents: write\n",
            (
                "    permissions:\n      contents: write\n"
                "    env:\n      GH_TOKEN: ${{ github.token }}\n"
            ),
        ),
        (
            "      - name: Publish verified release\n",
            (
                "      - run: gh release delete v1.0.0\n"
                "      - name: Publish verified release\n"
            ),
        ),
        (
            "      - name: Verify uploaded draft\n",
            (
                "      - run: gh release upload --clobber v1.0.0 asset.zip\n"
                "      - name: Verify uploaded draft\n"
            ),
        ),
    ],
)
def test_release_workflow_contract_rejects_extra_capabilities(
    anchor: str,
    unsafe_replacement: str,
) -> None:
    workflow = (_ROOT / ".github/workflows/release.yml").read_text()
    unsafe_workflow = workflow.replace(anchor, unsafe_replacement, 1)
    assert unsafe_workflow != workflow

    with pytest.raises(AssertionError):
        _assert_release_workflow_contract(unsafe_workflow)


def test_release_scripts_fail_closed_and_verify_uploaded_assets() -> None:
    absent_path = _ROOT / "scripts/check_release_absent"
    verify_path = _ROOT / "scripts/verify_draft_release"
    absent = absent_path.read_text()
    verify = verify_path.read_text()

    for path, script in ((absent_path, absent), (verify_path, verify)):
        header = script.splitlines()[:4]
        assert header[0] == "#!/bin/sh"
        assert header[1].startswith("# ABOUTME:")
        assert header[2].startswith("# ABOUTME:")
        assert header[3] == "set -eu"
        assert path.stat().st_mode & stat.S_IXUSR
        assert "set -x" not in script
        assert "${{" not in script
        assert "gh release delete" not in script
        assert "gh release upload --clobber" not in script
        assert 'case "$version" in' in script
        assert "*[!0-9.]*" in script

    assert 'git ls-remote --exit-code --tags origin "refs/tags/v$version"' in absent
    assert "/repos/$GITHUB_REPOSITORY/releases/tags/v$version" in absent
    assert "--paginate" in absent
    assert "--slurp" in absent
    assert '"repos/$GITHUB_REPOSITORY/releases?per_page=100"' in absent
    assert '"404"' in absent
    assert '"200"' in absent

    assert 'mktemp -d "${TMPDIR:-/tmp}/gentex-place-release.XXXXXX"' in verify
    assert 'gh release download "v$version"' in verify
    assert 'cmp -- dist/gentex_place.zip "$download_dir/gentex_place.zip"' in verify
    assert "sha256sum --check gentex_place.zip.sha256" in verify
    assert (
        'scripts/build_release.py --verify "$download_dir/gentex_place.zip"' in verify
    )
    assert "--json isDraft,assets" in verify
    assert '"repos/$GITHUB_REPOSITORY/git/ref/tags/v$version"' in verify


def test_dependabot_tracks_locked_python_and_action_dependencies() -> None:
    dependabot = (_ROOT / ".github/dependabot.yml").read_text()

    assert dependabot.startswith("version: 2\n")
    assert dependabot.count('directory: "/"') == _DEPENDABOT_UPDATE_COUNT
    assert dependabot.count('interval: "weekly"') == _DEPENDABOT_UPDATE_COUNT
    assert 'package-ecosystem: "uv"' in dependabot
    assert 'package-ecosystem: "github-actions"' in dependabot


def test_local_environment_credentials_are_ignored() -> None:
    """Keep local live-check credentials out of Git."""
    ignored_paths = set((_ROOT / ".gitignore").read_text().splitlines())

    assert ".env" in ignored_paths


def test_readme_explains_how_to_discover_new_devices() -> None:
    readme = (_ROOT / "README.md").read_text()

    assert "reload the Gentex PLACE config entry" in readme
    assert "restart Home Assistant" in readme


def test_plan_records_current_task_1_and_task_11_state() -> None:
    plan = (
        _ROOT / "docs/superpowers/plans/2026-08-12-gentex-place-home-assistant.md"
    ).read_text()
    task_1 = plan.split("### Task 1:", 1)[1].split("### Task 2:", 1)[0]
    task_11 = plan.split("### Task 11:", 1)[1]

    assert "local SDK" not in task_1
    assert _SDK_REQUIREMENT in task_1
    assert "released SDK wheel" not in task_11
    assert _SDK_REQUIREMENT in task_11
    for step in range(1, 8):
        assert f"- [x] **Step {step}:" in task_11
    assert "- [ ] **Step 8: Stop at external gates**" in task_11
    assert "remaining test debt" in task_11
