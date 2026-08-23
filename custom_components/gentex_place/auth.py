# Copyright (c) 2026 Harper Reed
# ABOUTME: Adapts Home Assistant config entries to the PLACE SDK auth interfaces.
# ABOUTME: Persists safe token data and builds clients with Home Assistant's session.
"""Authentication and token-cache adapters for Gentex PLACE."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from place import CognitoAuth, PlaceClient, PlaceConfig

from .const import CONF_REFRESH_TOKEN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


def _valid_token_data(data: dict[str, Any]) -> dict[str, Any] | None:
    """Return the two safe cache fields when both are non-empty strings."""
    username = data.get("username")
    refresh_token = data.get("refresh_token")
    if (
        not isinstance(username, str)
        or not username
        or not isinstance(refresh_token, str)
        or not refresh_token
    ):
        return None
    return {"username": username, "refresh_token": refresh_token}


class MemoryTokenCache:
    """Hold SDK token data in memory while collecting a config-flow login."""

    def __init__(self) -> None:
        """Create an empty token cache."""
        self._data: dict[str, Any] | None = None

    def load(self) -> dict[str, Any] | None:
        """Return a copy so callers cannot change stored state."""
        return dict(self._data) if self._data is not None else None

    def save(self, data: dict[str, Any]) -> None:
        """Keep only a valid username and refresh token."""
        self._data = _valid_token_data(data)

    def clear(self) -> None:
        """Forget the cached refresh token."""
        self._data = None


class ConfigEntryTokenCache:
    """Persist the SDK refresh token in an existing Home Assistant config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Bind the cache to an existing config entry."""
        self._hass = hass
        self._entry = entry

    def load(self) -> dict[str, Any] | None:
        """Return only the username and a valid refresh token."""
        return _valid_token_data(
            {
                "username": self._entry.data.get("username"),
                "refresh_token": self._entry.data.get(CONF_REFRESH_TOKEN),
            }
        )

    def save(self, data: dict[str, Any]) -> None:
        """Update only the refresh token, preserving all durable entry data."""
        token_data = _valid_token_data(data)
        entry_username = self._entry.data.get("username")
        if token_data is None or token_data["username"] != entry_username:
            return
        self._hass.config_entries.async_update_entry(
            self._entry,
            data={
                **self._entry.data,
                CONF_REFRESH_TOKEN: token_data["refresh_token"],
            },
        )

    def clear(self) -> None:
        """Remove only the refresh token from the config entry."""
        data = dict(self._entry.data)
        data.pop(CONF_REFRESH_TOKEN, None)
        self._hass.config_entries.async_update_entry(self._entry, data=data)


def create_auth(
    hass: HomeAssistant,
    token_cache: MemoryTokenCache | ConfigEntryTokenCache,
) -> CognitoAuth:
    """Build SDK authentication with Home Assistant's shared HTTP session."""
    return CognitoAuth(
        PlaceConfig(),
        async_get_clientsession(hass),
        token_cache=token_cache,
    )


def create_client(auth: CognitoAuth) -> PlaceClient:
    """Build the public SDK client for an authenticated account."""
    return PlaceClient.create(PlaceConfig(), auth)
