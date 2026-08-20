# Copyright (c) 2026 Gentex
# ABOUTME: Verifies PLACE push updates, liveness, motion, and fixed health timing.
# ABOUTME: Tests advance Home Assistant timers directly and never wait on wall time.
"""Tests for the Gentex PLACE runtime coordinator."""

from __future__ import annotations

import asyncio
import json
import logging
import traceback
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

import pytest
from homeassistant.util.async_ import get_scheduled_timer_handles
from place import (
    DeviceEvent,
    PlaceAuthError,
    PlaceClient,
    PlaceConnectionError,
    PlaceDevice,
    PlaceInvalidAuthError,
    PlaceTransientAuthError,
)
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.gentex_place.const import MOTION_WINDOW_SECONDS
from custom_components.gentex_place.coordinator import GentexPlaceCoordinator
from tests.components.gentex_place.fakes import (
    CancellationBlocker,
    CompletionBlocker,
    FakePlaceClient,
    RecordingConfigEntry,
    make_place_device,
)
from tests.components.gentex_place.test_init import make_entry

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_EXPECTED_PUSH_NOTIFICATIONS = 2
_EXPECTED_REAUTH_OUTAGES = 2
_EXPECTED_RETRIED_STOP_CALLS = 2


@dataclass
class MonotonicClock:
    """Expose deterministic elapsed time to coordinator liveness checks."""

    value: float

    def __call__(self) -> float:
        """Return the current test timestamp."""
        return self.value


async def start_coordinator(
    hass: HomeAssistant,
    *,
    entry: RecordingConfigEntry | None = None,
    devices: list[PlaceDevice] | None = None,
) -> tuple[GentexPlaceCoordinator, FakePlaceClient, RecordingConfigEntry]:
    """Create and start a ready coordinator around the hand-written client fake."""
    runtime_entry = entry or make_entry()
    runtime_devices = devices or [make_place_device()]
    client = FakePlaceClient(
        device_registry={device.thing_name: device for device in runtime_devices}
    )
    coordinator = GentexPlaceCoordinator(
        hass, runtime_entry, cast("PlaceClient", client)
    )
    await coordinator.async_start()
    return coordinator, client, runtime_entry


async def test_push_updates_and_connection_changes_notify_listeners(
    hass: HomeAssistant,
) -> None:
    coordinator, client, _entry = await start_coordinator(hass)
    notifications = 0

    def record_update() -> None:
        nonlocal notifications
        notifications += 1

    remove_listener = coordinator.async_add_listener(record_update)

    client.emit_update(client.device_registry["thing-1"])
    client.emit_connection_change(connected=False)

    assert notifications == _EXPECTED_PUSH_NOTIFICATIONS
    remove_listener()
    await coordinator.async_shutdown()


async def test_push_does_not_replace_fixed_health_timer(hass: HomeAssistant) -> None:
    coordinator, client, _entry = await start_coordinator(hass)
    existing_handles = set(get_scheduled_timer_handles(hass.loop))
    remove_listener = coordinator.async_add_listener(lambda: None)
    health_handles = set(get_scheduled_timer_handles(hass.loop)) - existing_handles
    assert len(health_handles) == 1
    health_handle = health_handles.pop()

    client.emit_update(client.device_registry["thing-1"])

    assert health_handle.cancelled() is False
    assert health_handle in get_scheduled_timer_handles(hass.loop)
    remove_listener()
    await coordinator.async_shutdown()


async def test_health_interval_refreshes_all_devices_once(
    hass: HomeAssistant,
) -> None:
    coordinator, client, _entry = await start_coordinator(hass)
    notifications = 0

    def record_update() -> None:
        nonlocal notifications
        notifications += 1

    remove_listener = coordinator.async_add_listener(record_update)

    async_fire_time_changed(hass, datetime.now(UTC) + timedelta(minutes=5, seconds=1))
    await hass.async_block_till_done()

    assert client.refresh_calls == 1
    assert notifications == 1
    remove_listener()
    await coordinator.async_shutdown()


async def test_disconnected_health_refresh_stays_scheduled(
    hass: HomeAssistant,
) -> None:
    coordinator, client, _entry = await start_coordinator(hass)
    client.refresh_result = PlaceConnectionError("offline")
    remove_listener = coordinator.async_add_listener(lambda: None)

    await coordinator.async_refresh()

    assert coordinator.last_update_success is False
    assert any(
        not handle.cancelled() for handle in get_scheduled_timer_handles(hass.loop)
    )
    remove_listener()
    await coordinator.async_shutdown()


