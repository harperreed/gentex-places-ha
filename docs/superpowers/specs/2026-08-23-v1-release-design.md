<!-- ABOUTME: Defines the Gentex PLACE v1.0.0 brand, release, and branch-protection contract. -->
<!-- ABOUTME: Keeps HACS packaging, GitHub publication, and rollback rules explicit and testable. -->
# Gentex PLACE v1 Release Design

## Decision

The repository will publish Gentex PLACE `v1.0.0` as its first stable GitHub
release. A matching version increase merged into protected `main` will trigger the
release. Ordinary merges will run a read-only detector and will not create tags,
releases, or assets.

The release will include an original project-owned Home Shield icon and one
HACS-compatible asset named `gentex_place.zip`. HACS will install that exact tested
asset. The repository will not publish the PLACE SDK to PyPI or submit this
integration to the HACS default store as part of this work.

## Goals

- Add original, licensed brand art that satisfies Home Assistant and HACS checks.
- Protect `main` with the existing test, Hassfest, and HACS checks.
- Publish only when `pyproject.toml` and the integration manifest make the same
  valid, increasing stable version change.
- Build and verify a reproducible HACS archive before making a release public.
- Publish `v1.0.0` from the exact reviewed merge commit without replacing or
  mutating an existing release.
- Leave failures visible and recoverable instead of hiding or overwriting them.

## Non-goals

- Do not publish any package to PyPI.
- Do not submit the repository to the HACS default store.
- Do not add Gentex, PLACE, or Home Assistant trademarks to the project icon.
- Do not create compatibility shims, alternate install formats, or a second release
  archive.
- Do not release on every merge to `main`.
- Do not automate deletion, replacement, or repair of a failed draft release.

## Brand contract

The integration will use an original Home Shield mark:

- a teal rounded-square field;
- a white shield;
- a charcoal house inside the shield; and
- one amber alert dot.

The mark will contain no text and will not copy Gentex, PLACE, Home Assistant, or
other third-party brand images. The repository will own the work and license it
under the repository's MIT license.

The editable source will live at `docs/brand/home-shield.svg`. Release files will
live at:

- `custom_components/gentex_place/brand/icon.png`, exactly 256 by 256 pixels; and
- `custom_components/gentex_place/brand/icon@2x.png`, exactly 512 by 512 pixels.

Both PNG files will use RGBA color and transparent corners. The design must stay
legible at Home Assistant's small icon sizes and must not depend on metadata,
animation, or an external font.

`docs/brand-provenance.md` will state that the artwork was created for this
repository on August 23, 2026, uses no external artwork, and is released under MIT.
The repository will retain the editable source so later exports can be traced to
one source of truth.

Tests will check that the two PNG files exist, decode as PNG, have the exact pixel
sizes, use an alpha channel, and have transparent pixels. They will also require the
SVG source and provenance document. The release archive must contain both PNGs.

## Version contract

`pyproject.toml` and `custom_components/gentex_place/manifest.json` remain the two
required version declarations. They must agree in both the commit before a merge
and the new `main` commit.

Releasable versions use stable semantic version form `X.Y.Z`, where each component
is a non-negative decimal integer. Pre-release labels, build metadata, a leading
`v` in the files, and malformed versions are invalid. A changed version must be
strictly greater than the prior version under semantic version ordering.

The detector has four outcomes:

1. Matching, unchanged valid versions produce a successful no-op.
2. Matching, strictly increased valid versions produce a release request.
3. Mismatched, malformed, or decreased versions fail the workflow.
4. An existing matching tag or GitHub release fails the workflow rather than
   replacing it.

The Git tag and GitHub release name will add the `v` prefix, so repository version
`1.0.0` maps to `v1.0.0`.

## Release workflow

`.github/workflows/release.yml` will run on pushes to `main`. It will contain two
jobs with separate authority.

### Read-only detection job

The detector will have only `contents: read` permission. It will check out enough
history to inspect the pushed commit and its `github.event.before` commit, then use
a repository script to validate both versions and decide whether a release is
needed. It will expose only the validated version and a release-required boolean to
the next job.

If either commit cannot be resolved, the job will fail closed. The validated version
will pass to shell commands through an environment variable, never by inserting
repository-controlled text into shell source.

For a version increase, the job will also confirm through Git and the GitHub API
that neither `vX.Y.Z` nor a GitHub release with that tag already exists. A duplicate
draft counts as an existing release. Any uncertain API result fails closed.

