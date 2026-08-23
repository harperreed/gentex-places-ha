# Copyright (c) 2026 Gentex
# ABOUTME: Verifies trusted GitHub checks and the protected-main policy contract.
# ABOUTME: Keeps branch protection strict, app-bound, and safe to read back.
"""Tests for the protected-main policy."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from scripts.protect_main import (
    protection_payload,
    trusted_checks,
    validate_protection,
)

_APP_ID = 15368
_ROOT = Path(__file__).parents[1]
_SCRIPT = _ROOT / "scripts/protect_main.py"
_CHECK_SHA = "a" * 40
_ARGPARSE_ERROR = 2
_CHECKS = [
    {"context": "hacs", "app_id": _APP_ID},
    {"context": "hassfest", "app_id": _APP_ID},
    {"context": "test", "app_id": _APP_ID},
]


def _check_run(
    name: str,
    *,
    status: str = "completed",
    conclusion: str | None = "success",
    app_id: int = _APP_ID,
    app_slug: str = "github-actions",
) -> dict[str, Any]:
    """Build one representative GitHub check-run document."""
    return {
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "app": {"id": app_id, "slug": app_slug},
    }


def _check_runs() -> dict[str, Any]:
    """Build required successes plus irrelevant and stale duplicate runs."""
    return {
        "total_count": 8,
        "check_runs": [
            _check_run("test"),
            _check_run("test", conclusion="failure"),
            _check_run("hassfest"),
            _check_run("hassfest", status="queued", conclusion=None),
            _check_run("hacs"),
            _check_run("hacs", conclusion="failure"),
            _check_run("lint"),
            _check_run("external", app_slug="other-app"),
        ],
    }


def _protection_response() -> dict[str, Any]:
    """Build the GitHub branch-protection read-back shape."""
    return {
        "required_status_checks": {
            "strict": True,
            "contexts": [check["context"] for check in _CHECKS],
            "checks": deepcopy(_CHECKS),
        },
        "enforce_admins": {"enabled": True},
        "required_pull_request_reviews": {
            "required_approving_review_count": 0,
            "require_last_push_approval": False,
        },
        "restrictions": None,
        "required_linear_history": {"enabled": True},
        "allow_force_pushes": {"enabled": False},
        "allow_deletions": {"enabled": False},
    }


def _set_path(document: dict[str, Any], path: str, value: object) -> None:
    """Set one dotted path in a representative GitHub response."""
    parts = path.split(".")
    target = document
    for part in parts[:-1]:
        child = target[part]
        assert isinstance(child, dict)
        target = child
    target[parts[-1]] = value


def _write_executable(path: Path, source: str) -> None:
    """Write one controlled executable for a real CLI test."""
    path.write_text(source)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _cli_environment(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    """Create a controlled GitHub CLI boundary and return its evidence paths."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    command_log = tmp_path / "commands"
    put_input = tmp_path / "put-input"
    _write_executable(
        bin_dir / "gh",
        """#!/bin/sh
printf '%s\n' "$*" >>"$COMMAND_LOG"
if [ "${GH_FAILURE:-0}" -ne 0 ]; then
    printf '%s\n' "$GH_RAW_ERROR" >&2
    exit "$GH_FAILURE"
fi
if [ "$3" = "PUT" ]; then
    [ "$7" = "--input" ] && [ "$8" = "-" ] || exit 8
    /bin/cat >"$PUT_INPUT"
    printf '{}'
elif [ "$3" = "GET" ]; then
    case "$6" in
        *"/check-runs?per_page=100") printf '%s' "$CHECK_RUNS_JSON" ;;
        *"/branches/main/protection") printf '%s' "$PROTECTION_JSON" ;;
        *) exit 9 ;;
    esac
else
    exit 10
fi
""",
    )
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "COMMAND_LOG": str(command_log),
        "PUT_INPUT": str(put_input),
        "CHECK_RUNS_JSON": json.dumps(_check_runs()),
        "PROTECTION_JSON": json.dumps(_protection_response()),
    }
    return env, command_log, put_input


