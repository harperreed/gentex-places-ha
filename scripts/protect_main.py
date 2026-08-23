# Copyright (c) 2026 Harper Reed
# ABOUTME: Builds and verifies the exact GitHub protection policy for main.
# ABOUTME: Trusts only successful required checks from one GitHub Actions app.
# ruff: noqa: INP001 - repository scripts are importable test targets without a package
"""Protect the Gentex PLACE main branch with trusted GitHub Actions checks."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from typing import Any

_REPOSITORY = "harperreed/gentex-places-ha"
_BRANCH = "main"
_API_VERSION_HEADER = "X-GitHub-Api-Version:2026-03-10"
_REQUIRED_CHECKS = ("hacs", "hassfest", "test")
_TRUSTED_APP_SLUG = "github-actions"
_COMMIT_SHA = re.compile(r"[0-9a-f]{40}\Z")
_MISSING = object()


def _complete_check_runs(check_runs: dict[str, Any]) -> list[Any]:
    """Return a complete GitHub check-run page or fail closed."""
    runs = check_runs.get("check_runs")
    if not isinstance(runs, list):
        message = "GitHub check-run response has no check_runs list"
        raise ValueError(message)  # noqa: TRY004 - CLI policy errors use ValueError
    total_count = check_runs.get("total_count")
    if (
        not isinstance(total_count, int)
        or isinstance(total_count, bool)
        or total_count < 0
    ):
        message = "GitHub check-run response has invalid total_count"
        raise ValueError(message)
    if total_count != len(runs):
        message = "GitHub check-run response has incomplete check_runs list"
        raise ValueError(message)
    return runs


def trusted_checks(check_runs: dict[str, Any]) -> list[dict[str, int | str]]:
    """Return the required successful checks bound to one GitHub Actions app."""
    runs = _complete_check_runs(check_runs)

    checks: list[dict[str, int | str]] = []
    for name in _REQUIRED_CHECKS:
        named = [
            run for run in runs if isinstance(run, dict) and run.get("name") == name
        ]
        if not named:
            message = f"missing required check: {name}"
            raise ValueError(message)
        if len(named) != 1:
            message = f"expected exactly one required check: {name}"
            raise ValueError(message)
        run = named[0]
        if run.get("status") != "completed" or run.get("conclusion") != "success":
            message = f"no successful completed check: {name}"
            raise ValueError(message)
        app = run.get("app")
        if not isinstance(app, dict) or app.get("slug") != _TRUSTED_APP_SLUG:
            message = f"no successful check from github-actions app: {name}"
            raise ValueError(message)
        app_id = app.get("id")
        if not isinstance(app_id, int) or isinstance(app_id, bool) or app_id <= 0:
            message = f"invalid github-actions app ID for check: {name}"
            raise ValueError(message)
        checks.append({"context": name, "app_id": app_id})

    app_ids = {check["app_id"] for check in checks}
    if len(app_ids) != 1:
        message = "required checks must use the same app ID"
        raise ValueError(message)
    return sorted(checks, key=lambda check: str(check["context"]))


def protection_payload(
    checks: list[dict[str, int | str]],
) -> dict[str, Any]:
    """Build the exact protected-main request document."""
    return {
        "required_status_checks": {
            "strict": True,
            "contexts": [],
            "checks": checks,
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


def _read_field(document: dict[str, Any], path: str) -> object:
    """Read one dotted response field or return the missing sentinel."""
    value: object = document
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return _MISSING
        value = value[part]
    return value


def _require_field(document: dict[str, Any], path: str, expected: object) -> None:
    """Require one response field to equal the protected-main policy."""
    if _read_field(document, path) != expected:
        message = f"branch protection mismatch: {path}"
        raise ValueError(message)


def validate_protection(
    response: dict[str, Any],
    checks: list[dict[str, int | str]],
) -> None:
    """Reject a GitHub read-back document that differs from the required policy."""
    _require_field(response, "required_status_checks.strict", expected=True)
    expected_contexts = [check["context"] for check in checks]
    contexts = _read_field(response, "required_status_checks.contexts")
    if (
        not isinstance(contexts, list)
        or any(not isinstance(context, str) for context in contexts)
        or any(not isinstance(context, str) for context in expected_contexts)
        or len(contexts) != len(set(contexts))
        or len(expected_contexts) != len(set(expected_contexts))
        or set(contexts) != set(expected_contexts)
    ):
        message = "branch protection mismatch: required_status_checks.contexts"
        raise ValueError(message)
    _require_field(response, "required_status_checks.checks", checks)
    _require_field(response, "enforce_admins.enabled", expected=True)
    reviews = _read_field(response, "required_pull_request_reviews")
    if not isinstance(reviews, dict):
        message = "branch protection mismatch: required_pull_request_reviews"
        raise ValueError(message)  # noqa: TRY004 - CLI policy errors use ValueError
    allowances = reviews.get("bypass_pull_request_allowances", _MISSING)
    if allowances is not _MISSING and (
        not isinstance(allowances, dict)
        or not set(allowances).issubset({"users", "teams", "apps"})
        or allowances.get("users", _MISSING) != []
        or allowances.get("teams", _MISSING) != []
        or allowances.get("apps", []) != []
    ):
        message = (
            "branch protection mismatch: "
            "required_pull_request_reviews.bypass_pull_request_allowances"
        )
        raise ValueError(message)
    _require_field(
        response,
        "required_pull_request_reviews.required_approving_review_count",
        0,
    )
    _require_field(
        response,
        "required_pull_request_reviews.require_last_push_approval",
        expected=False,
    )
    _require_field(response, "restrictions", None)
    _require_field(response, "required_linear_history.enabled", expected=True)
    _require_field(response, "allow_force_pushes.enabled", expected=False)
    _require_field(response, "allow_deletions.enabled", expected=False)


def _run_api(
    method: str,
    endpoint: str,
    error_message: str,
    *,
    input_text: str | None = None,
) -> str:
    """Run one exact GitHub API command and return captured output."""
    command = [
        "gh",
        "api",
        "--method",
        method,
        "-H",
        _API_VERSION_HEADER,
        endpoint,
    ]
    if input_text is not None:
        command.extend(["--input", "-"])
    try:
        result = subprocess.run(  # noqa: S603 - fixed gh command, never a shell
            command,
            shell=False,
            check=True,
            capture_output=True,
            text=True,
            input=input_text,
        )
    except OSError, subprocess.CalledProcessError:
        pass
    else:
        return result.stdout
    raise ValueError(error_message)


def _get_api_document(endpoint: str, error_message: str) -> dict[str, Any]:
    """Read and decode one GitHub API object without exposing raw output."""
    raw_response = _run_api("GET", endpoint, error_message)
    try:
        response = json.loads(raw_response)
    except json.JSONDecodeError:
        pass
    else:
        if isinstance(response, dict):
            return response
    raise ValueError(error_message)


def _parse_check_sha(value: str) -> str:
    """Require one canonical full commit SHA before building an API path."""
    if _COMMIT_SHA.fullmatch(value) is None:
        message = "must be a 40-character lowercase hexadecimal commit SHA"
        raise argparse.ArgumentTypeError(message)
    return value


def main() -> None:
    """Print the policy, and apply and verify it only when explicitly requested."""
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--repo", required=True, choices=[_REPOSITORY])
    parser.add_argument("--branch", required=True, choices=[_BRANCH])
    parser.add_argument("--check-sha", required=True, type=_parse_check_sha)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="apply and verify the proposed policy",
    )
    args = parser.parse_args()
    check_runs_endpoint = (
        f"repos/{_REPOSITORY}/commits/{args.check_sha}/check-runs?per_page=100"
    )
    protection_endpoint = f"repos/{_REPOSITORY}/branches/{_BRANCH}/protection"
    try:
        check_runs = _get_api_document(
            check_runs_endpoint,
            "cannot read GitHub check runs",
        )
        checks = trusted_checks(check_runs)
        payload = protection_payload(checks)
        encoded_payload = json.dumps(payload)
        print(encoded_payload)  # noqa: T201 - required dry-run output
        if not args.apply:
            return
        _run_api(
            "PUT",
            protection_endpoint,
            "cannot update branch protection",
            input_text=encoded_payload,
        )
        response = _get_api_document(
            protection_endpoint,
            "cannot read branch protection",
        )
        validate_protection(response, checks)
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
