# Copyright (c) 2026 Gentex
# ABOUTME: Builds deterministic root-level HACS archives and SHA-256 checksums.
# ABOUTME: Verifies archive paths and bytes against the release source tree.
# ruff: noqa: INP001 - repository scripts are importable test targets without a package
"""Build and verify the Gentex PLACE HACS release archive."""

from __future__ import annotations

import argparse
import errno
import hashlib
import os
import stat
import subprocess
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

_ROOT = Path(__file__).parents[1]
_ARCHIVE_TIME = (1980, 1, 1, 0, 0, 0)
_FILE_MODE = 0o100644 << 16
_ZIP_SYSTEM = 3
_SOURCE = Path("custom_components/gentex_place")


def _tracked_release_paths(root: Path) -> list[tuple[str, Path]]:
    """Return sorted Git-indexed paths mapped to root-level archive names."""
    result = subprocess.run(  # noqa: S603 - fixed Git query, never a shell
        [  # noqa: S607 - Git must resolve from the build environment
            "git",
            "ls-files",
            "-z",
            "--",
            _SOURCE.as_posix(),
            "LICENSE",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        shell=False,
    )
    tracked = [Path(raw.decode()) for raw in result.stdout.split(b"\0") if raw]
    files: list[tuple[str, Path]] = []
    for relative in tracked:
        name = (
            "LICENSE"
            if relative == Path("LICENSE")
            else relative.relative_to(_SOURCE).as_posix()
        )
        files.append((name, relative))
    return sorted(files)


def _open_root(root: Path) -> int:
    """Open the repository root without following a link."""
    try:
        return os.open(
            root,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
    except OSError as error:
        if error.errno not in {errno.ELOOP, errno.ENOTDIR}:
            raise
        message = "release source path contains a symlink or non-directory: ."
        raise ValueError(message) from None


def _read_source(root_descriptor: int, name: str, relative: Path) -> bytes:
    """Snapshot one tracked regular file through no-follow descriptors."""
    directory_descriptor = os.dup(root_descriptor)
    try:
        for index, part in enumerate(relative.parts[:-1], start=1):
            try:
                child_descriptor = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=directory_descriptor,
                )
            except FileNotFoundError:
                message = f"tracked release member is missing: {name}"
                raise ValueError(message) from None
            except OSError as error:
                if error.errno not in {errno.ELOOP, errno.ENOTDIR}:
                    raise
                path = Path(*relative.parts[:index]).as_posix()
                message = (
                    f"release source path contains a symlink or non-directory: {path}"
                )
                raise ValueError(message) from None
            os.close(directory_descriptor)
            directory_descriptor = child_descriptor

        try:
            descriptor = os.open(
                relative.name,
                os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directory_descriptor,
            )
        except FileNotFoundError:
            message = f"tracked release member is missing: {name}"
            raise ValueError(message) from None
        except OSError as error:
            if error.errno != errno.ELOOP:
                raise
            message = f"tracked release member is not a regular file: {name}"
            raise ValueError(message) from None
    finally:
        os.close(directory_descriptor)

    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        message = f"tracked release member is not a regular file: {name}"
        raise ValueError(message)
    with os.fdopen(descriptor, "rb") as source_file:
        return source_file.read()


def _archive_files(root: Path) -> list[tuple[str, bytes]]:
    """Snapshot exact tracked regular files for one release operation."""
    root_descriptor = _open_root(root)
    try:
        root_status = os.fstat(root_descriptor)
        tracked = _tracked_release_paths(root)
        try:
            path_status = root.lstat()
        except FileNotFoundError:
            message = "release repository root changed during tracked-file enumeration"
            raise ValueError(message) from None
        if (
            not stat.S_ISDIR(path_status.st_mode)
            or path_status.st_dev != root_status.st_dev
            or path_status.st_ino != root_status.st_ino
        ):
            message = "release repository root changed during tracked-file enumeration"
            raise ValueError(message)
        return [
            (name, _read_source(root_descriptor, name, relative))
            for name, relative in tracked
        ]
    finally:
        os.close(root_descriptor)


def _validate_member(info: zipfile.ZipInfo) -> None:
    """Reject one unsafe archive member before reading its content."""
    name = info.filename
    if "\\" in name:
        message = f"release archive contains a backslash path: {name}"
        raise ValueError(message)
    if PurePosixPath(name).is_absolute() or PureWindowsPath(name).is_absolute():
        message = f"release archive contains an absolute path: {name}"
        raise ValueError(message)
    if ".." in PurePosixPath(name).parts:
        message = f"release archive contains path traversal: {name}"
        raise ValueError(message)
    mode = info.external_attr >> 16
    if info.is_dir() or stat.S_ISDIR(mode):
        message = f"release archive contains a directory: {name}"
        raise ValueError(message)
    if stat.S_ISLNK(mode):
        message = f"release archive contains a symlink: {name}"
        raise ValueError(message)
    if name.startswith(("gentex_place/", "custom_components/")):
        message = f"release archive contains a wrapper path: {name}"
        raise ValueError(message)


def _validate_metadata(info: zipfile.ZipInfo) -> None:
    """Require the canonical deterministic metadata for one member."""
    name = info.filename
    if info.compress_type != zipfile.ZIP_STORED:
        message = f"release archive member has wrong compression: {name}"
        raise ValueError(message)
    if info.date_time != _ARCHIVE_TIME:
        message = f"release archive member has wrong timestamp: {name}"
        raise ValueError(message)
    if info.create_system != _ZIP_SYSTEM:
        message = f"release archive member has wrong origin system: {name}"
        raise ValueError(message)
    if info.external_attr != _FILE_MODE:
        message = f"release archive member has wrong mode: {name}"
        raise ValueError(message)


def verify_release(root: Path, archive: Path) -> None:
    """Verify that an archive contains only exact, safe release source bytes."""
    expected = dict(_archive_files(root))
    with zipfile.ZipFile(archive) as release:
        infos = release.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            message = "release archive contains duplicate members"
            raise ValueError(message)
        for info in infos:
            _validate_member(info)

        actual_names = set(names)
        expected_names = set(expected)
        missing = sorted(expected_names - actual_names)
        if missing:
            message = f"release archive is missing members: {', '.join(missing)}"
            raise ValueError(message)
        extra = sorted(actual_names - expected_names)
        if extra:
            message = f"release archive contains extra members: {', '.join(extra)}"
            raise ValueError(message)
        if names != sorted(expected_names):
            message = "release archive has wrong member order"
            raise ValueError(message)
        for info in infos:
            _validate_metadata(info)
        for name, source_bytes in expected.items():
            if release.read(name) != source_bytes:
                message = f"release archive byte mismatch: {name}"
                raise ValueError(message)


def build_release(root: Path, output: Path) -> Path:
    """Build, verify, and checksum one deterministic HACS release archive."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, source_bytes in _archive_files(root):
            info = zipfile.ZipInfo(name, _ARCHIVE_TIME)
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = _FILE_MODE
            info.create_system = _ZIP_SYSTEM
            archive.writestr(info, source_bytes)
    verify_release(root, output)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    checksum = output.with_suffix(output.suffix + ".sha256")
    checksum.write_text(f"{digest}  {output.name}\n")
    return checksum


def main() -> None:
    """Build a release archive or verify an existing archive."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=_ROOT,
        help="release source root (default: repository root)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="archive output (default: ROOT/dist/gentex_place.zip)",
    )
    parser.add_argument("--verify", type=Path, metavar="ARCHIVE")
    args = parser.parse_args()
    try:
        if args.verify is not None:
            verify_release(args.root, args.verify)
            print(args.verify)  # noqa: T201 - required CLI output
            return
        output = args.output or args.root / "dist/gentex_place.zip"
        checksum = build_release(args.root, output)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        parser.error(str(error))
    print(output)  # noqa: T201 - required CLI output
    print(checksum)  # noqa: T201 - required CLI output


if __name__ == "__main__":
    main()
