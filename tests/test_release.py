# Copyright (c) 2026 Gentex
# ABOUTME: Verifies stable release decisions across repository metadata revisions.
# ABOUTME: Keeps release automation tied to matching, increasing semantic versions.
"""Tests for release-change detection and artifact packaging."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_release import (
    ReleaseDecision,
    decide_release,
    detect_release,
    parse_version,
)

_ROOT = Path(__file__).parents[1]
_CHECKER = _ROOT / "scripts/check_release.py"
_MANIFEST = Path("custom_components/gentex_place/manifest.json")
_ARGPARSE_ERROR = 2


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


def _init_repo(tmp_path: Path) -> tuple[Path, str]:
    """Create a disposable repository with valid release metadata."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "release-test@example.com")
    _git(repo, "config", "user.name", "Release Test")
    _write_metadata(repo, project_version="0.1.0", manifest_version="0.1.0")
    _git(repo, "add", "pyproject.toml", str(_MANIFEST))
    _git(repo, "commit", "-m", "initial metadata")
    return repo, _git(repo, "rev-parse", "HEAD")


def _commit_bytes(repo: Path, path: Path, content: bytes) -> str:
    """Commit raw metadata bytes and return the new revision."""
    (repo / path).write_bytes(content)
    _git(repo, "add", str(path))
    _git(repo, "commit", "-m", f"replace {path.name}")
    return _git(repo, "rev-parse", "HEAD")


def _run_checker(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the public checker CLI with real Git behavior."""
    return subprocess.run(  # noqa: S603 - exact checked Python executable and script
        [sys.executable, str(_CHECKER), *args],
        cwd=_ROOT,
        shell=False,
        check=False,
        capture_output=True,
        text=True,
    )


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
    repo, first_sha = _init_repo(tmp_path)

    _write_metadata(repo, project_version="1.0.0", manifest_version="1.0.0")
    _git(repo, "add", "pyproject.toml", "custom_components/gentex_place/manifest.json")
    _git(repo, "commit", "-m", "release metadata")
    second_sha = _git(repo, "rev-parse", "HEAD")

    assert detect_release(first_sha, second_sha, repo) == ReleaseDecision(
        previous="0.1.0", current="1.0.0", required=True
    )

    with pytest.raises(ValueError, match="cannot read release metadata"):
        detect_release("0" * 40, second_sha, repo)


def test_detect_release_rejects_option_shaped_revision_without_writing_output(
    tmp_path: Path,
) -> None:
    repo, good_sha = _init_repo(tmp_path)
    injected_base = tmp_path / "git-show-output"
    option_revision = f"--output={injected_base}"
    injected_output = Path(f"{injected_base}:pyproject.toml")

    with pytest.raises(
        ValueError,
        match=re.escape(f"cannot read release metadata for {option_revision}"),
    ) as error:
        detect_release(option_revision, good_sha, repo)

    assert error.value.__context__ is None
    assert error.value.__cause__ is None
    assert not injected_output.exists()


@pytest.mark.parametrize("path", [Path("pyproject.toml"), _MANIFEST])
def test_detect_release_sanitizes_invalid_utf8(
    tmp_path: Path,
    path: Path,
) -> None:
    repo, _ = _init_repo(tmp_path)
    malformed_sha = _commit_bytes(repo, path, b"\xff")

    with pytest.raises(
        ValueError,
        match=re.escape(f"cannot read release metadata for {malformed_sha}"),
    ) as error:
        detect_release(malformed_sha, malformed_sha, repo)

    assert error.value.__context__ is None
    assert error.value.__cause__ is None


@pytest.mark.parametrize(
    ("path", "content"),
    [
        pytest.param(Path("pyproject.toml"), b"[project\n", id="invalid-toml"),
        pytest.param(_MANIFEST, b"{", id="invalid-json"),
        pytest.param(
            Path("pyproject.toml"),
            b'[project]\nname = "example"\n',
            id="missing-project-version",
        ),
        pytest.param(_MANIFEST, b"{}", id="missing-manifest-version"),
    ],
)
def test_detect_release_sanitizes_invalid_metadata(
    tmp_path: Path,
    path: Path,
    content: bytes,
) -> None:
    repo, _ = _init_repo(tmp_path)
    invalid_sha = _commit_bytes(repo, path, content)

    with pytest.raises(
        ValueError,
        match=re.escape(f"cannot read release metadata for {invalid_sha}"),
    ) as error:
        detect_release(invalid_sha, invalid_sha, repo)

    assert error.value.__context__ is None
    assert error.value.__cause__ is None


def test_cli_prints_exact_json_and_github_output(tmp_path: Path) -> None:
    github_output = tmp_path / "github-output"

    result = _run_checker("HEAD", "HEAD", "--github-output", str(github_output))

    assert result.returncode == 0
    assert result.stdout == (
        '{"previous": "0.1.0", "current": "0.1.0", "required": false}\n'
    )
    assert result.stderr == ""
    assert github_output.read_text() == ("release_required=false\nversion=0.1.0\n")


def test_cli_require_release_rejects_noop_without_writing_output(
    tmp_path: Path,
) -> None:
    github_output = tmp_path / "github-output"

    result = _run_checker(
        "HEAD",
        "HEAD",
        "--github-output",
        str(github_output),
        "--require-release",
    )

    assert result.returncode == _ARGPARSE_ERROR
    assert result.stdout == ""
    assert result.stderr.endswith(
        "check_release.py: error: release version did not increase\n"
    )
    assert not github_output.exists()


def test_workflow_builds_the_verified_root_level_release_archive() -> None:
    workflow = (_ROOT / ".github/workflows/release.yml").read_text()

    assert (
        "run: uv run python scripts/build_release.py --output dist/gentex_place.zip"
    ) in workflow
    assert "git archive" not in workflow
