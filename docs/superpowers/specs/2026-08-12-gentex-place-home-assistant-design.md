<!-- ABOUTME: Defines the approved architecture and release gates for Gentex PLACE. -->
<!-- ABOUTME: Keeps Home Assistant behavior tied to verified SDK and platform contracts. -->
# Gentex PLACE Home Assistant integration — design

- **Date:** 2026-08-12
- **Status:** approved and reviewed
- **Branch:** `wip/gentex-place-integration`
- **Integration domain:** `gentex_place`
- **Display name:** Gentex PLACE

## 1. Goal

Build a robust custom Home Assistant integration for Gentex PLACE devices. Users
install it through HACS and configure it in the Home Assistant UI. The integration
uses the standalone `place-integration-api` Python SDK for Cognito login, device
discovery, AWS IoT MQTT, shadow state, and device events.

The first release is a read-only monitoring integration. It exposes every state the
SDK can interpret, including safety alarms, live environmental readings, device
health, connectivity, and motion. MQTT pushes state changes at once. A slow shadow
refresh checks liveness and repairs missed state.

The integration should meet the current Home Assistant integration rules and the
HACS default-repository requirements at release time. Its minimum version is the
current stable Home Assistant release at that time. CI tests that minimum and tracks
latest stable; compatibility with an untested future release is not promised.

## 2. Assumptions and evidence

- The target SDK source is `git@github.com:harperreed/place-integration-api.git`.
- The inspected SDK checkout reports version `0.3.0` and provides the async
  `PlaceClient`, `CognitoAuth`, `TokenCache`, typed errors, discovery models,
  connection callbacks, shadow refresh, motion events, and device liveness stamps.
- PyPI served `place-integration-api` version `0.2.4` on 2026-08-12. That release does
  not match the inspected async SDK. Publishing the required SDK version is a release
  gate.
- The SDK's write-message helper only wraps arbitrary fields in an AWS desired-state
  envelope. Its tests state that the device-specific command schema is unknown.
  Therefore, the first release must not write desired state or expose controls.
- A real PLACE account may be used only for an explicit, read-only release check.
  Automated tests never use live account credentials.
- The project uses the MIT license.

## 3. Scope

### 3.1 First release

- HACS-compatible repository and SemVer releases.
- UI setup with username, password, and MFA when Cognito requests it.
- Store username and refresh token only. Never store the password or MFA code.
- One config entry per PLACE account, with multiple accounts supported.
- Reject a duplicate account by its stable Cognito identity, not by username.
- Discover every device returned for the account.
- Create one Home Assistant device-registry entry per PLACE device.
- Create enabled entities for every state supported by the SDK.
- Immediate MQTT updates, periodic shadow refresh, account availability, and
  per-device availability.
- Reauthentication, reload, unload, diagnostics, and translations. No repair flow
  ships until a separate, user-fixable issue exists.
- Unit, Home Assistant integration, packaged-system, and opt-in live tests.
- HACS validation, Hassfest, formatting, linting, type checking, and dependency checks.

### 3.2 Follow-up controls phase

Controls remain part of the product roadmap but do not ship in the first release.
Night-light, motion-sensitivity, alarm, hush, test, or other write features require:

1. Capturing or obtaining the real command and acknowledgement schema.
2. Testing that schema against a real device with explicit permission.
3. Adding typed SDK methods and error handling through TDD.
4. Publishing a new SDK release.
5. Adding Home Assistant control entities and live safety checks through TDD.

The integration must never publish arbitrary desired-shadow dictionaries.

### 3.3 Non-goals for the first release

- YAML configuration.
- Local communication with devices.
- User-configurable refresh, stale, or motion timing.
- Compatibility shims for older Home Assistant releases.
- Hot discovery of devices added after config-entry setup. Reloading the config entry
  performs discovery again. Periodic roster discovery can follow if real use shows a
  need.
