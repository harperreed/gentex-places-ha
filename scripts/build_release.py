# Copyright (c) 2026 Gentex
# ABOUTME: Builds deterministic root-level HACS archives and SHA-256 checksums.
# ABOUTME: Verifies archive paths and bytes against the release source tree.
# ruff: noqa: INP001 - repository scripts are importable test targets without a package
"""Build and verify the Gentex PLACE HACS release archive."""

from __future__ import annotations

import argparse
import hashlib
import stat
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

_ROOT = Path(__file__).parents[1]
_ARCHIVE_TIME = (1980, 1, 1, 0, 0, 0)
_FILE_MODE = 0o100644 << 16
_SOURCE = Path("custom_components/gentex_place")


def _archive_files(root: Path) -> list[tuple[str, Path]]:
    """Return sorted source files mapped to root-level archive names."""
    source = root / _SOURCE
    files = [(path.relative_to(source).as_posix(), path) for path in source.rglob("*")]
    regular = [(name, path) for name, path in files if path.is_file()]
    license_path = root / "LICENSE"
    if any(path.is_symlink() for _, path in files) or license_path.is_symlink():
        message = "release source contains a symlink"
        raise ValueError(message)
    return sorted([*regular, ("LICENSE", license_path)])


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
        for name, source in expected.items():
            if release.read(name) != source.read_bytes():
                message = f"release archive byte mismatch: {name}"
                raise ValueError(message)


def build_release(root: Path, output: Path) -> Path:
    """Build, verify, and checksum one deterministic HACS release archive."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, source in _archive_files(root):
            info = zipfile.ZipInfo(name, _ARCHIVE_TIME)
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = _FILE_MODE
            info.create_system = 3
            archive.writestr(info, source.read_bytes())
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