No-op merges finish in this job. They never start a job with write permission.

### Write-scoped publish job

The publisher will depend on the detector and run only when its release-required
output is true. This job alone will receive `contents: write` permission. It will:

1. check out the exact pushed `main` commit with stored credentials disabled;
2. rerun the release checks to guard against bad or stale job output;
3. run the canonical `scripts/check` gate;
4. build `gentex_place.zip` and `gentex_place.zip.sha256`;
5. create `vX.Y.Z` as a draft GitHub release targeting the exact pushed commit;
6. attach both files and release notes from `docs/releases/vX.Y.Z.md`;
7. inspect the draft tag, target commit, asset names, asset bytes, checksum, and ZIP
   contents through GitHub; and
8. make the draft public only after every check passes.

All third-party GitHub Actions will remain pinned to full commit SHAs. The workflow
will use the GitHub token only through explicit release commands and will not persist
checkout credentials. Validation, tests, and packaging will not receive the token in
their environment.

If a step fails before draft creation, no release will exist. If verification fails
after draft creation, the draft and tag will remain visible for diagnosis. The
workflow will not delete, overwrite, or publish that draft. A maintainer must inspect
the failure and choose the recovery action.

## HACS archive layout

`hacs.json` will set:

```json
{
  "zip_release": true,
  "filename": "gentex_place.zip"
}
```

HACS extracts a ZIP release directly into
`/config/custom_components/gentex_place`. Therefore `gentex_place.zip` must place
the integration files at the archive root. Required entries include:

```text
__init__.py
manifest.json
brand/icon.png
brand/icon@2x.png
LICENSE
```

The ZIP must not contain a top-level `gentex_place/` or
`custom_components/gentex_place/` wrapper. A wrapped archive would create a nested
integration directory and break HACS installation.

The archive will contain the tracked contents of
`custom_components/gentex_place/` plus a byte-identical copy of the repository's
root `LICENSE`. It will exclude repository development files, credentials, caches,
tests, and Git metadata.

The checksum file will contain the SHA-256 digest and exact asset name in the normal
`sha256sum` format. Archive member order, timestamps, permissions, and compression
settings will be deterministic so two clean builds from the same commit produce the
same bytes. Tests will build the archive with the same repository script or command
used by the workflow, inspect every member, reject absolute paths, parent traversal,
symlinks, and wrapped paths, and compare the archived license and integration files
with their tracked sources.

The builder will snapshot every tracked source through no-follow file descriptors
before it creates an output directory or touches a final asset. It will reject a
ZIP or checksum path that is a symlink, a non-regular file, an alias of a tracked
source, or an alias of the other final asset. It will write both assets to fresh
files in the destination directory, verify the staged ZIP against the captured
snapshot, and only then replace final paths.

A filesystem cannot replace the ZIP and checksum as one atomic pair. Publication
therefore replaces the checksum first and the ZIP second. Before the second replace,
the previous ZIP remains complete and the new checksum cannot validate it unless
the archive bytes are already identical. After the second replace, the pair matches.
Any error before replacement preserves both prior final files; staging files are
removed on handled failure, and a partial ZIP is never installed at the final path.

## Release notes

`docs/releases/v1.0.0.md` will be the reviewed source for the first release notes.
It will state that the integration is read-only, summarize device discovery and
live updates, give HACS installation and upgrade steps, disclose the pinned public
Git SDK dependency, and credit the original MIT Home Shield artwork.

The notes will not claim HACS default-store inclusion, Home Assistant Core support,
PyPI publication, write control, or behavior that the integration does not provide.

README release guidance will use GitHub Releases as the source of truth for public
version and asset availability. It will name `v1.0.0` as the first stable version
and describe the checks required before and after publication. It will not carry a
temporary candidate label, an open-gates checklist, or any claim that becomes false
when the workflow publishes the release.

## Branch protection

Before the release pull request merges, the public repository's `main` branch will
receive branch protection through the GitHub API. Protection will:

- run validation for pull requests and pushes to `main`, without creating
  same-name validation runs for pushes to work branches;
- require a pull request before merging;
- require the exact `test`, `hassfest`, and `hacs` status checks;
- bind those checks to the GitHub Actions app that produced the current successful
  runs;
- require the branch to be current before merge;
- require linear history;
- reject force pushes and branch deletion; and
- start with zero required approving reviews because the repository currently has
  one maintainer.