- Guessing a unit, enum meaning, command, or health-field schema.

## 4. Architecture

Use one hybrid account coordinator per config entry.

```text
Home Assistant config entry
          |
          v
GentexPlaceCoordinator  <---- fixed health timer
  |       |                         |
  |       +-- SDK connection state  +-- shadow/get for known devices
  |       +-- SDK device updates
  |       +-- SDK motion events
  |
  +-- PlaceClient ---- Cognito auth / HTTPS discovery / AWS IoT MQTT
  |
  +-- one shared PlaceDevice object per physical device
          |
          +-- sensor entities
          +-- binary-sensor entities
          +-- device availability
```

The SDK owns cloud protocol and mutable `PlaceDevice` state. The coordinator owns the
Home Assistant lifecycle, timers, authentication mapping, and listener fan-out.
Entities are views over SDK device objects. They do not cache or copy device state.

This keeps one source of truth and avoids routing PLACE data through Home Assistant's
unrelated MQTT integration.

### 4.1 Repository layout

```text
custom_components/gentex_place/
  __init__.py
  binary_sensor.py
  config_flow.py
  const.py
  coordinator.py
  diagnostics.py
  entity.py
  manifest.json
  brand/icon.png             # licensed 256x256 or larger brand/product art
  sensor.py
  translations/en.json
tests/
  components/gentex_place/
scripts/check
hacs.json
README.md
LICENSE
```

Files may be combined when that is simpler, but protocol, coordinator, entity, and
config-flow duties must remain separate. Hand-written source files start with the
project's two-line `ABOUTME:` comment.

### 4.2 Home Assistant manifest

The manifest declares:

- domain `gentex_place`;
- name `Gentex PLACE`;
- `config_flow: true`;
- integration type `hub`;
- IoT class `cloud_push`;
- the repository documentation and issue tracker;
- code owner `@harperreed`;
- a valid custom-integration version;
- an exact PyPI pin for the released async SDK; and
- SDK logger names needed for debug logging.

The release manifest must not use a Git branch, commit URL, local path, or version
range for the SDK.

## 5. Authentication and config entries

### 5.1 Initial setup

1. The user enters username and password.
2. The flow creates `CognitoAuth` with Home Assistant's shared `aiohttp` session and an
   in-memory implementation of the SDK `TokenCache` protocol.
3. If `authenticate()` raises `MfaRequired`, the same flow instance asks for the MFA
   code and calls `submit_mfa()`.
4. The flow calls `async_get_iot_credentials()` and uses the returned Cognito
   `identity_id` as the config-flow unique ID.
5. The flow aborts if that identity already has a config entry.
6. Discovery must succeed and return at least one usable device before entry creation.
7. The entry stores the username, captured refresh token, and stable account identity.
   It does not store password, MFA code, access token, ID token, or temporary IoT keys.

The username is kept because the SDK's token cache binds a refresh token to its login
name. The account identity, not the username, enforces uniqueness.

### 5.2 Runtime token store

An integration-owned `TokenCache` adapter loads the username and refresh token from
the config entry. When the SDK rotates or re-saves a refresh token, the adapter updates
the same config entry. It never writes a separate token file.

Home Assistant config-entry storage is not a password vault. The refresh token is a
bearer secret and must be treated like a password in logs, diagnostics, bug reports,
and tests.

Runtime startup must use a public SDK cache-only authentication operation. It must
never call SRP with an empty or synthetic password when a cached refresh token fails.
A rejected cache-only login returns a typed invalid-auth result so Home Assistant can
start reauthentication.

### 5.3 Reauthentication

- A rejected or expired refresh token starts Home Assistant's reauthentication flow.
- Reauthentication asks for password and MFA as needed, verifies that the resulting
  Cognito identity matches the existing entry, replaces the refresh token, and reloads
  the entry.
- A login for a different identity aborts reauthentication rather than moving the
  existing devices to another account.
