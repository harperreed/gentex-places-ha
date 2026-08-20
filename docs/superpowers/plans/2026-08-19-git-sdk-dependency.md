<!-- ABOUTME: Plans publication and exact Git pinning of the forked PLACE SDK. -->
<!-- ABOUTME: Replaces the local sibling dependency without publishing to PyPI. -->
# Git SDK Dependency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the HACS custom integration resolve PLACE SDK `0.3.0` from Doctor Biz's public GitHub fork at one immutable commit instead of PyPI or a sibling checkout.

**Architecture:** Publish the already-reviewed SDK `master` commit, then use one exact PEP 508 Git requirement in the Home Assistant manifest and development dependency group. Repository contract tests, lockfile assertions, and a clean-install script prove that both direct and locked installs fetch the same public commit.

**Tech Stack:** Git, GitHub HTTPS, Python 3.14.2, uv 0.9.25, pytest, TOML/JSON metadata, POSIX shell.

**Lock representation decision (2026-08-19):** Doctor Biz chose uv-generated
reproducibility as the source of truth. Keep uv 0.9.25's canonical Git source
form, `URL?rev=<full SHA>#<full SHA>`; do not hand-normalize it to
`URL#<full SHA>`.

## Global Constraints

- The only SDK commit approved for publication is `7f9f6bb6e4f5aeaae99cae30aa40a1bb3b5005ad` on local SDK branch `master`.
- The exact dependency string is `place-integration-api@git+https://github.com/harperreed/place-integration-api.git@7f9f6bb6e4f5aeaae99cae30aa40a1bb3b5005ad`.
- The public Git URL is `https://github.com/harperreed/place-integration-api.git`; dependency installation must not require SSH credentials.
- The SDK package version at the pinned commit remains `0.3.0` and every public symbol consumed by the integration must import successfully.
- Do not create or move a tag, create a GitHub release, publish to PyPI, change GitHub settings, push the Home Assistant repository, or make a live PLACE account call.
- Stop before pushing if the SDK worktree is dirty, its branch is not `master`, its HEAD differs from the approved commit, the public `master` no longer points to `c354ea31a4406ab3c66e1cf218c5f966878bc875`, or `scripts/check` fails.
- Never force-push. If the public SDK commit cannot be fetched after the push, restore the Home Assistant repository's sibling source and report the failure.
- Preserve the Home Assistant and test-tool versions already recorded in `uv.lock`; the intended source change is limited to `place-integration-api` and transitive resolution needed by that source.
- Hand-written source files begin with two `ABOUTME:` comment lines. Generated metadata such as `manifest.json` and `uv.lock` does not.
- Existing `pip-audit` findings from Home Assistant's `cryptography==48.0.1` pin remain visible release findings. Do not suppress or misreport them.

---

## File map

| File | Responsibility |
|---|---|
| `custom_components/gentex_place/manifest.json` | Home Assistant's install-time SDK requirement |
| `pyproject.toml` | The matching development SDK requirement, with no local source override |
| `uv.lock` | Exact public Git source and resolved commit for local and CI installs |
| `tests/components/gentex_place/test_manifest.py` | Repository metadata and lock-source contract |
| `scripts/check_sdk_dependency` | Repeatable direct and locked clean-install proof outside both source trees |
| `docs/superpowers/plans/2026-08-12-gentex-place-home-assistant.md` | Active integration plan and Task 9 gate state |
| `docs/superpowers/specs/2026-08-12-gentex-place-home-assistant-design.md` | Original design with an explicit newer distribution decision |
| `gotchas.md` | Durable dependency and audit facts for later sessions |

---

### Task 1: Publish the approved SDK commit

**State:** Complete. Public SDK `master` is
`7f9f6bb6e4f5aeaae99cae30aa40a1bb3b5005ad`; this publication task created no
Home Assistant commit.

**Files:**
- Verify only: `/Users/harper/Public/src/personal/place-integration-api`

