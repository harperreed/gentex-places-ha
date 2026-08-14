# Copyright (c) 2026 Gentex
# ABOUTME: Provides stateful PLACE SDK fakes for config-flow behavior tests.
# ABOUTME: Secret call values are hashed so test diagnostics cannot expose them.
"""Stateful test doubles for the public PLACE SDK interfaces."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from hashlib import sha256
from typing import TYPE_CHECKING, Never, cast

from place import Credentials, DiscoverDevice

from custom_components.gentex_place import auth as auth_helpers

_BLOCKER_RETURNED = "cancellation blocker returned"

if TYPE_CHECKING:
    import pytest

    from custom_components.gentex_place.auth import MemoryTokenCache


def _digest(value: str) -> str:
    """Hash a secret so failed assertions cannot print the input."""
    return sha256(value.encode()).hexdigest()


@dataclass
class CancellationBlocker:
    """Hold an SDK await open until its task receives cancellation."""

    entered: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    _never: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    async def wait(self) -> Never:
        """Signal entry, then propagate task cancellation from the blocked await."""
        self.entered.set()
        await self._never.wait()
        raise RuntimeError(_BLOCKER_RETURNED)


@dataclass(frozen=True)
class AuthenticationCall:
    """Record a login call without retaining its plain-text password."""

    username: str
    password_digest: str = field(repr=False)

    @classmethod
    def from_values(cls, username: str, password: str) -> AuthenticationCall:
        """Build a safe login-call record."""
        return cls(username=username, password_digest=_digest(password))


@dataclass(frozen=True)
class MfaCall:
    """Record an MFA call without retaining its plain-text code."""

    code_digest: str = field(repr=False)

    @classmethod
    def from_value(cls, code: str) -> MfaCall:
        """Build a safe MFA-call record."""
        return cls(code_digest=_digest(code))


@dataclass
class FakeAuth:
    """Script public Cognito authentication calls without network access."""

    token_cache: MemoryTokenCache = field(repr=False)
    authenticate_results: list[BaseException | CancellationBlocker | None] = field(
        default_factory=list, repr=False
    )
    mfa_results: list[BaseException | CancellationBlocker | None] = field(
        default_factory=list, repr=False
    )
    credential_results: list[Credentials | BaseException | CancellationBlocker] = field(
        default_factory=list, repr=False
    )
    save_token: bool = True
    authenticate_calls: list[AuthenticationCall] = field(default_factory=list)
    mfa_calls: list[MfaCall] = field(default_factory=list)
    credential_calls: int = 0
    _username: str | None = field(default=None, repr=False)

    async def authenticate(self, username: str, password: str) -> None:
        """Run the next login result and cache a token after success."""
        self.authenticate_calls.append(
            AuthenticationCall.from_values(username, password)
        )
        self._username = username
        result = self.authenticate_results.pop(0) if self.authenticate_results else None
        if isinstance(result, CancellationBlocker):
            await result.wait()
        if result is not None:
            raise result
        if self.save_token:
            self._save_token()

    async def submit_mfa(self, code: str) -> None:
        """Run the next MFA result and cache a token after success."""
        self.mfa_calls.append(MfaCall.from_value(code))
        result = self.mfa_results.pop(0) if self.mfa_results else None
        if isinstance(result, CancellationBlocker):
            await result.wait()
        if result is not None:
            raise result
        if self.save_token:
            self._save_token()

    async def async_get_iot_credentials(self) -> Credentials:
        """Return or raise the next scripted IoT credential result."""
        self.credential_calls += 1
        result = (
            self.credential_results.pop(0)
            if self.credential_results
            else make_credentials()
        )
        if isinstance(result, CancellationBlocker):
            await result.wait()
        if isinstance(result, BaseException):
            raise result
        return result

    def _save_token(self) -> None:
        """Match the real SDK's successful token-cache write."""
        assert self._username is not None
        self.token_cache.save(
            {"username": self._username, "refresh_token": "refresh-1"}
        )


