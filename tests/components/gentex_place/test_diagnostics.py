# Copyright (c) 2026 Gentex
# ABOUTME: Verifies PLACE diagnostics use a strict privacy-preserving allow list.
# ABOUTME: Canary tests cover diagnostics and meaningful setup/coordinator logs.
"""Tests for Gentex PLACE diagnostics and log privacy."""

from __future__ import annotations

import json
import logging
import traceback
from typing import TYPE_CHECKING, cast

import place
import pytest
from homeassistant import const as ha_const
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from place import (
    Credentials,
    PlaceAuthError,
    PlaceConnectionError,
    PlaceDiscoveryError,
    PlaceError,
    PlaceInvalidAuthError,
    PlaceTimeoutError,
    PlaceTransientAuthError,
)

from custom_components import gentex_place as integration_module
from custom_components.gentex_place.const import (
    CONF_ACCOUNT_ID,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)
from custom_components.gentex_place.diagnostics import (
    async_get_config_entry_diagnostics,
)
from tests.components.gentex_place.fakes import (
    FakePlaceClient,
    RecordingConfigEntry,
    install_runtime_fakes,
    make_place_device,
)
from tests.components.gentex_place.test_init import make_entry

if TYPE_CHECKING:
    from collections.abc import Sequence

    from homeassistant.core import HomeAssistant
    from place import PlaceClient, PlaceDevice

    from tests.components.gentex_place.fakes import RuntimeHarness

_USERNAME_CANARY = "PRIVATE_USERNAME_7DA2"
_REFRESH_TOKEN_CANARY = "PRIVATE_REFRESH_TOKEN_4B91"
_ACCOUNT_CANARY = "PRIVATE_ACCOUNT_ID_9C63"
_DEVICE_ID_CANARY = "PRIVATE_DEVICE_ID_51AF"
_THING_NAME_CANARY = "PRIVATE_THING_NAME_6D28"
_DEVICE_NAME_CANARY = "PRIVATE_DEVICE_NAME_03E7"
_LOCATION_CANARY = "PRIVATE_LOCATION_88BC"
_MQTT_TOPIC_CANARY = "PRIVATE_MQTT_TOPIC_142D"
_RAW_PAYLOAD_CANARY = "PRIVATE_RAW_PAYLOAD_39F0"
_ACCESS_TOKEN_CANARY = "PRIVATE_ACCESS_TOKEN_2E74"
_ID_TOKEN_CANARY = "PRIVATE_ID_TOKEN_5A19"
_AWS_ACCESS_KEY_CANARY = "PRIVATE_AWS_ACCESS_KEY_91C8"
_AWS_SECRET_KEY_CANARY = "PRIVATE_AWS_SECRET_KEY_A506"
_AWS_SESSION_TOKEN_CANARY = "PRIVATE_AWS_SESSION_TOKEN_B731"
_HOUSEHOLD_CANARY = "PRIVATE_HOUSEHOLD_C024"
_DIAGNOSTIC_ERROR_CANARY = "PRIVATE_DIAGNOSTIC_ERROR_D983"
_EXPECTED_RETRIED_STOP_CALLS = 2

_ALL_CANARIES = (
    _USERNAME_CANARY,
    _REFRESH_TOKEN_CANARY,
    _ACCOUNT_CANARY,
    _DEVICE_ID_CANARY,
    _THING_NAME_CANARY,
    _DEVICE_NAME_CANARY,
    _LOCATION_CANARY,
    _MQTT_TOPIC_CANARY,
    _RAW_PAYLOAD_CANARY,
    _ACCESS_TOKEN_CANARY,
    _ID_TOKEN_CANARY,
    _AWS_ACCESS_KEY_CANARY,
    _AWS_SECRET_KEY_CANARY,
    _AWS_SESSION_TOKEN_CANARY,
    _HOUSEHOLD_CANARY,
    _DIAGNOSTIC_ERROR_CANARY,
)

type SetupErrorCase = tuple[str, str, type[PlaceError]]

SETUP_ERROR_CASES: tuple[SetupErrorCase, ...] = (
    ("cache_invalid", "cache", PlaceInvalidAuthError),
    ("cache_auth", "cache", PlaceAuthError),
    ("cache_transient", "cache", PlaceTransientAuthError),
    ("start_invalid", "start", PlaceInvalidAuthError),
    ("start_auth", "start", PlaceAuthError),
    ("start_transient", "start", PlaceTransientAuthError),
    ("start_connection", "start", PlaceConnectionError),
    ("start_discovery", "start", PlaceDiscoveryError),
    ("start_timeout", "start", PlaceTimeoutError),
    ("callback_invalid", "callback", PlaceInvalidAuthError),
    ("callback_auth", "callback", PlaceAuthError),
    ("callback_transient", "callback", PlaceTransientAuthError),
)


