# Copyright (c) 2026 Gentex
# ABOUTME: Verifies deterministic, root-level HACS release archives and checksums.
# ABOUTME: Rejects unsafe or inexact ZIP members before packaging reaches users.
"""Release archive build and verification tests."""

from __future__ import annotations

import hashlib
import importlib
import os
import shutil
import stat
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
TrackedReleasePaths = Callable[[Path], list[tuple[str, Path]]]
OpenRoot = Callable[[Path], int]
ReadSource = Callable[[int, str, Path], bytes]


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
        assert stat.S_ISREG(source.stat(follow_symlinks=False).st_mode), (
            f"tracked release member is not a regular file: {relative}"
        )
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
            info = zipfile.ZipInfo(name, _ARCHIVE_TIME)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = _ZIP_SYSTEM
            info.external_attr = _FILE_MODE << 16
            archive.writestr(info, content)


def _release_repository(tmp_path: Path, name: str = "repository") -> Path:
    """Create a minimal Git-indexed release source tree."""
    root = tmp_path / name
    source = root / "custom_components/gentex_place"
    source.mkdir(parents=True)
    (root / "LICENSE").write_text("license")
    (source / "manifest.json").write_text("{}")
    subprocess.run(  # noqa: S603 - exact controlled Git test command
        [  # noqa: S607 - Git must resolve from the test environment
            "git",
            "init",
            "--quiet",
            str(root),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [  # noqa: S607 - Git must resolve from the test environment
            "git",
            "add",
            "--",
            "custom_components/gentex_place",
            "LICENSE",
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return root


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


def test_build_release_excludes_untracked_integration_files(tmp_path: Path) -> None:
    build_release, _ = _release_functions()
    root = _release_repository(tmp_path)
    secret = root / "custom_components/gentex_place/credentials.json"
    secret.write_text('{"token":"do not package"}')
    archive_path = tmp_path / "gentex_place.zip"

    build_release(root, archive_path)

    with zipfile.ZipFile(archive_path) as archive:
        assert archive.namelist() == ["LICENSE", "manifest.json"]
        assert "credentials.json" not in archive.namelist()


def test_build_release_rejects_missing_tracked_member(tmp_path: Path) -> None:
    build_release, _ = _release_functions()
    root = _release_repository(tmp_path)
    (root / "custom_components/gentex_place/manifest.json").unlink()

    with pytest.raises(ValueError, match="tracked release member is missing"):
        build_release(root, tmp_path / "gentex_place.zip")


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


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        pytest.param("order", "member order", id="member-order"),
        pytest.param("compression", "compression", id="compression"),
        pytest.param("timestamp", "timestamp", id="timestamp"),
        pytest.param("create-system", "origin system", id="create-system"),
        pytest.param("mode", "mode", id="mode"),
    ],
)
def test_verify_release_rejects_metadata_mutations(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    _, verify_release = _release_functions()
    archive_path = tmp_path / "metadata.zip"
    members = _tracked_members()
    names = sorted(members, reverse=mutation == "order")
    with zipfile.ZipFile(archive_path, "w") as archive:
        for index, name in enumerate(names):
            info = zipfile.ZipInfo(name, _ARCHIVE_TIME)
            info.compress_type = (
                zipfile.ZIP_DEFLATED
                if mutation == "compression" and index == 0
                else zipfile.ZIP_STORED
            )
            if mutation == "timestamp" and index == 0:
                info.date_time = (1980, 1, 2, 0, 0, 0)
            info.create_system = (
                0 if mutation == "create-system" and index == 0 else _ZIP_SYSTEM
            )
            mode = 0o100600 if mutation == "mode" and index == 0 else _FILE_MODE
            info.external_attr = mode << 16
            archive.writestr(info, members[name])

    with pytest.raises(ValueError, match=message):
        verify_release(_ROOT, archive_path)


def test_build_release_rejects_tracked_file_swapped_for_symlink(
    tmp_path: Path,
) -> None:
    build_release, _ = _release_functions()
    root = _release_repository(tmp_path)
    manifest = root / "custom_components/gentex_place/manifest.json"
    target = root / "untracked-secret.json"
    target.write_text('{"credential":"secret"}')
    manifest.unlink()
    manifest.symlink_to(target)

    with pytest.raises(
        ValueError, match="tracked release member is not a regular file"
    ):
        build_release(root, tmp_path / "release.zip")


def test_build_release_rejects_symlinked_integration_root(tmp_path: Path) -> None:
    build_release, _ = _release_functions()
    root = _release_repository(tmp_path)
    source = root / "custom_components/gentex_place"
    target = root / "real-component"
    source.rename(target)
    source.symlink_to(target, target_is_directory=True)

    with pytest.raises(ValueError, match="release source path contains a symlink"):
        build_release(root, tmp_path / "release.zip")


def test_source_reads_stay_anchored_to_the_open_repository_root(
    tmp_path: Path,
) -> None:
    root = _release_repository(tmp_path)
    module: ModuleType = importlib.import_module("scripts.build_release")
    tracked_release_paths = cast(
        "TrackedReleasePaths",
        module._tracked_release_paths,  # noqa: SLF001 - security boundary seam
    )
    open_root = cast(
        "OpenRoot",
        module._open_root,  # noqa: SLF001 - security boundary seam
    )
    read_source = cast(
        "ReadSource",
        module._read_source,  # noqa: SLF001 - security boundary seam
    )
    tracked = dict(tracked_release_paths(root))
    root_descriptor = open_root(root)
    moved_root = tmp_path / "moved-repository"
    root.rename(moved_root)
    replacement_source = root / "custom_components/gentex_place"
    replacement_source.mkdir(parents=True)
    (replacement_source / "manifest.json").write_text("replacement")

    try:
        content = read_source(
            root_descriptor,
            "manifest.json",
            tracked["manifest.json"],
        )
    finally:
        os.close(root_descriptor)

    assert content == b"{}"


def test_build_release_rejects_repository_swap_during_git_enumeration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_release, _ = _release_functions()
    root = _release_repository(tmp_path)
    replacement = _release_repository(tmp_path, "replacement-repository")
    replacement_manifest = replacement / "custom_components/gentex_place/manifest.json"
    replacement_manifest.write_text("replacement")
    moved_root = tmp_path / "moved-repository"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    git_shim = bin_dir / "git"
    git_shim.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        'if [ -d "$REPLACEMENT_ROOT" ]; then\n'
        '    mv "$REPOSITORY_ROOT" "$MOVED_ROOT"\n'
        '    mv "$REPLACEMENT_ROOT" "$REPOSITORY_ROOT"\n'
        "fi\n"
        'exec "$REAL_GIT" "$@"\n'
    )
    git_shim.chmod(0o700)
    real_git = shutil.which("git")
    assert real_git is not None
    monkeypatch.setenv("REAL_GIT", real_git)
    monkeypatch.setenv("REPOSITORY_ROOT", str(root))
    monkeypatch.setenv("MOVED_ROOT", str(moved_root))
    monkeypatch.setenv("REPLACEMENT_ROOT", str(replacement))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    archive = tmp_path / "release.zip"

    with pytest.raises(ValueError, match="repository root changed"):
        build_release(root, archive)

    if archive.exists():
        with zipfile.ZipFile(archive) as release:
            assert all(
                release.read(name) != b"replacement" for name in release.namelist()
            )


def test_build_release_rejects_tracked_fifo_without_blocking(tmp_path: Path) -> None:
    root = _release_repository(tmp_path)
    manifest = root / "custom_components/gentex_place/manifest.json"
    manifest.unlink()
    os.mkfifo(manifest)
    archive = tmp_path / "release.zip"
    process = subprocess.Popen(  # noqa: S603 - exact checked Python and script
        [
            sys.executable,
            str(_BUILDER),
            "--root",
            str(root),
            "--output",
            str(archive),
        ],
        cwd=_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        stdout, stderr = process.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        pytest.fail("release builder blocked while opening a tracked FIFO")

    assert process.returncode != 0
    assert stdout == ""
    assert "tracked release member is not a regular file: manifest.json" in stderr


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
