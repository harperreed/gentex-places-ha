# Copyright (c) 2026 Gentex
# ABOUTME: Verifies PLACE entity identity, device metadata, and availability.
# ABOUTME: Account-scoped identifiers prevent registry collisions across entries.
"""Tests for shared Gentex PLACE entity behavior."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import pytest
from homeassistant.helpers.entity import EntityDescription
from place import PlaceClient, PlaceDevice
from place.models import PlaceDeviceShadow

from custom_components.gentex_place.const import CONF_ACCOUNT_ID, DOMAIN
from custom_components.gentex_place.coordinator import GentexPlaceCoordinator
from custom_components.gentex_place.entity import (
    GentexPlaceAccountEntity,
    GentexPlaceDeviceEntity,
    stable_device_id,
)
from tests.components.gentex_place.fakes import FakePlaceClient, RecordingConfigEntry
from tests.components.gentex_place.test_init import make_entry

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


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
    last_update_success: bool = True

    def __post_init__(self) -> None:
        """Build the loaded entry carrying the stable account identity."""
        self.config_entry = RecordingConfigEntry(
            domain=DOMAIN,
            title="PLACE account",
            unique_id=self.account_id,
            data={CONF_ACCOUNT_ID: self.account_id},
        )


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
    last_shadow_at: float | None = None,
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
        last_shadow_at=last_shadow_at,
    )


def as_coordinator(runtime: RuntimeCoordinator) -> GentexPlaceCoordinator:
    """Narrow the hand-written fake to the production constructor contract."""
    return cast("GentexPlaceCoordinator", runtime)


@pytest.mark.parametrize("device_id", [None, "", "discovery-device-id"])
def test_stable_device_id_is_always_the_required_thing_name(
    device_id: str | None,
) -> None:
    device = make_device(thing_name="fallback-thing", device_id=device_id)

    assert stable_device_id(device) == "fallback-thing"


def test_device_entity_has_account_scoped_identity_and_discovery_metadata() -> None:
    device = make_device()
    runtime = RuntimeCoordinator(account_id="identity-1", data={"thing-1": device})
    description = EntityDescription(key="temperature", translation_key="temperature")

    entity = ExampleDeviceEntity(as_coordinator(runtime), "thing-1", description)
    device_info = entity.device_info

    assert entity.unique_id == "identity-1_thing-1_temperature"
    assert entity.has_entity_name is True
    assert entity.entity_description is description
    assert device_info is not None
    assert device_info == {
        "identifiers": {(DOMAIN, "identity-1:thing-1")},
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


def test_optional_device_id_does_not_change_registry_identity() -> None:
    without_device_id = make_device(thing_name="thing-1", device_id=None)
    with_device_id = make_device(thing_name="thing-1", device_id="device-1")
    description = EntityDescription(key="temperature")
    first = ExampleDeviceEntity(
        as_coordinator(
            RuntimeCoordinator(
                account_id="identity-1", data={"thing-1": without_device_id}
            )
        ),
        "thing-1",
        description,
    )
    second = ExampleDeviceEntity(
        as_coordinator(
            RuntimeCoordinator(
                account_id="identity-1", data={"thing-1": with_device_id}
            )
        ),
        "thing-1",
        description,
    )

    assert stable_device_id(without_device_id) == stable_device_id(with_device_id)
    assert first.unique_id == second.unique_id
    assert first.device_info == second.device_info


def test_device_id_cannot_collide_with_another_devices_thing_name() -> None:
    first_device = make_device(thing_name="unit-a", device_id="unit-b")
    second_device = make_device(thing_name="unit-b", device_id=None)
    description = EntityDescription(key="temperature")
    first = ExampleDeviceEntity(
        as_coordinator(
            RuntimeCoordinator(account_id="identity-1", data={"unit-a": first_device})
        ),
        "unit-a",
        description,
    )
    second = ExampleDeviceEntity(
        as_coordinator(
            RuntimeCoordinator(account_id="identity-1", data={"unit-b": second_device})
        ),
        "unit-b",
        description,
    )

    assert first.unique_id != second.unique_id
    assert first.device_info != second.device_info


def test_unique_id_escapes_device_and_entity_key_separators() -> None:
    first_device = make_device(thing_name="unit_board", device_id=None)
    second_device = make_device(thing_name="unit", device_id=None)
    first = ExampleDeviceEntity(
        as_coordinator(
            RuntimeCoordinator(
                account_id="identity-1", data={"unit_board": first_device}
            )
        ),
        "unit_board",
        EntityDescription(key="temperature"),
    )
    second = ExampleDeviceEntity(
        as_coordinator(
            RuntimeCoordinator(account_id="identity-1", data={"unit": second_device})
        ),
        "unit",
        EntityDescription(key="board_temperature"),
    )

    assert first.unique_id == "identity-1_unit%5Fboard_temperature"
    assert second.unique_id == "identity-1_unit_board%5Ftemperature"
    assert first.unique_id != second.unique_id
    assert first.device_info is not None
    assert second.device_info is not None
    assert first.device_info.get("identifiers") == {(DOMAIN, "identity-1:unit%5Fboard")}
    assert second.device_info.get("identifiers") == {(DOMAIN, "identity-1:unit")}


def test_identifier_escapes_account_and_thing_name_colons() -> None:
    first_device = make_device(thing_name="unit", device_id=None)
    second_device = make_device(thing_name="wing:unit", device_id=None)
    first = ExampleDeviceEntity(
        as_coordinator(
            RuntimeCoordinator(account_id="account:wing", data={"unit": first_device})
        ),
        "unit",
        EntityDescription(key="temperature"),
    )
    second = ExampleDeviceEntity(
        as_coordinator(
            RuntimeCoordinator(account_id="account", data={"wing:unit": second_device})
        ),
        "wing:unit",
        EntityDescription(key="temperature"),
    )

    assert first.device_info is not None
    assert second.device_info is not None
    assert first.unique_id == "account%3Awing_unit_temperature"
    assert second.unique_id == "account_wing%3Aunit_temperature"
    assert first.device_info.get("identifiers") == {(DOMAIN, "account%3Awing:unit")}
    assert second.device_info.get("identifiers") == {(DOMAIN, "account:wing%3Aunit")}


def test_identifier_escapes_percent_before_reserved_characters() -> None:
    percent_device = make_device(thing_name="unit%5Fboard", device_id=None)
    underscore_device = make_device(thing_name="unit_board", device_id=None)
    percent_entity = ExampleDeviceEntity(
        as_coordinator(
            RuntimeCoordinator(
                account_id="identity-1", data={"unit%5Fboard": percent_device}
            )
        ),
        "unit%5Fboard",
        EntityDescription(key="temperature"),
    )
    underscore_entity = ExampleDeviceEntity(
        as_coordinator(
            RuntimeCoordinator(
                account_id="identity-1", data={"unit_board": underscore_device}
            )
        ),
        "unit_board",
        EntityDescription(key="temperature"),
    )

    assert percent_entity.unique_id == "identity-1_unit%255Fboard_temperature"
    assert underscore_entity.unique_id == "identity-1_unit%5Fboard_temperature"
    assert percent_entity.unique_id != underscore_entity.unique_id
    assert percent_entity.device_info is not None
    assert underscore_entity.device_info is not None
    assert percent_entity.device_info.get("identifiers") == {
        (DOMAIN, "identity-1:unit%255Fboard")
    }
    assert underscore_entity.device_info.get("identifiers") == {
        (DOMAIN, "identity-1:unit%5Fboard")
    }


def make_coordinator(
    hass: HomeAssistant, device: PlaceDevice
) -> tuple[GentexPlaceCoordinator, FakePlaceClient]:
    """Build the real coordinator around the existing hand-written client fake."""
    client = FakePlaceClient(
        device_registry={device.thing_name: device}, connected=True
    )
    coordinator = GentexPlaceCoordinator(
        hass, make_entry(), cast("PlaceClient", client)
    )
    return coordinator, client


def test_normal_device_availability_uses_real_coordinator_liveness(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = make_device(last_shadow_at=100.0)
    coordinator, client = make_coordinator(hass, device)
    entity = ExampleDeviceEntity(
        coordinator, "thing-1", EntityDescription(key="temperature")
    )
    coordinator.last_update_success = False
    monkeypatch.setattr(
        "custom_components.gentex_place.coordinator.time.monotonic", lambda: 1000.0
    )

    assert entity.available is True

    client.connected = False
    assert entity.available is False

    client.connected = True
    monkeypatch.setattr(
        "custom_components.gentex_place.coordinator.time.monotonic", lambda: 1000.001
    )
    assert entity.available is False

    monkeypatch.setattr(
        "custom_components.gentex_place.coordinator.time.monotonic", lambda: 1000.0
    )
    assert entity.available is True
    coordinator.data.pop("thing-1")
    assert entity.available is False


def test_connectivity_entities_stay_available_with_real_coordinator(
    hass: HomeAssistant,
) -> None:
    device = make_device(last_shadow_at=100.0)
    coordinator, client = make_coordinator(hass, device)
    client.connected = False
    coordinator.last_update_success = False
    device_entity = ExampleDeviceConnectivityEntity(
        coordinator, "thing-1", EntityDescription(key="connection")
    )
    account_entity = ExampleAccountConnectivityEntity(
        coordinator, EntityDescription(key="connection")
    )

    assert device_entity.available is True
    assert account_entity.available is True


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


def test_account_unique_id_escapes_account_and_entity_key_separators() -> None:
    first = ExampleAccountEntity(
        as_coordinator(RuntimeCoordinator(account_id="unit_board", data={})),
        EntityDescription(key="temperature"),
    )
    second = ExampleAccountEntity(
        as_coordinator(RuntimeCoordinator(account_id="unit", data={})),
        EntityDescription(key="board_temperature"),
    )

    assert first.unique_id == "unit%5Fboard_temperature"
    assert second.unique_id == "unit_board%5Ftemperature"
    assert first.unique_id != second.unique_id


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