**Interfaces:**
- Consumes: clean local SDK `master` at `7f9f6bb6e4f5aeaae99cae30aa40a1bb3b5005ad`, public `origin/master` at `c354ea31a4406ab3c66e1cf218c5f966878bc875`, and SDK command `scripts/check`.
- Produces: public `refs/heads/master` at the approved full SHA, reachable through HTTPS.

- [ ] **Step 1: Verify the exact local and public SDK state**

Run:

```bash
cd /Users/harper/Public/src/personal/place-integration-api
test -z "$(git status --porcelain)"
test "$(git branch --show-current)" = "master"
test "$(git rev-parse HEAD)" = "7f9f6bb6e4f5aeaae99cae30aa40a1bb3b5005ad"
test "$(git remote get-url origin)" = "git@github.com:harperreed/place-integration-api.git"
test "$(git ls-remote origin refs/heads/master | cut -f1)" = \
  "c354ea31a4406ab3c66e1cf218c5f966878bc875"
test "$(git rev-list --count c354ea31a4406ab3c66e1cf218c5f966878bc875..HEAD)" = "24"
git log --oneline --reverse c354ea31a4406ab3c66e1cf218c5f966878bc875..HEAD
```

Expected: every `test` exits zero and the final command prints the 24 reviewed commits from `abf6d6d` through `7f9f6bb`. Stop if any value differs; do not force or reconcile the branch in this task.

- [ ] **Step 2: Run the SDK's canonical gate**

Run:

```bash
cd /Users/harper/Public/src/personal/place-integration-api
UV_PYTHON=3.11 scripts/check
```

Expected: Ruff formatting and lint pass, basedpyright reports zero errors, all 237 SDK tests pass, and Twine accepts both built distributions.

- [ ] **Step 3: Push only the approved branch update**

Run:

```bash
cd /Users/harper/Public/src/personal/place-integration-api
git push origin master
```

Expected: a fast-forward update from `c354ea3` to `7f9f6bb`. Do not use a force option.

- [ ] **Step 4: Verify public HTTPS reachability and local cleanliness**

Run:

```bash
cd /Users/harper/Public/src/personal/place-integration-api
test "$(git ls-remote https://github.com/harperreed/place-integration-api.git refs/heads/master | cut -f1)" = \
  "7f9f6bb6e4f5aeaae99cae30aa40a1bb3b5005ad"
test -z "$(git status --porcelain)"
test "$(git rev-parse HEAD)" = "$(git rev-parse origin/master)"
```

Expected: all checks exit zero. This task creates no new commit because it publishes existing reviewed commits unchanged.

---

### Task 2: Pin and prove the Git dependency

**State:** Complete in `e14a99a7f58f86c0ba44e554e3ebc66ae9cf35b4`, with
canonical uv lock representation follow-up
`c3fd496abd54eb59597262c6b45e0cedb9e85bf2`.

**Files:**
- Create: `tests/components/gentex_place/test_manifest.py`
- Create: `scripts/check_sdk_dependency`
- Modify: `custom_components/gentex_place/manifest.json`
- Modify: `pyproject.toml`
- Modify: `uv.lock`

**Interfaces:**
- Consumes: public SDK commit `7f9f6bb6e4f5aeaae99cae30aa40a1bb3b5005ad` from Task 1 and existing project metadata.
- Produces: `_SDK_REQUIREMENT: str` as the test's one expected dependency value; `scripts/check_sdk_dependency` as a no-argument clean-install gate; a lock entry whose source is `https://github.com/harperreed/place-integration-api.git?rev=7f9f6bb6e4f5aeaae99cae30aa40a1bb3b5005ad#7f9f6bb6e4f5aeaae99cae30aa40a1bb3b5005ad`.

- [ ] **Step 1: Write failing repository contract tests**

Create `tests/components/gentex_place/test_manifest.py`:

```python
# Copyright (c) 2026 Gentex
# ABOUTME: Verifies Home Assistant metadata and the immutable public SDK source.
# ABOUTME: Keeps manifest, project, and lock dependency contracts in agreement.
"""Repository metadata contract tests for the Gentex PLACE integration."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).parents[3]
_SDK_SHA = "7f9f6bb6e4f5aeaae99cae30aa40a1bb3b5005ad"
_SDK_GIT_URL = "https://github.com/harperreed/place-integration-api.git"
_SDK_REQUIREMENT = f"place-integration-api@git+{_SDK_GIT_URL}@{_SDK_SHA}"


def _load_toml(path: Path) -> dict[str, Any]:
    """Load a repository TOML document."""
    with path.open("rb") as stream:
        return tomllib.load(stream)


def test_manifest_and_project_share_the_git_sdk_requirement() -> None:
    manifest = json.loads(
        (_ROOT / "custom_components/gentex_place/manifest.json").read_text()
    )
    project = _load_toml(_ROOT / "pyproject.toml")
    sdk_dependencies = [
        dependency
        for dependency in project["dependency-groups"]["dev"]
        if dependency.partition("@")[0].strip() == "place-integration-api"
        or dependency.partition("==")[0].strip() == "place-integration-api"
    ]

    assert manifest["domain"] == "gentex_place"
    assert manifest["version"] == project["project"]["version"]
    assert manifest["requirements"] == [_SDK_REQUIREMENT]
    assert sdk_dependencies == [_SDK_REQUIREMENT]
    assert "sources" not in project.get("tool", {}).get("uv", {})


def test_lock_uses_the_approved_public_sdk_commit() -> None:
    lock = _load_toml(_ROOT / "uv.lock")
    sdk_package = next(
        package
        for package in lock["package"]
        if package["name"] == "place-integration-api"
    )

    assert sdk_package["version"] == "0.3.0"
    assert sdk_package["source"] == {"git": f"{_SDK_GIT_URL}?rev={_SDK_SHA}#{_SDK_SHA}"}
    assert all(
        package.get("source", {}).get("directory") != "../place-integration-api"
        for package in lock["package"]
    )
```

- [ ] **Step 2: Run the tests and confirm the old dependency contract fails**

Run:

```bash
cd /Users/harper/Public/src/personal/gentex-places-ha
uv run pytest tests/components/gentex_place/test_manifest.py -q
```

Expected: both tests fail because the manifest and project still say `place-integration-api==0.3.0`, `[tool.uv.sources]` still points to the sibling checkout, and the lock source is a directory.

- [ ] **Step 3: Replace both declarations with the exact public Git requirement**

Change `custom_components/gentex_place/manifest.json` so its dependency field is exactly:

```json
"requirements": ["place-integration-api@git+https://github.com/harperreed/place-integration-api.git@7f9f6bb6e4f5aeaae99cae30aa40a1bb3b5005ad"],
```

Change the matching `pyproject.toml` development dependency to exactly:

```toml
"place-integration-api@git+https://github.com/harperreed/place-integration-api.git@7f9f6bb6e4f5aeaae99cae30aa40a1bb3b5005ad",
```

Delete this complete local override from `pyproject.toml`:

```toml
[tool.uv.sources]
place-integration-api = { path = "../place-integration-api", editable = false }
```

- [ ] **Step 4: Regenerate and inspect the lock**

Run:

```bash
cd /Users/harper/Public/src/personal/gentex-places-ha
baseline_lock=$(mktemp "${TMPDIR:-/tmp}/gentex-places-ha-uv-lock.XXXXXX")
cp uv.lock "$baseline_lock"
uv lock --refresh-package place-integration-api
git diff -- pyproject.toml uv.lock custom_components/gentex_place/manifest.json
rg -n 'place-integration-api|source = \{ (directory|git)' uv.lock
diff -u "$baseline_lock" uv.lock || true
rm "$baseline_lock"
```

Expected: the root package metadata records the exact direct Git requirement; the SDK package is version `0.3.0`; its uv-generated source is `https://github.com/harperreed/place-integration-api.git?rev=7f9f6bb6e4f5aeaae99cae30aa40a1bb3b5005ad#7f9f6bb6e4f5aeaae99cae30aa40a1bb3b5005ad`; no `../place-integration-api` source remains. Review the displayed baseline diff and stop if unrelated direct pins change.

- [ ] **Step 5: Run the focused tests and locked sync**

Run:

