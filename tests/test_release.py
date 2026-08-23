# Copyright (c) 2026 Harper Reed
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
_REPOSITORY_URL = "https://github.com/harperreed/gentex-places-ha"
_HA_BACKUP_URL = "https://www.home-assistant.io/common-tasks/general/#backups"
_HACS_UPDATE_URL = "https://hacs.xyz/docs/use/update/"
_V1_DOCUMENT_CONTRACTS = (
    (
        Path("README.md"),
        "does not move a published tag or replace its zip asset",
    ),
    (
        Path("docs/releases/v1.0.0.md"),
        "published tags and assets stay unchanged",
    ),
)


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


def _normalized(document: str) -> str:
    """Collapse prose whitespace while keeping meaningful contract text."""
    return " ".join(document.split())


def _headings(document: str) -> set[str]:
    """Return normalized level-two Markdown headings."""
    return {
        match.group(1).casefold()
        for match in re.finditer(r"^##\s+(.+)$", document, flags=re.MULTILINE)
    }


def _section(document: str, heading_keyword: str) -> str:
    """Return one normalized Markdown section selected by heading meaning."""
    section = re.search(
        rf"^##\s+[^\n]*{re.escape(heading_keyword)}[^\n]*\n"
        r"(?P<body>.*?)(?=^##\s+|\Z)",
        document,
        flags=re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    if section is None:
        msg = f"missing level-two Markdown section: {heading_keyword.casefold()}"
        raise AssertionError(msg)
    return _normalized(section.group("body")).casefold()


def _require_document_contract(condition: object, message: str) -> None:
    """Raise one stable failure for a missing documentation contract."""
    if not condition:
        raise AssertionError(message)


def _assert_v1_hacs_lifecycle_contract(
    document: str,
    *,
    immutable_rule: str,
) -> None:
    """Require meaningful v1 HACS install, upgrade, and recovery guidance."""
    install = _section(document, "install")
    upgrade = _section(document, "upgrade")
    rollback = _section(document, "rollback")

    _require_document_contract(
        re.search(
            r"choose \*\*custom repositories\*\*.*"
            r"with the type \*\*integration\*\*.*"
            r"choose \*\*download\*\*.*"
            r"under \*\*need a different version\?\*\*.*"
            r"choose \*\*download\*\*",
            install,
        ),
        "install section must include ordered HACS install controls",
    )
    _require_document_contract(
        re.search(
            r"\*\*download backup\*\*.*"
            r"\*\*redownload\*\*.*"
            r"\*\*need a different version\?\*\*.*"
            r"\*\*download\*\*",
            upgrade,
        ),
        "upgrade section must include backup and HACS controls",
    )
    _require_document_contract(
        re.search(
            r"`v1\.0\.0` is (?:this repository's|the) first release, so hacs has "
            r"no earlier (?:gentex place )?release to select",
            rollback,
        ),
        "rollback section must state v1.0.0 has no earlier release",
    )
    _require_document_contract(
        (
            "off-device **download backup** copy remains available for wider "
            "home assistant recovery"
        )
        in rollback,
        "rollback section must retain the off-device backup",
    )
    _require_document_contract(
        re.search(
            r"for (?:releases after `v1\.0\.0`|later releases), hacs "
            r"\*\*redownload\*\* (?:can select|may offer) an earlier published "
            r"version under \*\*need a different version\?\*\*",
            rollback,
        ),
        "rollback section must distinguish later-version selection",
    )
    _require_document_contract(
        immutable_rule.casefold() in rollback,
        "rollback section must preserve published tags and assets",
    )
    _require_document_contract(
        "end-to-end" not in _normalized(document).casefold(),
        "documentation must not claim HACS end-to-end coverage",
    )


def test_section_includes_nested_markdown_headings() -> None:
    document = """## Install
Before
### Detail
After
## Upgrade
Next
"""

    assert _section(document, "install") == "before ### detail after"


def test_flattened_document_reports_section_failure_not_contract_mutation() -> None:
    relative_path, immutable_rule = _V1_DOCUMENT_CONTRACTS[0]
    document = (_ROOT / relative_path).read_text()
    _assert_v1_hacs_lifecycle_contract(document, immutable_rule=immutable_rule)

    with pytest.raises(
        AssertionError,
        match=r"^missing level-two Markdown section: install$",
    ):
        _assert_v1_hacs_lifecycle_contract(
            _normalized(document),
            immutable_rule=immutable_rule,
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
    version = detect_release("HEAD", "HEAD", _ROOT).current

    result = _run_checker("HEAD", "HEAD", "--github-output", str(github_output))

    assert result.returncode == 0
    assert result.stdout == (
        f'{{"previous": "{version}", "current": "{version}", "required": false}}\n'
    )
    assert result.stderr == ""
    assert github_output.read_text() == (f"release_required=false\nversion={version}\n")


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


def test_v1_release_notes_cover_the_public_distribution_contract() -> None:
    notes_path = _ROOT / "docs/releases/v1.0.0.md"

    assert notes_path.is_file()
    notes = notes_path.read_text()
    normalized_notes = _normalized(notes)
    for required in (
        "# Gentex PLACE v1.0.0",
        "read-only",
        "HACS",
        "d92f07ecc9b7e66162d60d4a66cc07366543b631",
        "gentex_place.zip",
        "gentex_place.zip.sha256",
        "Home Shield",
        "MIT",
    ):
        assert required in notes

    assert _REPOSITORY_URL in notes
    for required_feature in (
        "cloud-push",
        "five-minute health refresh",
        "device discovery",
        "alarms",
        "telemetry",
        "diagnostics",
        "MFA",
        "reauthentication",
        "multiple-account support",
    ):
        assert required_feature in normalized_notes
    assert "not in the HACS default store" in normalized_notes
    assert "not a Home Assistant Core integration" in normalized_notes
    assert "does not publish the SDK to PyPI" in normalized_notes
    assert "end-to-end" not in normalized_notes.casefold()


def test_readme_covers_v1_install_upgrade_and_rollback() -> None:
    readme = (_ROOT / "README.md").read_text()
    normalized_readme = _normalized(readme)
    release_language = normalized_readme.casefold()

    assert "`v1.0.0` is the first stable version" in release_language
    assert f"{_REPOSITORY_URL}/releases" in readme
    assert "before publication" in release_language
    assert "after publication" in release_language
    assert "release candidate" not in release_language
    assert "gates remain" not in release_language
    assert _REPOSITORY_URL in readme
    assert "not in the HACS default store" in normalized_readme
    assert "blocked on licensed brand-art" not in normalized_readme
    assert {"installation", "upgrade", "rollback"} <= _headings(readme)


@pytest.mark.parametrize(
    "relative_path",
    [Path("README.md"), Path("docs/releases/v1.0.0.md")],
)
def test_v1_upgrade_has_a_first_release_backup_and_restore_path(
    relative_path: Path,
) -> None:
    document = (_ROOT / relative_path).read_text()
    upgrade = _section(document, "upgrade")
    rollback = _section(document, "rollback")

    assert _HA_BACKUP_URL in document
    assert _HACS_UPDATE_URL in document
    assert "settings > system > backups" in upgrade
    for control in ("backup now", "manual backup", "create backup"):
        assert control in upgrade
    assert "show all backups" in upgrade
    assert "download backup" in upgrade
    assert "backup emergency kit" in upgrade
    assert "`config`" in upgrade
    assert "config entries" in upgrade
    assert "restore" in rollback
    assert "higher patch" in rollback
    assert any("install" in heading for heading in _headings(document))
    assert any("upgrade" in heading for heading in _headings(document))
    assert any("rollback" in heading for heading in _headings(document))


@pytest.mark.parametrize(("relative_path", "immutable_rule"), _V1_DOCUMENT_CONTRACTS)
def test_v1_hacs_lifecycle_contract(
    relative_path: Path,
    immutable_rule: str,
) -> None:
    document = (_ROOT / relative_path).read_text()

    _assert_v1_hacs_lifecycle_contract(document, immutable_rule=immutable_rule)


@pytest.mark.parametrize(("relative_path", "immutable_rule"), _V1_DOCUMENT_CONTRACTS)
@pytest.mark.parametrize(
    ("required", "replacement", "expected_failure"),
    [
        (
            "Custom repositories",
            "Repository settings",
            "install section must include ordered HACS install controls",
        ),
        (
            "**Integration**",
            "**Plugin**",
            "install section must include ordered HACS install controls",
        ),
        (
            "**Download**",
            "**Fetch**",
            "install section must include ordered HACS install controls",
        ),
        (
            "**Redownload**",
            "**Reinstall**",
            "upgrade section must include backup and HACS controls",
        ),
        (
            "**Need a different version?**",
            "**Choose version**",
            "install section must include ordered HACS install controls",
        ),
        (
            "no earlier",
            "an earlier",
            "rollback section must state v1.0.0 has no earlier release",
        ),
        (
            "**Download backup**",
            "**Keep backup**",
            "upgrade section must include backup and HACS controls",
        ),
        (
            "earlier published version",
            "current published version",
            "rollback section must distinguish later-version selection",
        ),
    ],
)
def test_v1_hacs_lifecycle_contract_rejects_missing_guidance(
    relative_path: Path,
    immutable_rule: str,
    required: str,
    replacement: str,
    expected_failure: str,
) -> None:
    document = (_ROOT / relative_path).read_text()
    _assert_v1_hacs_lifecycle_contract(document, immutable_rule=immutable_rule)

    required_pattern = re.escape(required).replace(r"\ ", r"\s+")
    mutated, replacements = re.subn(
        required_pattern,
        replacement,
        document,
        flags=re.IGNORECASE,
    )
    assert replacements > 0

    with pytest.raises(
        AssertionError,
        match=rf"^{re.escape(expected_failure)}$",
    ):
        _assert_v1_hacs_lifecycle_contract(mutated, immutable_rule=immutable_rule)


@pytest.mark.parametrize(("relative_path", "immutable_rule"), _V1_DOCUMENT_CONTRACTS)
def test_v1_hacs_lifecycle_contract_rejects_mutable_release_guidance(
    relative_path: Path,
    immutable_rule: str,
) -> None:
    document = (_ROOT / relative_path).read_text()
    _assert_v1_hacs_lifecycle_contract(document, immutable_rule=immutable_rule)

    immutable_pattern = re.escape(immutable_rule).replace(r"\ ", r"\s+")
    mutated, replacements = re.subn(
        immutable_pattern,
        "published release files may be replaced",
        document,
        flags=re.IGNORECASE,
    )
    assert replacements == 1

    with pytest.raises(
        AssertionError,
        match=r"^rollback section must preserve published tags and assets$",
    ):
        _assert_v1_hacs_lifecycle_contract(mutated, immutable_rule=immutable_rule)


def test_readme_states_detection_and_publication_as_separate_release_steps() -> None:
    readme = _normalized((_ROOT / "README.md").read_text())

    for contract_part in (
        "every push to `main`",
        "detect",
        "publishes only",
        "both version sources",
        "increase together",
    ):
        assert contract_part in readme
