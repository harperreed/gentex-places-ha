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