The setting must not allow administrators to bypass the protected flow for this
release. The implementation will read the resulting branch-protection document
back from GitHub and compare every required field before merging.

The protection helper will accept exactly one check run for each required name on
the supplied pull-request head SHA. A missing, duplicate, pending, failed, mixed,
or non-GitHub-Actions required run fails closed. The helper will not guess which
duplicate is newest because the consumed check-run shape has no tested ordering or
freshness contract.

Before inspecting names, the helper will require `total_count` to be a non-boolean,
nonnegative integer equal to the number of returned `check_runs`. The API request
uses the maximum page size of 100, so any larger total or other count mismatch proves
the response incomplete and fails closed instead of trusting a truncated page.

All release work will happen on the existing work branch and reach `main` through a
pull request. The pull request must show all three required checks passing. A merge
must not occur until branch protection has been applied and verified.

## Test strategy

Implementation will follow TDD. Tests will first fail for each new contract, then
pass after the smallest production change. Coverage will include:

- stable semantic-version parsing and ordering;
- unchanged-version no-op detection;
- matching version-increase detection;
- mismatched, malformed, and decreased-version failures;
- refusal to reuse a tag or release;
- detector and publisher job conditions and least-privilege permissions;
- the exact HACS `zip_release` and `filename` settings;
- root-level ZIP layout, safe paths, source equality, license, and SHA-256 output;
- PNG format, dimensions, alpha, source, provenance, and archive inclusion; and
- reviewed release-note presence for the detected version.

Unit tests will exercise the release helpers with temporary metadata and archives.
Integration tests will exercise the real archive command against the repository.
The release workflow plus a clean HACS upgrade on Doctor Biz's Home Assistant will
provide the end-to-end check; tests will not mock GitHub or HACS behavior and call
that an end-to-end result.

The canonical `scripts/check` command must pass locally and in the `test` job.
Hassfest and HACS must both pass remotely, with HACS moving from its current 8/9
result to 9/9 after brand art lands.

## Verification and rollout

Before merge:

1. Run `scripts/check` in the repository.
2. Build the exact release ZIP and inspect its paths, bytes, icon files, and license.
3. Install the archive into a clean Home Assistant test layout and load the real
   integration package;
4. open the pull request and wait for `test`, `hassfest`, and `hacs` to pass; and
5. apply and read back branch protection before enabling merge.

After merge:

1. Confirm `main`, tag `v1.0.0`, and the public release target the same commit SHA.
2. Download the public ZIP and checksum assets without repository credentials.
3. Compare their digest and contents with a clean local rebuild from that SHA.
4. Confirm the public archive has root-level integration files and no wrapper.
5. Have Doctor Biz upgrade the live HACS installation to `v1.0.0` and confirm the
   integration starts, discovers the expected devices, and continues receiving
   state.

Doctor Biz's already working live installation is evidence for the current code,
but the release is not complete until the published asset itself passes the upgrade
check.

## Failure and rollback policy

Published releases are immutable. Do not move `v1.0.0`, edit its assets, or replace
its ZIP. A code or packaging defect will be fixed through a new pull request and a
strictly higher patch version such as `1.0.1`.

A failed draft is not a published release. Leave it intact until its cause is known.
Recovery may require a maintainer to remove the draft and tag, but that destructive
choice is outside the automated workflow and requires a separate, explicit decision.

The release workflow serializes runs for the same Git ref and never cancels a run in
progress. This closes the gap between the absence checks and draft creation without
interrupting verification after a draft exists.

If the live upgrade fails, preserve the Home Assistant logs and downloaded asset,
restore the prior installed version through HACS, and fix the root cause in the next
version. Never replace the public `v1.0.0` asset to make the failure disappear.

## Completion boundary

This effort ends when branch protection is verified, the `v1.0.0` release and assets
are public and reproducible, all required checks pass, and Doctor Biz confirms the
live HACS upgrade. HACS default-store submission remains a later project.

## References

- [Home Assistant brands image specification](https://github.com/home-assistant/brands#image-specification)
- [HACS repository manifest](https://www.hacs.xyz/docs/publish/start/#hacsjson)
- [HACS integration requirements](https://www.hacs.xyz/docs/publish/integration/)
- [HACS ZIP extraction implementation](https://github.com/hacs/integration/blob/main/custom_components/hacs/repositories/base.py)
