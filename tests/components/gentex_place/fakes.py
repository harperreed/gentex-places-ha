# Copyright (c) 2026 Gentex
# ABOUTME: Provides stateful PLACE SDK fakes for config-flow behavior tests.
# ABOUTME: Secret call values are hashed so test diagnostics cannot expose them.
"""Stateful test doubles for the public PLACE SDK interfaces."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from hashlib import sha256
from typing import TYPE_CHECKING, Never, cast, override

from homeassistant.core import callback
from place import Credentials, DeviceEvent, DiscoverDevice, PlaceDevice, PlaceError
from place.models import PlaceDeviceShadow
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components import gentex_place as integration_module
from custom_components.gentex_place import auth as auth_helpers

_BLOCKER_RETURNED = "cancellation blocker returned"

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest
    from homeassistant.core import HomeAssistant

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


@dataclass
class CompletionBlocker:
    """Hold an SDK await until a test explicitly allows completion."""

    entered: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    release: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    async def wait(self) -> None:
        """Signal entry and wait for explicit release."""
        self.entered.set()
        await self.release.wait()


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
class FakeCachedAuth:
    """Script cache-only SDK authentication for config-entry setup."""

    order: list[str]
    result: BaseException | None = None
    usernames: list[str] = field(default_factory=list)

    async def authenticate_from_cache(self, username: str) -> None:
        """Record cache authentication and return or raise its scripted result."""
        self.order.append("authenticate_from_cache")
        self.usernames.append(username)
        if self.result is not None:
            raise self.result


@dataclass
class FakePlaceClient:
    """Model the public runtime client surface with real PLACE device objects."""

    device_registry: dict[str, PlaceDevice]
    order: list[str] = field(default_factory=list)
    start_result: BaseException | None = None
    ready_on_start: bool = True
    ready_after_start: bool = False
    error_after_start: PlaceError | None = None
    connected: bool = False
    start_calls: int = 0
    stop_calls: int = 0
    stop_completed: bool = False
    stop_results: list[
        BaseException | CancellationBlocker | CompletionBlocker | None
    ] = field(default_factory=list, repr=False)
    refresh_calls: int = 0
    refresh_result: BaseException | CancellationBlocker | None = None
    update_callbacks: list[Callable[[PlaceDevice], None]] = field(
        default_factory=list, repr=False
    )
    event_callbacks: list[Callable[[DeviceEvent], None]] = field(
        default_factory=list, repr=False
    )
    connection_callbacks: list[Callable[[bool], None]] = field(
        default_factory=list, repr=False
    )
    error_callbacks: list[Callable[[PlaceError], None]] = field(
        default_factory=list, repr=False
    )

    @property
    def devices(self) -> dict[str, PlaceDevice]:
        """Return the mutable devices through the SDK's defensive map copy."""
        return dict(self.device_registry)

    async def start(self) -> None:
        """Start and optionally expose immediate public readiness state."""
        self.order.append("start")
        self.start_calls += 1
        if self.start_result is not None:
            raise self.start_result
        if self.ready_on_start:
            self.connected = True
            if self.device_registry:
                next(iter(self.device_registry.values())).last_shadow_at = 100.0
        elif self.ready_after_start:
            self.connected = True
            asyncio.get_running_loop().call_soon(self._stamp_first_shadow)
        if self.error_after_start is not None:
            asyncio.get_running_loop().call_soon(
                self.emit_error, self.error_after_start
            )

    async def stop(self) -> None:
        """Record an awaited stop call."""
        self.order.append("stop")
        self.stop_calls += 1
        result = self.stop_results.pop(0) if self.stop_results else None
        if isinstance(result, (CancellationBlocker, CompletionBlocker)):
            await result.wait()
        elif result is not None:
            raise result
        self.stop_completed = True

    def on_update(self, callback_: Callable[[PlaceDevice], None]) -> Callable[[], None]:
        """Register a device-update callback."""
        self.order.append("on_update")
        return self._register(self.update_callbacks, callback_)

    def on_event(self, callback_: Callable[[DeviceEvent], None]) -> Callable[[], None]:
        """Register an event callback."""
        self.order.append("on_event")
        return self._register(self.event_callbacks, callback_)

    def on_connection_change(
        self, callback_: Callable[[bool], None]
    ) -> Callable[[], None]:
        """Register a connection-state callback."""
        self.order.append("on_connection_change")
        return self._register(self.connection_callbacks, callback_)

    def on_error(self, callback_: Callable[[PlaceError], None]) -> Callable[[], None]:
        """Register a typed SDK error callback."""
        self.order.append("on_error")
        return self._register(self.error_callbacks, callback_)

    async def async_refresh_shadow(self, thing_name: str | None = None) -> None:
        """Record one all-device refresh and return or raise its script."""
        assert thing_name is None
        self.refresh_calls += 1
        if isinstance(self.refresh_result, CancellationBlocker):
            await self.refresh_result.wait()
        if self.refresh_result is not None:
            raise self.refresh_result

    def emit_update(self, device: PlaceDevice) -> None:
        """Emit one SDK device update."""
        for callback_ in list(self.update_callbacks):
            callback_(device)

    def emit_event(self, event: DeviceEvent, *, now: float) -> None:
        """Apply and emit an event in the same order as the real client."""
        device = self._device_for_event(event)
        if device is not None:
            device.apply_event(event, now=now)
            self.emit_update(device)
        for callback_ in list(self.event_callbacks):
            callback_(event)

    def emit_connection_change(self, *, connected: bool) -> None:
        """Expose and emit a connection-state transition."""
        self.connected = connected
        for callback_ in list(self.connection_callbacks):
            callback_(connected)

    def emit_error(self, error: PlaceError) -> None:
        """Emit one typed SDK runtime error."""
        for callback_ in list(self.error_callbacks):
            callback_(error)

    def _device_for_event(self, event: DeviceEvent) -> PlaceDevice | None:
        if event.thing_name is not None:
            return self.device_registry.get(event.thing_name)
        if event.device_id is not None:
            return next(
                (
                    device
                    for device in self.device_registry.values()
                    if device.device_id == event.device_id
                ),
                None,
            )
        return None

    def _stamp_first_shadow(self) -> None:
        """Stamp public liveness without emitting a state-change callback."""
        if self.device_registry:
            next(iter(self.device_registry.values())).last_shadow_at = 100.0

    @staticmethod
    def _register[CallbackT](
        registry: list[CallbackT], callback_: CallbackT
    ) -> Callable[[], None]:
        registry.append(callback_)

        def unsubscribe() -> None:
            if callback_ in registry:
                registry.remove(callback_)

        return unsubscribe


