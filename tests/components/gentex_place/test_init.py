# Copyright (c) 2026 Gentex
# ABOUTME: Verifies config-entry startup, typed setup failures, and clean unload.
# ABOUTME: Runtime tests use hand-written SDK fakes and no live account calls.
"""Tests for the Gentex PLACE config-entry lifecycle."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.util.async_ import get_scheduled_timer_handles
from place import (
    DeviceEvent,
    PlaceAuthError,
    PlaceConnectionError,
    PlaceDiscoveryError,
    PlaceInvalidAuthError,
    PlaceTransientAuthError,
)

from custom_components import gentex_place as integration_module
from custom_components.gentex_place.const import (
    CONF_ACCOUNT_ID,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)
from tests.components.gentex_place.fakes import (
    RecordingConfigEntry,
    install_runtime_fakes,
    make_place_device,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_INITIAL_SHADOW_TIME = 100.0


def make_entry() -> RecordingConfigEntry:
    """Build a loaded-account config entry for lifecycle tests."""
    return RecordingConfigEntry(
        domain=DOMAIN,
        title="alice",
        unique_id="identity-1",
        data={
            "username": "alice",
            CONF_REFRESH_TOKEN: "refresh-1",
            CONF_ACCOUNT_ID: "identity-1",
        },
    )


async def test_setup_authenticates_from_cache_and_registers_callbacks_before_start(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = install_runtime_fakes(monkeypatch)
    entry = make_entry()
    entry.add_to_hass(hass)

    assert await integration_module.async_setup_entry(hass, entry) is True

    assert harness.auth.usernames == ["alice"]
    assert harness.client.order == [
        "authenticate_from_cache",
        "on_update",
        "on_event",
        "on_connection_change",
        "on_error",
        "start",
    ]
    assert entry.runtime_data.coordinator.client is harness.client
    await entry.runtime_data.coordinator.async_shutdown()


async def test_setup_observes_unchanged_initial_shadow_through_public_state(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = make_place_device(last_shadow_at=None)
    harness = install_runtime_fakes(
        monkeypatch,
        ready_on_start=False,
        ready_after_start=True,
        devices=[device],
    )
    entry = make_entry()
    entry.add_to_hass(hass)

    assert await integration_module.async_setup_entry(hass, entry) is True

    assert device.last_shadow_at == _INITIAL_SHADOW_TIME
    assert len(harness.client.update_callbacks) == 1
    await entry.runtime_data.coordinator.async_shutdown()


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (PlaceInvalidAuthError("rejected"), ConfigEntryAuthFailed),
        (PlaceTransientAuthError("temporary"), ConfigEntryNotReady),
        (PlaceAuthError("unclassified"), ConfigEntryNotReady),
    ],
)
async def test_setup_maps_cache_auth_failures(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    error: BaseException,
    expected: type[Exception],
) -> None:
    install_runtime_fakes(monkeypatch, auth_result=error)
    entry = make_entry()
    entry.add_to_hass(hass)

    with pytest.raises(expected):
        await integration_module.async_setup_entry(hass, entry)


@pytest.mark.parametrize(
    "error",
    [
        PlaceTransientAuthError("temporary"),
        PlaceDiscoveryError("discovery"),
        PlaceConnectionError("connection"),
    ],
)
async def test_setup_maps_retryable_client_start_failures(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    harness = install_runtime_fakes(monkeypatch, start_result=error)
    entry = make_entry()
    entry.add_to_hass(hass)

    with pytest.raises(ConfigEntryNotReady):
        await integration_module.async_setup_entry(hass, entry)

    assert harness.client.stop_completed is True
    assert harness.client.update_callbacks == []
    assert harness.client.event_callbacks == []
    assert harness.client.connection_callbacks == []
    assert harness.client.error_callbacks == []


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (PlaceInvalidAuthError("rejected"), ConfigEntryAuthFailed),
        (PlaceTransientAuthError("temporary"), ConfigEntryNotReady),
        (PlaceAuthError("unclassified"), ConfigEntryNotReady),
    ],
)
async def test_setup_maps_errors_emitted_by_startup_callback(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    error: PlaceAuthError,
    expected: type[Exception],
) -> None:
    harness = install_runtime_fakes(
        monkeypatch,
        ready_on_start=False,
        error_after_start=error,
    )
    monkeypatch.setattr(
        "custom_components.gentex_place.coordinator._STARTUP_POLL_SECONDS", 0
    )
    entry = make_entry()
    entry.add_to_hass(hass)

    with pytest.raises(expected):
        await integration_module.async_setup_entry(hass, entry)

    assert harness.client.stop_completed is True


async def test_setup_preserves_programmer_timeout_from_client_start(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_runtime_fakes(
        monkeypatch, start_result=TimeoutError("non-network programmer error")
    )
    entry = make_entry()
    entry.add_to_hass(hass)

    with pytest.raises(TimeoutError, match="programmer error"):
        await integration_module.async_setup_entry(hass, entry)


async def test_setup_preserves_cancellation_from_client_start(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_runtime_fakes(monkeypatch, start_result=asyncio.CancelledError())
    entry = make_entry()
    entry.add_to_hass(hass)

    with pytest.raises(asyncio.CancelledError):
        await integration_module.async_setup_entry(hass, entry)


@pytest.mark.parametrize(
    ("connected", "last_shadow_at"),
    [(False, 100.0), (True, None)],
)
async def test_setup_requires_connection_and_one_shadow_within_deadline(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    connected: bool,  # noqa: FBT001 - table parameter models connection state
    last_shadow_at: float | None,
) -> None:
    device = make_place_device(last_shadow_at=last_shadow_at)
    harness = install_runtime_fakes(monkeypatch, ready_on_start=False, devices=[device])
    harness.client.connected = connected
    monkeypatch.setattr(
        "custom_components.gentex_place.coordinator.STARTUP_TIMEOUT_SECONDS", 0
    )
    entry = make_entry()
    entry.add_to_hass(hass)

    with pytest.raises(ConfigEntryNotReady):
        await integration_module.async_setup_entry(hass, entry)

    assert harness.client.stop_completed is True


async def test_setup_accepts_one_answering_device_and_leaves_sibling_unavailable(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    answering = make_place_device(thing_name="thing-answer", last_shadow_at=100.0)
    silent = make_place_device(
        thing_name="thing-silent", device_id="device-2", last_shadow_at=None
    )
    harness = install_runtime_fakes(
        monkeypatch, ready_on_start=False, devices=[answering, silent]
    )
    harness.client.connected = True
    entry = make_entry()
    entry.add_to_hass(hass)

    assert await integration_module.async_setup_entry(hass, entry) is True

    coordinator = entry.runtime_data.coordinator
    monkeypatch.setattr(
        "custom_components.gentex_place.coordinator.time.monotonic", lambda: 100.0
    )
    assert coordinator.device_available("thing-answer") is True
    assert coordinator.device_available("thing-silent") is False
    await coordinator.async_shutdown()


async def test_unload_cancels_runtime_resources_and_awaits_stop(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = install_runtime_fakes(monkeypatch)
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await integration_module.async_setup_entry(hass, entry) is True
    coordinator = entry.runtime_data.coordinator
    existing_handles = set(get_scheduled_timer_handles(hass.loop))
    remove_listener = coordinator.async_add_listener(lambda: None)
    harness.client.emit_event(
        DeviceEvent(event_type="motionDetected", thing_name="thing-1"),
        now=100.0,
    )
    runtime_handles = {
        handle
        for handle in get_scheduled_timer_handles(hass.loop)
        if not handle.cancelled() and handle not in existing_handles
    }

    assert await integration_module.async_unload_entry(hass, entry) is True

    remove_listener()
    assert runtime_handles
    assert all(handle.cancelled() for handle in runtime_handles)
    assert harness.client.stop_completed is True
    assert harness.client.update_callbacks == []
    assert harness.client.event_callbacks == []
    assert harness.client.connection_callbacks == []
    assert harness.client.error_callbacks == []