async def test_consecutive_failed_health_intervals_notify_when_device_becomes_stale(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = make_place_device(last_shadow_at=100.0)
    coordinator, client, _entry = await start_coordinator(hass, devices=[device])
    clock = MonotonicClock(1000.0)
    monkeypatch.setattr(
        "custom_components.gentex_place.coordinator.time.monotonic", clock
    )
    client.refresh_result = PlaceConnectionError("offline")
    availability_updates: list[bool] = []
    remove_listener = coordinator.async_add_listener(
        lambda: availability_updates.append(coordinator.device_available("thing-1"))
    )

    await coordinator.async_refresh()
    clock.value = 1000.001
    await coordinator.async_refresh()

    assert availability_updates == [True, False]
    remove_listener()
    await coordinator.async_shutdown()


@pytest.mark.parametrize(
    ("now", "expected"),
    [(1000.0, True), (1000.001, False)],
)
async def test_device_availability_has_exact_stale_edge(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    now: float,
    expected: bool,  # noqa: FBT001 - table parameter intentionally models a boolean
) -> None:
    device = make_place_device(last_shadow_at=100.0)
    coordinator, _client, _entry = await start_coordinator(hass, devices=[device])
    clock = MonotonicClock(now)
    monkeypatch.setattr(
        "custom_components.gentex_place.coordinator.time.monotonic", clock
    )

    assert coordinator.device_available("thing-1") is expected
    await coordinator.async_shutdown()


async def test_motion_remains_active_through_window(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    coordinator, client, _entry = await start_coordinator(hass)
    clock = MonotonicClock(100.0)
    monkeypatch.setattr(
        "custom_components.gentex_place.coordinator.time.monotonic", clock
    )
    client.emit_event(
        DeviceEvent(event_type="motionDetected", thing_name="thing-1"), now=100.0
    )

    clock.value = 100.0 + MOTION_WINDOW_SECONDS
    assert coordinator.motion_active("thing-1") is True
    clock.value += 0.001
    assert coordinator.motion_active("thing-1") is False
    await coordinator.async_shutdown()


async def test_motion_is_inactive_for_absent_device(hass: HomeAssistant) -> None:
    coordinator, _client, _entry = await start_coordinator(hass)

    assert coordinator.motion_active("missing-thing") is False

    await coordinator.async_shutdown()


async def test_non_motion_event_does_not_create_motion_window(
    hass: HomeAssistant,
) -> None:
    coordinator, client, _entry = await start_coordinator(hass)
    motion_updates: list[bool] = []
    remove_listener = coordinator.async_add_listener(
        lambda: motion_updates.append(coordinator.motion_active("thing-1"))
    )

    client.emit_event(
        DeviceEvent(event_type="buttonPressed", thing_name="thing-1"), now=100.0
    )
    async_fire_time_changed(hass, datetime.now(UTC) + timedelta(seconds=31))
    await hass.async_block_till_done()

    assert motion_updates == [False]
    assert coordinator.motion_active("thing-1") is False
    remove_listener()
    await coordinator.async_shutdown()


async def test_unknown_device_motion_event_is_ignored(hass: HomeAssistant) -> None:
    coordinator, client, _entry = await start_coordinator(hass)
    motion_updates: list[bool] = []
    remove_listener = coordinator.async_add_listener(
        lambda: motion_updates.append(coordinator.motion_active("thing-1"))
    )

    client.emit_event(
        DeviceEvent(event_type="motionDetected", thing_name="missing-thing"),
        now=100.0,
    )
    async_fire_time_changed(hass, datetime.now(UTC) + timedelta(seconds=31))
    await hass.async_block_till_done()

    assert motion_updates == []
    assert coordinator.motion_active("thing-1") is False
    remove_listener()
    await coordinator.async_shutdown()


async def test_motion_event_uses_known_device_id_when_thing_name_is_absent(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    coordinator, client, _entry = await start_coordinator(hass)
    clock = MonotonicClock(100.0)
    monkeypatch.setattr(
        "custom_components.gentex_place.coordinator.time.monotonic", clock
    )

    client.emit_event(
        DeviceEvent(event_type="motionDetected", device_id="device-1"), now=100.0
    )

    assert coordinator.motion_active("thing-1") is True
    clock.value = 100.0 + MOTION_WINDOW_SECONDS + 0.001
    async_fire_time_changed(hass, datetime.now(UTC) + timedelta(seconds=31))
    await hass.async_block_till_done()
    assert coordinator.motion_active("thing-1") is False
    await coordinator.async_shutdown()


async def test_repeated_motion_replaces_clear_timer_and_notifies_once_at_end(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    coordinator, client, _entry = await start_coordinator(hass)
    clock = MonotonicClock(100.0)
    monkeypatch.setattr(
        "custom_components.gentex_place.coordinator.time.monotonic", clock
    )
    notifications = 0

    def record_update() -> None:
        nonlocal notifications
        notifications += 1

    remove_listener = coordinator.async_add_listener(record_update)
    client.emit_event(
        DeviceEvent(event_type="motionDetected", thing_name="thing-1"), now=100.0
    )
    assert notifications == 1
    first_motion_handles = {
        handle
        for handle in get_scheduled_timer_handles(hass.loop)
        if not handle.cancelled()
    }
    clock.value = 120.0
    client.emit_event(
        DeviceEvent(event_type="motionDetected", thing_name="thing-1"), now=120.0
    )

    assert any(handle.cancelled() for handle in first_motion_handles)
    notifications_before_clear = notifications
    clock.value = 151.0
    async_fire_time_changed(hass, datetime.now(UTC) + timedelta(seconds=31))
    await hass.async_block_till_done()
    assert notifications == notifications_before_clear + 1
    assert coordinator.motion_active("thing-1") is False
    remove_listener()
    await coordinator.async_shutdown()


async def test_invalid_runtime_auth_starts_reauth_once_per_outage(
    hass: HomeAssistant,
) -> None:
    entry = make_entry()
    coordinator, client, _entry = await start_coordinator(hass, entry=entry)

    client.emit_connection_change(connected=False)
    client.emit_error(PlaceInvalidAuthError("rejected"))
    client.emit_error(PlaceInvalidAuthError("rejected again"))
    client.emit_connection_change(connected=True)
    client.emit_connection_change(connected=False)
    client.emit_error(PlaceInvalidAuthError("new outage"))

    assert entry.reauth_calls == _EXPECTED_REAUTH_OUTAGES
    await coordinator.async_shutdown()


@pytest.mark.parametrize(
    "error",
    [PlaceTransientAuthError("temporary"), PlaceAuthError("unclassified")],
)
async def test_other_runtime_auth_errors_do_not_start_reauth(
    hass: HomeAssistant, error: PlaceAuthError
) -> None:
    entry = make_entry()
    coordinator, client, _entry = await start_coordinator(hass, entry=entry)

    client.emit_connection_change(connected=False)
    client.emit_error(error)

    assert entry.reauth_calls == 0
    await coordinator.async_shutdown()


async def test_cancelled_health_refresh_propagates(
    hass: HomeAssistant,
) -> None:
    coordinator, client, _entry = await start_coordinator(hass)
    blocker = CancellationBlocker()
    client.refresh_result = blocker
    refresh = asyncio.create_task(coordinator.async_refresh())
    await blocker.entered.wait()
    refresh.cancel()

    with pytest.raises(asyncio.CancelledError):
        await refresh

    await coordinator.async_shutdown()


async def test_programmer_timeout_from_refresh_is_not_remapped(
    hass: HomeAssistant,
) -> None:
    coordinator, client, _entry = await start_coordinator(hass)
    client.refresh_result = TimeoutError("programmer error")

    await coordinator.async_refresh()

    assert isinstance(coordinator.last_exception, TimeoutError)
    await coordinator.async_shutdown()


async def test_concurrent_shutdown_waits_for_the_single_client_stop(
    hass: HomeAssistant,
) -> None:
    coordinator, client, _entry = await start_coordinator(hass)
    blocker = CompletionBlocker()
    client.stop_results = [blocker]

    first_shutdown = asyncio.create_task(coordinator.async_shutdown())
    await blocker.entered.wait()
    second_shutdown = asyncio.create_task(coordinator.async_shutdown())
    loop_turn = asyncio.Event()
    hass.loop.call_soon(loop_turn.set)
    await loop_turn.wait()

    assert second_shutdown.done() is False
    blocker.release.set()
    await asyncio.gather(first_shutdown, second_shutdown)
    assert client.stop_calls == 1
    assert client.stop_completed is True


async def test_shutdown_retries_client_stop_after_failure(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    coordinator, client, _entry = await start_coordinator(hass)
    canary = "PRIVATE_STOP_ERROR_7F31"
    raw_error = PlaceConnectionError(canary)
    client.stop_results = [raw_error, None]
    caplog.set_level(logging.DEBUG)

    with pytest.raises(PlaceConnectionError) as error_info:
        await coordinator.async_shutdown()
    public_error = error_info.value
    assert public_error is not raw_error
    assert public_error.__cause__ is None
    assert public_error.__context__ is None
    serialized = json.dumps(
        {
            "error": public_error,
            "traceback": traceback.format_exception(public_error),
            "logs": caplog.text,
        },
        default=str,
    )
    assert canary not in serialized
    assert "PlaceConnectionError" in serialized
    assert client.stop_calls == 1
    assert client.stop_completed is False
    assert client.update_callbacks == []
    assert client.event_callbacks == []
    assert client.connection_callbacks == []
    assert client.error_callbacks == []

    await coordinator.async_shutdown()

    assert client.stop_calls == _EXPECTED_RETRIED_STOP_CALLS
    assert client.stop_completed is True


async def test_shutdown_retries_client_stop_after_genuine_cancellation(
    hass: HomeAssistant,
) -> None:
    coordinator, client, _entry = await start_coordinator(hass)
    blocker = CancellationBlocker()
    client.stop_results = [blocker, None]
    cancelled_shutdown = asyncio.create_task(coordinator.async_shutdown())
    await blocker.entered.wait()
    cancelled_shutdown.cancel()

    with pytest.raises(asyncio.CancelledError):
        await cancelled_shutdown
    await coordinator.async_shutdown()

    assert client.stop_calls == _EXPECTED_RETRIED_STOP_CALLS
    assert client.stop_completed is True
