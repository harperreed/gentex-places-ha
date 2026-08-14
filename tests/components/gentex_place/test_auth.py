# Copyright (c) 2026 Gentex
# ABOUTME: Verifies config-entry refresh-token persistence and auth factories.
# ABOUTME: Passwords and short-lived cloud credentials must never enter entry data.
"""Tests for token persistence and SDK factory construction."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from place import CognitoAuth, PlaceClient, PlaceConfig
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.gentex_place import auth as auth_module
from custom_components.gentex_place.auth import (
    ConfigEntryTokenCache,
    MemoryTokenCache,
    create_auth,
    create_client,
)
from custom_components.gentex_place.const import (
    CONF_ACCOUNT_ID,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

SECRET_FIELDS = {
    "password": "PASSWORD-CANARY",
    "access_token": "ACCESS-CANARY",
    "id_token": "ID-CANARY",
    "aws_access_key_id": "AWS-ACCESS-CANARY",
    "aws_secret_access_key": "AWS-SECRET-CANARY",
    "aws_session_token": "AWS-SESSION-CANARY",
}


def _entry_data(*, refresh_token: object = "old") -> dict[str, Any]:
    """Return the durable account fields used by token-cache tests."""
    return {
        "username": "alice",
        CONF_REFRESH_TOKEN: refresh_token,
        CONF_ACCOUNT_ID: "acct",
    }


def test_config_entry_token_cache_loads_only_username_and_refresh_token(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={**_entry_data(), **SECRET_FIELDS})
    entry.add_to_hass(hass)

    result = ConfigEntryTokenCache(hass, entry).load()

    assert result == {"username": "alice", "refresh_token": "old"}


def test_config_entry_token_cache_save_changes_only_refresh_token_for_same_account(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data())
    entry.add_to_hass(hass)
    cache = ConfigEntryTokenCache(hass, entry)

    cache.save(
        {
            "username": "alice",
            "refresh_token": "new",
            **SECRET_FIELDS,
        }
    )

    assert entry.data == _entry_data(refresh_token="new")
    assert not SECRET_FIELDS.keys() & entry.data.keys()


@pytest.mark.parametrize(
    "token_data",
    [
        {"refresh_token": "new"},
        {"username": None, "refresh_token": "new"},
        {"username": 42, "refresh_token": "new"},
        {"username": "", "refresh_token": "new"},
        {"username": "mallory", "refresh_token": "new"},
    ],
)
def test_config_entry_token_cache_rejects_token_for_invalid_or_other_account(
    hass: HomeAssistant, token_data: dict[str, object]
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data())
    entry.add_to_hass(hass)

    ConfigEntryTokenCache(hass, entry).save({**token_data, **SECRET_FIELDS})

    assert entry.data == _entry_data()
    assert not SECRET_FIELDS.keys() & entry.data.keys()


def test_config_entry_token_cache_does_not_save_without_entry_username(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_REFRESH_TOKEN: "old", CONF_ACCOUNT_ID: "acct"},
    )
    entry.add_to_hass(hass)

    ConfigEntryTokenCache(hass, entry).save(
        {"username": "alice", "refresh_token": "new", **SECRET_FIELDS}
    )

    assert entry.data == {CONF_REFRESH_TOKEN: "old", CONF_ACCOUNT_ID: "acct"}
    assert not SECRET_FIELDS.keys() & entry.data.keys()


@pytest.mark.parametrize("entry_username", [None, 42, ""])
def test_config_entry_token_cache_does_not_save_for_invalid_entry_username(
    hass: HomeAssistant, entry_username: object
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": entry_username,
            CONF_REFRESH_TOKEN: "old",
            CONF_ACCOUNT_ID: "acct",
        },
    )
    entry.add_to_hass(hass)

    ConfigEntryTokenCache(hass, entry).save(
        {"username": "alice", "refresh_token": "new", **SECRET_FIELDS}
    )

    assert entry.data[CONF_REFRESH_TOKEN] == "old"
    assert not SECRET_FIELDS.keys() & entry.data.keys()


def test_config_entry_token_cache_clear_removes_only_refresh_token(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data())
    entry.add_to_hass(hass)

    ConfigEntryTokenCache(hass, entry).clear()

    assert entry.data == {"username": "alice", CONF_ACCOUNT_ID: "acct"}


@pytest.mark.parametrize("refresh_token", [None, 42, ""])
def test_config_entry_token_cache_rejects_invalid_stored_refresh_token(
    hass: HomeAssistant, refresh_token: object
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, data=_entry_data(refresh_token=refresh_token)
    )
    entry.add_to_hass(hass)

    assert ConfigEntryTokenCache(hass, entry).load() is None


def test_config_entry_token_cache_rejects_missing_stored_refresh_token(
    hass: HomeAssistant,
) -> None:
    data = _entry_data()
    del data[CONF_REFRESH_TOKEN]
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    entry.add_to_hass(hass)

    assert ConfigEntryTokenCache(hass, entry).load() is None


@pytest.mark.parametrize("refresh_token", [None, 42, ""])
def test_config_entry_token_cache_does_not_save_invalid_refresh_token(
    hass: HomeAssistant, refresh_token: object
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data())
    entry.add_to_hass(hass)

    ConfigEntryTokenCache(hass, entry).save(
        {"username": "alice", "refresh_token": refresh_token}
    )

    assert entry.data == _entry_data()


def test_config_entry_token_cache_rejects_invalid_username(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"username": "", CONF_REFRESH_TOKEN: "refresh", CONF_ACCOUNT_ID: "acct"},
    )
    entry.add_to_hass(hass)

    assert ConfigEntryTokenCache(hass, entry).load() is None


def test_memory_token_cache_keeps_only_username_and_refresh_token() -> None:
    cache = MemoryTokenCache()

    cache.save(
        {
            "username": "alice",
            "refresh_token": "refresh",
            **SECRET_FIELDS,
        }
    )

    assert cache.load() == {"username": "alice", "refresh_token": "refresh"}


def test_memory_token_cache_returns_defensive_copy() -> None:
    cache = MemoryTokenCache()
    cache.save({"username": "alice", "refresh_token": "refresh"})
    loaded = cache.load()
    assert loaded is not None

    loaded["refresh_token"] = "changed"

    assert cache.load() == {"username": "alice", "refresh_token": "refresh"}


@pytest.mark.parametrize(
    ("username", "refresh_token"),
    [
        (None, "refresh"),
        (42, "refresh"),
        ("", "refresh"),
        ("alice", None),
        ("alice", 42),
        ("alice", ""),
    ],
)
def test_memory_token_cache_clears_state_on_invalid_save(
    username: object, refresh_token: object
) -> None:
    cache = MemoryTokenCache()
    cache.save({"username": "alice", "refresh_token": "old"})

    cache.save({"username": username, "refresh_token": refresh_token, **SECRET_FIELDS})

    assert cache.load() is None


def test_memory_token_cache_clear_removes_saved_token() -> None:
    cache = MemoryTokenCache()
    cache.save({"username": "alice", "refresh_token": "refresh"})

    cache.clear()

    assert cache.load() is None


async def test_create_auth_returns_real_sdk_auth_using_ha_session(
    hass: HomeAssistant,
) -> None:
    cache = MemoryTokenCache()

    result = create_auth(hass, cache)

    assert isinstance(result, CognitoAuth)
    assert async_get_clientsession(hass) is not None


async def test_create_auth_passes_ha_session_and_cache_to_sdk(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = MemoryTokenCache()
    expected_session = async_get_clientsession(hass)
    constructed: dict[str, object] = {}

    class RecordingCognitoAuth:
        """Record the arguments at the public SDK constructor boundary."""

        def __init__(
            self,
            config: PlaceConfig,
            session: object,
            *,
            token_cache: object,
        ) -> None:
            """Capture constructor arguments without inspecting SDK internals."""
            constructed.update(
                {
                    "instance": self,
                    "config": config,
                    "session": session,
                    "token_cache": token_cache,
                }
            )

    monkeypatch.setattr(auth_module, "CognitoAuth", RecordingCognitoAuth)

    result = create_auth(hass, cache)

    assert result is constructed["instance"]
    assert isinstance(constructed["config"], PlaceConfig)
    assert constructed["session"] is expected_session
    assert constructed["token_cache"] is cache


async def test_create_client_returns_real_sdk_client(hass: HomeAssistant) -> None:
    sdk_auth = create_auth(hass, MemoryTokenCache())

    result = create_client(sdk_auth)

    assert isinstance(result, PlaceClient)


async def test_create_client_passes_auth_to_public_sdk_factory(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    sdk_auth = create_auth(hass, MemoryTokenCache())
    sentinel = object()
    constructed: dict[str, object] = {}

    class RecordingPlaceClient:
        """Record the arguments at the public SDK factory boundary."""

        @classmethod
        def create(cls, config: PlaceConfig, auth: CognitoAuth) -> object:
            """Capture factory arguments without inspecting SDK internals."""
            constructed.update({"config": config, "auth": auth})
            return sentinel

    monkeypatch.setattr(auth_module, "PlaceClient", RecordingPlaceClient)

    result = create_client(sdk_auth)

    assert result is sentinel
    assert isinstance(constructed["config"], PlaceConfig)
    assert constructed["auth"] is sdk_auth