def _run_cli(
    env: dict[str, str],
    *extra_arguments: str,
    repo: str = "harperreed/gentex-places-ha",
    branch: str = "main",
    check_sha: str = _CHECK_SHA,
) -> subprocess.CompletedProcess[str]:
    """Run the protection CLI with its required safe target arguments."""
    return subprocess.run(  # noqa: S603 - exact Python and repository script
        [
            sys.executable,
            str(_SCRIPT),
            "--repo",
            repo,
            "--branch",
            branch,
            "--check-sha",
            check_sha,
            *extra_arguments,
        ],
        cwd=_ROOT,
        env=env,
        shell=False,
        check=False,
        capture_output=True,
        text=True,
    )


def test_trusted_checks_selects_required_successes_from_github_actions() -> None:
    assert trusted_checks(_check_runs()) == _CHECKS


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        pytest.param("missing", "missing required check: hacs", id="missing"),
        pytest.param("failure", "successful completed check: hacs", id="failure"),
        pytest.param("app-slug", "github-actions app: hacs", id="app-slug"),
        pytest.param("app-id", "same app ID", id="app-id"),
    ],
)
def test_trusted_checks_fails_closed(
    mutation: str,
    message: str,
) -> None:
    response = _check_runs()
    runs = response["check_runs"]
    assert isinstance(runs, list)
    if mutation == "missing":
        response["check_runs"] = [run for run in runs if run["name"] != "hacs"]
    elif mutation == "failure":
        response["check_runs"] = [
            run
            for run in runs
            if run["name"] != "hacs" or run["conclusion"] != "success"
        ]
    elif mutation == "app-slug":
        for run in runs:
            if run["name"] == "hacs" and run["conclusion"] == "success":
                run["app"]["slug"] = "other-app"
    else:
        for run in runs:
            if run["name"] == "hacs" and run["conclusion"] == "success":
                run["app"]["id"] = 99999

    with pytest.raises(ValueError, match=message):
        trusted_checks(response)


def test_protection_payload_is_the_exact_protected_main_policy() -> None:
    payload = protection_payload(_CHECKS)

    assert payload == {
        "required_status_checks": {
            "strict": True,
            "contexts": [],
            "checks": _CHECKS,
        },
        "enforce_admins": True,
        "required_pull_request_reviews": {
            "required_approving_review_count": 0,
            "require_last_push_approval": False,
        },
        "restrictions": None,
        "required_linear_history": True,
        "allow_force_pushes": False,
        "allow_deletions": False,
    }


def test_validate_protection_accepts_exact_github_read_back() -> None:
    validate_protection(_protection_response(), _CHECKS)


def test_validate_protection_accepts_reordered_status_contexts() -> None:
    response = _protection_response()
    response["required_status_checks"]["contexts"] = ["test", "hacs", "hassfest"]

    validate_protection(response, _CHECKS)


@pytest.mark.parametrize(
    "allowances",
    [
        {"users": [], "teams": []},
        {"users": [], "teams": [], "apps": []},
    ],
)
def test_validate_protection_accepts_structurally_empty_bypass_allowances(
    allowances: dict[str, list[object]],
) -> None:
    response = _protection_response()
    response["required_pull_request_reviews"]["bypass_pull_request_allowances"] = (
        allowances
    )

    validate_protection(response, _CHECKS)