def _serialized_logs(caplog: pytest.LogCaptureFixture) -> str:
    """Serialize messages and exception records so hidden causes are inspected."""
    return json.dumps(
        {
            "text": caplog.text,
            "records": [
                {
                    "name": record.name,
                    "level": record.levelname,
                    "message": record.getMessage(),
                    "args": record.args,
                    "exception": record.exc_info,
                }
                for record in caplog.records
            ],
        },
        default=str,
    )


def _assert_canaries_absent(serialized: str, canaries: Sequence[str]) -> None:
    """Assert serialized support data contains none of the seeded private values."""
    for canary in canaries:
        assert canary not in serialized


def _direct_object_state(value: object) -> tuple[dict[str, object], list[object]]:
    """Return direct instance-dict and slot values without walking object graphs."""
    instance_values = vars(value)
    slot_values: list[object] = []
    for owner in type(value).__mro__:
        slots = owner.__dict__.get("__slots__", ())
        if isinstance(slots, str):
            slots = (slots,)
        slot_values.extend(
            getattr(value, slot)
            for slot in slots
            if slot not in {"__dict__", "__weakref__"} and hasattr(value, slot)
        )
    return instance_values, slot_values


def _private_entry() -> RecordingConfigEntry:
    """Build one config entry containing distinct private canaries."""
    return RecordingConfigEntry(
        domain=DOMAIN,
        title=_USERNAME_CANARY,
        unique_id=_ACCOUNT_CANARY,
        data={
            "username": _USERNAME_CANARY,
            CONF_REFRESH_TOKEN: _REFRESH_TOKEN_CANARY,
            CONF_ACCOUNT_ID: _ACCOUNT_CANARY,
            "household_id": _HOUSEHOLD_CANARY,
            "access_token": _ACCESS_TOKEN_CANARY,
        },
    )


def _install_setup_error_boundary(
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
    error: PlaceError,
) -> None:
    """Install one typed setup error at a hand-written SDK fake boundary."""
    if boundary == "cache":
        install_runtime_fakes(monkeypatch, auth_result=error)
    elif boundary == "start":
        install_runtime_fakes(monkeypatch, start_result=error)
    else:
        install_runtime_fakes(
            monkeypatch, ready_on_start=False, error_after_start=error
        )
        monkeypatch.setattr(
            "custom_components.gentex_place.coordinator._STARTUP_POLL_SECONDS", 0
        )


def _private_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[PlaceDevice, RuntimeHarness]:
    """Build one runtime with private canaries attached beyond public SDK fields."""
    device = make_place_device(
        thing_name=_THING_NAME_CANARY,
        device_id=_DEVICE_ID_CANARY,
        last_shadow_at=100.0,
    )
    device.name = _DEVICE_NAME_CANARY
    device.location = _LOCATION_CANARY
    device.model = "PL1AS"
    device.firmware_version = "1.2.3"
    device.__dict__["mqtt_topic"] = _MQTT_TOPIC_CANARY
    device.__dict__["raw_payload"] = {"payload": _RAW_PAYLOAD_CANARY}
    device.__dict__["household_id"] = _HOUSEHOLD_CANARY
    harness = install_runtime_fakes(monkeypatch, devices=[device])
    harness.client.__dict__["mqtt_topic"] = _MQTT_TOPIC_CANARY
    harness.client.__dict__["raw_payload"] = _RAW_PAYLOAD_CANARY
    harness.auth.__dict__["id_token"] = _ID_TOKEN_CANARY
    harness.client.__dict__["id_token"] = _ID_TOKEN_CANARY
    harness.client.__dict__["credentials"] = Credentials(
        access_key_id=_AWS_ACCESS_KEY_CANARY,
        secret_access_key=_AWS_SECRET_KEY_CANARY,
        session_token=_AWS_SESSION_TOKEN_CANARY,
        identity_id=_HOUSEHOLD_CANARY,
        access_token=_ACCESS_TOKEN_CANARY,
    )
    return device, harness


