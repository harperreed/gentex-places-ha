<!-- ABOUTME: Defines the immutable Git dependency contract for the forked PLACE SDK. -->
<!-- ABOUTME: Replaces the blocked PyPI 0.3.0 gate for this HACS custom integration. -->
# Git SDK Dependency Design

## Decision

The Gentex PLACE custom integration will install the forked SDK from its public
GitHub repository at one immutable commit. The exact requirement string is:

```text
place-integration-api@git+https://github.com/harperreed/place-integration-api.git@7f9f6bb6e4f5aeaae99cae30aa40a1bb3b5005ad
```

The integration will use this same string in `manifest.json` and its development
dependency declaration. The local sibling checkout will stop overriding dependency
resolution. `uv.lock` must resolve the public HTTPS Git source and exact commit, with
no directory source for `place-integration-api`.

This is an interim distribution contract for a HACS custom integration. Home
Assistant supports public Git requirements, but Home Assistant Core inclusion still
requires a suitable PyPI release. The project will not claim Core eligibility or a
PyPI `0.3.0` release.

## SDK publication boundary

The local SDK `master` is currently 24 commits ahead of
`harperreed/place-integration-api` and ends at
`7f9f6bb6e4f5aeaae99cae30aa40a1bb3b5005ad`. Doctor Biz authorized pushing those
reviewed commits.

Before the push, the implementation must:

1. confirm the SDK worktree is clean and still ends at the approved commit;
2. run the SDK's canonical `scripts/check` command successfully;
3. inspect the exact `origin/master..HEAD` commit range; and
4. stop if the branch or commit differs from this design.

The only authorized SDK write is pushing local `master` to `origin/master`. Do not
create or move a tag, create a GitHub release, publish to PyPI, or change repository
settings. After the push, verify through the public HTTPS remote that the full commit
is reachable before changing the Home Assistant dependency.

## Integration dependency changes

`custom_components/gentex_place/manifest.json` will replace its PyPI pin with the
exact Git requirement above. `pyproject.toml` will use the same direct requirement
for development and will remove `[tool.uv.sources]`. Regenerating `uv.lock` must not
change the intended Home Assistant or test-tool pins.

The package metadata at the pinned commit must still report SDK version `0.3.0` and
provide every public symbol consumed by the integration. A direct Git reference does
not use a floating branch, tag, shortened SHA, SSH URL, credential, or local path.

## Verification

Tests will define the expected Git requirement once and assert that both the manifest
and project dependency use it. They will also assert that the manifest and project
versions still agree and that no local uv source remains.

An isolated clean-install check will:

1. create a temporary environment outside both source trees;
2. install the exact public Git requirement;
3. verify `place.__version__ == "0.3.0"` and the required public imports;
4. install the Home Assistant project from its locked dependencies; and
5. run the complete integration test, lint, formatting, and type gates.

The lockfile review must prove that dependency resolution records the approved Git
URL and commit and contains no sibling-directory source. `pip-audit` will still run,
but a Git dependency may not receive registry vulnerability matching; the immutable
commit, public source, SDK canonical checks, and clean-install test are the explicit
compensating controls. Existing Home Assistant-pinned dependency findings remain
release findings rather than ignored output.

Hassfest and HACS validation will run in pinned GitHub Actions after the integration
repository is later pushed with separate approval. A local test must not claim those
remote validators ran.

## Failure and update policy

If the public commit cannot be fetched or its package contract differs from the local
candidate, restore the sibling source and stop the release work. Do not fall back to
PyPI `0.2.4`, a branch name, or vendored source.

Future SDK updates require a new immutable commit, the SDK canonical gate, clean
installation, integration regression tests, and an explicit review of the dependency
diff. Existing installations remain reproducible as long as the public fork retains
the pinned commit. Deleting or making the fork private is therefore a breaking
distribution change.

## Known limits

- Installation requires network access to the public GitHub fork and Git-capable
  Python package installation in Home Assistant.
- This design targets HACS custom distribution, not Home Assistant Core inclusion.
- HACS default inclusion still requires its separate repository, brand, release, and
  validator gates.
- No PyPI, GitHub release, tag, live-account, or integration-repository push is part
  of this dependency change.

## References

- [Home Assistant integration manifest requirements](https://developers.home-assistant.io/docs/creating_integration_manifest/)
- [Home Assistant dependency transparency rule](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/dependency-transparency/)
- [HACS integration repository requirements](https://hacs.xyz/docs/publish/integration/)
- [HACS default repository requirements](https://hacs.xyz/docs/publish/include/)
