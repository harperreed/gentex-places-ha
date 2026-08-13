<!-- ABOUTME: Records durable project facts that can prevent repeat mistakes. -->
<!-- ABOUTME: Keep entries short, current, and grounded in tests or primary docs. -->
# Gotchas

- Home Assistant 2026.8 custom integrations use `translations/en.json`, not
  `strings.json`, and keep licensed brand art under the integration's `brand/` folder.
- `DataUpdateCoordinator.async_set_updated_data()` resets the poll timer. Override it
  for MQTT pushes so traffic cannot postpone the fixed five-minute health refresh.
- SDK 0.3.0 release needs cache-only login and typed invalid/transient runtime auth;
  never call interactive login with a fake password or parse SDK log text.
