# Copyright (c) 2026 Harper Reed
# ABOUTME: Verifies packaged-runner setup failures stop and preserve useful logs.
# ABOUTME: Uses a controlled executable boundary while exercising the real POSIX shell.
"""Shell lifecycle tests for the isolated packaged-system runner."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_ROOT = Path(__file__).parents[1]
_RUNNER = _ROOT / "tests/system/run.sh"
_EARLY_FAILURE = 23


def test_runner_stops_at_early_setup_failure_and_prints_preserved_log(
    tmp_path: Path,
) -> None:
    """Require an early tool failure to survive later successful stub behavior."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "run" ] && [ "$2" = "python" ]; then\n'
        "    shift 2\n"
        '    exec /usr/bin/python3 "$@"\n'
        "fi\n"
        'if [ "$1" = "venv" ]; then\n'
        '    mkdir -p "$4/bin"\n'
        "    printf '#!/bin/sh\\nexit 0\\n' >\"$4/bin/python\"\n"
        '    chmod +x "$4/bin/python"\n'
        '    printf "controlled early setup failure\\n" >&2\n'
        f"    exit {_EARLY_FAILURE}\n"
        "fi\n"
        "exit 0\n"
    )
    uv.chmod(0o755)
    environment = {
        "LANG": "C",
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "TMPDIR": str(tmp_path),
    }

    result = subprocess.run(  # noqa: S603 - fixed repository executable under test
        [str(_RUNNER)],
        cwd=_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == _EARLY_FAILURE
    match = re.fullmatch(
        r"Packaged system test failed; full log and temp state: (.+)\n",
        result.stderr,
    )
    assert match is not None
    log_path = Path(match.group(1))
    assert log_path.is_file()
    assert "controlled early setup failure" in log_path.read_text()


def test_runner_stops_when_packaged_working_directory_disappears(
    tmp_path: Path,
) -> None:
    """Preserve a pre-pytest cd failure instead of testing the source checkout."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "run" ] && [ "$2" = "python" ]; then\n'
        "    shift 2\n"
        '    exec /usr/bin/python3 "$@"\n'
        "fi\n"
        'if [ "$1" = "venv" ]; then\n'
        '    mkdir -p "$4/bin"\n'
        "    printf '#!/bin/sh\\nexit 0\\n' >\"$4/bin/python\"\n"
        '    chmod +x "$4/bin/python"\n'
        "    exit 0\n"
        "fi\n"
        'if [ "$1" = "pip" ]; then\n'
        '    test_root=$(dirname "$(dirname "$(dirname "$4")")")\n'
        '    rm -rf "$test_root/package"\n'
        '    printf "controlled package removal\\n"\n'
        "    exit 0\n"
        "fi\n"
        "exit 0\n"
    )
    uv.chmod(0o755)
    environment = {
        "LANG": "C",
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "TMPDIR": str(tmp_path),
    }

    result = subprocess.run(  # noqa: S603 - fixed repository executable under test
        [str(_RUNNER)],
        cwd=_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    match = re.fullmatch(
        r"Packaged system test failed; full log and temp state: (.+)\n",
        result.stderr,
    )
    assert match is not None
    log_path = Path(match.group(1))
    assert log_path.is_file()
    package_root = log_path.parent / "package"
    cd_result = subprocess.run(  # noqa: S603 - fixed system shell
        ["/bin/sh", "-c", 'cd "$1"', "sh", str(package_root)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert cd_result.returncode != 0
    assert result.returncode == cd_result.returncode
    log = log_path.read_text()
    assert "controlled package removal" in log
    assert str(package_root) in log


def test_runner_builds_and_extracts_the_release_before_packaged_tests() -> None:
    """Require the system run to exercise the HACS ZIP instead of source files."""
    runner = _RUNNER.read_text()
    build = 'uv run python "$source_root/scripts/build_release.py"'
    extract = 'uv run python -m zipfile -e "$test_root/release/gentex_place.zip"'
    packaged_target = '"$package_root/custom_components/gentex_place"'
    pytest = '"$venv_root/bin/python" -m pytest'

    assert build in runner
    assert extract in runner
    assert packaged_target in runner
    assert "cp -R" not in runner
    assert runner.index(build) < runner.index(extract) < runner.index(pytest)
