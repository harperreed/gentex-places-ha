# Copyright (c) 2026 Gentex
# ABOUTME: Exercises the packaged integration through real Home Assistant registries.
# ABOUTME: Replaces only SDK network behavior with one deterministic local boundary.
"""Packaged Home Assistant registry and entity lifecycle scenario."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from aiohttp import ClientSession
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
from place import Credentials, PlaceClient, PlaceDevice
from place import client as place_client_module
from place.auth import cognito_auth as cognito_auth_module
from place.config import FULFILLMENT_URL

from custom_components import gentex_place as integration_module
from custom_components.gentex_place import auth as auth_helpers
from custom_components.gentex_place.const import DOMAIN
from tests.system.entity_contract import EXPECTED_ENTITY_KEYS

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from typing import Self

    from homeassistant.core import HomeAssistant

_ACCOUNT_ID = "identity-1"
_THING_NAME = "thing-1"
_RELOADED_THING_NAME = "thing-2"
_INITIAL_REPORTED = {"temperatureC": 21.5, "humidity": 42.0}
_INITIAL_DISCOVERY_CALLS = 2
_EXPECTED_DISCOVERY_CALLS = 3
_EXPECTED_IOT_CALLS = 3
_EXPECTED_TRANSPORTS = 2


def _discovery_device(*, thing_name: str = _THING_NAME) -> dict[str, Any]:
    """Return one sanitized raw fulfillment discovery record."""
    return {
        "location": "Hallway",
        "shadow": {},
        "deviceName": "PLACE",
        "thingName": thing_name,
        "firmwareVersion": "1.0.0",
        "modelNumber": "PLACE-1",
        "deviceId": f"device-{thing_name}",
        "online": True,
    }


class _CognitoGateway:
    """Provide deterministic responses at the SDK's blocking Cognito seam."""

    def __init__(self) -> None:
        self.srp_calls = 0
        self.refresh_calls = 0
        self.iot_calls = 0

    @staticmethod
    def _tokens(*, include_refresh: bool) -> dict[str, Any]:
        tokens = {
            "AccessToken": "sanitized-access-token",
            "IdToken": "sanitized-id-token",
            "ExpiresIn": 3600,
        }
        if include_refresh:
            tokens["RefreshToken"] = "sanitized-refresh-token"
        return tokens

    def srp_login(self, username: str, password: str) -> dict[str, Any]:
        """Return real CognitoAuth's expected successful SRP envelope."""
        assert username == "system@example.invalid"
        assert password == "sanitized-password"
        self.srp_calls += 1
        return {"AuthenticationResult": self._tokens(include_refresh=True)}

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        """Return refreshed tokens for the config entry's cached token."""
        assert refresh_token == "sanitized-refresh-token"
        self.refresh_calls += 1
        return self._tokens(include_refresh=False)

    def respond_mfa(self, **_kwargs: str) -> dict[str, Any]:
        """Reject unexpected MFA use in this non-MFA packaged scenario."""
        pytest.fail("packaged scenario does not request MFA", pytrace=False)

    def iot_credentials(self, id_token: str, access_token: str) -> Credentials:
        """Return deterministic IoT credentials without calling Cognito."""
        assert id_token == "sanitized-id-token"
        assert access_token == "sanitized-access-token"
        self.iot_calls += 1
        return Credentials(
            access_key_id="sanitized-access-key",
            secret_access_key="sanitized-secret-key",
            session_token="sanitized-session-token",
            identity_id=_ACCOUNT_ID,
            access_token=access_token,
        )


class _DiscoveryResponse:
    """Expose the aiohttp response surface consumed by Provider."""

    def __init__(self, devices: list[dict[str, Any]]) -> None:
        self._devices = devices

    async def json(self) -> dict[str, Any]:
        """Return one successful fulfillment response."""
        return {"success": True, "data": {"devices": self._devices}}


class _MqttTransport:
    """Deliver shadow replies beneath the real PlaceConnection."""

    def __init__(self) -> None:
        self._messages: asyncio.Queue[tuple[str, bytes]] = asyncio.Queue()
        self.subscriptions: list[str] = []
        self.publishes: list[str] = []
        self.exited = False

    async def __aenter__(self) -> Self:
        """Open the deterministic transport."""
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: object,
    ) -> None:
        """Record transport cleanup by the real connection loop."""
        self.exited = True

    async def subscribe(self, topic: str, qos: int = 1) -> None:
        """Record the real connection's subscriptions."""
        assert qos == 1
        self.subscriptions.append(topic)

    async def publish(self, topic: str, payload: bytes = b"", qos: int = 1) -> None:
        """Answer each reported-shadow request with sanitized state."""
        assert qos == 1
        assert payload == b""
        self.publishes.append(topic)
        if topic.endswith("/shadow/get"):
            response = json.dumps({"state": {"reported": _INITIAL_REPORTED}}).encode()
            await self._messages.put((f"{topic}/accepted", response))

    async def messages(self) -> AsyncIterator[tuple[str, bytes]]:
        """Stream deterministic MQTT messages until the real task is cancelled."""
        while True:
            yield await self._messages.get()


