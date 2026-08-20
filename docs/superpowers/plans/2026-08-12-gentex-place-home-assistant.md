<!-- ABOUTME: Plans the HACS-ready Gentex PLACE integration in test-first steps. -->
<!-- ABOUTME: Uses one immutable public Git SDK commit for HACS distribution. -->
# Gentex PLACE Home Assistant Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only, HACS-compatible Gentex PLACE custom integration with MFA setup, multiple accounts, push updates, health refreshes, complete supported entities, safe diagnostics, and release checks.

**Architecture:** One typed `GentexPlaceCoordinator` owns one async SDK client per config entry. The SDK's mutable device registry is the single source of truth; MQTT callbacks and a fixed health timer notify `CoordinatorEntity` views. Config flows store only username, refresh token, and stable account identity.

**Tech Stack:** Python 3.14.2, Home Assistant 2026.8.1, `place-integration-api@git+https://github.com/harperreed/place-integration-api.git@7f9f6bb6e4f5aeaae99cae30aa40a1bb3b5005ad`, asyncio/aiohttp, pytest-homeassistant-custom-component 0.13.355, pytest, Ruff, basedpyright, uv, Hassfest, HACS Action.

## Global Constraints

- Work on branch `wip/gentex-place-integration`; preserve unrelated changes and the approved spec.
- Domain is permanently `gentex_place`; display name is `Gentex PLACE`; code owner is `@harperreed`.
- Minimum supported Home Assistant is `2026.8.1`; Python floor is `3.14.2`. CI tests
  that minimum and a scheduled latest-stable resolver, but does not promise unknown
  future releases before they are tested.
- The manifest and development dependency always use
  `place-integration-api@git+https://github.com/harperreed/place-integration-api.git@7f9f6bb6e4f5aeaae99cae30aa40a1bb3b5005ad`.
  `uv.lock` resolves that public HTTPS Git source at the same full SHA with no sibling
  directory source.
- Task 9 may begin after `2026-08-19-git-sdk-dependency.md` is complete. Do not fake
  public SDK methods or inspect SDK private fields.
- First release is read-only: no desired-state publish, commands, control entities, or services.
- Store username, refresh token, and account identity only. Never persist password, MFA code, access/ID token, temporary AWS keys, or raw payloads.
- Fixed timings: health refresh 5 minutes; stale timeout 15 minutes; motion window 30 seconds; initial connection/shadow deadline 30 seconds.
- All supported entities are enabled by default. Missing values stay unavailable; zero and false remain real values.
- Automated tests use hand-written SDK fakes and sanitized fixtures. They never use live credentials or mock Home Assistant internals.
- Hand-written source files begin with two `ABOUTME:` comment lines. Generated JSON, fixtures, data files, and workflow YAML do not.
- Run `scripts/check` before each completion claim. Never bypass hooks or ignored HACS/Hassfest failures.

## File map

| File | One responsibility |
|---|---|
| `custom_components/gentex_place/__init__.py` | Config-entry setup, unload, and typed runtime data |
| `auth.py` | Config-entry token-cache adapter and SDK auth/client factories |
| `config_flow.py` | User, MFA, duplicate-account, and reauth flows |
| `const.py` | Domain, entry keys, platforms, and fixed timing constants |
| `coordinator.py` | SDK lifecycle, push callbacks, health timer, motion timers, and availability |
| `entity.py` | Shared per-device entity identity, device info, and availability |
| `binary_sensor.py` | Alarm, motion, health, mode, and connectivity entities |
| `sensor.py` | Alarm-detail and numeric entities |
| `diagnostics.py` | Explicit allow-list diagnostics with no identifiers or secrets |
| `translations/en.json` | Full config-flow, exception, entity, and enum English text |
| `brand/icon.png` | Licensed local brand image for Home Assistant and HACS |
| `tests/components/gentex_place/fakes.py` | Hand-written SDK boundary fakes |
| `tests/components/gentex_place/conftest.py` | Home Assistant fixtures and sample devices |
| Test modules | One behavior group each; no production mock modes |
| `scripts/check` | Canonical local and CI verification |
| `scripts/live_check.py` | Opt-in read-only real-account release check |
| `hacs.json`, workflows, README | HACS packaging, CI, and user docs |

## Execution preflight

```bash
cd /Users/harper/Public/src/personal/gentex-places-ha
git status --short --branch
test "$(git branch --show-current)" = "wip/gentex-place-integration"
uv python install 3.14.2
scripts/check_sdk_dependency
```

Expected: the approved spec is committed, only planned files are changed, and the
approved public SDK commit and required imports are verified.

---

### Task 1: Reproducible project and token store

**State:** Complete in HA commits `7a197cd` and `c3e3c6e`; spec and quality reviews approved. Development uses local SDK `7f9f6bb`.

**Files:**
- Create: `pyproject.toml`
- Create: `uv.lock`
- Create: `.python-version`
- Create: `.gitignore`
- Create: `LICENSE`
- Create: `hacs.json`
- Create: `custom_components/gentex_place/__init__.py`
- Create: `custom_components/gentex_place/const.py`
- Create: `custom_components/gentex_place/auth.py`
- Create: `custom_components/gentex_place/manifest.json`
- Create: `tests/conftest.py`
- Create: `tests/components/gentex_place/test_auth.py`

**Interfaces:**
- Consumes: SDK `TokenCache`, `CognitoAuth`, `PlaceClient`, `PlaceConfig`.
- Produces: `MemoryTokenCache`, `ConfigEntryTokenCache`, `create_auth(hass, token_cache)`, `create_client(auth)`, constants, and typed `GentexPlaceConfigEntry` placeholder.

- [x] **Step 1: Create the minimal test environment**

Create `pyproject.toml`:

```toml
[project]
name = "gentex-place-home-assistant"
version = "0.1.0"
requires-python = ">=3.14.2"
dependencies = []

[dependency-groups]
dev = [
  "basedpyright==1.39.9",
  "pip-audit==2.10.1",
  "place-integration-api==0.3.0",
  "pytest-cov==7.1.0",
  "pytest-homeassistant-custom-component==0.13.355",
  "ruff==0.16.2",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
testpaths = ["tests"]

[tool.ruff]
target-version = "py314"
line-length = 88

[tool.ruff.lint]
select = ["ALL"]
ignore = ["ANN401", "COM812", "D203", "D213"]

[tool.basedpyright]
pythonVersion = "3.14"
typeCheckingMode = "standard"
include = ["custom_components/gentex_place", "tests"]

[tool.uv.sources]
place-integration-api = { path = "../place-integration-api", editable = false }
```

Create `tests/conftest.py`:

```python
# ABOUTME: Enables Home Assistant's custom-integration pytest fixtures and loader.
# ABOUTME: Shared Gentex PLACE fixtures live under the component test package.
import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield
```

Run:

```bash
uv sync
uv lock
```

Expected: dependency resolution succeeds on Python 3.14 and the locked non-editable
local SDK reports version `0.3.0`.

- [x] **Step 2: Write failing token-cache tests**

Create `tests/components/gentex_place/test_auth.py`:

```python
# ABOUTME: Verifies config-entry refresh-token persistence and auth factories.
# ABOUTME: Passwords and short-lived cloud credentials must never enter entry data.
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.gentex_place.auth import ConfigEntryTokenCache, MemoryTokenCache
from custom_components.gentex_place.const import (
    CONF_ACCOUNT_ID,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)


def test_token_cache_round_trip_updates_only_refresh_token(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"username": "alice", CONF_REFRESH_TOKEN: "old", CONF_ACCOUNT_ID: "acct"},
    )
    entry.add_to_hass(hass)
    cache = ConfigEntryTokenCache(hass, entry)

    assert cache.load() == {"username": "alice", "refresh_token": "old"}
    cache.save({"username": "alice", "refresh_token": "new", "password": "CANARY"})

    assert entry.data == {
        "username": "alice",
        CONF_REFRESH_TOKEN: "new",
        CONF_ACCOUNT_ID: "acct",
    }


def test_token_cache_clear_removes_only_refresh_token(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"username": "alice", CONF_REFRESH_TOKEN: "old", CONF_ACCOUNT_ID: "acct"},
    )
    entry.add_to_hass(hass)

    ConfigEntryTokenCache(hass, entry).clear()

    assert entry.data == {"username": "alice", CONF_ACCOUNT_ID: "acct"}


def test_memory_token_cache_keeps_only_sdk_token_fields() -> None:
    cache = MemoryTokenCache()
    cache.save(
        {
            "username": "alice",
            "refresh_token": "refresh",
            "password": "PASSWORD-CANARY",
        }
    )

    assert cache.load() == {"username": "alice", "refresh_token": "refresh"}
```

- [x] **Step 3: Run tests and confirm missing integration files**

Run: `uv run pytest tests/components/gentex_place/test_auth.py -q`

Expected: collection FAIL because `custom_components.gentex_place` does not exist.

- [x] **Step 4: Implement constants, manifest, token adapter, and factories**

Create `const.py` with:

```python
# ABOUTME: Shared Gentex PLACE integration keys, platforms, and fixed timers.
# ABOUTME: Protocol field names remain in the standalone PLACE SDK.
from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "gentex_place"
MANUFACTURER = "Gentex"
CONF_ACCOUNT_ID = "account_id"
CONF_REFRESH_TOKEN = "refresh_token"
PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]
HEALTH_INTERVAL = timedelta(minutes=5)
STALE_AFTER_SECONDS = 15 * 60
MOTION_WINDOW_SECONDS = 30
STARTUP_TIMEOUT_SECONDS = 30
```

Create `auth.py` with this public surface:

```python
# ABOUTME: Adapts Home Assistant config entries to the PLACE SDK auth interfaces.
# ABOUTME: Persists only username and refresh token and builds clients with HA's session.
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from place import CognitoAuth, PlaceClient, PlaceConfig

from .const import CONF_REFRESH_TOKEN


class MemoryTokenCache:
    def __init__(self) -> None:
        self._data: dict[str, Any] | None = None

    def load(self) -> dict[str, Any] | None:
        return dict(self._data) if self._data is not None else None

    def save(self, data: dict[str, Any]) -> None:
        username = data.get("username")
        token = data.get("refresh_token")
        if isinstance(username, str) and isinstance(token, str) and token:
            self._data = {"username": username, "refresh_token": token}

    def clear(self) -> None:
        self._data = None


class ConfigEntryTokenCache:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry

    def load(self) -> dict[str, Any] | None:
        token = self._entry.data.get(CONF_REFRESH_TOKEN)
        username = self._entry.data.get("username")
        if not isinstance(username, str) or not isinstance(token, str) or not token:
            return None
        return {"username": username, "refresh_token": token}

    def save(self, data: dict[str, Any]) -> None:
        token = data.get("refresh_token")
        if isinstance(token, str) and token:
            self._hass.config_entries.async_update_entry(
                self._entry, data={**self._entry.data, CONF_REFRESH_TOKEN: token}
            )

    def clear(self) -> None:
        data = dict(self._entry.data)
        data.pop(CONF_REFRESH_TOKEN, None)
        self._hass.config_entries.async_update_entry(self._entry, data=data)


def create_auth(hass: HomeAssistant, token_cache: MemoryTokenCache | ConfigEntryTokenCache) -> CognitoAuth:
    return CognitoAuth(
        PlaceConfig(),
        async_get_clientsession(hass),
        token_cache=token_cache,
    )


def create_client(auth: CognitoAuth) -> PlaceClient:
    return PlaceClient.create(PlaceConfig(), auth)
```