class RecordingConfigEntry(MockConfigEntry):
    """Record reauth requests without starting a Home Assistant flow."""

    reauth_calls: int

    def __init__(
        self,
        *,
        domain: str,
        title: str,
        unique_id: str | None,
        data: dict[str, object],
    ) -> None:
        """Create a config entry with an empty reauth history."""
        super().__init__(
            domain=domain,
            title=title,
            unique_id=unique_id,
            data=data,
        )
        self.reauth_calls = 0

    @callback
    @override
    def async_start_reauth(
        self,
        hass: HomeAssistant,
        context: object | None = None,
        data: dict[str, object] | None = None,
    ) -> None:
        """Record one reauth request."""
        _ = hass, context, data
        self.reauth_calls += 1


@dataclass
class RuntimeHarness:
    """Own cache-auth and runtime-client fakes for lifecycle tests."""

    auth: FakeCachedAuth
    client: FakePlaceClient


@dataclass
class PlatformLifecycleBoundary:
    """Record integration calls at Home Assistant's platform lifecycle boundary."""

    order: list[str]
    forward_result: BaseException | CancellationBlocker | CompletionBlocker | None = (
        None
    )
    unload_results: list[bool | BaseException] = field(default_factory=list)

    async def async_forward_entry_setups(
        self, _entry: object, _platforms: object
    ) -> None:
        """Record forwarding and return or raise the configured result."""
        self.order.append("forward_platforms")
        if isinstance(self.forward_result, (CancellationBlocker, CompletionBlocker)):
            await self.forward_result.wait()
        elif self.forward_result is not None:
            raise self.forward_result

    async def async_unload_platforms(self, _entry: object, _platforms: object) -> bool:
        """Record unload and return or raise its next result."""
        self.order.append("unload_platforms")
        result = self.unload_results.pop(0) if self.unload_results else True
        if isinstance(result, BaseException):
            raise result
        return result


def install_runtime_fakes(  # noqa: PLR0913 - explicit scripts keep cases readable
    monkeypatch: pytest.MonkeyPatch,
    *,
    auth_result: BaseException | None = None,
    start_result: BaseException | None = None,
    ready_on_start: bool = True,
    ready_after_start: bool = False,
    error_after_start: PlaceError | None = None,
    devices: list[PlaceDevice] | None = None,
    stop_results: list[BaseException | CancellationBlocker | CompletionBlocker | None]
    | None = None,
) -> RuntimeHarness:
    """Patch the integration's public auth and client construction boundaries."""
    order: list[str] = []
    auth = FakeCachedAuth(order=order, result=auth_result)
    runtime_devices = devices if devices is not None else [make_place_device()]
    client = FakePlaceClient(
        device_registry={device.thing_name: device for device in runtime_devices},
        order=order,
        start_result=start_result,
        ready_on_start=ready_on_start,
        ready_after_start=ready_after_start,
        error_after_start=error_after_start,
        stop_results=stop_results or [],
    )

    def create_auth(_hass: object, _cache: object) -> FakeCachedAuth:
        return auth

    def create_client(received_auth: object) -> FakePlaceClient:
        assert received_auth is auth
        return client

    monkeypatch.setattr(integration_module, "create_auth", create_auth)
    monkeypatch.setattr(integration_module, "create_client", create_client)
    return RuntimeHarness(auth=auth, client=client)


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


def make_place_device(
    *,
    thing_name: str = "thing-1",
    device_id: str = "device-1",
    last_shadow_at: float | None = None,
) -> PlaceDevice:
    """Build one real SDK runtime device for coordinator tests."""
    return PlaceDevice(
        thing_name=thing_name,
        device_id=device_id,
        name="PLACE",
        model="PLACE-1",
        firmware_version="1.0.0",
        location="Hallway",
        online=True,
        shadow=PlaceDeviceShadow(),
        last_shadow_at=last_shadow_at,
    )


def invalid_credentials(identity_id: object) -> Credentials:
    """Build deliberately invalid typed credentials for boundary tests."""
    return cast("Credentials", make_credentials(cast("str", identity_id)))