@dataclass
class FakeClient:
    """Script public device-discovery calls without network access."""

    discover_results: list[
        list[DiscoverDevice] | BaseException | CancellationBlocker
    ] = field(default_factory=list, repr=False)
    discover_calls: int = 0

    async def async_discover(self) -> list[DiscoverDevice]:
        """Return or raise the next scripted discovery result."""
        self.discover_calls += 1
        result = (
            self.discover_results.pop(0) if self.discover_results else [make_device()]
        )
        if isinstance(result, CancellationBlocker):
            await result.wait()
        if isinstance(result, BaseException):
            raise result
        return result


@dataclass
class PlaceFlowHarness:
    """Own the fake instances created through the integration factory boundary."""

    authenticate_results: list[BaseException | CancellationBlocker | None] = field(
        default_factory=list, repr=False
    )
    mfa_results: list[BaseException | CancellationBlocker | None] = field(
        default_factory=list, repr=False
    )
    credential_results: list[Credentials | BaseException | CancellationBlocker] = field(
        default_factory=list, repr=False
    )
    discover_results: list[
        list[DiscoverDevice] | BaseException | CancellationBlocker
    ] = field(default_factory=list, repr=False)
    save_token: bool = True
    auth: FakeAuth | None = field(default=None, repr=False)
    client: FakeClient | None = field(default=None, repr=False)
    token_cache: MemoryTokenCache | None = field(default=None, repr=False)
    auth_instances: list[FakeAuth] = field(default_factory=list, repr=False)
    client_instances: list[FakeClient] = field(default_factory=list, repr=False)

    def create_auth(self, _hass: object, token_cache: MemoryTokenCache) -> FakeAuth:
        """Create the fake auth with the flow-owned token cache."""
        self.token_cache = token_cache
        self.auth = FakeAuth(
            token_cache=token_cache,
            authenticate_results=self.authenticate_results,
            mfa_results=self.mfa_results,
            credential_results=self.credential_results,
            save_token=self.save_token,
        )
        self.auth_instances.append(self.auth)
        return self.auth

    def create_client(self, _auth: object) -> FakeClient:
        """Create the fake discovery client."""
        self.client = FakeClient(discover_results=self.discover_results)
        self.client_instances.append(self.client)
        return self.client


def install_place_fakes(  # noqa: PLR0913 - explicit scripts keep scenarios readable
    monkeypatch: pytest.MonkeyPatch,
    *,
    authenticate_results: list[BaseException | CancellationBlocker | None]
    | None = None,
    mfa_results: list[BaseException | CancellationBlocker | None] | None = None,
    credential_results: list[Credentials | BaseException | CancellationBlocker]
    | None = None,
    discover_results: list[list[DiscoverDevice] | BaseException | CancellationBlocker]
    | None = None,
    save_token: bool = True,
) -> PlaceFlowHarness:
    """Patch only the integration's public SDK construction boundary."""
    harness = PlaceFlowHarness(
        authenticate_results=authenticate_results or [],
        mfa_results=mfa_results or [],
        credential_results=credential_results or [],
        discover_results=discover_results or [],
        save_token=save_token,
    )
    monkeypatch.setattr(auth_helpers, "create_auth", harness.create_auth)
    monkeypatch.setattr(auth_helpers, "create_client", harness.create_client)
    return harness


def make_credentials(identity_id: str = "identity-1") -> Credentials:
    """Build public SDK credentials for a stable test account identity."""
    return Credentials(
        access_key_id="AWS-ACCESS-CANARY",
        secret_access_key="AWS-SECRET-CANARY",
        session_token="AWS-SESSION-CANARY",
        identity_id=identity_id,
        access_token="ID-TOKEN-CANARY",
    )


def make_device() -> DiscoverDevice:
    """Build one public SDK discovery result."""
    return DiscoverDevice(
        location="Hallway",
        shadow={},
        device_name="PLACE",
        thing_name="thing-1",
        firmware_version="1.0.0",
        model_number="PLACE-1",
        device_id="device-1",
        online=True,
    )


def invalid_credentials(identity_id: object) -> Credentials:
    """Build deliberately invalid typed credentials for boundary tests."""
    return cast("Credentials", make_credentials(cast("str", identity_id)))
