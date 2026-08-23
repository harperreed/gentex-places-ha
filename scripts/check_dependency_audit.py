# Copyright (c) 2026 Harper Reed
# ABOUTME: Runs pip-audit and enforces the approved cryptography risk exception.
# ABOUTME: Rejects any drift in the audited package, version, or finding set.
# ruff: noqa: INP001, T201
"""Fail-closed dependency audit gate for the repository's narrow risk exception."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

_APPROVED_PACKAGE = "cryptography"
_APPROVED_VERSION = "48.0.1"
_APPROVED_FINDINGS = frozenset(
    {
        "PYSEC-2026-3552",
        "PYSEC-2026-3553",
        "PYSEC-2026-3554",
    }
)
_APPROVED_SKIPPED_PACKAGE = "place-integration-api"


class AuditPolicyError(ValueError):
    """Report a dependency audit result outside the approved exception."""


def _load_report(path: Path | None) -> dict[str, Any]:
    """Load a fixture report or run pip-audit for the active environment."""
    if path is not None:
        with path.open(encoding="utf-8") as stream:
            report = json.load(stream)
    else:
        result = subprocess.run(
            [sys.executable, "-m", "pip_audit", "--format=json"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        if result.returncode not in {0, 1}:
            msg = f"pip-audit exited with unexpected status {result.returncode}"
            raise AuditPolicyError(msg)
        report = json.loads(result.stdout)

    if not isinstance(report, dict):
        msg = "pip-audit report must be a JSON object"
        raise AuditPolicyError(msg)
    return report


def _validated_vulnerabilities(
    dependency: object,
) -> tuple[str, str, frozenset[str]]:
    """Return one dependency's normalized identity and vulnerability IDs."""
    if not isinstance(dependency, dict):
        msg = "pip-audit dependency entries must be JSON objects"
        raise AuditPolicyError(msg)
    name = dependency.get("name")
    version = dependency.get("version")
    vulnerabilities = dependency.get("vulns")
    skip_reason = dependency.get("skip_reason")
    if (
        name == _APPROVED_SKIPPED_PACKAGE
        and isinstance(skip_reason, str)
        and version is None
        and vulnerabilities is None
    ):
        return name, "<not audited: immutable Git dependency>", frozenset()
    if not isinstance(name, str) or not isinstance(version, str):
        msg = "audited dependencies must include string names and versions"
        raise AuditPolicyError(msg)
    if not isinstance(vulnerabilities, list):
        msg = f"{name}=={version} has no vulnerability list"
        raise AuditPolicyError(msg)

    findings: set[str] = set()
    for vulnerability in vulnerabilities:
        if not isinstance(vulnerability, dict) or not isinstance(
            vulnerability.get("id"), str
        ):
            msg = f"{name}=={version} has a malformed vulnerability entry"
            raise AuditPolicyError(msg)
        findings.add(vulnerability["id"])
    return name, version, frozenset(findings)


def _enforce_policy(report: dict[str, Any]) -> None:
    """Accept only the exact package, version, and finding set Doctor Biz approved."""
    dependencies = report.get("dependencies")
    if not isinstance(dependencies, list):
        msg = "pip-audit report has no dependency list"
        raise AuditPolicyError(msg)

    audited = [_validated_vulnerabilities(dependency) for dependency in dependencies]
    cryptography = [item for item in audited if item[0] == _APPROVED_PACKAGE]
    if len(cryptography) != 1:
        msg = "expected exactly one audited cryptography package"
        raise AuditPolicyError(msg)

    _, version, findings = cryptography[0]
    if version != _APPROVED_VERSION:
        msg = f"expected cryptography=={_APPROVED_VERSION}, found {version}"
        raise AuditPolicyError(msg)
    if findings != _APPROVED_FINDINGS:
        missing = sorted(_APPROVED_FINDINGS - findings)
        unexpected = sorted(findings - _APPROVED_FINDINGS)
        msg = (
            "cryptography finding set changed; "
            f"missing={missing}, unexpected={unexpected}"
        )
        raise AuditPolicyError(msg)

    unapproved = [
        (name, item_version, item_findings)
        for name, item_version, item_findings in audited
        if name != _APPROVED_PACKAGE and item_findings
    ]
    if unapproved:
        details = "; ".join(
            f"{name}=={item_version}: {', '.join(sorted(item_findings))}"
            for name, item_version, item_findings in unapproved
        )
        msg = f"unapproved vulnerabilities found: {details}"
        raise AuditPolicyError(msg)

    print("Dependency audit findings:")
    print(
        f"  {_APPROVED_PACKAGE}=={_APPROVED_VERSION}: "
        f"{', '.join(sorted(_APPROVED_FINDINGS))}"
    )
    print("Accepted under Doctor Biz's approved narrow exception.")


def main() -> int:
    """Run the audit policy against pip-audit or an optional JSON fixture."""
    arguments = sys.argv[1:]
    if len(arguments) > 1:
        print("usage: check_dependency_audit.py [pip-audit.json]", file=sys.stderr)
        return 2
    report_path = Path(arguments[0]) if arguments else None
    try:
        _enforce_policy(_load_report(report_path))
    except (AuditPolicyError, json.JSONDecodeError, OSError) as error:
        print(f"dependency audit rejected: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
