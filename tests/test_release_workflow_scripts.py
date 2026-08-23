# Copyright (c) 2026 Harper Reed
# ABOUTME: Exercises release preflight and draft verification as real shell processes.
# ABOUTME: Covers strict versions, draft pagination, signals, and exact uploaded assets.
"""Behavioral tests for the release workflow's POSIX helpers."""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
_ABSENCE_CHECK = _ROOT / "scripts/check_release_absent"
_DRAFT_CHECK = _ROOT / "scripts/verify_draft_release"
_RELEASE_SHA = "a" * 40
_EXPECTED_ASSETS = "gentex_place.zip\ngentex_place.zip.sha256"


def _write_executable(path: Path, source: str) -> None:
    """Write one controlled executable used by a real shell helper."""
    path.write_text(source)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _environment(bin_dir: Path, temp_dir: Path) -> dict[str, str]:
    """Return a credential-free controlled release-helper environment."""
    return {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GH_TOKEN": "test-token",
        "GITHUB_REPOSITORY": "example/repository",
        "TMPDIR": str(temp_dir),
    }


@pytest.mark.parametrize("version", ["1", "1.2", "01.2.3", "1.02.3", "1.2.03"])
@pytest.mark.parametrize(
    ("script", "extra_arguments"),
    [(_ABSENCE_CHECK, []), (_DRAFT_CHECK, [_RELEASE_SHA])],
)
def test_release_helpers_reject_noncanonical_versions_before_network_access(
    script: Path,
    extra_arguments: list[str],
    version: str,
) -> None:
    env = {**os.environ}
    env.pop("GH_TOKEN", None)
    env.pop("GITHUB_REPOSITORY", None)

    result = subprocess.run(  # noqa: S603 - exact checked repository script
        [str(script), version, *extra_arguments],
        cwd=_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "version must be a stable semantic version\n"


def _absence_environment(tmp_path: Path) -> tuple[dict[str, str], Path]:
    """Create controlled Git, curl, and GitHub CLI boundaries."""
    bin_dir = tmp_path / "bin"
    temp_dir = tmp_path / "temp"
    bin_dir.mkdir()
    temp_dir.mkdir()
    command_log = tmp_path / "gh-commands"
    _write_executable(bin_dir / "git", '#!/bin/sh\nexit "${GIT_STATUS:-2}"\n')
    _write_executable(
        bin_dir / "curl",
        '#!/bin/sh\nprintf \'%s\' "${CURL_STATUS:-404}"\nexit "${CURL_EXIT:-0}"\n',
    )
    _write_executable(
        bin_dir / "gh",
        "#!/bin/sh\n"
        'printf \'%s\\n\' "$*" >>"$COMMAND_LOG"\n'
        '[ "${GH_API_STATUS:-0}" -eq 0 ] || exit "$GH_API_STATUS"\n'
        '[ "$*" = "api --method GET -H X-GitHub-Api-Version: 2026-03-10 '
        "--paginate repos/example/repository/releases?per_page=100 --jq "
        '.[] | select(.tag_name == \\"v1.2.3\\") | .tag_name" ] || exit 91\n'
        "printf '%s\\n' \"${GH_API_TAGS:-}\" | "
        "awk -v target=\"v1.2.3\" '$0 == target { print }'\n",
    )
    env = _environment(bin_dir, temp_dir)
    env["COMMAND_LOG"] = str(command_log)
    return env, command_log


def test_write_preflight_finds_a_draft_on_any_paginated_release_page(
    tmp_path: Path,
) -> None:
    env, command_log = _absence_environment(tmp_path)
    env["GH_API_TAGS"] = "v0.9.0\nv1.2.3"

    result = subprocess.run(  # noqa: S603 - exact checked repository script
        [str(_ABSENCE_CHECK), "1.2.3", "--include-drafts"],
        cwd=_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert result.stderr == "release v1.2.3 already exists\n"
    command = command_log.read_text()
    assert "--paginate" in command
    assert "--slurp" not in command
    assert '.[] | select(.tag_name == "v1.2.3") | .tag_name' in command
    assert "repos/example/repository/releases?per_page=100" in command


def test_write_preflight_passes_only_after_all_release_pages_are_checked(
    tmp_path: Path,
) -> None:
    env, command_log = _absence_environment(tmp_path)
    env["GH_API_TAGS"] = "v0.9.0\nv1.2.30"

    result = subprocess.run(  # noqa: S603 - exact checked repository script
        [str(_ABSENCE_CHECK), "1.2.3", "--include-drafts"],
        cwd=_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
    command = command_log.read_text()
    assert "--paginate" in command
    assert "--slurp" not in command
    assert '.[] | select(.tag_name == "v1.2.3") | .tag_name' in command


def test_write_preflight_fails_closed_when_release_listing_fails(
    tmp_path: Path,
) -> None:
    env, _command_log = _absence_environment(tmp_path)
    env["GH_API_STATUS"] = "7"

    result = subprocess.run(  # noqa: S603 - exact checked repository script
        [str(_ABSENCE_CHECK), "1.2.3", "--include-drafts"],
        cwd=_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.endswith("cannot prove release v1.2.3 is absent\n")


@pytest.mark.parametrize(
    ("signal_name", "expected_status"),
    [("HUP", 129), ("INT", 130), ("TERM", 143)],
)
def test_draft_verifier_preserves_signal_status_and_cleans_temp_directory(
    tmp_path: Path,
    signal_name: str,
    expected_status: int,
) -> None:
    bin_dir = tmp_path / "bin"
    temp_dir = tmp_path / "temp"
    bin_dir.mkdir()
    temp_dir.mkdir()
    _write_executable(
        bin_dir / "gh",
        '#!/bin/sh\nkill -"$TEST_SIGNAL" "$PPID"\nexit 0\n',
    )
    env = _environment(bin_dir, temp_dir)
    env["TEST_SIGNAL"] = signal_name

    result = subprocess.run(  # noqa: S603 - exact checked repository script
        [str(_DRAFT_CHECK), "1.2.3", _RELEASE_SHA],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == expected_status
    assert list(temp_dir.glob("gentex-place-release.*")) == []


def _draft_environment(tmp_path: Path, release_state: str) -> dict[str, str]:
    """Create controlled download, release-view, and build boundaries."""
    bin_dir = tmp_path / "bin"
    temp_dir = tmp_path / "temp"
    dist_dir = tmp_path / "dist"
    bin_dir.mkdir()
    temp_dir.mkdir()
    dist_dir.mkdir()
    archive = dist_dir / "gentex_place.zip"
    archive.write_bytes(b"controlled release archive")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (dist_dir / "gentex_place.zip.sha256").write_text(f"{digest}  gentex_place.zip\n")
    _write_executable(bin_dir / "uv", "#!/bin/sh\nexit 0\n")
    _write_executable(
        bin_dir / "gh",
        "#!/bin/sh\n"
        'if [ "$1 $2" = "release download" ]; then\n'
        "    shift 2\n"
        "    download_dir=\n"
        '    while [ "$#" -gt 0 ]; do\n'
        '        if [ "$1" = "--dir" ]; then\n'
        "            shift\n"
        "            download_dir=$1\n"
        "        fi\n"
        "        shift\n"
        "    done\n"
        '    mkdir -p "$download_dir"\n'
        '    cp "$TEST_DIST/gentex_place.zip" "$download_dir/"\n'
        '    cp "$TEST_DIST/gentex_place.zip.sha256" "$download_dir/"\n'
        'elif [ "$1 $2" = "release view" ]; then\n'
        '    case " $* " in\n'
        '        *" --json isDraft,targetCommitish,assets "*) '
        "printf '%s\\n' \"$RELEASE_STATE\" ;;\n"
        "        *) exit 10 ;;\n"
        "    esac\n"
        "else\n"
        "    exit 9\n"
        "fi\n",
    )
    env = _environment(bin_dir, temp_dir)
    env["TEST_DIST"] = str(dist_dir)
    env["RELEASE_STATE"] = release_state
    return env


def test_draft_verifier_accepts_the_exact_asset_set(tmp_path: Path) -> None:
    env = _draft_environment(
        tmp_path,
        f"true\n{_RELEASE_SHA}\n{_EXPECTED_ASSETS}",
    )

    result = subprocess.run(  # noqa: S603 - exact checked repository script
        [str(_DRAFT_CHECK), "1.2.3", _RELEASE_SHA],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stderr == ""


@pytest.mark.parametrize(
    "release_state",
    [
        f"false\n{_RELEASE_SHA}\n{_EXPECTED_ASSETS}",
        f"true\n{'b' * 40}\n{_EXPECTED_ASSETS}",
    ],
)
def test_draft_verifier_rejects_unexpected_target_or_draft_state(
    tmp_path: Path,
    release_state: str,
) -> None:
    env = _draft_environment(tmp_path, release_state)

    result = subprocess.run(  # noqa: S603 - exact checked repository script
        [str(_DRAFT_CHECK), "1.2.3", _RELEASE_SHA],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert result.stderr == "release v1.2.3 has unexpected target or draft state\n"


@pytest.mark.parametrize(
    "release_state",
    [
        f"true\n{_RELEASE_SHA}\ngentex_place.zip",
        f"true\n{_RELEASE_SHA}\n{_EXPECTED_ASSETS}\nunexpected.bin",
    ],
)
def test_draft_verifier_rejects_missing_or_extra_assets(
    tmp_path: Path,
    release_state: str,
) -> None:
    env = _draft_environment(tmp_path, release_state)

    result = subprocess.run(  # noqa: S603 - exact checked repository script
        [str(_DRAFT_CHECK), "1.2.3", _RELEASE_SHA],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert result.stderr == "release v1.2.3 has unexpected assets or draft state\n"