class _NetworkBoundary:
    """Inject deterministic behavior only at the pinned SDK's network seams."""

    def __init__(self) -> None:
        self.gateway = _CognitoGateway()
        self.discovery_calls = 0
        self.transports: list[_MqttTransport] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Replace Cognito, HTTP, and MQTT I/O below real SDK objects."""
        monkeypatch.setattr(
            cognito_auth_module,
            "RealCognitoGateway",
            lambda _config: self.gateway,
        )
        monkeypatch.setattr(ClientSession, "request", self.request)
        monkeypatch.setattr(
            place_client_module,
            "_aiomqtt_transport_factory",
            self.create_mqtt_transport,
        )

    async def request(
        self,
        method: str,
        url: str,
        **kwargs: object,
    ) -> _DiscoveryResponse:
        """Answer the real Provider's fulfillment HTTP request."""
        assert method == "POST"
        assert url == FULFILLMENT_URL
        assert kwargs["json"] == {"command": "DISCOVER", "data": {}}
        assert kwargs["headers"] == {"authorization": "Bearer sanitized-access-token"}
        thing_name = (
            _THING_NAME
            if self.discovery_calls < _INITIAL_DISCOVERY_CALLS
            else _RELOADED_THING_NAME
        )
        self.discovery_calls += 1
        return _DiscoveryResponse([_discovery_device(thing_name=thing_name)])

    def create_mqtt_transport(
        self,
        _config: object,
        credentials: Credentials,
    ) -> _MqttTransport:
        """Return a deterministic transport to the real PlaceConnection."""
        assert credentials.identity_id == _ACCOUNT_ID
        transport = _MqttTransport()
        self.transports.append(transport)
        return transport


def _escape(value: str) -> str:
    """Match production escaping for expected registry unique IDs."""
    return value.replace("%", "%25").replace("_", "%5F").replace(":", "%3A")


def _expected_unique_ids(thing_name: str = _THING_NAME) -> set[tuple[str, str]]:
    """Build exact account- and device-scoped registry identifiers."""
    return {
        (
            platform,
            (
                f"{_ACCOUNT_ID}_{_escape(key)}"
                if key == "account_connection"
                else f"{_ACCOUNT_ID}_{thing_name}_{_escape(key)}"
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


def _assert_real_sdk_runtime(entry: config_entries.ConfigEntry) -> None:
    """Prove the packaged runtime uses the pinned SDK above its network seams."""
    assert integration_module.create_auth is auth_helpers.create_auth
    assert integration_module.create_client is auth_helpers.create_client
    client = entry.runtime_data.coordinator.client
    assert type(client) is PlaceClient
    assert all(type(device) is PlaceDevice for device in client.devices.values())


@pytest.mark.skipif(
    os.environ.get("GENTEX_PLACE_PACKAGED_TEST") != "1",
    reason="run through tests/system/run.sh",
)
async def test_packaged_config_flow_registry_and_unload(  # noqa: PLR0915
    hass: HomeAssistant,
    enable_custom_integrations: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Create one packaged entry, device, all entities, then unload cleanly."""
    _ = enable_custom_integrations
    boundary = _NetworkBoundary()
    boundary.install(monkeypatch)

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
    _assert_real_sdk_runtime(entry)
    runtime_client = entry.runtime_data.coordinator.client

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

    old_client = runtime_client
    assert await hass.config_entries.async_reload(entry.entry_id) is True
    await hass.async_block_till_done()
    runtime_client = entry.runtime_data.coordinator.client
    assert runtime_client is not old_client
    assert set(runtime_client.devices) == {_RELOADED_THING_NAME}
    _assert_real_sdk_runtime(entry)
    assert old_client.connected is False
    assert boundary.transports[0].exited is True

    devices = dr.async_entries_for_config_entry(device_registry, entry.entry_id)
    assert (DOMAIN, f"{_ACCOUNT_ID}:{_RELOADED_THING_NAME}") in {
        identifier for device in devices for identifier in device.identifiers
    }
    entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    registered_entity_ids = {(item.domain, item.unique_id) for item in entities}
    reloaded_entity_ids = _expected_unique_ids(_RELOADED_THING_NAME)
    assert reloaded_entity_ids <= registered_entity_ids
    assert all(
        hass.states.get(item.entity_id) is not None
        for item in entities
        if (item.domain, item.unique_id) in reloaded_entity_ids
    )

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
    assert runtime_client.connected is False
    assert boundary.gateway.srp_calls == 1
    assert boundary.gateway.refresh_calls == _EXPECTED_TRANSPORTS
    assert boundary.gateway.iot_calls == _EXPECTED_IOT_CALLS
    assert boundary.discovery_calls == _EXPECTED_DISCOVERY_CALLS
    assert len(boundary.transports) == _EXPECTED_TRANSPORTS
    assert all(transport.exited for transport in boundary.transports)
    assert [transport.publishes for transport in boundary.transports] == [
        [f"$aws/things/{_THING_NAME}/shadow/get"],
        [f"$aws/things/{_RELOADED_THING_NAME}/shadow/get"],
    ]
    assert all(transport.subscriptions for transport in boundary.transports)