@pytest.mark.parametrize(
    "allowances",
    [
        pytest.param(
            {"users": [{"login": "octocat"}], "teams": []},
            id="user-bypass",
        ),
        pytest.param(
            {"users": [], "teams": [{"slug": "release"}]},
            id="team-bypass",
        ),
        pytest.param(
            {"users": [], "teams": [], "apps": [{"slug": "octoapp"}]},
            id="app-bypass",
        ),
        pytest.param(None, id="null"),
        pytest.param({}, id="missing-required-lists"),
        pytest.param({"users": []}, id="missing-teams"),
        pytest.param({"teams": []}, id="missing-users"),
        pytest.param({"users": "octocat", "teams": []}, id="users-not-list"),
        pytest.param({"users": [], "teams": None}, id="teams-not-list"),
        pytest.param(
            {"users": [], "teams": [], "apps": None},
            id="apps-not-list",
        ),
        pytest.param(
            {"users": [], "teams": [], "unknown": []},
            id="unknown-field",
        ),
    ],
)
def test_validate_protection_rejects_bypass_allowances(
    allowances: object,
) -> None:
    response = _protection_response()
    response["required_pull_request_reviews"]["bypass_pull_request_allowances"] = (
        allowances
    )

    with pytest.raises(ValueError, match="bypass_pull_request_allowances"):
        validate_protection(response, _CHECKS)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        ("required_status_checks.strict", False, "required_status_checks.strict"),
        (
            "required_status_checks.checks",
            [{"context": "hacs", "app_id": 99999}, *_CHECKS[1:]],
            "required_status_checks.checks",
        ),
        ("enforce_admins.enabled", False, "enforce_admins.enabled"),
        (
            "required_pull_request_reviews",
            None,
            "required_pull_request_reviews",
        ),
        (
            "required_pull_request_reviews.required_approving_review_count",
            1,
            "required_pull_request_reviews.required_approving_review_count",
        ),
        (
            "required_pull_request_reviews.require_last_push_approval",
            True,
            "required_pull_request_reviews.require_last_push_approval",
        ),
        ("restrictions", {}, "restrictions"),
        ("required_linear_history.enabled", False, "required_linear_history.enabled"),
        ("allow_force_pushes.enabled", True, "allow_force_pushes.enabled"),
        ("allow_deletions.enabled", True, "allow_deletions.enabled"),
    ],
)
def test_validate_protection_rejects_policy_drift(
    path: str,
    value: object,
    message: str,
) -> None:
    response = _protection_response()
    _set_path(response, path, value)

    with pytest.raises(ValueError, match=message):
        validate_protection(response, _CHECKS)


@pytest.mark.parametrize(
    "contexts",
    [
        pytest.param([], id="empty"),
        pytest.param(["hacs", "hassfest", "test", "lint"], id="extra"),
        pytest.param(["hacs", "hassfest", "test", "test"], id="duplicate"),
        pytest.param(["hacs", "hassfest", "lint"], id="wrong-name"),
        pytest.param("hacs,hassfest,test", id="not-list"),
        pytest.param(["hacs", "hassfest", 7], id="non-string-item"),
    ],
)
def test_validate_protection_rejects_invalid_status_contexts(
    contexts: object,
) -> None:
    response = _protection_response()
    response["required_status_checks"]["contexts"] = contexts

    with pytest.raises(ValueError, match=r"required_status_checks\.contexts"):
        validate_protection(response, _CHECKS)


def test_validate_protection_rejects_missing_required_status_contexts() -> None:
    response = _protection_response()
    del response["required_status_checks"]["contexts"]

    with pytest.raises(ValueError, match=r"required_status_checks\.contexts"):
        validate_protection(response, _CHECKS)


def test_validate_protection_rejects_contexts_matching_wrong_read_back_checks() -> None:
    response = _protection_response()
    response["required_status_checks"]["contexts"] = ["hacs", "hassfest", "lint"]
    response["required_status_checks"]["checks"][-1]["context"] = "lint"

    with pytest.raises(ValueError, match=r"required_status_checks\.contexts"):
        validate_protection(response, _CHECKS)


def test_cli_defaults_to_read_only_and_prints_the_proposed_payload(
    tmp_path: Path,
) -> None:
    env, command_log, put_input = _cli_environment(tmp_path)

    result = _run_cli(env)

    assert result.returncode == 0
    assert result.stdout == f"{json.dumps(protection_payload(_CHECKS))}\n"
    assert result.stderr == ""
    assert command_log.read_text().splitlines() == [
        (
            "api --method GET -H X-GitHub-Api-Version:2026-03-10 "
            f"repos/harperreed/gentex-places-ha/commits/{_CHECK_SHA}/"
            "check-runs?per_page=100"
        )
    ]
    assert not put_input.exists()