async def test_diagnostics_are_fresh_exact_allow_list_without_private_canaries(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    device, harness = _private_runtime(monkeypatch)
    monkeypatch.setattr(integration_module, "PLATFORMS", [])
    entry = _private_entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id) is True
    assert entry.title == "Gentex PLACE"
    coordinator = entry.runtime_data.coordinator
    device.last_shadow_at = 100.4
    monkeypatch.setattr(
        "custom_components.gentex_place.coordinator.time.monotonic", lambda: 106.0
    )
    coordinator.last_exception = PlaceConnectionError(_DIAGNOSTIC_ERROR_CANARY)
    try:
        diagnostics = await async_get_config_entry_diagnostics(hass, entry)
        second = await async_get_config_entry_diagnostics(hass, entry)

        assert diagnostics is not second
        assert diagnostics["devices"] is not second["devices"]
        assert set(diagnostics) == {
            "integration_version",
            "home_assistant_version",
            "sdk_version",
            "connected",
            "config_entry_state",
            "last_update_success",
            "device_count",
            "devices",
            "timing",
            "last_error",
        }
        assert diagnostics["integration_version"] == "0.1.0"
        assert diagnostics["home_assistant_version"] == ha_const.__version__
        assert diagnostics["sdk_version"] == place.__version__ == "0.3.0"
        assert diagnostics["connected"] is True
        assert diagnostics["config_entry_state"] == ConfigEntryState.LOADED.value
        assert diagnostics["last_update_success"] is True
        assert diagnostics["device_count"] == 1
        assert diagnostics["devices"] == [
            {
                "model": "PL1AS",
                "firmware": "1.2.3",
                "available": True,
                "liveness_age_seconds": 6,
            }
        ]
        assert diagnostics["timing"] == {
            "health_interval_seconds": 300,
            "stale_after_seconds": 900,
            "motion_window_seconds": 30,
        }
        assert diagnostics["last_error"] == "PlaceConnectionError"

        device.last_shadow_at = None
        coordinator.client.connected = False
        coordinator.last_update_success = False
        disconnected = await async_get_config_entry_diagnostics(hass, entry)
        assert disconnected["connected"] is False
        assert disconnected["last_update_success"] is False
        assert disconnected["devices"] == [
            {
                "model": "PL1AS",
                "firmware": "1.2.3",
                "available": False,
                "liveness_age_seconds": None,
            }
        ]

        serialized = json.dumps(
            {
                "diagnostics": diagnostics,
                "disconnected": disconnected,
                "logs": _serialized_logs(caplog),
            },
            default=str,
        )
        _assert_canaries_absent(serialized, _ALL_CANARIES)
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id) is True
    assert harness.client.stop_completed is True


