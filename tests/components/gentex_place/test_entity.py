# Copyright (c) 2026 Gentex
# ABOUTME: Verifies PLACE entity identity, device metadata, and availability.
# ABOUTME: Account-scoped identifiers prevent registry collisions across entries.
"""Tests for shared Gentex PLACE entity behavior."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import pytest
from homeassistant.helpers.entity import EntityDescription
from place import PlaceDevice
from place.models import PlaceDeviceShadow

from custom_components.gentex_place.const import CONF_ACCOUNT_ID, DOMAIN
from custom_components.gentex_place.entity import (
    GentexPlaceAccountEntity,
    GentexPlaceDeviceEntity,
    stable_device_id,
)
from tests.components.gentex_place.fakes import RecordingConfigEntry

if TYPE_CHECKING:
    from custom_components.gentex_place.coordinator import GentexPlaceCoordinator


@dataclass
class RuntimeClient:
    """Expose the account connection state read by account entities."""

    connected: bool = True


@dataclass
class RuntimeCoordinator:
    """Provide the public coordinator surface used by shared entity bases."""

    account_id: str
    data: dict[str, PlaceDevice]
    client: RuntimeClient = field(default_factory=RuntimeClient)
    available_devices: dict[str, bool] = field(default_factory=dict)
    last_update_success: bool = True

    def __post_init__(self) -> None:
        """Build the loaded entry carrying the stable account identity."""
        self.config_entry = RecordingConfigEntry(
            domain=DOMAIN,
            title="PLACE account",
            unique_id=self.account_id,
            data={CONF_ACCOUNT_ID: self.account_id},
        )

    def device_available(self, device_key: str) -> bool:
        """Return scripted liveness without replacing production behavior."""
        return self.available_devices.get(device_key, True)


class ExampleDeviceEntity(GentexPlaceDeviceEntity):
    """Concrete normal device entity used to exercise the shared base."""


class ExampleDeviceConnectivityEntity(GentexPlaceDeviceEntity):
    """Concrete device entity that describes the liveness exception."""

    _describes_connectivity = True


class ExampleAccountEntity(GentexPlaceAccountEntity):
    """Concrete normal account entity used to exercise the shared base."""


class ExampleAccountConnectivityEntity(GentexPlaceAccountEntity):
    """Concrete account entity that describes the connection exception."""

    _describes_connectivity = True


def make_device(  # noqa: PLR0913 - explicit SDK metadata keeps cases readable
    *,
    thing_name: str = "thing-1",
    device_id: str | None = "device-1",
    name: str | None = "Hallway",
    model: str | None = "PL1AS",
    firmware_version: str | None = "1.2.3",
    location: str | None = "Hallway",
) -> PlaceDevice:
    """Build a real SDK device with discovery metadata."""
    return PlaceDevice(
        thing_name=thing_name,
        shadow=PlaceDeviceShadow(),
        device_id=device_id,
        name=name,
        model=model,
        firmware_version=firmware_version,
        location=location,
    )


def as_coordinator(runtime: RuntimeCoordinator) -> GentexPlaceCoordinator:
    """Narrow the hand-written fake to the production constructor contract."""
    return cast("GentexPlaceCoordinator", runtime)


@pytest.mark.parametrize("device_id", [None, ""])
def test_stable_device_id_falls_back_to_thing_name(device_id: str | None) -> None:
    device = make_device(thing_name="fallback-thing", device_id=device_id)

    assert stable_device_id(device) == "fallback-thing"


def test_device_entity_has_account_scoped_identity_and_discovery_metadata() -> None:
    device = make_device()
    runtime = RuntimeCoordinator(account_id="identity-1", data={"thing-1": device})
    description = EntityDescription(key="temperature", translation_key="temperature")

    entity = ExampleDeviceEntity(as_coordinator(runtime), "thing-1", description)
    device_info = entity.device_info

    assert entity.unique_id == "identity-1_device-1_temperature"
    assert entity.has_entity_name is True
    assert entity.entity_description is description
    assert device_info is not None
    assert device_info == {
        "identifiers": {(DOMAIN, "identity-1:device-1")},
        "manufacturer": "Gentex",
        "name": "Hallway",
        "model": "PL1AS",
        "sw_version": "1.2.3",
        "suggested_area": "Hallway",
    }
    assert "configuration_url" not in device_info


@pytest.mark.parametrize("device_id", [None, ""])
def test_device_entity_uses_thing_name_for_identity_when_device_id_is_absent(
    device_id: str | None,
) -> None:
    device = make_device(thing_name="thing-cdef", device_id=device_id, name=None)
    runtime = RuntimeCoordinator(account_id="identity-1", data={"thing-cdef": device})

    entity = ExampleDeviceEntity(
        as_coordinator(runtime), "thing-cdef", EntityDescription(key="temperature")
    )
    device_info = entity.device_info

    assert entity.unique_id == "identity-1_thing-cdef_temperature"
    assert device_info is not None
    assert device_info.get("identifiers") == {(DOMAIN, "identity-1:thing-cdef")}
    assert device_info.get("name") == "PLACE device cdef"


def test_device_entity_reads_the_live_device_from_coordinator_data() -> None:
    original = make_device(name="Original")
    replacement = make_device(name="Replacement", firmware_version="2.0.0")
    runtime = RuntimeCoordinator(account_id="identity-1", data={"thing-1": original})
    entity = ExampleDeviceEntity(
        as_coordinator(runtime), "thing-1", EntityDescription(key="temperature")
    )

    runtime.data["thing-1"] = replacement

    assert entity.device is replacement


@pytest.mark.parametrize("available", [True, False])
def test_normal_device_availability_comes_only_from_device_liveness(
    available: bool,  # noqa: FBT001 - parameter models the liveness result
) -> None:
    device = make_device()
    runtime = RuntimeCoordinator(
        account_id="identity-1",
        data={"thing-1": device},
        available_devices={"thing-1": available},
        last_update_success=False,
    )
    entity = ExampleDeviceEntity(
        as_coordinator(runtime), "thing-1", EntityDescription(key="temperature")
    )

    assert entity.available is available


def test_device_connectivity_entity_stays_available_while_disconnected() -> None:
    device = make_device()
    runtime = RuntimeCoordinator(
        account_id="identity-1",
        data={"thing-1": device},
        available_devices={"thing-1": False},
        last_update_success=False,
    )

    entity = ExampleDeviceConnectivityEntity(
        as_coordinator(runtime), "thing-1", EntityDescription(key="connection")
    )

    assert entity.available is True


@pytest.mark.parametrize("connected", [True, False])
def test_normal_account_availability_comes_from_client_connection(
    connected: bool,  # noqa: FBT001 - parameter models account connection state
) -> None:
    runtime = RuntimeCoordinator(
        account_id="identity-1",
        data={},
        client=RuntimeClient(connected=connected),
        last_update_success=False,
    )
    entity = ExampleAccountEntity(
        as_coordinator(runtime), EntityDescription(key="status")
    )

    assert entity.available is connected
    assert entity.device_info is None


def test_account_connectivity_entity_stays_available_while_disconnected() -> None:
    runtime = RuntimeCoordinator(
        account_id="identity-1",
        data={},
        client=RuntimeClient(connected=False),
        last_update_success=False,
    )

    entity = ExampleAccountConnectivityEntity(
        as_coordinator(runtime), EntityDescription(key="connection")
    )

    assert entity.available is True


def test_account_entity_unique_id_is_scoped_to_the_account() -> None:
    first = ExampleAccountEntity(
        as_coordinator(RuntimeCoordinator(account_id="identity-1", data={})),
        EntityDescription(key="status"),
    )
    second = ExampleAccountEntity(
        as_coordinator(RuntimeCoordinator(account_id="identity-2", data={})),
        EntityDescription(key="status"),
    )

    assert first.unique_id == "identity-1_status"
    assert second.unique_id == "identity-2_status"


def test_same_device_in_two_accounts_has_no_registry_collisions() -> None:
    device = make_device()
    description = EntityDescription(key="temperature")
    first = ExampleDeviceEntity(
        as_coordinator(
            RuntimeCoordinator(account_id="identity-1", data={"thing-1": device})
        ),
        "thing-1",
        description,
    )
    second = ExampleDeviceEntity(
        as_coordinator(
            RuntimeCoordinator(account_id="identity-2", data={"thing-1": device})
        ),
        "thing-1",
        description,
    )
    first_device_info = first.device_info
    second_device_info = second.device_info

    assert first.unique_id != second.unique_id
    assert first_device_info is not None
    assert second_device_info is not None
    assert first_device_info.get("identifiers") != second_device_info.get("identifiers")