def test_cli_apply_sends_only_the_payload_then_validates_read_back(
    tmp_path: Path,
) -> None:
    env, command_log, put_input = _cli_environment(tmp_path)

    result = _run_cli(env, "--apply")

    expected_payload = protection_payload(_CHECKS)
    assert result.returncode == 0
    assert result.stdout == f"{json.dumps(expected_payload)}\n"
    assert result.stderr == ""
    assert command_log.read_text().splitlines() == [
        (
            "api --method GET -H X-GitHub-Api-Version:2026-03-10 "
            f"repos/harperreed/gentex-places-ha/commits/{_CHECK_SHA}/"
            "check-runs?per_page=100"
        ),
        (
            "api --method PUT -H X-GitHub-Api-Version:2026-03-10 "
            "repos/harperreed/gentex-places-ha/branches/main/protection --input -"
        ),
        (
            "api --method GET -H X-GitHub-Api-Version:2026-03-10 "
            "repos/harperreed/gentex-places-ha/branches/main/protection"
        ),
    ]
    assert put_input.read_text() == json.dumps(expected_payload)


@pytest.mark.parametrize(
    ("repo", "branch"),
    [
        ("harperreed/other-repository", "main"),
        ("harperreed/gentex-places-ha", "develop"),
    ],
)
def test_cli_rejects_any_other_repository_or_branch_before_api_access(
    tmp_path: Path,
    repo: str,
    branch: str,
) -> None:
    env, command_log, put_input = _cli_environment(tmp_path)

    result = _run_cli(env, repo=repo, branch=branch)

    assert result.returncode == _ARGPARSE_ERROR
    assert result.stdout == ""
    assert "invalid choice" in result.stderr
    assert not command_log.exists()
    assert not put_input.exists()


def test_cli_requires_the_full_apply_flag_before_api_access(tmp_path: Path) -> None:
    env, command_log, put_input = _cli_environment(tmp_path)

    result = _run_cli(env, "--ap")

    assert result.returncode == _ARGPARSE_ERROR
    assert result.stdout == ""
    assert "unrecognized arguments: --ap" in result.stderr
    assert not command_log.exists()
    assert not put_input.exists()


@pytest.mark.parametrize("check_sha", ["main", "a" * 39, "A" * 40])
def test_cli_rejects_a_noncanonical_check_sha_before_api_access(
    tmp_path: Path,
    check_sha: str,
) -> None:
    env, command_log, put_input = _cli_environment(tmp_path)

    result = _run_cli(env, check_sha=check_sha)

    assert result.returncode == _ARGPARSE_ERROR
    assert result.stdout == ""
    assert "40-character lowercase hexadecimal commit SHA" in result.stderr
    assert not command_log.exists()
    assert not put_input.exists()


def test_cli_prints_no_payload_when_a_required_check_failed(tmp_path: Path) -> None:
    env, command_log, put_input = _cli_environment(tmp_path)
    check_runs = _check_runs()
    check_runs["check_runs"] = [
        run
        for run in check_runs["check_runs"]
        if run["name"] != "hacs" or run["conclusion"] != "success"
    ]
    env["CHECK_RUNS_JSON"] = json.dumps(check_runs)

    result = _run_cli(env)

    assert result.returncode == _ARGPARSE_ERROR
    assert result.stdout == ""
    assert result.stderr.endswith(
        "protect_main.py: error: no successful completed check: hacs\n"
    )
    assert len(command_log.read_text().splitlines()) == 1
    assert not put_input.exists()


def test_cli_does_not_print_raw_github_errors(tmp_path: Path) -> None:
    env, command_log, put_input = _cli_environment(tmp_path)
    env["GH_FAILURE"] = "7"
    env["GH_RAW_ERROR"] = "authorization: secret-test-token"

    result = _run_cli(env)

    assert result.returncode == _ARGPARSE_ERROR
    assert result.stdout == ""
    assert result.stderr.endswith(
        "protect_main.py: error: cannot read GitHub check runs\n"
    )
    assert "secret-test-token" not in result.stderr
    assert len(command_log.read_text().splitlines()) == 1
    assert not put_input.exists()
