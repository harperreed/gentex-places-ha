# Copyright (c) 2026 Gentex
# ABOUTME: Tests the narrow cryptography audit exception as a subprocess contract.
# ABOUTME: Any package, version, or finding drift must fail the repository gate.
"""Dependency-audit exception contract tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).parents[1]
_CHECKER = _ROOT / "scripts/check_dependency_audit.py"
_APPROVED_FINDINGS = {
    "PYSEC-2026-3552",
    "PYSEC-2026-3553",
    "PYSEC-2026-3554",
}


def _audit_report(*, version: str = "48.0.1", findings: set[str]) -> dict[str, Any]:
    return {
        "dependencies": [
            {
                "name": "cryptography",
                "version": version,
                "vulns": [{"id": finding} for finding in sorted(findings)],
            },
            {"name": "homeassistant", "version": "2026.8.1", "vulns": []},
        ],
        "fixes": [],
    }


def _run_checker(
    tmp_path: Path, report: dict[str, Any]
) -> subprocess.CompletedProcess[str]:
    report_path = tmp_path / "pip-audit.json"
    report_path.write_text(json.dumps(report))
    return subprocess.run(  # noqa: S603
        [sys.executable, str(_CHECKER), str(report_path)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_approved_cryptography_findings_are_visible_and_pass(tmp_path: Path) -> None:
    result = _run_checker(
        tmp_path,
        _audit_report(findings=_APPROVED_FINDINGS),
    )

    assert result.returncode == 0, result.stderr
    assert "cryptography==48.0.1" in result.stdout
    assert all(finding in result.stdout for finding in _APPROVED_FINDINGS)
    assert "approved narrow exception" in result.stdout


def test_skipped_git_dependency_preserves_narrow_exception(tmp_path: Path) -> None:
    report = _audit_report(findings=_APPROVED_FINDINGS)
    report["dependencies"].append(
        {
            "name": "place-integration-api",
            "skip_reason": "Dependency not found on PyPI and could not be audited",
        }
    )

    result = _run_checker(tmp_path, report)

    assert result.returncode == 0, result.stderr
    assert "cryptography==48.0.1" in result.stdout


def test_changed_cryptography_version_fails_closed(tmp_path: Path) -> None:
    result = _run_checker(
        tmp_path,
        _audit_report(version="49.0.0", findings=_APPROVED_FINDINGS),
    )

    assert result.returncode == 1
    assert "expected cryptography==48.0.1" in result.stderr


@pytest.mark.parametrize(
    "findings",
    [
        _APPROVED_FINDINGS - {"PYSEC-2026-3554"},
        _APPROVED_FINDINGS | {"PYSEC-2099-9999"},
    ],
)
def test_changed_cryptography_finding_set_fails_closed(
    tmp_path: Path,
    findings: set[str],
) -> None:
    result = _run_checker(tmp_path, _audit_report(findings=findings))

    assert result.returncode == 1
    assert "cryptography finding set changed" in result.stderr


def test_vulnerability_in_another_package_fails_closed(tmp_path: Path) -> None:
    report = _audit_report(findings=_APPROVED_FINDINGS)
    report["dependencies"].append(
        {
            "name": "other-package",
            "version": "1.0.0",
            "vulns": [{"id": "PYSEC-2099-9999"}],
        }
    )

    result = _run_checker(tmp_path, report)

    assert result.returncode == 1
    assert "unapproved vulnerabilities" in result.stderr
    assert "other-package==1.0.0: PYSEC-2099-9999" in result.stderr