Create `manifest.json` with version `0.1.0`, `cloud_push`, `hub`, config flow, repo URLs, `@harperreed`, and exact requirement `place-integration-api==0.3.0`. Create an empty lifecycle `__init__.py` with its required `ABOUTME:` header. Create root `hacs.json` as `{"name": "Gentex PLACE", "homeassistant": "2026.8.1"}`, `.python-version` as `3.14`, and copy the SDK repository's MIT license text into `LICENSE` after verifying its copyright wording.

- [x] **Step 5: Verify and commit**

Run:

```bash
uv run pytest tests/components/gentex_place/test_auth.py -q
uv run ruff check custom_components tests
uv run basedpyright
git diff --check
```

Expected: PASS.

```bash
git status --short
git add pyproject.toml uv.lock .python-version .gitignore LICENSE hacs.json custom_components tests
git commit -m "feat: add Gentex PLACE integration foundation"
```

---

### Task 2: User, MFA, duplicate-account, and reauth config flow

**State:** Complete in HA commits `68f4843`, `fc4a67c`, and `c2a3376`, with SDK timeout normalization in `ac9bf45`. Spec and quality reviews approved; 106 HA tests and 234 SDK tests pass. The Home Assistant 2026.8.1 test dependency pin on vulnerable `cryptography==48.0.1` remains a release gate, not a Task 2 code failure.

**Files:**
- Create: `custom_components/gentex_place/config_flow.py`
- Create: `custom_components/gentex_place/translations/en.json`
- Create: `tests/components/gentex_place/fakes.py`
- Create: `tests/components/gentex_place/test_config_flow.py`

**Interfaces:**
- Consumes: `CognitoAuth.authenticate(username, password)`, `submit_mfa(code)`, `async_get_iot_credentials()`, `PlaceClient.async_discover()`, typed SDK errors, and token-cache `load()`.
- Produces: config entries containing `username`, `refresh_token`, and `account_id`; user/MFA/reauth flow steps.

- [x] **Step 1: Build hand-written auth/client fakes and failing happy-path test**

In `fakes.py`, define `FakeAuth` with scripted `authenticate`, `submit_mfa`, and `async_get_iot_credentials`, plus a cache save of `{"username": ..., "refresh_token": "refresh-1"}` after success. Define `FakeClient.async_discover()` returning a supplied `DiscoverDevice` list. Counters must record calls and values without logging passwords or codes.

In `test_config_flow.py`:

```python
async def test_user_flow_stores_refresh_token_not_password(
    hass, mock_place_auth, mock_place_client
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": "alice", "password": "PASSWORD-CANARY"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        "username": "alice",
        CONF_REFRESH_TOKEN: "refresh-1",
        CONF_ACCOUNT_ID: "identity-1",
    }
    assert "PASSWORD-CANARY" not in repr(result)
```

- [x] **Step 2: Add failing MFA, duplicate, error, and reauth scenarios**

Add separate tests asserting:

```python
# authenticate raises MfaRequired -> FORM step_id "mfa"
# submit bad code raises PlaceInvalidAuthError -> same form, invalid_mfa
# valid code -> CREATE_ENTRY with no password/code
# second login returning identity-1 -> ABORT already_configured
# PlaceInvalidAuthError on login -> user form invalid_auth
# PlaceTransientAuthError/PlaceDiscoveryError -> user form cannot_connect
# empty discovery -> user form no_devices
# reauth returning identity-1 -> ABORT reauth_successful and new token stored
# reauth returning identity-2 -> ABORT wrong_account and old entry unchanged
```

Use `FlowResultType` and inspect exact result data; never patch `hass.config_entries.flow` internals.

- [x] **Step 3: Run tests and confirm the flow is absent**

Run: `uv run pytest tests/components/gentex_place/test_config_flow.py -q`

Expected: FAIL because `config_flow.py` is absent.

- [x] **Step 4: Implement the flow**

Create `GentexPlaceConfigFlow(ConfigFlow, domain=DOMAIN)` with `VERSION = 1`. Keep `_auth`, `_client`, `_username`, `_token_cache`, and `_reauth_entry` only on the live flow object. Never retain the password or MFA code on the flow object. Use:

```python
USER_SCHEMA = vol.Schema(
    {vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str}
)
MFA_SCHEMA = vol.Schema({vol.Required("mfa_code"): str})
```

After interactive auth/MFA, call `async_get_iot_credentials()` for `identity_id`, call public `async_discover()`, and read the saved refresh token from the in-memory flow cache. Then:

```python
await self.async_set_unique_id(identity_id)
self._abort_if_unique_id_configured()
return self.async_create_entry(
    title=safe_entry_title(
        entry.title
        for entry in self.hass.config_entries.async_entries(DOMAIN)
    ),
    data={
        CONF_USERNAME: self._username,
        CONF_REFRESH_TOKEN: refresh_token,
        CONF_ACCOUNT_ID: identity_id,
    },
)
```

For reauth, use `_get_reauth_entry()`, `await self.async_set_unique_id(identity_id)`, `_abort_if_unique_id_mismatch()`, and `async_update_reload_and_abort(..., data_updates=...)`. Use standard result keys `invalid_auth`, `invalid_mfa`, `cannot_connect`, `no_devices`, `already_configured`, `wrong_account`, and `reauth_successful` in `translations/en.json`. Custom integrations do not ship `strings.json`; write full English strings with no core-build placeholders.

- [x] **Step 5: Verify and commit**

Run:

```bash
uv run pytest tests/components/gentex_place/test_config_flow.py -q
uv run ruff check custom_components tests
uv run basedpyright
```

Expected: every flow scenario PASS and captured entry data contains no password/MFA.

```bash
git add custom_components/gentex_place/config_flow.py custom_components/gentex_place/translations/en.json tests/components/gentex_place
git commit -m "feat: add PLACE account setup and reauth"
```

---

### Task 3: Coordinator lifecycle, push updates, and health timing

**State:** Complete in HA commits `45293e7` and `0c29032`, with SDK shutdown-cancellation fixes in `14b64d6` and `7f9f6bb`. Spec and quality reviews approved. Fresh verification passes 145 HA tests and 237 SDK tests; both type and lint gates report zero findings.