```bash
cd /Users/harper/Public/src/personal/gentex-places-ha
uv sync --locked
uv run pytest tests/components/gentex_place/test_manifest.py -q
```

Expected: the locked sync fetches the public HTTPS Git source and both metadata tests pass.

- [ ] **Step 6: Add the repeatable clean-install gate**

Create executable `scripts/check_sdk_dependency`:

```sh
#!/bin/sh
# ABOUTME: Proves direct and locked installs fetch the approved public PLACE SDK.
# ABOUTME: Uses temporary environments outside both source checkouts.
set -eu

sdk_requirement='place-integration-api@git+https://github.com/harperreed/place-integration-api.git@7f9f6bb6e4f5aeaae99cae30aa40a1bb3b5005ad'
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repository_root=$(CDPATH= cd -- "$script_dir/.." && pwd)
check_root=$(mktemp -d "${TMPDIR:-/tmp}/gentex-place-sdk-check.XXXXXX")
trap 'rm -rf "$check_root"' EXIT HUP INT TERM

direct_root="$check_root/direct"
locked_root="$check_root/locked"
mkdir -p "$direct_root" "$locked_root"

uv venv --python 3.14.2 "$direct_root/.venv"
uv pip install --python "$direct_root/.venv/bin/python" "$sdk_requirement"
(
    cd "$direct_root"
    PYTHONPATH= "$direct_root/.venv/bin/python" - <<'PY'
from place import (
    AlarmStatus,
    CognitoAuth,
    DeviceEvent,
    MfaRequired,
    PlaceAuthError,
    PlaceClient,
    PlaceConfig,
    PlaceConnectionError,
    PlaceDevice,
    PlaceDiscoveryError,
    PlaceError,
    PlaceInvalidAuthError,
    PlaceTimeoutError,
    PlaceTransientAuthError,
    __version__,
)

assert __version__ == "0.3.0"
PY
)

cp "$repository_root/pyproject.toml" "$locked_root/pyproject.toml"
cp "$repository_root/uv.lock" "$locked_root/uv.lock"
cp "$repository_root/.python-version" "$locked_root/.python-version"
uv sync --locked --project "$locked_root" --python 3.14.2
(
    cd "$locked_root"
    PYTHONPATH= "$locked_root/.venv/bin/python" -c \
        'import place; assert place.__version__ == "0.3.0"'
)
```

Then run:

```bash
cd /Users/harper/Public/src/personal/gentex-places-ha
chmod +x scripts/check_sdk_dependency
sh -n scripts/check_sdk_dependency
scripts/check_sdk_dependency
```

Expected: the shell syntax check passes; uv creates two temporary environments outside both repositories; the direct requirement and copied lock install from public Git; the package reports `0.3.0`; the script removes its temporary directory on exit.

- [ ] **Step 7: Run the integration regression gates**

Run:

```bash
cd /Users/harper/Public/src/personal/gentex-places-ha
uv run ruff format --check custom_components tests scripts
uv run ruff check custom_components tests scripts
uv run basedpyright
uv run pytest -q
git diff --check
```

Expected: formatting and lint pass, basedpyright reports zero errors, all existing tests plus the two metadata tests pass, and Git reports no whitespace errors.

- [ ] **Step 8: Commit the dependency contract**

Run:

```bash
cd /Users/harper/Public/src/personal/gentex-places-ha
git status --short
git add custom_components/gentex_place/manifest.json pyproject.toml uv.lock tests/components/gentex_place/test_manifest.py scripts/check_sdk_dependency
git commit -m "build: pin PLACE SDK Git dependency"
```

Expected: one commit contains only the two declarations, generated lock, contract tests, and clean-install script.

---

### Task 3: Retire the stale PyPI blocker

**State:** Complete in `98987d0d942f5f0916142ca2903e9632afc1bbad`, with
active-preflight follow-up `2f974fe3a784c9acd1fe289991040ab262c18d58`.

**Files:**
- Modify: `docs/superpowers/plans/2026-08-12-gentex-place-home-assistant.md`
- Modify: `docs/superpowers/specs/2026-08-12-gentex-place-home-assistant-design.md`
- Modify: `gotchas.md`

