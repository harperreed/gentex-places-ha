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
import tempfile
import zipfile
from contextlib import suppress
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


def _read_source_entry(
    root_descriptor: int,
    name: str,
    relative: Path,
) -> tuple[bytes, tuple[int, int]]:
    """Snapshot one tracked regular file and its filesystem identity."""
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

    source_status = os.fstat(descriptor)
    if not stat.S_ISREG(source_status.st_mode):
        os.close(descriptor)
        message = f"tracked release member is not a regular file: {name}"
        raise ValueError(message)
    with os.fdopen(descriptor, "rb") as source_file:
        return source_file.read(), (source_status.st_dev, source_status.st_ino)


def _read_source(root_descriptor: int, name: str, relative: Path) -> bytes:
    """Snapshot one tracked regular file through no-follow descriptors."""
    return _read_source_entry(root_descriptor, name, relative)[0]


def _archive_snapshot(
    root: Path,
) -> tuple[list[tuple[str, bytes]], frozenset[tuple[int, int]]]:
    """Snapshot exact tracked files and the identities they occupied."""
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
        entries = [
            (name, *_read_source_entry(root_descriptor, name, relative))
            for name, relative in tracked
        ]
        files = [(name, source_bytes) for name, source_bytes, _ in entries]
        identities = frozenset(identity for _, _, identity in entries)
        return files, identities
    finally:
        os.close(root_descriptor)


def _archive_files(root: Path) -> list[tuple[str, bytes]]:
    """Snapshot exact tracked regular files for one release operation."""
    return _archive_snapshot(root)[0]


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


def _verify_archive(archive: Path, expected: dict[str, bytes]) -> None:
    """Verify one archive against an already captured source snapshot."""
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


def verify_release(root: Path, archive: Path) -> None:
    """Verify that an archive contains only exact, safe release source bytes."""
    _verify_archive(archive, dict(_archive_files(root)))


def _validate_final_paths(
    output: Path,
    checksum: Path,
    source_identities: frozenset[tuple[int, int]],
) -> None:
    """Reject unsafe final paths without following their final components."""
    identities: list[tuple[int, int]] = []
    for final_path in (output, checksum):
        try:
            final_status = final_path.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(final_status.st_mode):
            message = f"release output path is a symlink: {final_path}"
            raise ValueError(message)
        if not stat.S_ISREG(final_status.st_mode):
            message = f"release output path is not a regular file: {final_path}"
            raise ValueError(message)
        identity = (final_status.st_dev, final_status.st_ino)
        if identity in source_identities:
            message = (
                f"release output path aliases tracked release source: {final_path}"
            )
            raise ValueError(message)
        identities.append(identity)
    if len(identities) != len(set(identities)):
        message = "release archive and checksum paths alias the same file"
        raise ValueError(message)


def _new_stage(parent: Path, final_name: str) -> tuple[int, Path]:
    """Create one private staging file beside its final destination."""
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{final_name}.",
        suffix=".tmp",
        dir=parent,
    )
    return descriptor, Path(raw_path)


def _remove_stage(stage: Path | None) -> None:
    """Remove only a staging path created by this process."""
    if stage is not None:
        with suppress(FileNotFoundError):
            stage.unlink()


def build_release(root: Path, output: Path) -> Path:
    """Build, verify, and checksum one deterministic HACS release archive."""
    files, source_identities = _archive_snapshot(root)
    expected = dict(files)
    checksum = output.with_suffix(output.suffix + ".sha256")
    output.parent.mkdir(parents=True, exist_ok=True)
    _validate_final_paths(output, checksum, source_identities)
    staged_archive: Path | None = None
    staged_checksum: Path | None = None
    try:
        archive_descriptor, staged_archive = _new_stage(output.parent, output.name)
        with os.fdopen(archive_descriptor, "w+b") as archive_file:
            with zipfile.ZipFile(
                archive_file,
                "w",
                compression=zipfile.ZIP_STORED,
            ) as archive:
                for name, source_bytes in files:
                    info = zipfile.ZipInfo(name, _ARCHIVE_TIME)
                    info.compress_type = zipfile.ZIP_STORED
                    info.external_attr = _FILE_MODE
                    info.create_system = _ZIP_SYSTEM
                    archive.writestr(info, source_bytes)
            archive_file.flush()
            os.fsync(archive_file.fileno())
        _verify_archive(staged_archive, expected)
        digest = hashlib.sha256(staged_archive.read_bytes()).hexdigest()

        checksum_descriptor, staged_checksum = _new_stage(
            output.parent,
            checksum.name,
        )
        with os.fdopen(checksum_descriptor, "w", encoding="utf-8") as checksum_file:
            checksum_file.write(f"{digest}  {output.name}\n")
            checksum_file.flush()
            os.fsync(checksum_file.fileno())

        _validate_final_paths(output, checksum, source_identities)
        staged_checksum.replace(checksum)
        staged_checksum = None
        staged_archive.replace(output)
        staged_archive = None
    finally:
        _remove_stage(staged_checksum)
        _remove_stage(staged_archive)
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