**Files:**
- Modify: `custom_components/gentex_place/__init__.py`
- Create: `custom_components/gentex_place/coordinator.py`
- Create: `custom_components/gentex_place/binary_sensor.py` (loadable staged entry point)
- Create: `custom_components/gentex_place/sensor.py` (loadable staged entry point)
- Modify: `tests/components/gentex_place/fakes.py`
- Create: `tests/components/gentex_place/test_init.py`
- Create: `tests/components/gentex_place/test_coordinator.py`

**Interfaces:**
- Consumes: `authenticate_from_cache`, `PlaceClient.start/stop`, `devices`, `connected`, `on_update`, `on_event`, `on_connection_change`, `on_error`, `async_refresh_shadow`.
- Produces: `GentexPlaceRuntimeData`, `GentexPlaceConfigEntry`, `GentexPlaceCoordinator`, `device_available()`, `motion_active()`, setup/unload.

- [x] **Step 1: Add lifecycle and timer tests**

Write tests using a `FakePlaceClient` that owns real SDK `PlaceDevice` objects and explicit emit methods. Cover:

```python
# setup authenticates from cache before start and registers on_error before start
# PlaceInvalidAuthError during cache login -> ConfigEntryAuthFailed
# PlaceTransientAuthError/PlaceDiscoveryError/PlaceConnectionError -> ConfigEntryNotReady
# setup waits for connected + one last_shadow_at, bounded at 30 seconds
# one answering device allows setup; silent sibling remains unavailable
# device update and connection change notify coordinator listeners
# health callback every 5 minutes calls async_refresh_shadow once for all devices
# device available at age 900 and stale at age 900.001
# motion true through 30 seconds, repeated event replaces clear timer
# invalid runtime auth calls entry.async_start_reauth(hass) once
# transient or unknown runtime auth does not start reauth
# unload cancels timers/listeners and awaits client.stop
```

Patch monotonic time and Home Assistant's time helpers; do not sleep in tests.

- [x] **Step 2: Run and confirm missing coordinator/lifecycle**

Run:

```bash
uv run pytest tests/components/gentex_place/test_init.py tests/components/gentex_place/test_coordinator.py -q
```

Expected: FAIL on missing runtime/coordinator code.

- [x] **Step 3: Implement typed runtime data and setup**

In `coordinator.py`:

```python
type DeviceMap = dict[str, PlaceDevice]


class GentexPlaceCoordinator(DataUpdateCoordinator[DeviceMap]):
    def __init__(self, hass, entry, client) -> None:
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=HEALTH_INTERVAL,
            always_update=False,
        )
        self.client = client
        self.data = client.devices
```

Register all callbacks before `client.start()`. Override `async_set_updated_data()` with `@callback` and `@override` to assign `self.data`, set `last_update_success = True`, and call `async_update_listeners()` without touching the scheduled refresh handle; default coordinator behavior would reset the five-minute health clock on every push. `_async_update_data()` calls `await client.async_refresh_shadow()` and returns `client.devices`; it catches a disconnected `PlaceConnectionError` as `UpdateFailed` without ending future intervals. Invalid runtime auth becomes `ConfigEntryAuthFailed` during setup; after setup, call `entry.async_start_reauth(hass)` once per outage. Transient and unclassified `PlaceAuthError` notifications keep reconnecting and never start reauth.

Use Home Assistant's `async_call_later` helper for the 30-second motion notification and Python `asyncio.timeout(STARTUP_TIMEOUT_SECONDS)` for startup. Completion requires `client.connected` and `any(device.last_shadow_at is not None ...)`.

In `__init__.py`, define:

```python
@dataclass
class GentexPlaceRuntimeData:
    coordinator: GentexPlaceCoordinator


type GentexPlaceConfigEntry = ConfigEntry[GentexPlaceRuntimeData]
```

`async_setup_entry` authenticates from cache, starts coordinator/client, assigns `entry.runtime_data`, and forwards `PLATFORMS`. `async_unload_entry` unloads platforms first, then calls coordinator shutdown when successful.

- [x] **Step 4: Verify exact timing and cleanup**

Run:

```bash
uv run pytest tests/components/gentex_place/test_init.py tests/components/gentex_place/test_coordinator.py -q
uv run pytest tests/components/gentex_place -q
uv run basedpyright
```

Expected: PASS; no pending-task warning appears after unload tests.

- [x] **Step 5: Commit**

```bash
git add custom_components/gentex_place/__init__.py custom_components/gentex_place/coordinator.py tests/components/gentex_place
git commit -m "feat: coordinate PLACE push updates and liveness"
```

---

### Task 4: Shared entity identity and availability

**State:** Complete in commits `e57d20f` and `22ca827`. Doctor Biz chose the
required thing name as the sole stable device identity; optional device IDs never
change registry identity. Spec and quality reviews approved. Fresh verification
passes all 164 integration tests with zero type or lint findings.

**Files:**
- Create: `custom_components/gentex_place/entity.py`
- Create: `tests/components/gentex_place/test_entity.py`

**Interfaces:**
- Consumes: coordinator and SDK `PlaceDevice` metadata.
- Produces: `GentexPlaceDeviceEntity`, `GentexPlaceAccountEntity`, `stable_device_id(device)`.

- [x] **Step 1: Write failing identity/device-info tests**

Assert these exact rules:

```python
assert entity.unique_id == "identity-1_thing-1_temperature"
assert entity.device_info.identifiers == {(DOMAIN, "identity-1:thing-1")}
assert entity.device_info.manufacturer == "Gentex"
assert entity.device_info.name == "Hallway"
assert entity.device_info.model == "PL1AS"
assert entity.device_info.sw_version == "1.2.3"
assert entity.device_info.suggested_area == "Hallway"
```

Also cover identity stability when an optional device ID appears or disappears,
fallback display name `PLACE device cdef`, percent escaping of `%`, `_`, and `:`,
normal entity unavailable when account is down or shadow is stale, and
connectivity-entity subclasses remaining available while the entry is loaded.