- Password and MFA values leave memory with the flow and never enter entry data.

### 5.4 Required SDK authentication contract

The current SDK falls back from a rejected cached refresh token to password-based SRP,
but Home Assistant correctly does not retain the password. It also retries every
`PlaceAuthError` inside its background connection loop. That prevents Home Assistant
from learning that a persistent session needs reauthentication.

Before release, the SDK must provide both:

- a public cache-only authentication operation that never falls back to SRP; and
- a typed, secret-safe runtime error notification that distinguishes invalid or
  revoked credentials from a transient Cognito or network failure.

The coordinator maps only confirmed invalid credentials to reauthentication. It keeps
retrying transient failures. Polling SDK private fields, passing a fake password, or
parsing exception strings or logs is forbidden.

## 6. Coordinator and data flow

### 6.1 Startup

1. Build `CognitoAuth` from the entry token adapter and shared web session.
2. Authenticate from the cached refresh token.
3. Create and start one `PlaceClient`.
4. Let the client discover the account, build its `PlaceDevice` registry, subscribe to
   shadow and household event topics, and request initial shadows.
5. Wait up to 30 seconds for the MQTT connection and at least one initial reported
   shadow answer when devices exist.
6. Forward the config entry to `sensor` and `binary_sensor` platforms.

A temporary discovery or connection failure raises `ConfigEntryNotReady`. A confirmed
auth failure raises `ConfigEntryAuthFailed`. An empty usable-device set aborts initial
setup with a clear form error.

### 6.2 Push updates

- An SDK device update calls the coordinator on Home Assistant's event loop.
- The coordinator updates the same device registry and notifies entity listeners
  without resetting its fixed health-refresh clock. Home Assistant's default
  `async_set_updated_data()` reschedules the next poll, so using it unchanged could let
  frequent MQTT traffic postpone health checks forever.
- A connection callback updates account availability and all listeners.
- A motion event updates the source device and schedules that device's motion entity to
  clear 30 seconds after the latest event. A newer event cancels and replaces the old
  clear timer.

Callbacks are removed during unload. No SDK callback may schedule work after its config
entry has unloaded.

### 6.3 Fixed health refresh

- Every five minutes, the coordinator requests a shadow refresh for every known device.
- A refresh publish is a read trigger; its successful publish does not by itself prove
  the device is alive.
- Only an MQTT message carrying non-empty reported shadow state advances the SDK
  device's `last_shadow_at` value.
- The coordinator notifies listeners after each health interval so stale availability
  changes are visible even when no device message arrives.
- Timers use monotonic time for elapsed-time decisions.

### 6.4 Shutdown and reload

Unload cancels the health and motion timers, unregisters every SDK listener, awaits
`PlaceClient.stop()`, closes no Home Assistant-owned session, and unloads platforms.
A reload runs discovery again and recreates the runtime from entry data.

## 7. Availability

Account availability is `PlaceClient.connected`. The integration exposes it as an
account connection binary sensor and uses it as the first availability condition for
device entities.

A device is available only when:

1. the account connection is up; and
2. the device has supplied reported shadow state no more than 15 minutes ago. It
   becomes stale only when the age exceeds 15 minutes.

During startup, discovered devices receive a 30-second grace window while the initial
shadow request is outstanding. If no discovered device supplies reported state by the
deadline, setup retries instead of presenting a dead account as healthy. Once one
device answers, setup completes; any silent sibling loads as unavailable rather than
blocking the whole account.

Each device also has an enabled connectivity binary sensor. Other entities retain
their last values during a disconnect but report unavailable. One stale device does
not make sibling devices unavailable.

The two connectivity entities are deliberate exceptions to normal entity
availability. The account connectivity entity stays available while the entry is
loaded and reports the SDK connection boolean. A device connectivity entity also
stays available while the entry is loaded and reports true only when both the account
and that device are live. Otherwise it reports false. If these entities inherited the
availability they describe, they would become `unavailable` at the exact time a user
needs an explicit disconnected state.

