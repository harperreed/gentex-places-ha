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
- Home Assistant 2026.8.1 exact-pins vulnerable `cryptography==48.0.1`. Do not force a
  newer cryptography over that pin; move to a fixed supported HA release or record an
  explicit risk exception before release, then rerun `pip-audit`.
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