- [x] **Step 2: Run and confirm failure**

Run: `uv run pytest tests/components/gentex_place/test_entity.py -q`

Expected: FAIL because entity base classes are missing.

- [x] **Step 3: Implement the two base classes**

`GentexPlaceDeviceEntity(CoordinatorEntity[GentexPlaceCoordinator])` sets
`_attr_has_entity_name = True`, reads its live device from
`coordinator.data[device_key]`, uses the required thing name for account-scoped
registry identifiers and unique IDs, percent-escapes opaque identifier components,
and overrides `available` with coordinator device liveness.
`GentexPlaceAccountEntity` uses the account identity for unique ID and has no
physical `DeviceInfo`. Add a protected `describes_connectivity` flag so connectivity
subclasses override `available` to `True` while loaded.

- [x] **Step 4: Verify and commit**

Run:

```bash
uv run pytest tests/components/gentex_place/test_entity.py -q
uv run ruff check custom_components/gentex_place/entity.py tests/components/gentex_place/test_entity.py
uv run basedpyright
```

Expected: PASS.

```bash
git add custom_components/gentex_place/entity.py tests/components/gentex_place/test_entity.py
git commit -m "feat: add PLACE entity identity and availability"
```

---

### Task 5: Safety alarm entities

**State:** Complete in commits `a3b13f2` and `9ed07a0`. Spec and quality
reviews approved. Fresh verification passes 95 focused alarm tests and all 259
integration tests with zero type or lint findings. The loaded-state regression
proves push transitions and sibling-device isolation through Home Assistant.

**Files:**
- Modify: `custom_components/gentex_place/binary_sensor.py`
- Modify: `custom_components/gentex_place/sensor.py`
- Modify: `custom_components/gentex_place/translations/en.json`
- Create: `tests/components/gentex_place/test_alarms.py`

**Interfaces:**
- Consumes: `AlarmStatus`, entity bases, coordinator device map.
- Produces: six binary alarm entities and six enum-detail entities per supported device value.

- [x] **Step 1: Write table-driven failing alarm tests**

Parameterize all six SDK attributes and device classes:

```python
(
    ("smoke_alarm_status", BinarySensorDeviceClass.SMOKE),
    ("co_alarm_status", BinarySensorDeviceClass.CO),
    ("heat_alarm_status", BinarySensorDeviceClass.HEAT),
    ("aqi_alarm_status", BinarySensorDeviceClass.SAFETY),
    ("voc_alarm_status", BinarySensorDeviceClass.SAFETY),
    ("explosive_gas_alarm_status", BinarySensorDeviceClass.GAS),
)
```

For every attribute assert binary `IDLE=False`; `TEST`, `PRE_ALARM`, `ALARM`, `CRITICAL_ALARM`, `HUSHED=True`; `NOT_PRESENT` gives `is_on is None` and entity unavailable. Assert the matching sensor has device class `ENUM`, exact options `idle`, `test`, `pre_alarm`, `alarm`, `critical_alarm`, `hushed`, and `native_value` matching the lowercase enum name.

- [x] **Step 2: Run and confirm missing platforms**

Run: `uv run pytest tests/components/gentex_place/test_alarms.py -q`

Expected: FAIL because platform entity descriptions are absent.

- [x] **Step 3: Implement reusable alarm descriptions**

Define frozen description subclasses carrying `value_fn: Callable[[PlaceDevice], AlarmStatus]`. Generate binary and enum entity lists from one shared six-item alarm metadata tuple so labels and field mappings cannot drift. Platform `async_setup_entry` adds every alarm description for every discovered device. An initial or later `NOT_PRESENT` value makes that entity unavailable rather than omitting or deleting it.

- [x] **Step 4: Add translation keys and verify loaded HA states**

Add English names and enum values to `translations/en.json`. Extend tests to load
the config entry and assert registry/state creation and live push transitions, not
only Python properties.

Run:

```bash
uv run pytest tests/components/gentex_place/test_alarms.py -q
uv run basedpyright
```

Expected: PASS for all 84 alarm property cases plus registry and push assertions.

- [x] **Step 5: Commit**

```bash
git add custom_components/gentex_place/binary_sensor.py custom_components/gentex_place/sensor.py custom_components/gentex_place/translations/en.json tests/components/gentex_place/test_alarms.py
git commit -m "feat: expose detailed PLACE safety alarms"
```

---

### Task 6: Motion, connectivity, health, and mode binary sensors

**State:** Complete in commits `f64a45d` and `bfaad2f`. Spec and quality
reviews approved. Fresh verification passes all 303 integration tests with zero
type or lint findings. Loaded-state tests exposed and now prevent motion timer
callbacks from writing entity state through an executor thread.

**Files:**
- Modify: `custom_components/gentex_place/binary_sensor.py`
- Modify: `custom_components/gentex_place/translations/en.json`
- Create: `tests/components/gentex_place/test_binary_sensor.py`

**Interfaces:**
- Consumes: coordinator `motion_active`, account/device availability, SDK booleans and health maps.
- Produces: account/device connectivity, motion, battery warning, chatty mode, alerts, faults, end-of-life, and night-light state.

- [x] **Step 1: Write failing entity-matrix tests**

Assert these mappings and values:

```python
# account/device connectivity -> CONNECTIVITY and remains available while false
# motion -> MOTION
# battery_low_pre_warning -> BATTERY
# in_chatty_mode -> no device class
# temperature/humidity alert nonzero -> PROBLEM; zero false; None unavailable
# faults/end_of_life -> PROBLEM with raw mapping attributes
# all-numeric zero map false; any numeric nonzero true
# empty map unavailable; unknown-only map unavailable
# unknown plus numeric nonzero true
# night_light.on -> LIGHT; None unavailable
```

Assert false is preserved and every description creates an enabled entity even when its initial value is absent.

- [x] **Step 2: Run and confirm failure**

