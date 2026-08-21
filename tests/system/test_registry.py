# Copyright (c) 2026 Gentex
# ABOUTME: Exercises the packaged integration through real Home Assistant registries.
# ABOUTME: Replaces only SDK network behavior with one deterministic local boundary.
"""Packaged Home Assistant registry and entity lifecycle scenario."""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    STATE_UNAVAILABLE,
    EntityStateAttribute,
)
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from place import Credentials, DiscoverDevice, PlaceDevice
from place.models import PlaceDeviceShadow

from custom_components import gentex_place as integration_module
from custom_components.gentex_place import auth as auth_helpers
from custom_components.gentex_place.const import DOMAIN
from tests.system.entity_contract import EXPECTED_ENTITY_KEYS

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from custom_components.gentex_place.auth import (
        ConfigEntryTokenCache,
        MemoryTokenCache,
    )

type TokenCache = MemoryTokenCache | ConfigEntryTokenCache
type DeviceCallback = Callable[[PlaceDevice], None]
type ConnectionCallback = Callable[[bool], None]
type ErrorCallback = Callable[[Any], None]
type EventCallback = Callable[[Any], None]

_ACCOUNT_ID = "identity-1"
_THING_NAME = "thing-1"


class _SystemAuth:
    """Provide deterministic auth results through the SDK boundary."""

    def __init__(self, token_cache: TokenCache) -> None:
        self.token_cache = token_cache

    async def authenticate(self, username: str, password: str) -> None:
        """Accept sanitized setup input and cache one fake refresh token."""
        assert password
        self.token_cache.save(
            {"username": username, "refresh_token": "sanitized-refresh-token"}
        )

    async def authenticate_from_cache(self, username: str) -> None:
        """Accept the config entry's cached sanitized refresh token."""
        assert self.token_cache.load() == {
            "username": username,
            "refresh_token": "sanitized-refresh-token",
        }

    async def async_get_iot_credentials(self) -> Credentials:
        """Return a stable account identity without a network call."""
        return Credentials(
            access_key_id="sanitized-access-key",
            secret_access_key="sanitized-secret-key",
            session_token="sanitized-session-token",
            identity_id=_ACCOUNT_ID,
            access_token="sanitized-access-token",
        )


class _DiscoveryClient:
    """Return one deterministic device during the config flow."""

    async def async_discover(self) -> list[DiscoverDevice]:
        """Return the sanitized discovery record."""
        return [
            DiscoverDevice(
                location="Hallway",
                shadow={},
                device_name="PLACE",
                thing_name=_THING_NAME,
                firmware_version="1.0.0",
                model_number="PLACE-1",
                device_id="device-1",
                online=True,
            )
        ]


class _RuntimeClient:
    """Expose the public runtime SDK surface around one real SDK device."""

    def __init__(self) -> None:
        self.connected = False
        self.stopped = False
        self._devices = {
            _THING_NAME: PlaceDevice(
                thing_name=_THING_NAME,
                device_id="device-1",
                name="PLACE",
                model="PLACE-1",
                firmware_version="1.0.0",
                location="Hallway",
                online=True,
                shadow=PlaceDeviceShadow(),
            )
        }
        self._callbacks: list[list[Callable[..., None]]] = []

    @property
    def devices(self) -> dict[str, PlaceDevice]:
        """Return the SDK-style defensive device mapping."""
        return dict(self._devices)

    async def start(self) -> None:
        """Expose immediate connected and shadow-ready public state."""
        self.connected = True
        self._devices[_THING_NAME].last_shadow_at = time.monotonic()

    async def stop(self) -> None:
        """Record clean coordinator shutdown."""
        self.connected = False
        self.stopped = True

    async def async_refresh_shadow(self, thing_name: str | None = None) -> None:
        """Accept a health refresh without changing deterministic state."""
        assert thing_name is None

    def on_update(self, callback: DeviceCallback) -> Callable[[], None]:
        """Register a device update callback."""
        return self._register(callback)

    def on_event(self, callback: EventCallback) -> Callable[[], None]:
        """Register an event callback."""
        return self._register(callback)

    def on_connection_change(self, callback: ConnectionCallback) -> Callable[[], None]:
        """Register a connection callback."""
        return self._register(callback)

    def on_error(self, callback: ErrorCallback) -> Callable[[], None]:
        """Register an error callback."""
        return self._register(callback)

    def _register(self, callback: Callable[..., None]) -> Callable[[], None]:
        callbacks = [callback]
        self._callbacks.append(callbacks)

        def unsubscribe() -> None:
            callbacks.clear()

        return unsubscribe

    @property
    def callback_count(self) -> int:
        """Return the number of callbacks still registered."""
        return sum(len(callbacks) for callbacks in self._callbacks)