**Interfaces:**
- Consumes: the approved Git dependency design and verified Task 2 repository state.
- Produces: one active distribution rule: public full-SHA Git for HACS now, PyPI still required only for a future Home Assistant Core submission.

- [ ] **Step 1: Mark the original design's PyPI rule as superseded**

Add this block after the title in `docs/superpowers/specs/2026-08-12-gentex-place-home-assistant-design.md`:

```markdown
> **Distribution update (2026-08-19):** The approved
> [Git SDK dependency design](2026-08-19-git-sdk-dependency-design.md) supersedes
> this document's PyPI-only manifest and release-blocker statements for HACS custom
> distribution. Home Assistant Core submission still requires a suitable PyPI
> release.
```

- [ ] **Step 2: Update the active implementation plan's dependency state**

In `docs/superpowers/plans/2026-08-12-gentex-place-home-assistant.md`:

- change the second `ABOUTME:` line to `<!-- ABOUTME: Uses one immutable public Git SDK commit for HACS distribution. -->`;
- change the Tech Stack SDK entry to the exact requirement from Global Constraints;
- replace the two local/PyPI Global Constraints with the public full-SHA Git rule and state that Task 9 may begin after this dependency plan passes;
- replace the execution-preflight sibling `--with` command with `scripts/check_sdk_dependency`;
- replace Task 9's blocked state with `Ready after 2026-08-19-git-sdk-dependency.md is complete`;
- replace Task 9 Step 0 with a check that `test_manifest.py`, `manifest.json`, `pyproject.toml`, and `uv.lock` all contain the approved Git contract; and
- change Task 9's manifest assertion to the exact Git requirement.

Use this exact replacement for Task 9 Step 0:

```markdown
- [ ] **Step 0: Verify the public Git SDK contract**

Run `scripts/check_sdk_dependency` and the focused manifest tests. Inspect
`manifest.json`, `pyproject.toml`, and `uv.lock` to confirm they resolve the public
SDK at `7f9f6bb6e4f5aeaae99cae30aa40a1bb3b5005ad` with no directory source. Stop if
the clean install or public API import contract differs from the approved dependency
design.
```

- [ ] **Step 3: Replace the durable dependency gotcha**

Replace the existing PyPI/local-source entry at the end of `gotchas.md` with:

```markdown
- HACS installs the forked PLACE SDK from public Git commit
  `7f9f6bb6e4f5aeaae99cae30aa40a1bb3b5005ad`; keep the manifest, pyproject, and
  lock on that full SHA with no sibling uv source. PyPI remains required only for a
  future Home Assistant Core submission.
```

- [ ] **Step 4: Verify the documentation has one current rule**

Run:

```bash
cd /Users/harper/Public/src/personal/gentex-places-ha
rg -n "Blocked at Step 0|sibling uv source remains|Task 9 may not begin|manifest always pins exactly.*==0.3.0" docs/superpowers gotchas.md
rg -n "7f9f6bb6e4f5aeaae99cae30aa40a1bb3b5005ad|Git SDK dependency design|Home Assistant Core" docs/superpowers gotchas.md
git diff --check
```

Expected: the first search returns only deliberately quoted historical material, if any; the second search finds the approved current rule in the spec, active plan, and gotchas; the whitespace check passes.

- [ ] **Step 5: Commit the documentation state change**

Run:

```bash
cd /Users/harper/Public/src/personal/gentex-places-ha
git status --short
git add docs/superpowers/plans/2026-08-12-gentex-place-home-assistant.md docs/superpowers/specs/2026-08-12-gentex-place-home-assistant-design.md gotchas.md
git commit -m "docs: adopt public Git SDK contract"
```

Expected: the commit changes only the active plan, original design notice, and durable gotcha.

---

### Task 4: Verify the completed dependency migration

**State:** Local verification complete after test-only coverage commits
`15baa970adba6292bf89027ff509edcbc20cc657` and
`9eb571ad4b883e2f984bad4e5b5d074d46b84b6b`. Fresh-eyes review found no open
migration issue. Public-contract follow-up
`9c021ad16dba471757c6330d8091a9ee6838c4c2` makes both clean-install environments
run one complete consumed-export and version checker. Independent approval of the
follow-up and the final whole-branch review remain pending.