Run: `uv run pytest tests/components/gentex_place/test_binary_sensor.py -q`

Expected: FAIL on missing descriptions/entities.

- [x] **Step 3: Implement descriptions and health evaluation**

Use one pure helper:

```python
def health_problem(value: dict[str, object] | None) -> bool | None:
    if not value:
        return None
    numeric = [item for item in value.values() if type(item) in (int, float)]
    if any(item != 0 for item in numeric):
        return True
    if len(numeric) != len(value):
        return None
    return False
```

Do not treat `bool` as numeric. Entity extra attributes return a shallow copy of the SDK mapping. Connectivity entities use the base-class exception from Task 4.

- [x] **Step 4: Verify and commit**

Run:

```bash
uv run pytest tests/components/gentex_place/test_binary_sensor.py tests/components/gentex_place/test_coordinator.py -q
uv run ruff check custom_components tests
uv run basedpyright
```

Expected: PASS.

```bash
git add custom_components/gentex_place/binary_sensor.py custom_components/gentex_place/translations/en.json tests/components/gentex_place/test_binary_sensor.py
git commit -m "feat: expose PLACE device status sensors"
```

---

### Task 7: Complete numeric telemetry sensors

**State:** Complete in commit `fe2746f`. Spec and quality reviews approved.
Fresh verification passes all 347 integration tests with zero type, lint, or
Home Assistant sensor-validation findings.

**Files:**
- Modify: `custom_components/gentex_place/sensor.py`
- Modify: `custom_components/gentex_place/translations/en.json`
- Create: `tests/components/gentex_place/test_sensor.py`

**Interfaces:**
- Consumes: supported numeric fields from `PlaceDevice.shadow`.
- Produces: all numeric sensors in spec section 8.3.

- [x] **Step 1: Write one parameterized field-contract test**

Use a table with exact attribute, device class, unit, and state class:

```python
TELEMETRY_CASES = (
    ("co_ppm", SensorDeviceClass.CO, UnitOfRatio.PARTS_PER_MILLION),
    ("methane_ppm", None, UnitOfRatio.PARTS_PER_MILLION),
    ("temperature_c", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS),
    ("board_temp_c", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS),
    ("humidity", SensorDeviceClass.HUMIDITY, PERCENTAGE),
    ("wifi_signal_strength", SensorDeviceClass.SIGNAL_STRENGTH, SIGNAL_STRENGTH_DECIBELS_MILLIWATT),
    ("co_accumulation", None, None),
    ("blue_front_scatter", None, None),
    ("blue_back_scatter", None, None),
    ("ir_front_scatter", None, None),
    ("ir_back_scatter", None, None),
    ("battery_status", None, None),
    ("motion_sensitivity", None, None),
    ("temperature_alert_status", None, None),
    ("humidity_alert_status", None, None),
)
```

Add four night-light channel cases. Assert every known value, real zero, `None` availability, enabled-by-default registry state, and that battery status has no battery device class or percent unit.

- [x] **Step 2: Run and confirm missing telemetry**

Run: `uv run pytest tests/components/gentex_place/test_sensor.py -q`

Expected: FAIL because telemetry descriptions are absent.

- [x] **Step 3: Implement data-driven telemetry entities**

Define a frozen sensor description with `value_fn`. Use `SensorStateClass.MEASUREMENT` only for fields with verified physical units; leave raw status/scatter/sensitivity/alert/channel values without a state class. Mark board temperature, optical scatter, battery raw status, motion sensitivity, raw alert codes, and RGBA channels as `EntityCategory.DIAGNOSTIC` while keeping `entity_registry_enabled_default=True`, as Doctor Biz requested. For nested night-light values, return `None` when the `NightLight` block is absent. Do not coerce or round SDK values.

- [x] **Step 4: Verify and commit**

Run:

```bash
uv run pytest tests/components/gentex_place/test_sensor.py tests/components/gentex_place/test_alarms.py -q
uv run basedpyright
```

Expected: PASS for the full supported field matrix.

```bash
git add custom_components/gentex_place/sensor.py custom_components/gentex_place/translations/en.json tests/components/gentex_place/test_sensor.py
git commit -m "feat: expose PLACE telemetry sensors"
```

---

### Task 8: Allow-list diagnostics and secret-log regression tests

**State:** Complete in commits `c8ea64d`, `9fa1e0f`, and `383b9bd`.
Spec and quality reviews approved. Fresh verification passes all 369 integration
tests with zero type or lint findings. Canary regressions cover diagnostics,
Home Assistant logs, tracebacks, frame-local coordinator state, setup, refresh,
startup callbacks, and shutdown.

**Files:**
- Create: `custom_components/gentex_place/diagnostics.py`
- Create: `tests/components/gentex_place/test_diagnostics.py`

**Interfaces:**
- Consumes: config entry, coordinator, SDK version.
- Produces: `async_get_config_entry_diagnostics(hass, entry) -> dict[str, Any]` containing no stored secrets or home identifiers.

- [x] **Step 1: Write canary leakage tests**

Seed distinct canaries in username, refresh token, account identity, device ID,
thing name, device name, location, MQTT topic, raw payload, access token, ID token,
and AWS keys. Serialize diagnostics and captured logs with
`json.dumps(..., default=str)`. Assert every canary is absent while these safe
values remain:

```python
assert diagnostics["integration_version"] == "0.1.0"
assert diagnostics["sdk_version"] == "0.3.0"
assert diagnostics["connected"] is True
assert diagnostics["device_count"] == 1
assert diagnostics["devices"][0]["model"] == "PL1AS"
assert diagnostics["devices"][0]["firmware"] == "1.2.3"
assert diagnostics["timing"]["health_interval_seconds"] == 300
assert diagnostics["timing"]["stale_after_seconds"] == 900
```

- [x] **Step 2: Run and confirm missing diagnostics**

Run: `uv run pytest tests/components/gentex_place/test_diagnostics.py -q`