class _SdkBoundary:
    """Create config-flow and runtime fakes at production SDK factories."""

    def __init__(self) -> None:
        self.runtime_client = _RuntimeClient()

    def create_auth(self, _hass: HomeAssistant, cache: TokenCache) -> _SystemAuth:
        """Build an auth fake around the production token cache."""
        return _SystemAuth(cache)

    def create_client(self, auth: _SystemAuth) -> _DiscoveryClient | _RuntimeClient:
        """Select discovery or runtime behavior from the production cache type."""
        if isinstance(auth.token_cache, auth_helpers.MemoryTokenCache):
            return _DiscoveryClient()
        return self.runtime_client


def _escape(value: str) -> str:
    """Match production escaping for expected registry unique IDs."""
    return value.replace("%", "%25").replace("_", "%5F").replace(":", "%3A")


def _expected_unique_ids() -> set[tuple[str, str]]:
    """Build exact account- and device-scoped registry identifiers."""
    return {
        (
            platform,
            (
                f"{_ACCOUNT_ID}_{_escape(key)}"
                if key == "account_connection"
                else f"{_ACCOUNT_ID}_{_THING_NAME}_{_escape(key)}"
            ),
        )
        for platform, key in EXPECTED_ENTITY_KEYS
    }


def _assert_imports_are_packaged() -> None:
    """Prove integration modules resolve only from the copied temp package."""
    package_root = (
        Path(__file__).parents[2] / "custom_components/gentex_place"
    ).resolve()
    source_checkout = Path(os.environ["GENTEX_PLACE_SOURCE_CHECKOUT"]).resolve()
    assert all(Path(item or ".").resolve() != source_checkout for item in sys.path)
    for module_name in (
        "custom_components.gentex_place",
        "custom_components.gentex_place.auth",
        "custom_components.gentex_place.binary_sensor",
        "custom_components.gentex_place.config_flow",
        "custom_components.gentex_place.sensor",
    ):
        module_file = sys.modules[module_name].__file__
        assert module_file is not None
        module_path = Path(module_file).resolve()
        assert module_path.is_relative_to(package_root)


@pytest.mark.skipif(
    os.environ.get("GENTEX_PLACE_PACKAGED_TEST") != "1",
    reason="run through tests/system/run.sh",
)
async def test_packaged_config_flow_registry_and_unload(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Create one packaged entry, device, all entities, then unload cleanly."""
    _ = enable_custom_integrations
    boundary = _SdkBoundary()
    monkeypatch.setattr(auth_helpers, "create_auth", boundary.create_auth)
    monkeypatch.setattr(auth_helpers, "create_client", boundary.create_client)
    monkeypatch.setattr(integration_module, "create_auth", boundary.create_auth)
    monkeypatch.setattr(integration_module, "create_client", boundary.create_client)

    form = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert form.get("type") is FlowResultType.FORM
    flow_id = form.get("flow_id")
    assert flow_id is not None
    result = await hass.config_entries.flow.async_configure(
        flow_id,
        {CONF_USERNAME: "system@example.invalid", CONF_PASSWORD: "sanitized-password"},
    )
    assert result.get("type") is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    entry = result.get("result")
    assert entry is not None
    assert hass.config_entries.async_entries(DOMAIN) == [entry]
    assert entry.state is ConfigEntryState.LOADED

    device_registry = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(device_registry, entry.entry_id)
    assert len(devices) == 1
    assert devices[0].identifiers == {(DOMAIN, f"{_ACCOUNT_ID}:{_THING_NAME}")}

    entity_registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    assert {(item.domain, item.unique_id) for item in entities} == (
        _expected_unique_ids()
    )
    assert all(item.disabled_by is None for item in entities)
    assert all(hass.states.get(item.entity_id) is not None for item in entities)
    _assert_imports_are_packaged()

    assert await hass.config_entries.async_unload(entry.entry_id) is True
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    unloaded_states = [hass.states.get(item.entity_id) for item in entities]
    assert all(state is not None for state in unloaded_states)
    assert all(state.state == STATE_UNAVAILABLE for state in unloaded_states if state)
    assert all(
        state.attributes[EntityStateAttribute.RESTORED] is True
        for state in unloaded_states
        if state
    )
    assert boundary.runtime_client.stopped is True
    assert boundary.runtime_client.callback_count == 0