## 8. Device and entity model

Each `PlaceDevice` becomes one device-registry record:

- identifiers combine the account identity with the SDK device ID when present, else
  its thing name, so two configured accounts cannot collide;
- name uses the discovered device name, falling back to `PLACE device` plus the last
  four characters of its stable identifier;
- manufacturer is Gentex;
- model and firmware use discovery metadata when present;
- suggested area uses the discovered location when present; and
- configuration URL is omitted unless a real, device-specific URL is verified.

Entity unique IDs combine the account identity, stable device identifier, and entity
description key. Entity names use Home Assistant's entity naming model and
translations.

### 8.1 Safety alarms

For each SDK alarm field—smoke, carbon monoxide, heat, air quality, VOC, and explosive
gas—the integration creates:

- a safety binary sensor with the device class mapped below; and
- a detailed enum sensor with `idle`, `test`, `pre_alarm`, `alarm`,
  `critical_alarm`, and `hushed` options.

The binary sensor is active for `test`, `pre_alarm`, `alarm`, `critical_alarm`, and
`hushed`. It is inactive only for `idle`. `NOT_PRESENT` is unavailable, never active or
clear.

Binary-sensor device classes are explicit: smoke uses `SMOKE`, carbon monoxide uses
`CO`, heat uses `HEAT`, explosive gas uses `GAS`, and air-quality and VOC alarms use
`SAFETY`.

### 8.2 Other binary sensors

- Motion: active for 30 seconds after the latest `motionDetected` event.
- Battery pre-low warning: direct SDK boolean with device class `BATTERY`.
- Chatty mode: direct SDK boolean with no device class.
- Device connectivity: coordinator liveness result with device class `CONNECTIVITY`.
- Temperature alert and humidity alert: active when the SDK's numeric status is
  non-zero; unavailable when absent; device class `PROBLEM`.
- Device fault and end-of-life: active when a reported numeric health flag is non-zero.
  They use device class `PROBLEM`. The unmodified health mapping is exposed as entity
  attributes. Unknown value types do not get coerced. A mapping containing any
  non-numeric value is unavailable unless another numeric flag is non-zero and proves
  the problem active. An absent or empty mapping is unavailable. A non-empty mapping
  whose numeric flags are all zero is inactive.

The account connection binary sensor belongs to the config entry rather than a
physical device and uses device class `CONNECTIVITY`. Motion uses `MOTION`; the
night-light reported-state sensor uses `LIGHT`.

### 8.3 Numeric and enum sensors

| SDK value | Home Assistant representation |
|---|---|
| Alarm status fields | Enum sensor, as defined above |
| `co_ppm` | Carbon monoxide concentration in ppm |
| `methane_ppm` | Methane concentration in ppm |
| `temperature_c` | Temperature in °C |
| `board_temp_c` | Temperature in °C |
| `humidity` | Relative humidity in % |
| `wifi_signal_strength` | Signal strength in dBm |
| `co_accumulation` | Raw numeric sensor; no invented unit |
| Four optical scatter values | Raw numeric sensors; no invented unit |
| `battery_status` | Raw status sensor; not battery percentage |
| `motion_sensitivity` | Raw numeric sensor; no invented scale |
| Temperature and humidity alert status | Raw numeric detail sensors |
| Night-light red, green, blue, and alpha | Raw numeric channel sensors |

The night-light `on` value is a read-only binary sensor. It is not a `light` entity
because this release cannot control it.

All supported entities are enabled by default, including low-level telemetry. A value
of `None` or `NOT_PRESENT` makes that entity unavailable. A real numeric zero or false
boolean remains a valid state. The integration never substitutes zero, `idle`, or
`off` for absent data.

## 9. Errors, logging, and repairs

- Setup maps confirmed auth errors to reauthentication, transient cloud errors to
  retry, and unsupported or empty discovery data to clear config-flow errors.
