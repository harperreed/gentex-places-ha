# Copyright (c) 2026 Harper Reed
# ABOUTME: Runs an opt-in read-only PLACE account release check outside CI.
# ABOUTME: Prints counts and connection state only; it never captures identifiers or payloads.
# ruff: noqa: E501, INP001
"""Run the explicit read-only PLACE release check."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import sys
from typing import TYPE_CHECKING, Any, Never, override

from aiohttp import ClientSession
from place import (
    CognitoAuth,
    MfaRequired,
    PlaceAuthError,
    PlaceClient,
    PlaceConfig,
    PlaceConnectionError,
    PlaceDiscoveryError,
    PlaceError,
    PlaceTimeoutError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from place import PlaceDevice

_STARTUP_TIMEOUT_SECONDS = 30
_READINESS_POLL_SECONDS = 0.1


class LiveCheckDiscoveryError(Exception):
    """Signal that an authenticated PLACE account has no devices."""


class _DiscardingTokenCache:
    """Satisfy the SDK cache contract without retaining authentication data."""

    def load(self) -> dict[str, Any] | None:
        """Return no cached authentication data."""
        return None

    def save(self, data: dict[str, Any]) -> None:
        """Discard authentication data instead of persisting it."""
        del data

    def clear(self) -> None:
        """Clear no state because this cache stores none."""


class _SafeArgumentParser(argparse.ArgumentParser):
    """Reject invalid arguments without echoing their values."""

    @override
    def error(self, message: str) -> Never:
        """Exit with fixed safe JSON instead of argparse's input-bearing text."""
        del message
        safe_error = {"error_type": "ArgumentError", "category": "usage"}
        self.exit(2, f"{json.dumps(safe_error, sort_keys=True)}\n")


def build_summary(
    devices: Mapping[str, PlaceDevice], *, connected: bool
) -> dict[str, bool | int]:
    """Return only public connection state and aggregate device counts."""
    return {
        "connected": connected,
        "device_count": len(devices),
        "devices_with_reported_state": sum(
            device.last_shadow_at is not None for device in devices.values()
        ),
    }


def redact_exception(error: BaseException) -> dict[str, str]:
    """Describe an error by safe class and category without its message."""
    if isinstance(error, (MfaRequired, PlaceAuthError)):
        category = "authentication"
    elif isinstance(error, (PlaceTimeoutError, TimeoutError)):
        category = "timeout"
    elif isinstance(error, (PlaceDiscoveryError, LiveCheckDiscoveryError)):
        category = "discovery"
    elif isinstance(error, PlaceConnectionError):
        category = "connection"
    elif isinstance(error, PlaceError):
        category = "place"
    elif isinstance(error, (asyncio.CancelledError, KeyboardInterrupt)):
        category = "cancellation"
    else:
        category = "unexpected"
    return {"error_type": type(error).__name__, "category": category}


async def _wait_until_connected(client: PlaceClient) -> None:
    """Wait until public client state shows an active connection."""
    while not client.connected:  # noqa: ASYNC110 - SDK exposes public polling state
        await asyncio.sleep(_READINESS_POLL_SECONDS)


async def _wait_for_reported_shadow(client: PlaceClient) -> None:
    """Wait until one public device has received a reported shadow."""
    while True:
        if not client.connected:
            raise PlaceConnectionError
        if any(device.last_shadow_at is not None for device in client.devices.values()):
            return
        await asyncio.sleep(_READINESS_POLL_SECONDS)


async def _start_refresh_and_wait(client: PlaceClient) -> None:
    """Start the client, request one refresh, and await public readiness."""
    await client.start()
    if not client.devices:
        raise LiveCheckDiscoveryError
    await _wait_until_connected(client)
    await client.async_refresh_shadow()
    await _wait_for_reported_shadow(client)


async def async_live_check(username: str) -> dict[str, bool | int]:
    """Authenticate at runtime and run one bounded read-only account check."""
    config = PlaceConfig()
    async with ClientSession() as session:
        auth = CognitoAuth(config, session, token_cache=_DiscardingTokenCache())
        password = getpass.getpass("PLACE password: ")
        try:
            await auth.authenticate(username, password)
        except MfaRequired:
            mfa_code = getpass.getpass("PLACE verification code: ")
            try:
                await auth.submit_mfa(mfa_code)
            finally:
                mfa_code = ""
        finally:
            password = ""

        client = PlaceClient.create(config, auth)
        start_attempted = False
        try:
            async with asyncio.timeout(_STARTUP_TIMEOUT_SECONDS):
                start_attempted = True
                await _start_refresh_and_wait(client)
            connected = client.connected
            if not connected:
                raise PlaceConnectionError
            return build_summary(client.devices, connected=connected)
        finally:
            if start_attempted:
                stop_task = asyncio.create_task(client.stop())
                try:
                    await asyncio.shield(stop_task)
                except asyncio.CancelledError:
                    await stop_task
                    raise


def _parser() -> argparse.ArgumentParser:
    """Build the command-line parser without reading credentials."""
    parser = _SafeArgumentParser(
        description="Run an opt-in read-only check against one PLACE account."
    )
    parser.add_argument("--username", required=True, help="PLACE account username")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and emit only allow-listed JSON."""
    args = _parser().parse_args(argv)
    try:
        summary = asyncio.run(async_live_check(args.username))
    except BaseException as error:  # noqa: BLE001 - sanitize every terminal error
        sys.stderr.write(f"{json.dumps(redact_exception(error), sort_keys=True)}\n")
        return (
            130 if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt)) else 1
        )
    sys.stdout.write(f"{json.dumps(summary, sort_keys=True)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