async def test_setup_migrates_legacy_title_before_failure_logging(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    error_canary = "PRIVATE_LEGACY_SETUP_ERROR_771C"
    install_runtime_fakes(
        monkeypatch,
        auth_result=PlaceTransientAuthError(error_canary),
    )
    monkeypatch.setattr(integration_module, "PLATFORMS", [])
    first_entry = RecordingConfigEntry(
        domain=DOMAIN,
        title="Gentex PLACE",
        unique_id="safe-existing-account",
        data={
            "username": "safe-existing-user",
            CONF_REFRESH_TOKEN: "safe-existing-refresh",
            CONF_ACCOUNT_ID: "safe-existing-account",
        },
    )
    first_entry.add_to_hass(hass)
    entry = _private_entry()
    entry.add_to_hass(hass)
    caplog.set_level(logging.DEBUG)

    assert await hass.config_entries.async_setup(entry.entry_id) is False
    await hass.async_block_till_done()

    assert entry.title == "Gentex PLACE 2"
    serialized = _serialized_logs(caplog)
    _assert_canaries_absent(
        serialized,
        (*_ALL_CANARIES, error_canary),
    )
    assert "Gentex PLACE 2" in serialized
    assert "PlaceTransientAuthError" in serialized


@pytest.mark.parametrize("setup_case", SETUP_ERROR_CASES)
async def test_setup_error_boundaries_never_log_exception_messages(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    setup_case: SetupErrorCase,
) -> None:
    case_name, boundary, error_type = setup_case
    canary = f"PRIVATE_SETUP_ERROR_{case_name.upper()}"
    error = error_type(canary)
    _install_setup_error_boundary(monkeypatch, boundary, error)
    monkeypatch.setattr(integration_module, "PLATFORMS", [])
    entry = _private_entry()
    entry.add_to_hass(hass)
    caplog.set_level(logging.DEBUG)

    expected_error = (
        ConfigEntryAuthFailed
        if issubclass(error_type, PlaceInvalidAuthError)
        else ConfigEntryNotReady
    )
    with pytest.raises(expected_error) as error_info:
        await integration_module.async_setup_entry(hass, entry)
    public_error = error_info.value
    assert public_error.__cause__ is None
    assert public_error.__context__ is None
    serialized_error = json.dumps(
        {
            "error": public_error,
            "traceback": traceback.format_exception(public_error),
        },
        default=str,
    )
    assert canary not in serialized_error
    assert error_type.__name__ in serialized_error
    caplog.clear()

    assert await hass.config_entries.async_setup(entry.entry_id) is False
    await hass.async_block_till_done()

    serialized = _serialized_logs(caplog)
    _assert_canaries_absent(serialized, (*_ALL_CANARIES, canary))
    assert error_type.__name__ in serialized


async def test_callback_startup_error_is_not_reachable_from_public_traceback(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canary = "PRIVATE_REACHABLE_CALLBACK_ERROR_82D4"
    raw_error = PlaceTransientAuthError(canary)
    _install_setup_error_boundary(monkeypatch, "callback", raw_error)
    monkeypatch.setattr(integration_module, "PLATFORMS", [])
    entry = _private_entry()
    entry.add_to_hass(hass)

    with pytest.raises(ConfigEntryNotReady) as error_info:
        await integration_module.async_setup_entry(hass, entry)

    public_error = error_info.value
    coordinator_values: list[object] = []
    current_traceback = public_error.__traceback__
    while current_traceback is not None:
        coordinator = current_traceback.tb_frame.f_locals.get("coordinator")
        if coordinator is not None:
            coordinator_values.append(coordinator)
        current_traceback = current_traceback.tb_next

    assert len(coordinator_values) == 1
    instance_state, slot_values = _direct_object_state(coordinator_values[0])
    direct_values = (*instance_state.values(), *slot_values)
    assert instance_state.get("_startup_error") is None
    assert raw_error not in direct_values
    assert all(
        canary not in str(value)
        for value in direct_values
        if isinstance(value, PlaceError | str)
    )
    assert public_error.__cause__ is None
    assert public_error.__context__ is None


async def test_coordinator_error_boundaries_never_log_exception_messages(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    refresh_canary = "PRIVATE_REFRESH_ERROR_0A61"
    transient_canary = "PRIVATE_TRANSIENT_ERROR_14F8"
    invalid_canary = "PRIVATE_INVALID_ERROR_39D2"
    device = make_place_device(last_shadow_at=100.0)
    client = FakePlaceClient(
        device_registry={device.thing_name: device},
        connected=True,
    )
    entry = make_entry()
    coordinator = integration_module.GentexPlaceCoordinator(
        hass, entry, cast("PlaceClient", client)
    )
    await coordinator.async_start()
    caplog.set_level(logging.DEBUG)
    client.refresh_result = PlaceConnectionError(refresh_canary)

    await coordinator.async_refresh()
    client.emit_error(PlaceTransientAuthError(transient_canary))
    client.emit_error(PlaceInvalidAuthError(invalid_canary))

    assert coordinator.last_update_success is False
    public_error = coordinator.last_exception
    assert type(public_error).__name__ == "UpdateFailed"
    assert public_error is not None
    assert public_error.__cause__ is None
    assert public_error.__context__ is None
    serialized_error = json.dumps(
        {
            "error": public_error,
            "traceback": traceback.format_exception(public_error),
        },
        default=str,
    )
    assert refresh_canary not in serialized_error
    assert entry.reauth_calls == 1
    serialized = _serialized_logs(caplog)
    _assert_canaries_absent(
        serialized, (refresh_canary, transient_canary, invalid_canary)
    )
    await coordinator.async_shutdown()


async def test_ha_unload_sanitizes_stop_failure_and_allows_retry(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    canary = "PRIVATE_UNLOAD_STOP_ERROR_61BC"
    raw_error = PlaceConnectionError(canary)
    harness = install_runtime_fakes(monkeypatch, stop_results=[raw_error, None])
    monkeypatch.setattr(integration_module, "PLATFORMS", [])
    entry = _private_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id) is True
    caplog.clear()
    caplog.set_level(logging.DEBUG)

    assert await hass.config_entries.async_unload(entry.entry_id) is False

    assert entry.state is ConfigEntryState.FAILED_UNLOAD
    assert entry.reason == "PlaceConnectionError"
    assert harness.client.stop_calls == 1
    assert harness.client.stop_completed is False
    serialized = _serialized_logs(caplog)
    assert canary not in serialized
    assert "PlaceConnectionError" in serialized

    assert await integration_module.async_unload_entry(hass, entry) is True
    assert harness.client.stop_calls == _EXPECTED_RETRIED_STOP_CALLS
    assert harness.client.stop_completed is True