- Runtime MQTT failures mark the account unavailable while the SDK reconnects with
  backoff. Last state remains visible but unavailable.
- A refresh publish attempted while disconnected is expected transient failure; it
  must not kill the coordinator timer.
- Entity accessors tolerate an optional field disappearing on a later partial or
  malformed update.
- Unknown alarm enum values remain unavailable through the SDK's `NOT_PRESENT` value.
- Logs record lifecycle transitions, error types, retry state, and counts. They do not
  include usernames, tokens, AWS keys, MQTT topics, thing names, device IDs, household
  IDs, MFA codes, raw payloads, or full cloud responses.
- Reauthentication uses Home Assistant's standard config-entry flow; the integration
  does not create a duplicate repair for it. Repairs are created only when Home
  Assistant can offer another concrete user action. Ordinary cloud outages stay in
  logs and availability state.

The SDK's exception and logging paths must receive the same secret review. An SDK log
that includes a server response or bearer value blocks release even if integration
logging is clean.

## 10. Diagnostics and privacy

Diagnostics include only data needed to debug the adapter:

- integration, Home Assistant, and SDK versions;
- connection and setup state;
- device count;
- redacted per-device model, firmware, entity availability, and liveness age;
- coordinator timing constants; and
- sanitized error class names.

Diagnostics redact or omit username, refresh/access/ID tokens, temporary IoT
credentials, account identity, device IDs, thing names, household IDs, location,
device names, MQTT topics, and raw payloads. Tests seed every sensitive field with a
distinct canary and assert that none appear in serialized diagnostics or captured
logs.

## 11. Testing

Production code follows TDD: write a failing behavior test, confirm the intended
failure, implement the smallest change, and run the focused test again.

### 11.1 Unit tests

- Entity-description completeness and unique IDs.
- Alarm binary and enum semantics, including `NOT_PRESENT`.
- Every numeric field, false/zero preservation, and missing-field availability.
- Motion expiry, repeated motion, and timer cancellation.
- Account and per-device stale availability at exact boundaries.
- Health flag evaluation without coercing unknown types.
- Token adapter load/save behavior and password/MFA non-persistence.
- Diagnostics and log redaction canaries.

### 11.2 Home Assistant integration tests

Use deterministic SDK fakes and sanitized recorded payload fixtures to exercise real
Home Assistant config-flow and config-entry machinery:

- initial login, software-token MFA, SMS MFA, invalid auth, and duplicate accounts;
- cache-only runtime login, invalid-token reauth, transient-auth retry, and proof that
  two fresh sessions for one account return the same account identity;
- setup, platform forwarding, device/entity registry contents, reload, and unload;
- reauthentication success, wrong-account rejection, and token replacement;
- push updates, reconnect, sibling isolation, stale devices, and shadow refresh;
- entity state, units, device classes, enum translation, and availability; and
- diagnostics download and redaction.

Tests use hand-written fakes at the SDK boundary. They do not assert a mocking
framework's behavior or mock Home Assistant internals.

### 11.3 Packaged-system scenarios

Boot a real Home Assistant test instance with the packaged custom component and a
deterministic protocol harness backed by sanitized fixtures. Drive setup through Home
Assistant's config-flow APIs and inspect the real config-entry, device, entity, and
state registries. These scenarios prove packaging and wiring without live credentials.
They are system tests, not a claim that the real PLACE cloud was exercised.

### 11.4 Live end-to-end check

An explicit, opt-in script uses a real PLACE account and the released SDK in read-only
mode. It verifies authentication/MFA, discovery, initial shadow responses, connection
state, at least one live or refreshed update, and clean shutdown. It publishes only
SDK-supported `shadow/get` reads and never device desired state.

The script reads credentials at runtime, writes no capture by default, and sanitizes
its logs. CI never receives live credentials. A release candidate does not ship until
an authorized person records a passing live check outside Git.

