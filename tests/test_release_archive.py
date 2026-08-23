# Copyright (c) 2026 Gentex
# ABOUTME: Verifies deterministic, root-level HACS release archives and checksums.
# ABOUTME: Rejects unsafe or inexact ZIP members before packaging reaches users.
"""Release archive build and verification tests."""

from __future__ import annotations

import hashlib
import importlib
import subprocess
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

if TYPE_CHECKING:
    from types import ModuleType

_ROOT = Path(__file__).parents[1]
_SOURCE = _ROOT / "custom_components/gentex_place"
_BUILDER = _ROOT / "scripts/build_release.py"
_FILE_MODE = 0o100644
_ARCHIVE_TIME = (1980, 1, 1, 0, 0, 0)
_ZIP_SYSTEM = 3

BuildRelease = Callable[[Path, Path], Path]
VerifyRelease = Callable[[Path, Path], None]


def _release_functions() -> tuple[BuildRelease, VerifyRelease]:
    """Load the release interfaces after proving the builder exists."""
    assert _BUILDER.is_file(), "scripts/build_release.py is missing"
    module: ModuleType = importlib.import_module("scripts.build_release")
    return (
        cast("BuildRelease", module.build_release),
        cast("VerifyRelease", module.verify_release),
    )


def _tracked_members() -> dict[str, bytes]:
    """Return the tracked integration and license bytes by archive name."""
    result = subprocess.run(
        [  # noqa: S607 - Git must resolve from the test environment
            "git",
            "ls-files",
            "-z",
            "--",
            "custom_components/gentex_place",
            "LICENSE",
        ],
        cwd=_ROOT,
        check=True,
        capture_output=True,
    )
    paths = [Path(raw.decode()) for raw in result.stdout.split(b"\0") if raw]
    members: dict[str, bytes] = {}
    for relative in paths:
        source = _ROOT / relative
        if not source.is_file():
            continue
        name = (
            "LICENSE"
            if relative == Path("LICENSE")
            else relative.relative_to("custom_components/gentex_place").as_posix()
        )
        members[name] = source.read_bytes()
    return members


def _write_members(path: Path, members: dict[str, bytes]) -> None:
    """Write a small ZIP fixture with the supplied members."""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)


def test_build_release_is_reproducible_and_has_exact_root_members(
    tmp_path: Path,
) -> None:
    build_release, _ = _release_functions()
    first = tmp_path / "first/gentex_place.zip"
    second = tmp_path / "second/gentex_place.zip"

    first_checksum = build_release(_ROOT, first)
    second_checksum = build_release(_ROOT, second)

    assert first.read_bytes() == second.read_bytes()
    assert first_checksum.read_text() == second_checksum.read_text()
    digest = hashlib.sha256(first.read_bytes()).hexdigest()
    assert first_checksum.read_text() == f"{digest}  gentex_place.zip\n"

    expected = _tracked_members()
    with zipfile.ZipFile(first) as archive:
        names = archive.namelist()
        assert names == sorted(expected)
        assert "manifest.json" in names
        assert "LICENSE" in names
        assert "brand/icon.png" in names
        assert "brand/icon@2x.png" in names
        assert not any(name.startswith("gentex_place/") for name in names)
        assert not any(name.startswith("custom_components/") for name in names)
        assert archive.read("LICENSE") == (_ROOT / "LICENSE").read_bytes()
        for info in archive.infolist():
            assert info.date_time == _ARCHIVE_TIME
            assert info.compress_type == zipfile.ZIP_STORED
            assert info.create_system == _ZIP_SYSTEM
            assert info.external_attr >> 16 == _FILE_MODE
            assert not info.is_dir()
            assert archive.read(info.filename) == expected[info.filename]


@pytest.mark.parametrize(
    ("name", "mode", "message"),
    [
        pytest.param("../escape", None, "traversal", id="traversal"),
        pytest.param("/absolute", None, "absolute", id="absolute"),
        pytest.param("brand\\icon.png", None, "backslash", id="backslash"),
        pytest.param("brand/", None, "directory", id="directory"),
        pytest.param("brand", 0o040755, "directory", id="mode-directory"),
        pytest.param("link", 0o120777, "symlink", id="symlink"),
        pytest.param("gentex_place/manifest.json", None, "wrapper", id="wrapper"),
    ],
)
def test_verify_release_rejects_unsafe_members(
    tmp_path: Path,
    name: str,
    mode: int | None,
    message: str,
) -> None:
    _, verify_release = _release_functions()
    archive_path = tmp_path / "hostile.zip"
    info = zipfile.ZipInfo(name)
    if mode is not None:
        info.create_system = 3
        info.external_attr = mode << 16
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(info, b"hostile")

    with pytest.raises(ValueError, match=message):
        verify_release(_ROOT, archive_path)


def test_verify_release_rejects_duplicate_members(tmp_path: Path) -> None:
    _, verify_release = _release_functions()
    archive_path = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("manifest.json", b"first")
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr("manifest.json", b"second")

    with pytest.raises(ValueError, match="duplicate"):
        verify_release(_ROOT, archive_path)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        pytest.param("missing", "missing", id="missing"),
        pytest.param("extra", "extra", id="extra"),
        pytest.param("mismatch", "byte mismatch", id="byte-mismatch"),
    ],
)
def test_verify_release_rejects_inexact_members(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    _, verify_release = _release_functions()
    archive_path = tmp_path / "inexact.zip"
    members = _tracked_members()
    if mutation == "missing":
        del members["manifest.json"]
    elif mutation == "extra":
        members["unexpected.txt"] = b"extra"
    else:
        members["manifest.json"] = b"wrong bytes"
    _write_members(archive_path, members)

    with pytest.raises(ValueError, match=message):
        verify_release(_ROOT, archive_path)


def test_build_release_rejects_source_symlinks(tmp_path: Path) -> None:
    build_release, _ = _release_functions()
    source = tmp_path / "custom_components/gentex_place"
    source.mkdir(parents=True)
    (tmp_path / "LICENSE").write_text("license")
    target = source / "manifest.json"
    target.write_text("{}")
    (source / "linked.json").symlink_to(target)

    with pytest.raises(ValueError, match="source contains a symlink"):
        build_release(tmp_path, tmp_path / "release.zip")


def test_release_cli_builds_and_verifies_an_archive(tmp_path: Path) -> None:
    assert _BUILDER.is_file(), "scripts/build_release.py is missing"
    archive = tmp_path / "gentex_place.zip"

    build = subprocess.run(  # noqa: S603 - exact checked Python and repository script
        [
            sys.executable,
            str(_BUILDER),
            "--root",
            str(_ROOT),
            "--output",
            str(archive),
        ],
        cwd=_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert build.returncode == 0
    assert build.stderr == ""
    assert build.stdout == f"{archive}\n{archive}.sha256\n"

    verify = subprocess.run(  # noqa: S603 - exact checked Python and repository script
        [sys.executable, str(_BUILDER), "--root", str(_ROOT), "--verify", str(archive)],
        cwd=_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert verify.returncode == 0
    assert verify.stderr == ""
    assert verify.stdout == f"{archive}\n"
