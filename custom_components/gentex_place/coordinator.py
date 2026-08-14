# Copyright (c) 2026 Gentex
# ABOUTME: Coordinates PLACE client startup, push state, health, and motion timing.
# ABOUTME: The SDK device registry remains the single source of device state.
"""Runtime coordinator for Gentex PLACE accounts."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, override

from homeassistant.core import callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from place import (
    DeviceEvent,
    PlaceClient,
    PlaceConnectionError,
    PlaceDevice,
    PlaceError,
    PlaceInvalidAuthError,
    PlaceTransientAuthError,
)

from .const import (
    DOMAIN,
    HEALTH_INTERVAL,
    MOTION_WINDOW_SECONDS,
    STALE_AFTER_SECONDS,
    STARTUP_TIMEOUT_SECONDS,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from homeassistant.core import HomeAssistant

    from . import GentexPlaceConfigEntry

type DeviceMap = dict[str, PlaceDevice]

LOGGER = logging.getLogger(__name__)
_STARTUP_POLL_SECONDS = 0.1
_DISCONNECTED_UPDATE = "PLACE client is disconnected"


class StartupTimeoutError(Exception):
    """The account did not produce its first connected shadow before the deadline."""


class GentexPlaceCoordinator(DataUpdateCoordinator[DeviceMap]):
    """Own one PLACE client and translate its callbacks into HA updates."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: GentexPlaceConfigEntry,
        client: PlaceClient,
    ) -> None:
        """Create an idle coordinator for one config entry."""
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
        self._entry = entry
        self._client_unsubscribers: list[Callable[[], None]] = []
        self._motion_timers: dict[str, Callable[[], None]] = {}
        self._starting = False
        self._startup_error: PlaceError | None = None
        self._reauth_requested = False
        self._shutdown_lock = asyncio.Lock()
        self._cleanup_complete = False
        self._client_stopped = False
        self._refresh_previous_success = self.last_update_success
        self._refresh_previous_data = self.data

    async def async_start(self) -> None:
        """Register callbacks, start the client, and await public readiness state."""
        self._starting = True
        self._client_unsubscribers = [
            self.client.on_update(self._handle_update),
            self.client.on_event(self._handle_event),
            self.client.on_connection_change(self._handle_connection_change),
            self.client.on_error(self._handle_error),
        ]
        deadline = asyncio.timeout(STARTUP_TIMEOUT_SECONDS)
        try:
            async with deadline:
                await self.client.start()
                await self._async_wait_until_ready()
        except TimeoutError as err:
            await self.async_shutdown()
            if deadline.expired():
                raise StartupTimeoutError from err
            raise
        except asyncio.CancelledError:
            await self.async_shutdown()
            raise
        except Exception:
            await self.async_shutdown()
            raise
        self._starting = False
        self.data = self.client.devices

    async def _async_wait_until_ready(self) -> None:
        """Observe public client state until one device has answered a shadow get."""
        while True:
            if self._startup_error is not None:
                raise self._startup_error
            devices = self.client.devices
            if self.client.connected and any(
                device.last_shadow_at is not None for device in devices.values()
            ):
                return
            await asyncio.sleep(_STARTUP_POLL_SECONDS)

    @callback
    @override
    def async_set_updated_data(self, data: DeviceMap) -> None:
        """Notify push data without postponing the fixed health refresh."""
        self.data = data
        self.last_update_success = True
        self.async_update_listeners()

    @override
    async def _async_update_data(self) -> DeviceMap:
        """Request one shadow refresh covering every discovered device."""
        self._refresh_previous_success = self.last_update_success
        self._refresh_previous_data = self.data
        update_error: UpdateFailed | None = None
        try:
            await self.client.async_refresh_shadow()
        except PlaceConnectionError:
            update_error = UpdateFailed(_DISCONNECTED_UPDATE)
        if update_error is not None:
            raise update_error
        return self.client.devices

    @callback
    @override
    def _async_refresh_finished(self) -> None:
        """Notify availability views after every fixed health refresh."""
        if (
            self.last_update_success == self._refresh_previous_success
            and self.data == self._refresh_previous_data
        ):
            self.async_update_listeners()

    def device_available(self, device_key: str) -> bool:
        """Return whether a device has answered within the stale window."""
        if not self.client.connected:
            return False
        device = self.data.get(device_key)
        if device is None or device.last_shadow_at is None:
            return False
        return time.monotonic() - device.last_shadow_at <= STALE_AFTER_SECONDS

    def motion_active(self, device_key: str) -> bool:
        """Return whether a device emitted motion within the configured window."""
        device = self.data.get(device_key)
        if device is None:
            return False
        return device.motion(MOTION_WINDOW_SECONDS, now=time.monotonic())

    @callback
    def _handle_update(self, _device: PlaceDevice) -> None:
        """Publish the client's current registry after an SDK state change."""
        self.async_set_updated_data(self.client.devices)

    @callback
    def _handle_connection_change(self, connected: bool) -> None:  # noqa: FBT001
        """Publish connection changes and reset reauth gating after recovery."""
        if connected:
            self._reauth_requested = False
        self.async_set_updated_data(self.client.devices)

    @callback
    def _handle_error(self, error: PlaceError) -> None:
        """Map startup errors and request reauth for invalid runtime auth."""
        if self._starting:
            self._startup_error = error
            return
        if isinstance(error, PlaceInvalidAuthError) and not self._reauth_requested:
            self._reauth_requested = True
            self._entry.async_start_reauth(self.hass)
        elif isinstance(error, PlaceTransientAuthError):
            return

    @callback
    def _handle_event(self, event: DeviceEvent) -> None:
        """Schedule the end notification for a motion event."""
        if not event.is_motion:
            return
        device_key = self._device_key_for_event(event)
        if device_key is None:
            return
        if cancel := self._motion_timers.pop(device_key, None):
            cancel()

        @callback
        def clear_motion(_now: datetime) -> None:
            self._clear_motion(device_key)

        self._motion_timers[device_key] = async_call_later(
            self.hass,
            MOTION_WINDOW_SECONDS,
            clear_motion,
        )

    def _device_key_for_event(self, event: DeviceEvent) -> str | None:
        """Resolve an event through its public thing or device identity."""
        devices = self.client.devices
        if event.thing_name is not None and event.thing_name in devices:
            return event.thing_name
        if event.device_id is None:
            return None
        return next(
            (
                key
                for key, device in devices.items()
                if device.device_id == event.device_id
            ),
            None,
        )

    @callback
    def _clear_motion(self, device_key: str) -> None:
        """Notify listeners that a device's motion window has elapsed."""
        self._motion_timers.pop(device_key, None)
        self.async_set_updated_data(self.client.devices)

    @override
    async def async_shutdown(self) -> None:
        """Cancel callbacks and timers, then await SDK client shutdown."""
        async with self._shutdown_lock:
            if self._client_stopped:
                return
            if not self._cleanup_complete:
                self._starting = False
                for unsubscribe in self._client_unsubscribers:
                    unsubscribe()
                self._client_unsubscribers.clear()
                for cancel in self._motion_timers.values():
                    cancel()
                self._motion_timers.clear()
                await super().async_shutdown()
                self._cleanup_complete = True
            stop_error: PlaceConnectionError | None = None
            try:
                await self.client.stop()
            except PlaceConnectionError as err:
                stop_error = PlaceConnectionError(type(err).__name__)
            if stop_error is not None:
                raise stop_error
            self._client_stopped = True