### 11.5 Canonical checks

`scripts/check` runs the repository's formatter check, linter, type checker, complete
test suite, manifest validation, and dependency/security checks. CI invokes this
script rather than maintaining a second local command list. Separate official HACS
and Hassfest CI jobs perform repository-aware validation that cannot run fully offline.

Checks produce no new warnings or errors. Expected error logs are captured and
asserted. Pre-existing third-party noise is documented rather than ignored.

## 12. HACS packaging and release

- `hacs.json` lives at the repository root and names Gentex PLACE.
- The repository contains exactly one directory under `custom_components/`.
- The README covers supported devices and entities, installation, UI setup, MFA,
  reauthentication, troubleshooting, diagnostics, removal, privacy, read-only scope,
  and example automations.
- The public GitHub repository has a description, relevant topics, issues enabled,
  and published GitHub Releases. Tags alone are insufficient.
- HACS and Hassfest GitHub Actions pass with no ignored failures.
- The integration ships a licensed `custom_components/gentex_place/brand/icon.png`
  that meets current Home Assistant custom-integration image rules. Brand usage rights
  must be verified before release.
- Release versions use SemVer. The integration manifest version and GitHub release tag
  match.
- `hacs.json` pins the minimum Home Assistant version to the stable release used by
  the release test matrix.
- Release notes list supported Home Assistant and SDK versions and any known limits.

### 12.1 Hard release gates

1. The required async SDK version is published to PyPI and installs on every supported
   Home Assistant Python architecture.
2. The SDK exposes cache-only runtime authentication, distinguishes invalid auth from
   transient auth failure, reports terminal auth state, and passes the secret-log audit.
3. The manifest pins that exact SDK version.
4. `scripts/check`, CI, HACS validation, and Hassfest pass without ignores.
5. The package installs through HACS into a clean current-stable Home Assistant system.
6. The opt-in read-only live check passes against a real PLACE account.
7. Diagnostics and logs contain none of the redaction canaries.
8. The local licensed brand image and repository metadata required for HACS default
   inclusion exist.

## 13. Success criteria

The design succeeds when a user can install a released package through HACS, add one
or more PLACE accounts through the UI with MFA, see one device entry per discovered
unit and all supported entities, receive immediate MQTT changes, see motion clear at
30 seconds, and see a disconnected or stale account/device become unavailable without
losing its last known state.

The integration must reload and unload cleanly, prompt for reauthentication when the
refresh token fails, avoid every device-write path, pass all canonical checks, and
produce diagnostics and logs with no credentials or home identifiers.

## 14. Known limits and recommendation

- **Release blocker:** async SDK `0.3.0` was not on PyPI when this spec was written.
- **Release blocker:** the SDK needs the cache-only and typed runtime-auth contract in
  section 5.4.
- **Medium:** added devices require a config-entry reload before discovery sees them.
- **Low:** low-level values with unverified units remain raw numeric sensors.
- **Planned:** controls wait for proven command and acknowledgement schemas.

Recommendation: ship monitoring only after both blockers clear. Do not weaken the
release gates by pinning a Git checkout or guessing device writes.

## 15. References

- [Home Assistant integration manifest](https://developers.home-assistant.io/docs/creating_integration_manifest/)
- [Home Assistant config flow](https://developers.home-assistant.io/docs/core/integration/config_flow/)
- [Home Assistant integration quality scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/)
- [Home Assistant custom-integration translations](https://developers.home-assistant.io/docs/internationalization/custom_integration/)
- [Home Assistant custom-integration brand images](https://developers.home-assistant.io/docs/core/integration/brand_images/)
- [HACS integration requirements](https://hacs.xyz/docs/publish/integration/)
- [HACS default repository requirements](https://hacs.xyz/docs/publish/include/)
- [place-integration-api on PyPI](https://pypi.org/project/place-integration-api/)