Expected: FAIL because `diagnostics.py` is absent.

- [x] **Step 3: Implement from an explicit allow list**

Return a newly built dictionary. Read the integration version from `await homeassistant.loader.async_get_integration(hass, DOMAIN)` so `manifest.json` remains its only source; read the SDK version from `place.__version__`. Do not call `entry.as_dict()`, `asdict(device)`, or SDK raw-data serializers. Per-device output may contain model, firmware, a boolean availability value, and liveness age rounded to whole seconds. Include only error class names, never exception text. Use enumeration indexes rather than device identifiers as keys.

- [x] **Step 4: Audit logs and verify**

Search production logging calls:

```bash
rg -n "LOGGER\.|logging\." custom_components/gentex_place ../place-integration-api/src/place
```

Add a captured-log assertion for every error path touched by setup/coordinator tests. Then run:

```bash
uv run pytest tests/components/gentex_place/test_diagnostics.py tests/components/gentex_place/test_init.py tests/components/gentex_place/test_coordinator.py -q
```

Expected: PASS; all canaries absent.

- [x] **Step 5: Commit**

```bash
git add custom_components/gentex_place/diagnostics.py tests/components/gentex_place/test_diagnostics.py
git commit -m "feat: add private PLACE diagnostics"
```

---

### Task 9: Canonical checks and CI validation

**State:** Ready after 2026-08-19-git-sdk-dependency.md is complete

**Files:**
- Create: `scripts/check`
- Create: `.github/workflows/validate.yml`
- Create: `.github/dependabot.yml`
- Create when licensed art is available: `custom_components/gentex_place/brand/icon.png`
- Create with the licensed art: `docs/brand-provenance.md`
- Modify: `pyproject.toml`
- Create: `tests/components/gentex_place/test_manifest.py`

**Interfaces:**
- Consumes: complete integration.
- Produces: one local/CI quality command and HACS/Hassfest checks.

- [ ] **Step 0: Verify the public Git SDK contract**

Run `scripts/check_sdk_dependency` and the focused manifest tests. Inspect
`manifest.json`, `pyproject.toml`, and `uv.lock` to confirm they resolve the public
SDK at `7f9f6bb6e4f5aeaae99cae30aa40a1bb3b5005ad` with no directory source. Stop if
the clean install or public API import contract differs from the approved dependency
design.

- [ ] **Step 1: Add manifest/repository contract tests**

Create tests that load JSON and assert:

```python
assert manifest["domain"] == "gentex_place"
assert manifest["version"] == project["project"]["version"]
assert manifest["requirements"] == ["place-integration-api@git+https://github.com/harperreed/place-integration-api.git@7f9f6bb6e4f5aeaae99cae30aa40a1bb3b5005ad"]
assert manifest["config_flow"] is True
assert manifest["iot_class"] == "cloud_push"
assert hacs["homeassistant"] == "2026.8.1"
assert len([p for p in Path("custom_components").iterdir() if p.is_dir()]) == 1
```

- [ ] **Step 2: Create the canonical check script**

Create executable `scripts/check`:

```sh
#!/bin/sh
# ABOUTME: Runs every local Gentex PLACE integration quality gate.
# ABOUTME: CI calls this before Home Assistant and HACS repository validators.
set -eu

uv sync --locked
uv run ruff format --check custom_components tests scripts
uv run ruff check custom_components tests scripts
uv run basedpyright
uv run pytest --cov=custom_components.gentex_place --cov-report=term-missing --cov-fail-under=100
uv run pip-audit
git diff --check
```

Run `chmod +x scripts/check`.

- [ ] **Step 3: Add official validation workflows**

Before adding the image, obtain a 256x256-or-larger PNG from Doctor Biz or another source with verified Gentex usage rights. Do not scrape or generate a lookalike mark. Record source, owner, license/permission, date obtained, and any modification in `docs/brand-provenance.md`. If no authorized image exists, omit both files and record HACS default inclusion as blocked; do not substitute a placeholder.

Create `validate.yml` with read-only repository access and three jobs:

```yaml
permissions:
  contents: read

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0
      - uses: astral-sh/setup-uv@ae62891fec2bb8e7d6c99fc78c9fec3a63790f8d
      - run: uv python install 3.14.2
      - run: scripts/check
  hassfest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0
      - uses: home-assistant/actions/hassfest@f4ca6f671bd429efb108c0f2fa0ae8af0215986c
  hacs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0
      - uses: hacs/action@d556e736723344f83838d08488c983a15381059a
        with:
          category: integration
```

Create `.github/dependabot.yml` with weekly `uv` updates at `/` and weekly
`github-actions` updates at `/`. Dependabot PRs must pass the same minimum-version
checks before pins move; this is how the repository tracks new stable Home Assistant
and validator versions without an unpinned CI environment.

Keep all action references pinned to reviewed commit SHAs and let Dependabot propose updates.

- [ ] **Step 4: Run local checks and record remote validator gates**

Run:

```bash
scripts/check
```

Expected: local checks exit zero. Hassfest and HACS remain pending until Doctor Biz authorizes a push that runs the pinned GitHub jobs; require both jobs to pass without ignores before a release claim. Do not claim either remote validator ran from this local command.

- [ ] **Step 5: Fresh-eyes review and commit**

Run fresh-eyes review over all integration code, fix findings with tests, rerun `scripts/check`, then:

```bash
git add scripts/check .github/workflows/validate.yml .github/dependabot.yml pyproject.toml uv.lock tests/components/gentex_place/test_manifest.py
# Add brand/icon.png and docs/brand-provenance.md only when verified licensed art exists.
git commit -m "ci: validate Gentex PLACE integration"
```

---

### Task 10: User documentation and opt-in read-only live check