**Verification:** Public SDK `master` resolves to
`7f9f6bb6e4f5aeaae99cae30aa40a1bb3b5005ad`; direct and locked clean installs pass;
format, lint, type, and full coverage gates pass. `pip-audit` still reports only the
three documented Home Assistant `cryptography==48.0.1` findings. HACS and Hassfest
remote jobs, integration repository push, release, brand approval, live-account
check, PyPI publication, and Home Assistant Core submission remain outside this plan.

Fresh local evidence on 2026-08-19: the focused metadata tests pass 2/2; the full
suite passes 381/381 with all 679 production statements covered; `uv lock --check`
leaves lock SHA-256
`136e1bc48ed383f953ce2fc3ddd4267adf7e0d51dbc784608f5b20d17b6d3fad`
unchanged; and unsuppressed `pip-audit` exits 1 with exactly `PYSEC-2026-3552`,
`PYSEC-2026-3553`, and `PYSEC-2026-3554` plus the expected Git SDK skip. The direct
and copied-lock interpreters both pass the same full public contract checker; a
temporary real-package mutation proves it rejects a missing required export.

**Files:**
- Modify after verification: `docs/superpowers/plans/2026-08-19-git-sdk-dependency.md`

**Interfaces:**
- Consumes: Tasks 1-3 and all project verification commands.
- Produces: recorded evidence that the Git migration is complete, plus an honest list of release gates that remain.

- [ ] **Step 1: Run clean-install and full local gates from committed state**

Run:

```bash
cd /Users/harper/Public/src/personal/gentex-places-ha
test -z "$(git status --porcelain)"
scripts/check_sdk_dependency
uv sync --locked
uv run ruff format --check custom_components tests scripts
uv run ruff check custom_components tests scripts
uv run basedpyright
uv run pytest --cov=custom_components.gentex_place --cov-report=term-missing --cov-fail-under=100
git diff --check
```

Expected: both clean installs pass; uv reports a locked environment; formatting, lint, and types pass; the full suite passes at 100% integration coverage; Git reports no whitespace errors.

- [ ] **Step 2: Run the security audit without hiding known findings**

Run:

```bash
cd /Users/harper/Public/src/personal/gentex-places-ha
uv run pip-audit
```

Expected: `pip-audit` may skip the Git SDK because it cannot match a registry artifact, and it reports the three already-known `cryptography==48.0.1` findings (`PYSEC-2026-3552`, `PYSEC-2026-3553`, and `PYSEC-2026-3554`). Stop and investigate any new finding or changed package; do not suppress the command's nonzero exit.

- [ ] **Step 3: Run fresh-eyes and two-stage task review**

Use the required `fresh-eyes-review` workflow over the Task 1-3 diff. Then run the subagent-driven development skill's specification review followed by quality review. Fix each accepted finding with a failing test where behavior changes, rerun the focused and full gates, and commit the fix with exact file staging.

Expected: both reviews approve the migration with no open correctness, security, or scope findings.

- [ ] **Step 4: Record final evidence and remaining gates**

Update each task heading in this plan with its commit or publication state and add a final evidence paragraph containing:

```markdown
**Verification:** Public SDK `master` resolves to
`7f9f6bb6e4f5aeaae99cae30aa40a1bb3b5005ad`; direct and locked clean installs pass;
format, lint, type, and full coverage gates pass. `pip-audit` still reports only the
three documented Home Assistant `cryptography==48.0.1` findings. HACS and Hassfest
remote jobs, integration repository push, release, brand approval, live-account
check, PyPI publication, and Home Assistant Core submission remain outside this plan.
```

- [ ] **Step 5: Commit the implementation record**

Run:

```bash
cd /Users/harper/Public/src/personal/gentex-places-ha
git status --short
git add docs/superpowers/plans/2026-08-19-git-sdk-dependency.md
git commit -m "docs: record Git SDK migration"
```

Expected: the repository is clean after the plan-only evidence commit. Do not push the Home Assistant repository.
