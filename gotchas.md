<!-- ABOUTME: Records durable project facts that can prevent repeat mistakes. -->
<!-- ABOUTME: Keep entries short, current, and grounded in tests or primary docs. -->
# Gotchas

- Home Assistant 2026.8 custom integrations use `translations/en.json`, not
  `strings.json`, and keep licensed brand art under the integration's `brand/` folder.
- `DataUpdateCoordinator.async_set_updated_data()` resets the poll timer. Override it
  for MQTT pushes so traffic cannot postpone the fixed five-minute health refresh.
- SDK 0.3.0 release needs cache-only login and typed invalid/transient runtime auth;
  never call interactive login with a fake password or parse SDK log text.
- SDK auth results and typed failures need a principal-generation check. Delayed work
  from an old account must not change or stop the current account.
- Raising a sanitized error `from None` inside an `except` block still leaves the raw
  error in `__context__` or `sys.exception()`. Leave the handler before notifying or
  raising across the public boundary.
- Plain SDK `PlaceConfig()` must use literal PLACE defaults. Only `from_env()` may
  read process or `.env` values; ambient Home Assistant settings must not redirect it.
- Config-entry token saves require the supplied username to match the entry username.
  Never relabel a refresh token from one account as another account's token.
- Config flows must clear SDK objects and token caches on cancellation and on Home
  Assistant's synchronous `async_remove` hook; MFA state loss returns to the form for
  the flow's source.
- Normalize built-in and aiohttp discovery timeouts to `PlaceTimeoutError` inside the
  SDK. In Home Assistant, translate timeouts only at explicit SDK await boundaries so
  programmer `TimeoutError` exceptions still surface.
- Doctor Biz approved a narrow audit exception for Home Assistant 2026.8.1's exact
  `cryptography==48.0.1` pin and only `PYSEC-2026-3552`, `PYSEC-2026-3553`, and
  `PYSEC-2026-3554`. The canonical audit must fail closed on any version or finding
  drift; never force a newer cryptography over Home Assistant's pin.
- SDK shutdown must consume cancellation from its owned MQTT task while preserving a
  new caller cancellation. Snapshot the caller's cancellation count so cleanup inside
  an existing `CancelledError` handler does not mistake owned cancellation for a new one.
- Coordinator shutdown marks the client stopped only after `PlaceClient.stop()` returns.
  Serialize concurrent calls and leave a failed or cancelled stop retryable.
- Home Assistant device identity uses the required PLACE thing name, never the
  optional device ID. Percent-escape `%`, `_`, and `:` in opaque components before
  joining them so registry IDs stay stable and collision-free.
- Tests for live Home Assistant entities must cross the SDK callback boundary and
  assert loaded state changes. Direct property reads do not prove coordinator
  listener fan-out or cached-property overrides.
- Mark `async_call_later` actions that touch Home Assistant state with `@callback`.
  An unmarked callable becomes an executor job, where coordinator listeners cannot
  safely write entity state.
- Give `SensorStateClass.MEASUREMENT` only to fields with verified physical units.
  Raw battery, alert, optical, sensitivity, and light-channel values need no invented
  unit or statistics meaning.
- Consume startup callback errors before raising them and clear coordinator storage
  at start and shutdown; a sanitized exception traceback can expose coordinator locals.
- PLACE account titles use the lowest free generic ordinal, while an existing safe
  ordinal stays stable. Concurrent flows can choose the same cosmetic title, but the
  account unique ID remains the duplicate-account authority.
- HACS installs the forked PLACE SDK from public Git commit
  `d92f07ecc9b7e66162d60d4a66cc07366543b631`; keep the manifest, pyproject, and
  lock on that full SHA with no sibling uv source. PyPI remains required only for a
  future Home Assistant Core submission.
- SDK client updates include value-identical reported-shadow replies because they
  advance liveness; device-local listeners remain field-change only. Empty MQTT
  echoes neither stamp liveness nor emit an update.
- Task 9 validation includes the `place` logger and a fail-closed exception for the
  three approved cryptography findings. On 2026-08-22, public CI and Hassfest passed;
  HACS passed 8/9 checks and remains blocked only on licensed brand art with
  provenance. A clean user HACS install, live-candidate check, and release remain open.
- Root `.env` holds local live-check credentials. Keep it ignored and mode `0600`;
  inspect key names only, never print values, and request MFA at runtime.
- The authorized read-only live check passed on 2026-08-21 at `a11133a`: the account
  connected and all five discovered devices reported state. Keep sanitized evidence
  outside Git and rerun the check for every release candidate.
- POSIX shells suppress `set -e` throughout a compound command used as the left side
  of `||`. Release runners must check each logged setup phase explicitly so an early
  failure cannot be masked by a later successful command.
- Packaged system tests keep the real integration factories and pinned SDK client,
  auth, provider, connection, and device paths. Inject only at Cognito, fulfillment
  HTTP, and MQTT transport seams; prove cleanup through public state and seam events,
  never SDK private fields.
- `git archive --prefix=gentex_place/ --add-file=LICENSE` puts the root MIT notice at
  `gentex_place/LICENSE`, preserving one source of truth and the single-directory ZIP.