**Files:**
- Modify: `README.md`
- Create: `scripts/live_check.py`
- Create: `tests/components/gentex_place/test_live_check.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: released SDK public API and integration entity list.
- Produces: user/install docs and an explicit live release check; no live automation in CI.

- [ ] **Step 1: Test live-check guardrails**

Extract `build_summary()` and `redact_exception()` as pure helpers, then test:

```python
def test_live_summary_has_counts_not_identifiers(sample_devices) -> None:
    text = json.dumps(build_summary(sample_devices, connected=True))
    assert "thing-CANARY" not in text
    assert "device-CANARY" not in text
    assert json.loads(text) == {
        "connected": True,
        "device_count": 1,
        "devices_with_reported_state": 1,
    }


def test_live_check_source_contains_no_desired_write() -> None:
    source = Path("scripts/live_check.py").read_text()
    assert "desired_shadow_update" not in source
    assert "shadow/update" not in source
```

- [ ] **Step 2: Run and confirm missing script**

Run: `uv run pytest tests/components/gentex_place/test_live_check.py -q`

Expected: FAIL because `scripts.live_check` is absent.

- [ ] **Step 3: Implement the explicit script**

Use `argparse` with `--username`, prompt via `getpass`, handle `MfaRequired`, call `PlaceClient.create`, wait at most 30 seconds for connection/one shadow, call only `async_refresh_shadow`, print the allow-list summary, and exit nonzero on timeout/auth/discovery failure. Add this header:

```python
# ABOUTME: Runs an opt-in read-only PLACE account release check outside CI.
# ABOUTME: Prints counts and connection state only; it never captures identifiers or payloads.
```

The script must have no output-file argument and no dependency on environment-stored password/MFA values.

- [ ] **Step 4: Write the complete README**

Cover: supported devices/fields; read-only status; HACS custom-repo install and default-store goal; UI setup and MFA; multiple accounts; entity table; fixed refresh/stale/motion timings; reauth; diagnostics/privacy; troubleshooting; removal; two example automations; developer setup; `scripts/check`; explicit live-check invocation; known SDK/release blockers; MIT license.

Do not claim HACS default inclusion, live validation, or PyPI `0.3.0` until each is true.

- [ ] **Step 5: Verify and commit**

Run:

```bash
uv run pytest tests/components/gentex_place/test_live_check.py -q
scripts/check
rg -n "PASSWORD|TOKEN|AKIA|thingName|household" README.md scripts/live_check.py
```

Expected: tests/checks PASS; search returns only explanatory words, never real values.

```bash
git add README.md scripts/live_check.py tests/components/gentex_place/test_live_check.py .gitignore
git commit -m "docs: add PLACE setup and release checks"
```

---

### Task 11: Packaged Home Assistant scenario and release candidate

**Files:**
- Create: `tests/system/run.sh`
- Create: `tests/system/test_registry.py`
- Create: `scripts/check_release.py`
- Create: `tests/test_release.py`
- Create: `.github/workflows/release.yml`
- Modify: `scripts/check`

**Interfaces:**
- Consumes: packaged `custom_components/gentex_place`, sanitized fake SDK harness, pinned Home Assistant test runtime.
- Produces: clean-install proof and release artifact workflow; no release publication without approval.

- [ ] **Step 1: Add a failing packaged registry scenario**

The system test must copy only `custom_components/gentex_place` into an isolated temporary package tree, install the released SDK wheel, start the pinned Home Assistant 2026.8.1 pytest runtime, drive the real config flow through Home Assistant's flow manager with the deterministic SDK fake injected at the network boundary, then assert one config entry, one device, all expected enabled entities, and clean unload. It must not import integration code from the source checkout or patch entity properties or registry calls.

Put the expected entity keys in one constant imported by both the system assertion and unit description-completeness test.

- [ ] **Step 2: Run and confirm the unpackaged assumption fails**

Run: `tests/system/run.sh`

Expected: FAIL before the harness/config exists or before the component is copied.

- [ ] **Step 3: Implement an isolated system runner**

`run.sh` creates temp directories with `mktemp -d`, copies the integration and system test into them, installs the pinned Home Assistant test environment plus the released SDK, traps cleanup, and preserves full logs on failure at a printed temp path. It must clear the source checkout from Python's import path and never use the operator's real Home Assistant config or credentials. Add it to `scripts/check` after unit tests.

- [ ] **Step 4: Add a failing release-version test**

Test a public `check_release_version(requested: str, pyproject: Path, manifest: Path) -> str` helper. It returns the shared version when the workflow input, `[project].version`, and manifest `version` match. It raises a clear `ValueError` naming the mismatched sources when any differ. Cover `0.1.0` success, project/manifest mismatch, and requested/project mismatch.

- [ ] **Step 5: Implement the checked release-artifact workflow**

Implement the helper with `argparse`, `json`, and `tomllib`. The workflow triggers on `workflow_dispatch` with a required `version` input, runs `scripts/check`, validates that input with `scripts/check_release.py`, builds `gentex_place.zip` containing only the integration directory, uploads `gentex_place-<version>` as a workflow artifact, and stops. Publishing a GitHub Release and creating a Git tag remain separate authorized actions.

- [ ] **Step 6: Run final verification**

Run:

```bash
scripts/check
tests/system/run.sh
git status --short
git log --oneline --decorate --max-count=12
```

Expected: all checks PASS, no pending asyncio tasks or warnings, and only planned release files remain uncommitted.

- [ ] **Step 7: Fresh-eyes review and commit**

Run the mandatory fresh-eyes review, fix every finding through TDD, rerun all commands above, then:

```bash
git add tests/system scripts/check_release.py tests/test_release.py .github/workflows/release.yml scripts/check
git commit -m "test: verify packaged PLACE integration"
```

- [ ] **Step 8: Stop at external gates**

Do not push, publish, submit to the HACS default list, or create releases without Doctor Biz's approval. Report:

- integration candidate commit and `scripts/check` output;
- published SDK artifact verification status;
- opt-in live-check status;
- local brand asset/license status;
- GitHub repository metadata status; and
- any warnings or unsupported device fields.

Only after those gates pass should release version `1.0.0` replace the development version and the manifest/tag/notes change together.
