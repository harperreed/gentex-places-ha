# Copyright (c) 2026 Gentex
# ABOUTME: Verifies the opt-in PLACE live check exposes no secrets or write paths.
# ABOUTME: Exercises pure output helpers and credential-free CLI source contracts.
"""Tests for the read-only PLACE live release check."""

from __future__ import annotations

import ast
import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest
from place import (
    PlaceClient,
    PlaceConnectionError,
    PlaceDevice,
    PlaceDeviceShadow,
    PlaceInvalidAuthError,
)

from scripts.live_check import (
    _start_refresh_and_wait,
    build_summary,
    redact_exception,
)

LIVE_CHECK_PATH = Path("scripts/live_check.py")
_EXCEPTION_CANARY = "PASSWORD-CANARY"
_ARGUMENT_CANARY = "IDENTIFIER-CANARY"
_ARGUMENT_ERROR_EXIT_CODE = 2


class DelayedConnectionClient:
    """Expose the public client state while connection arrives on the next turn."""

    def __init__(self) -> None:
        """Create one discovered device with no reported shadow yet."""
        self.connected = False
        self._devices = {
            "device": PlaceDevice(
                thing_name="device",
                shadow=PlaceDeviceShadow(),
            )
        }
        self.refresh_calls = 0

    @property
    def devices(self) -> dict[str, PlaceDevice]:
        """Return a defensive copy through the SDK's public shape."""
        return dict(self._devices)

    async def start(self) -> None:
        """Schedule connection after start returns, as the real SDK does."""
        asyncio.get_running_loop().call_soon(self._connect)

    async def async_refresh_shadow(self) -> None:
        """Reject refresh before connection and then expose one reported shadow."""
        assert self.connected, "refresh called before connection"
        self.refresh_calls += 1
        self._devices["device"].last_shadow_at = 1.0

    def _connect(self) -> None:
        """Expose the delayed public connection state."""
        self.connected = True


class ConnectionDroppingClient(DelayedConnectionClient):
    """Drop the public connection after refresh supplies a reported shadow."""

    async def start(self) -> None:
        """Expose a connection before the refresh request."""
        self.connected = True

    async def async_refresh_shadow(self) -> None:
        """Supply reported state, then lose the connection before returning."""
        assert self.connected
        self.refresh_calls += 1
        self._devices["device"].last_shadow_at = 1.0
        self.connected = False


async def test_live_check_waits_for_connection_before_refresh() -> None:
    client = DelayedConnectionClient()

    await _start_refresh_and_wait(cast("PlaceClient", client))

    assert client.refresh_calls == 1
    assert client.devices["device"].last_shadow_at == 1.0


async def test_live_check_rejects_shadow_when_connection_drops() -> None:
    client = ConnectionDroppingClient()

    with pytest.raises(PlaceConnectionError, match=r"^$"):
        await _start_refresh_and_wait(cast("PlaceClient", client))

    assert client.refresh_calls == 1


def test_live_summary_has_counts_not_identifiers() -> None:
    devices = {
        "thing-CANARY": PlaceDevice(
            thing_name="thing-CANARY",
            device_id="device-CANARY",
            shadow=PlaceDeviceShadow(),
            last_shadow_at=1.0,
        )
    }

    text = json.dumps(build_summary(devices, connected=True))

    assert "thing-CANARY" not in text
    assert "device-CANARY" not in text
    assert json.loads(text) == {
        "connected": True,
        "device_count": 1,
        "devices_with_reported_state": 1,
    }


def test_live_summary_counts_only_public_reported_state() -> None:
    devices = {
        "silent": PlaceDevice(
            thing_name="silent",
            shadow=PlaceDeviceShadow(),
        ),
        "reported": PlaceDevice(
            thing_name="reported",
            shadow=PlaceDeviceShadow(),
            last_shadow_at=0.0,
        ),
    }

    assert build_summary(devices, connected=False) == {
        "connected": False,
        "device_count": 2,
        "devices_with_reported_state": 1,
    }


def test_redacted_exception_has_safe_type_and_category_only() -> None:
    error = PlaceInvalidAuthError(_EXCEPTION_CANARY)

    text = json.dumps(redact_exception(error))

    assert _EXCEPTION_CANARY not in text
    assert json.loads(text) == {
        "error_type": "PlaceInvalidAuthError",
        "category": "authentication",
    }


def test_live_check_help_needs_no_credentials() -> None:
    result = subprocess.run(  # noqa: S603 - fixed interpreter and repository script
        [sys.executable, str(LIVE_CHECK_PATH), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--username" in result.stdout
    assert "--password" not in result.stdout
    assert "--mfa" not in result.stdout
    assert "--output" not in result.stdout
    assert result.stderr == ""


def test_invalid_cli_input_does_not_echo_identifiers() -> None:
    result = subprocess.run(  # noqa: S603 - fixed interpreter and repository script
        [
            sys.executable,
            str(LIVE_CHECK_PATH),
            "--username",
            "safe-example",
            _ARGUMENT_CANARY,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == _ARGUMENT_ERROR_EXIT_CODE
    assert _ARGUMENT_CANARY not in result.stdout
    assert _ARGUMENT_CANARY not in result.stderr
    assert json.loads(result.stderr) == {
        "error_type": "ArgumentError",
        "category": "usage",
    }


def test_live_check_source_contains_no_desired_write_or_secret_input() -> None:
    source = LIVE_CHECK_PATH.read_text()

    assert "desired_shadow_update" not in source
    assert "shadow/update" not in source
    assert "getenv" not in source
    assert "environ" not in source
    assert "--output" not in source
    assert source.count("client.async_refresh_shadow()") == 1


def test_live_check_source_closes_session_and_stops_client_in_finally() -> None:
    tree = ast.parse(LIVE_CHECK_PATH.read_text())
    async_with_calls: list[ast.expr] = [
        node.items[0].context_expr.func
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncWith)
        and isinstance(node.items[0].context_expr, ast.Call)
        and isinstance(node.items[0].context_expr.func, (ast.Attribute, ast.Name))
    ]
    stop_calls_in_finally = [
        call
        for try_node in ast.walk(tree)
        if isinstance(try_node, ast.Try)
        for statement in try_node.finalbody
        for call in ast.walk(statement)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "stop"
    ]

    assert any(
        (isinstance(call, ast.Attribute) and call.attr == "ClientSession")
        or (isinstance(call, ast.Name) and call.id == "ClientSession")
        for call in async_with_calls
    )
    assert len(stop_calls_in_finally) == 1
