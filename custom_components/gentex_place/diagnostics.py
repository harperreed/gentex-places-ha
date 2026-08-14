# Copyright (c) 2026 Gentex
# ABOUTME: Builds a strict allow-list of private-safe PLACE support diagnostics.
# ABOUTME: Device and exception identifiers never enter the returned structure.
"""Diagnostics support for Gentex PLACE."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import place
from homeassistant import const as ha_const
from homeassistant import loader

from .const import (
    DOMAIN,
    HEALTH_INTERVAL,
    MOTION_WINDOW_SECONDS,
    STALE_AFTER_SECONDS,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from . import GentexPlaceConfigEntry


def _liveness_age(last_shadow_at: float | None) -> int | None:
    """Return whole seconds since the last shadow without exposing its timestamp."""
    if last_shadow_at is None:
        return None
    return round(time.monotonic() - last_shadow_at)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: GentexPlaceConfigEntry
) -> dict[str, Any]:
    """Return freshly built, explicitly allowed diagnostics for one PLACE entry."""
    integration = await loader.async_get_integration(hass, DOMAIN)
    coordinator = entry.runtime_data.coordinator
    devices = [
        {
            "model": device.model,
            "firmware": device.firmware_version,
            "available": coordinator.device_available(device_key),
            "liveness_age_seconds": _liveness_age(device.last_shadow_at),
        }
        for device_key, device in coordinator.data.items()
    ]
    last_exception = coordinator.last_exception
    integration_version = integration.version
    return {
        "integration_version": (
            str(integration_version) if integration_version is not None else None
        ),
        "home_assistant_version": ha_const.__version__,
        "sdk_version": place.__version__,
        "connected": coordinator.client.connected,
        "config_entry_state": entry.state.value,
        "last_update_success": coordinator.last_update_success,
        "device_count": len(devices),
        "devices": devices,
        "timing": {
            "health_interval_seconds": int(HEALTH_INTERVAL.total_seconds()),
            "stale_after_seconds": STALE_AFTER_SECONDS,
            "motion_window_seconds": MOTION_WINDOW_SECONDS,
        },
        "last_error": (
            type(last_exception).__name__ if last_exception is not None else None
        ),
    }
