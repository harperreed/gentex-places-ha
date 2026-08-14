# Copyright (c) 2026 Gentex
# ABOUTME: Verifies PLACE connectivity, motion, health, and mode binary sensors.
# ABOUTME: Loaded-entry tests exercise SDK pushes through Home Assistant state paths.
"""Tests for Gentex PLACE device-status binary sensors."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.translation import async_get_translations
from place import DeviceEvent, NightLight, PlaceDevice
from place.models import PlaceDeviceShadow

from custom_components.gentex_place.binary_sensor import (
    ACCOUNT_CONNECTIVITY_DESCRIPTION,
    DEVICE_STATUS_DESCRIPTIONS,
    GentexPlaceAccountConnectivityBinarySensor,
    GentexPlaceStatusBinarySensor,
    GentexPlaceStatusBinarySensorEntityDescription,
    health_problem,
)
from custom_components.gentex_place.const import DOMAIN
from custom_components.gentex_place.coordinator import GentexPlaceCoordinator
from tests.components.gentex_place.fakes import (
    FakePlaceClient,
    install_runtime_fakes,
    make_place_device,
)
from tests.components.gentex_place.test_init import make_entry

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, State
    from place import PlaceClient

type StatusCase = tuple[str, BinarySensorDeviceClass | None, str]
type DirectStatusCase = tuple[str, str, BinarySensorDeviceClass | None]
type AttributeCase = tuple[str, str]

STATUS_CASES: tuple[StatusCase, ...] = (
    ("connection", BinarySensorDeviceClass.CONNECTIVITY, "Connection"),
    ("motion", BinarySensorDeviceClass.MOTION, "Motion"),
    (
        "battery_low_pre_warning",
        BinarySensorDeviceClass.BATTERY,
        "Battery low pre-warning",
    ),
    ("chatty_mode", None, "Chatty mode"),
    ("temperature_alert", BinarySensorDeviceClass.PROBLEM, "Temperature alert"),
    ("humidity_alert", BinarySensorDeviceClass.PROBLEM, "Humidity alert"),
    ("faults", BinarySensorDeviceClass.PROBLEM, "Fault"),
    ("end_of_life", BinarySensorDeviceClass.PROBLEM, "End of life"),
    ("night_light", BinarySensorDeviceClass.LIGHT, "Night light"),
)


def make_device(
    *,
    thing_name: str = "thing-1",
    last_shadow_at: float | None = 100.0,
) -> PlaceDevice:
    """Build one real SDK device for status-entity tests."""
    return PlaceDevice(
        thing_name=thing_name,
        shadow=PlaceDeviceShadow(),
        device_id=f"device-{thing_name}",
        name="Hallway",
        model="PL1AS",
        firmware_version="1.2.3",
        location="Hallway",
        last_shadow_at=last_shadow_at,
    )


def make_coordinator(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    *devices: PlaceDevice,
    connected: bool = True,
) -> tuple[GentexPlaceCoordinator, FakePlaceClient]:
    """Build the real coordinator around the public hand-written SDK fake."""
    monkeypatch.setattr(
        "custom_components.gentex_place.coordinator.time.monotonic", lambda: 100.0
    )
    client = FakePlaceClient(
        device_registry={device.thing_name: device for device in devices},
        connected=connected,
    )
    coordinator = GentexPlaceCoordinator(
        hass, make_entry(), cast("PlaceClient", client)
    )
    return coordinator, client


def description(key: str) -> GentexPlaceStatusBinarySensorEntityDescription:
    """Return one generated status description by key."""
    return next(item for item in DEVICE_STATUS_DESCRIPTIONS if item.key == key)


def entity(
    coordinator: GentexPlaceCoordinator,
    key: str,
    *,
    device_key: str = "thing-1",
) -> GentexPlaceStatusBinarySensor:
    """Build one concrete device-status entity."""
    return GentexPlaceStatusBinarySensor(coordinator, device_key, description(key))


def unique_id(thing_name: str, key: str) -> str:
    """Build the expected Task 4 account-scoped entity unique ID."""
    return f"identity-1_{thing_name}_{key.replace('_', '%5F')}"


def loaded_state(
    hass: HomeAssistant,
    registry: er.EntityRegistry,
    unique: str,
) -> tuple[er.RegistryEntry, State]:
    """Return one loaded binary-sensor registry entry and state."""
    entity_id = registry.async_get_entity_id("binary_sensor", DOMAIN, unique)
    assert entity_id is not None
    registry_entry = registry.async_get(entity_id)
    state = hass.states.get(entity_id)
    assert registry_entry is not None
    assert state is not None
    return registry_entry, state


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ({}, None),
        ({"a": 0, "b": 0.0}, False),
        ({"a": 1}, True),
        ({"a": -1.5}, True),
        ({"state": "unknown"}, None),
        ({"a": 0, "state": "unknown"}, None),
        ({"a": 1, "state": "unknown"}, True),
        ({"flag": True}, None),
        ({"flag": True, "a": 0}, None),
        ({"flag": True, "a": 1}, True),
    ],
)
def test_health_problem_contract(
    value: dict[str, object] | None,
    expected: bool | None,  # noqa: FBT001 - table models tri-state output
) -> None:
    assert health_problem(value) is expected


def test_account_and_device_connectivity_remain_available_while_false(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = make_device()
    coordinator, client = make_coordinator(hass, monkeypatch, device, connected=False)
    device_connection = entity(coordinator, "connection")
    account_connection = GentexPlaceAccountConnectivityBinarySensor(coordinator)

    assert device_connection.device_class is BinarySensorDeviceClass.CONNECTIVITY
    assert device_connection.is_on is False
    assert device_connection.available is True
    assert account_connection.device_class is BinarySensorDeviceClass.CONNECTIVITY
    assert account_connection.is_on is False
    assert account_connection.available is True
    assert account_connection.device_info is None

    client.connected = True
    assert device_connection.is_on is True
    assert account_connection.is_on is True

    device.last_shadow_at = None
    assert device_connection.is_on is False
    assert device_connection.available is True


def test_motion_uses_coordinator_window_and_device_liveness(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = make_device()
    device.last_motion_at = 100.0
    coordinator, _client = make_coordinator(hass, monkeypatch, device)
    motion = entity(coordinator, "motion")

    assert motion.device_class is BinarySensorDeviceClass.MOTION
    assert motion.is_on is True
    assert motion.available is True

    device.last_motion_at = None
    assert motion.is_on is False
    assert motion.available is True

    device.last_shadow_at = None
    assert motion.available is False


@pytest.mark.parametrize(
    "status_case",
    [
        (
            "battery_low_pre_warning",
            "battery_low_pre_warning",
            BinarySensorDeviceClass.BATTERY,
        ),
        ("chatty_mode", "in_chatty_mode", None),
    ],
)
@pytest.mark.parametrize("value", [False, True, None])
def test_direct_boolean_status_preserves_false_and_none_availability(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    status_case: DirectStatusCase,
    value: bool | None,  # noqa: FBT001 - table models SDK tri-state input
) -> None:
    key, attribute, device_class = status_case
    device = make_device()
    setattr(device.shadow, attribute, value)
    coordinator, _client = make_coordinator(hass, monkeypatch, device)
    status = entity(coordinator, key)

    assert status.device_class is device_class
    assert status.is_on is value
    assert status.available is (value is not None)


@pytest.mark.parametrize(
    "attribute_case",
    [
        ("temperature_alert", "temperature_alert_status"),
        ("humidity_alert", "humidity_alert_status"),
    ],
)
@pytest.mark.parametrize(("value", "expected"), [(0, False), (2.5, True), (None, None)])
def test_numeric_alert_status_uses_zero_nonzero_and_none(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    attribute_case: AttributeCase,
    value: float | None,
    expected: bool | None,  # noqa: FBT001 - table models tri-state output
) -> None:
    key, attribute = attribute_case
    device = make_device()
    setattr(device.shadow, attribute, value)
    coordinator, _client = make_coordinator(hass, monkeypatch, device)
    status = entity(coordinator, key)

    assert status.device_class is BinarySensorDeviceClass.PROBLEM
    assert status.is_on is expected
    assert status.available is (expected is not None)


@pytest.mark.parametrize(
    "attribute_case", [("faults", "faults"), ("end_of_life", "end_of_life")]
)
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"code": 0}, False),
        ({"code": 1}, True),
        ({"state": "unknown"}, None),
        ({}, None),
        (None, None),
    ],
)
def test_health_entities_expose_problem_state_and_shallow_copy(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    attribute_case: AttributeCase,
    value: dict[str, object] | None,
    expected: bool | None,  # noqa: FBT001 - table models tri-state output
) -> None:
    key, attribute = attribute_case
    device = make_device()
    setattr(device.shadow, attribute, value)
    coordinator, _client = make_coordinator(hass, monkeypatch, device)
    status = entity(coordinator, key)

    assert status.device_class is BinarySensorDeviceClass.PROBLEM
    assert status.is_on is expected
    assert status.available is (expected is not None)
    attributes = status.extra_state_attributes
    if value is None:
        assert attributes is None
    else:
        assert attributes == value
        assert attributes is not value


@pytest.mark.parametrize(
    ("night_light", "expected"),
    [
        (None, None),
        (NightLight(on=None), None),
        (NightLight(on=False), False),
        (NightLight(on=True), True),
    ],
)
def test_night_light_state_and_availability(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    night_light: NightLight | None,
    expected: bool | None,  # noqa: FBT001 - table models tri-state output
) -> None:
    device = make_device()
    device.shadow.night_light = night_light
    coordinator, _client = make_coordinator(hass, monkeypatch, device)
    status = entity(coordinator, "night_light")

    assert status.device_class is BinarySensorDeviceClass.LIGHT
    assert status.is_on is expected
    assert status.available is (expected is not None)


async def test_loaded_entry_creates_enabled_status_entities_when_values_absent(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    devices = [
        make_place_device(
            thing_name="thing-1", device_id="device-1", last_shadow_at=100.0
        ),
        make_place_device(
            thing_name="thing-2", device_id="device-2", last_shadow_at=100.0
        ),
    ]
    harness = install_runtime_fakes(monkeypatch, devices=devices)
    monkeypatch.setattr(
        "custom_components.gentex_place.coordinator.time.monotonic", lambda: 100.0
    )
    entry = make_entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id) is True
    registry = er.async_get(hass)
    try:
        account_entry, account_state = loaded_state(
            hass, registry, "identity-1_account%5Fconnection"
        )
        assert account_entry.disabled_by is None
        assert account_entry.device_id is None
        assert account_entry.original_name == "Account connection"
        assert account_state.state == STATE_ON

        for device in devices:
            for key, _device_class, name in STATUS_CASES:
                registry_entry, state = loaded_state(
                    hass, registry, unique_id(device.thing_name, key)
                )
                assert registry_entry.disabled_by is None
                assert registry_entry.original_name == name
                if key == "connection":
                    assert state.state == STATE_ON
                elif key == "motion":
                    assert state.state == STATE_OFF
                else:
                    assert state.state == STATE_UNAVAILABLE
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id) is True
    assert harness.client.stop_completed is True


async def test_loaded_status_entities_follow_pushes_and_account_disconnect(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = make_place_device(last_shadow_at=100.0)
    sibling = make_place_device(
        thing_name="thing-2", device_id="device-2", last_shadow_at=100.0
    )
    device.shadow.battery_low_pre_warning = False
    sibling.shadow.battery_low_pre_warning = False
    harness = install_runtime_fakes(monkeypatch, devices=[device, sibling])
    monkeypatch.setattr(
        "custom_components.gentex_place.coordinator.time.monotonic", lambda: 100.0
    )
    entry = make_entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id) is True
    registry = er.async_get(hass)
    try:
        _entry, primary_battery = loaded_state(
            hass, registry, unique_id("thing-1", "battery_low_pre_warning")
        )
        _entry, sibling_battery = loaded_state(
            hass, registry, unique_id("thing-2", "battery_low_pre_warning")
        )
        assert primary_battery.state == STATE_OFF
        assert sibling_battery.state == STATE_OFF

        device.shadow.battery_low_pre_warning = True
        harness.client.emit_update(device)
        await hass.async_block_till_done()
        assert (
            loaded_state(
                hass, registry, unique_id("thing-1", "battery_low_pre_warning")
            )[1].state
            == STATE_ON
        )
        assert (
            loaded_state(
                hass, registry, unique_id("thing-2", "battery_low_pre_warning")
            )[1].state
            == STATE_OFF
        )

        device.shadow.battery_low_pre_warning = None
        harness.client.emit_update(device)
        await hass.async_block_till_done()
        assert (
            loaded_state(
                hass, registry, unique_id("thing-1", "battery_low_pre_warning")
            )[1].state
            == STATE_UNAVAILABLE
        )
        assert (
            loaded_state(
                hass, registry, unique_id("thing-2", "battery_low_pre_warning")
            )[1].state
            == STATE_OFF
        )

        harness.client.emit_event(
            DeviceEvent(event_type="motionDetected", thing_name="thing-1"), now=100.0
        )
        await hass.async_block_till_done()
        assert (
            loaded_state(hass, registry, unique_id("thing-1", "motion"))[1].state
            == STATE_ON
        )
        assert (
            loaded_state(hass, registry, unique_id("thing-2", "motion"))[1].state
            == STATE_OFF
        )

        harness.client.emit_connection_change(connected=False)
        await hass.async_block_till_done()
        assert (
            loaded_state(hass, registry, "identity-1_account%5Fconnection")[1].state
            == STATE_OFF
        )
        for thing_name in ("thing-1", "thing-2"):
            assert (
                loaded_state(hass, registry, unique_id(thing_name, "connection"))[
                    1
                ].state
                == STATE_OFF
            )
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id) is True
    assert harness.client.stop_completed is True


async def test_english_status_entity_names_are_translated(hass: HomeAssistant) -> None:
    translations = await async_get_translations(
        hass, "en", "entity", integrations={DOMAIN}
    )

    assert (
        translations[f"component.{DOMAIN}.entity.binary_sensor.account_connection.name"]
        == "Account connection"
    )
    for key, _device_class, name in STATUS_CASES:
        assert (
            translations[f"component.{DOMAIN}.entity.binary_sensor.{key}.name"] == name
        )


def test_account_description_is_enabled_connectivity() -> None:
    assert (
        ACCOUNT_CONNECTIVITY_DESCRIPTION.device_class
        is BinarySensorDeviceClass.CONNECTIVITY
    )
    assert ACCOUNT_CONNECTIVITY_DESCRIPTION.entity_registry_enabled_default is True
