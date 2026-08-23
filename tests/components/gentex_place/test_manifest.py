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
_DEPENDABOT_UPDATE_COUNT = 2
_CHECKOUT_ACTION = "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"
_SETUP_UV_SHA = "ae62891fec2bb8e7d6c99fc78c9fec3a63790f8d"
_UPLOAD_ARTIFACT_ACTION = (
    "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
)
_EXPECTED_RELEASE_WORKFLOW = (
    "name: Build release candidate\n"
    "\n"
    "on:\n"
    "  workflow_dispatch:\n"
    "    inputs:\n"
    "      version:\n"
    "        description: Version matching pyproject.toml and the integration "
    "manifest\n"
    "        required: true\n"
    "        type: string\n"
    "\n"
    "permissions:\n"
    "  contents: read\n"
    "\n"
    "jobs:\n"
    "  artifact:\n"
    "    runs-on: ubuntu-latest\n"
    "    steps:\n"
    f"      - uses: {_CHECKOUT_ACTION}\n"
    "        with:\n"
    "          persist-credentials: false\n"
    f"      - uses: astral-sh/setup-uv@{_SETUP_UV_SHA}\n"
    "      - run: uv python install 3.14.2\n"
    "      - run: scripts/check\n"
    "      - name: Check release version\n"
    "        env:\n"
    "          RELEASE_VERSION: ${{ inputs.version }}\n"
    '        run: uv run python scripts/check_release.py "$RELEASE_VERSION"\n'
    "      - name: Build integration archive\n"
    "        run: >-\n"
    "          git archive --format=zip --prefix=gentex_place/\n"
    "          --add-file=LICENSE --output=gentex_place.zip\n"
    "          HEAD:custom_components/gentex_place\n"
    f"      - uses: {_UPLOAD_ARTIFACT_ACTION}\n"
    "        with:\n"
    "          name: gentex_place-${{ inputs.version }}\n"
    "          path: gentex_place.zip\n"
    "          if-no-files-found: error\n"
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


def test_release_workflow_builds_only_a_read_only_manual_artifact() -> None:
    workflow = (_ROOT / ".github/workflows/release.yml").read_text()

    _assert_release_workflow_contract(workflow)


@pytest.mark.parametrize(
    ("anchor", "unsafe_replacement"),
    [
        ("\npermissions:\n", "\n  push:\n\npermissions:\n"),
        (
            "permissions:\n  contents: read",
            "permissions:\n  contents: read\n  issues: write",
        ),
        (
            f"      - uses: {_UPLOAD_ARTIFACT_ACTION}",
            (
                "      - uses: untrusted/example@"
                "0000000000000000000000000000000000000000\n"
                f"      - uses: {_UPLOAD_ARTIFACT_ACTION}"
            ),
        ),
        (
            "      - name: Check release version",
            (
                "      - run: curl https://example.invalid/publish\n"
                "      - name: Check release version"
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
