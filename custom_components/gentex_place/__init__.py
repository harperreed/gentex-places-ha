# Copyright (c) 2026 Harper Reed
# ABOUTME: Defines the Gentex PLACE Home Assistant integration package.
# ABOUTME: Loads config entries and owns their typed PLACE runtime lifecycle.
"""The Gentex PLACE Home Assistant integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from place import (
    PlaceAuthError,
    PlaceConnectionError,
    PlaceDiscoveryError,
    PlaceInvalidAuthError,
    PlaceTimeoutError,
)

from .auth import ConfigEntryTokenCache, create_auth, create_client
from .const import DOMAIN, PLATFORMS, safe_entry_title
from .coordinator import GentexPlaceCoordinator, StartupTimeoutError

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


@dataclass
class GentexPlaceRuntimeData:
    """Hold the active account coordinator for a loaded config entry."""

    coordinator: GentexPlaceCoordinator


type GentexPlaceConfigEntry = ConfigEntry[GentexPlaceRuntimeData]


def _raise_setup_error(
    error: ConfigEntryAuthFailed | ConfigEntryNotReady | None,
) -> None:
    """Raise a sanitized setup error after leaving the raw SDK handler."""
    if error is not None:
        raise error


async def async_setup_entry(hass: HomeAssistant, entry: GentexPlaceConfigEntry) -> bool:
    """Authenticate from the stored refresh token and start one account runtime."""
    entry_title = safe_entry_title(
        (
            existing_entry.title
            for existing_entry in hass.config_entries.async_entries(DOMAIN)
        ),
        current_title=entry.title,
    )
    if entry.title != entry_title:
        hass.config_entries.async_update_entry(entry, title=entry_title)
    token_cache = ConfigEntryTokenCache(hass, entry)
    auth = create_auth(hass, token_cache)
    username = entry.data["username"]
    setup_error: ConfigEntryAuthFailed | ConfigEntryNotReady | None = None
    try:
        await auth.authenticate_from_cache(username)
    except PlaceInvalidAuthError as err:
        setup_error = ConfigEntryAuthFailed(type(err).__name__)
    except PlaceAuthError as err:
        setup_error = ConfigEntryNotReady(type(err).__name__)
    _raise_setup_error(setup_error)

    client = create_client(auth)
    coordinator = GentexPlaceCoordinator(hass, entry, client)
    setup_error = None
    try:
        await coordinator.async_start()
    except PlaceInvalidAuthError as err:
        setup_error = ConfigEntryAuthFailed(type(err).__name__)
    except (
        PlaceAuthError,
        PlaceConnectionError,
        PlaceDiscoveryError,
        PlaceTimeoutError,
        StartupTimeoutError,
    ) as err:
        setup_error = ConfigEntryNotReady(type(err).__name__)
    _raise_setup_error(setup_error)

    entry.runtime_data = GentexPlaceRuntimeData(coordinator=coordinator)
    if PLATFORMS:
        try:
            await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        except asyncio.CancelledError:
            await coordinator.async_shutdown()
            raise
        except Exception:
            await coordinator.async_shutdown()
            raise
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: GentexPlaceConfigEntry
) -> bool:
    """Unload entity platforms before stopping the PLACE client."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await entry.runtime_data.coordinator.async_shutdown()
    return True
