# Copyright (c) 2026 Gentex
# ABOUTME: Verifies all PLACE safety alarm binary and enum sensor contracts.
# ABOUTME: Loaded-entry tests exercise real Home Assistant state and registry paths.
"""Tests for Gentex PLACE safety alarm entities."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.translation import async_get_translations
from place import AlarmStatus, PlaceDevice
from place.models import PlaceDeviceShadow

from custom_components.gentex_place.binary_sensor import (
    ALARM_BINARY_SENSOR_DESCRIPTIONS,
    ALARM_METADATA,
    GentexPlaceAlarmBinarySensor,
    GentexPlaceAlarmBinarySensorEntityDescription,
)
from custom_components.gentex_place.const import DOMAIN
from custom_components.gentex_place.coordinator import GentexPlaceCoordinator
from custom_components.gentex_place.sensor import (
    ALARM_SENSOR_DESCRIPTIONS,
    GentexPlaceAlarmSensor,
    GentexPlaceAlarmSensorEntityDescription,
)
from tests.components.gentex_place.fakes import (
    FakePlaceClient,
    install_runtime_fakes,
    make_place_device,
)
from tests.components.gentex_place.test_init import make_entry

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, State
    from place import PlaceClient

type AlarmCase = tuple[str, str, BinarySensorDeviceClass, str]

ALARM_CASES: tuple[AlarmCase, ...] = (
    (
        "smoke_alarm_status",
        "smoke_alarm",
        BinarySensorDeviceClass.SMOKE,
        "Smoke alarm",
    ),
    (
        "co_alarm_status",
        "co_alarm",
        BinarySensorDeviceClass.CO,
        "Carbon monoxide alarm",
    ),
    (
        "heat_alarm_status",
        "heat_alarm",
        BinarySensorDeviceClass.HEAT,
        "Heat alarm",
    ),
    (
        "aqi_alarm_status",
        "air_quality_alarm",
        BinarySensorDeviceClass.SAFETY,
        "Air quality alarm",
    ),
    (
        "voc_alarm_status",
        "voc_alarm",
        BinarySensorDeviceClass.SAFETY,
        "VOC alarm",
    ),
    (
        "explosive_gas_alarm_status",
        "explosive_gas_alarm",
        BinarySensorDeviceClass.GAS,
        "Explosive gas alarm",
    ),
)

ALARM_OPTIONS = [
    "idle",
    "test",
    "pre_alarm",
    "alarm",
    "critical_alarm",
    "hushed",
]
ALARM_STATES = (
    AlarmStatus.IDLE,
    AlarmStatus.TEST,
    AlarmStatus.PRE_ALARM,
    AlarmStatus.ALARM,
    AlarmStatus.CRITICAL_ALARM,
    AlarmStatus.HUSHED,
    AlarmStatus.NOT_PRESENT,
)
_EXPECTED_ALARM_ENTITIES = len(ALARM_CASES) * 2 * 2


def make_alarm_device(attribute: str, status: AlarmStatus) -> PlaceDevice:
    """Build one live real SDK device with the selected alarm status."""
    shadow = PlaceDeviceShadow()
    setattr(shadow, attribute, status)
    return PlaceDevice(
        thing_name="thing-1",
        shadow=shadow,
        device_id="device-1",
        name="Hallway",
        model="PL1AS",
        firmware_version="1.2.3",
        location="Hallway",
        last_shadow_at=100.0,
    )


def make_coordinator(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    device: PlaceDevice,
) -> GentexPlaceCoordinator:
    """Build the real coordinator around the hand-written SDK client fake."""
    monkeypatch.setattr(
        "custom_components.gentex_place.coordinator.time.monotonic", lambda: 100.0
    )
    client = FakePlaceClient(
        device_registry={device.thing_name: device}, connected=True
    )
    return GentexPlaceCoordinator(hass, make_entry(), cast("PlaceClient", client))


def binary_description(key: str) -> GentexPlaceAlarmBinarySensorEntityDescription:
    """Return the generated binary description for one shared alarm key."""
    return next(item for item in ALARM_BINARY_SENSOR_DESCRIPTIONS if item.key == key)


def sensor_description(key: str) -> GentexPlaceAlarmSensorEntityDescription:
    """Return the generated enum description for one shared alarm key."""
    detail_key = f"{key}_status"
    return next(item for item in ALARM_SENSOR_DESCRIPTIONS if item.key == detail_key)


def alarm_unique_id(thing_name: str, key: str) -> str:
    """Build the expected account-scoped ID using Task 4's escaping contract."""
    escaped_key = key.replace("_", "%5F")
    return f"identity-1_{thing_name}_{escaped_key}"


def loaded_entity(
    hass: HomeAssistant,
    registry: er.EntityRegistry,
    platform: str,
    unique_id: str,
) -> tuple[er.RegistryEntry, State]:
    """Return one loaded registry entry and its current Home Assistant state."""
    entity_id = registry.async_get_entity_id(platform, DOMAIN, unique_id)
    assert entity_id is not None
    registry_entry = registry.async_get(entity_id)
    state = hass.states.get(entity_id)
    assert registry_entry is not None
    assert state is not None
    return registry_entry, state


def loaded_alarm_states(
    hass: HomeAssistant,
    registry: er.EntityRegistry,
    thing_name: str,
    key: str,
) -> tuple[str, str]:
    """Return the loaded binary and enum states for one device alarm."""
    _binary_entry, binary_state = loaded_entity(
        hass,
        registry,
        "binary_sensor",
        alarm_unique_id(thing_name, key),
    )
    _sensor_entry, sensor_state = loaded_entity(
        hass,
        registry,
        "sensor",
        alarm_unique_id(thing_name, f"{key}_status"),
    )
    return binary_state.state, sensor_state.state


def test_one_metadata_table_drives_both_alarm_platforms() -> None:
    """Keep alarm order, field mapping, and generated keys in one source."""
    assert len(ALARM_METADATA) == len(ALARM_CASES)
    assert [item.key for item in ALARM_BINARY_SENSOR_DESCRIPTIONS] == [
        case[1] for case in ALARM_CASES
    ]
    assert [item.key for item in ALARM_SENSOR_DESCRIPTIONS] == [
        f"{case[1]}_status" for case in ALARM_CASES
    ]


@pytest.mark.parametrize("alarm_case", ALARM_CASES)
@pytest.mark.parametrize("status", ALARM_STATES)
def test_binary_alarm_status_contract(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    alarm_case: AlarmCase,
    status: AlarmStatus,
) -> None:
    attribute, key, device_class, _name = alarm_case
    device = make_alarm_device(attribute, status)
    coordinator = make_coordinator(hass, monkeypatch, device)

    entity = GentexPlaceAlarmBinarySensor(
        coordinator, "thing-1", binary_description(key)
    )

    assert entity.device_class is device_class
    expected_is_on = (
        None if status is AlarmStatus.NOT_PRESENT else status is not AlarmStatus.IDLE
    )
    assert entity.is_on is expected_is_on
    assert entity.available is (status is not AlarmStatus.NOT_PRESENT)


@pytest.mark.parametrize("alarm_case", ALARM_CASES)
@pytest.mark.parametrize("status", ALARM_STATES)
def test_enum_alarm_status_contract(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    alarm_case: AlarmCase,
    status: AlarmStatus,
) -> None:
    attribute, key, _class, _name = alarm_case
    device = make_alarm_device(attribute, status)
    coordinator = make_coordinator(hass, monkeypatch, device)

    entity = GentexPlaceAlarmSensor(coordinator, "thing-1", sensor_description(key))

    assert entity.device_class is SensorDeviceClass.ENUM
    assert entity.options == ALARM_OPTIONS
    assert entity.native_value == (
        None if status is AlarmStatus.NOT_PRESENT else status.name.lower()
    )
    assert entity.available is (status is not AlarmStatus.NOT_PRESENT)


@pytest.mark.parametrize("alarm_case", ALARM_CASES)
def test_later_not_present_makes_both_entities_unavailable(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    alarm_case: AlarmCase,
) -> None:
    attribute, key, _class, _name = alarm_case
    device = make_alarm_device(attribute, AlarmStatus.ALARM)
    coordinator = make_coordinator(hass, monkeypatch, device)
    binary = GentexPlaceAlarmBinarySensor(
        coordinator, "thing-1", binary_description(key)
    )
    sensor = GentexPlaceAlarmSensor(coordinator, "thing-1", sensor_description(key))
    assert binary.available is True
    assert sensor.available is True

    setattr(device.shadow, attribute, AlarmStatus.NOT_PRESENT)

    assert binary.is_on is None
    assert sensor.native_value is None
    assert binary.available is False
    assert sensor.available is False


def test_device_liveness_still_controls_supported_alarm_availability(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = make_alarm_device("smoke_alarm_status", AlarmStatus.ALARM)
    device.last_shadow_at = None
    coordinator = make_coordinator(hass, monkeypatch, device)

    binary = GentexPlaceAlarmBinarySensor(
        coordinator, "thing-1", binary_description("smoke_alarm")
    )
    sensor = GentexPlaceAlarmSensor(
        coordinator, "thing-1", sensor_description("smoke_alarm")
    )

    assert binary.is_on is True
    assert sensor.native_value == "alarm"
    assert binary.available is False
    assert sensor.available is False


async def test_loaded_entry_creates_all_alarm_states_and_registry_entries(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = make_place_device(last_shadow_at=100.0)
    sibling = make_place_device(
        thing_name="thing-2", device_id="device-2", last_shadow_at=100.0
    )
    statuses = (*ALARM_STATES[:-2], AlarmStatus.NOT_PRESENT)
    for (attribute, _key, _class, _name), status in zip(
        ALARM_CASES, statuses, strict=True
    ):
        setattr(device.shadow, attribute, status)
    harness = install_runtime_fakes(monkeypatch, devices=[device, sibling])
    monkeypatch.setattr(
        "custom_components.gentex_place.coordinator.time.monotonic", lambda: 100.0
    )
    entry = make_entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id) is True
    registry = er.async_get(hass)
    try:
        expected_alarm_unique_ids = {
            alarm_unique_id(thing_name, key)
            for thing_name in ("thing-1", "thing-2")
            for _attribute, alarm_key, _class, _name in ALARM_CASES
            for key in (alarm_key, f"{alarm_key}_status")
        }
        loaded_entries = [
            item
            for item in registry.entities.values()
            if item.config_entry_id == entry.entry_id
            and item.unique_id in expected_alarm_unique_ids
        ]
        assert len(loaded_entries) == _EXPECTED_ALARM_ENTITIES

        for (_attribute, key, _class, name), status in zip(
            ALARM_CASES, statuses, strict=True
        ):
            binary_entry, binary_state = loaded_entity(
                hass,
                registry,
                "binary_sensor",
                alarm_unique_id("thing-1", key),
            )
            sensor_entry, sensor_state = loaded_entity(
                hass,
                registry,
                "sensor",
                alarm_unique_id("thing-1", f"{key}_status"),
            )
            assert binary_entry.disabled_by is None
            assert sensor_entry.disabled_by is None
            assert binary_entry.original_name == name
            assert sensor_entry.original_name == f"{name} status"
            if status is AlarmStatus.NOT_PRESENT:
                assert binary_state.state == STATE_UNAVAILABLE
                assert sensor_state.state == STATE_UNAVAILABLE
            else:
                assert binary_state.state == (
                    STATE_OFF if status is AlarmStatus.IDLE else STATE_ON
                )
                assert sensor_state.state == status.name.lower()
            assert sensor_state.attributes["options"] == ALARM_OPTIONS

        for _attribute, key, _class, _name in ALARM_CASES:
            _binary_entry, sibling_binary_state = loaded_entity(
                hass,
                registry,
                "binary_sensor",
                alarm_unique_id("thing-2", key),
            )
            _sensor_entry, sibling_sensor_state = loaded_entity(
                hass,
                registry,
                "sensor",
                alarm_unique_id("thing-2", f"{key}_status"),
            )
            assert sibling_binary_state.state == STATE_UNAVAILABLE
            assert sibling_sensor_state.state == STATE_UNAVAILABLE
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id) is True
    assert harness.client.stop_completed is True


async def test_loaded_alarm_states_follow_sdk_push_without_changing_sibling(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = make_place_device(last_shadow_at=100.0)
    sibling = make_place_device(
        thing_name="thing-2", device_id="device-2", last_shadow_at=100.0
    )
    device.shadow.smoke_alarm_status = AlarmStatus.ALARM
    sibling.shadow.smoke_alarm_status = AlarmStatus.TEST
    harness = install_runtime_fakes(monkeypatch, devices=[device, sibling])
    monkeypatch.setattr(
        "custom_components.gentex_place.coordinator.time.monotonic", lambda: 100.0
    )
    entry = make_entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id) is True
    registry = er.async_get(hass)
    sibling_states = (STATE_ON, "test")
    try:
        assert loaded_alarm_states(hass, registry, "thing-1", "smoke_alarm") == (
            STATE_ON,
            "alarm",
        )
        assert (
            loaded_alarm_states(hass, registry, "thing-2", "smoke_alarm")
            == sibling_states
        )

        device.shadow.smoke_alarm_status = AlarmStatus.IDLE
        harness.client.emit_update(device)
        await hass.async_block_till_done()

        assert loaded_alarm_states(hass, registry, "thing-1", "smoke_alarm") == (
            STATE_OFF,
            "idle",
        )
        assert (
            loaded_alarm_states(hass, registry, "thing-2", "smoke_alarm")
            == sibling_states
        )

        device.shadow.smoke_alarm_status = AlarmStatus.NOT_PRESENT
        harness.client.emit_update(device)
        await hass.async_block_till_done()

        assert loaded_alarm_states(hass, registry, "thing-1", "smoke_alarm") == (
            STATE_UNAVAILABLE,
            STATE_UNAVAILABLE,
        )
        assert (
            loaded_alarm_states(hass, registry, "thing-2", "smoke_alarm")
            == sibling_states
        )
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id) is True
    assert harness.client.stop_completed is True


async def test_english_alarm_names_and_enum_values_are_translated(
    hass: HomeAssistant,
) -> None:
    translations = await async_get_translations(
        hass, "en", "entity", integrations={DOMAIN}
    )

    expected_states = {
        "idle": "Idle",
        "test": "Test",
        "pre_alarm": "Pre-alarm",
        "alarm": "Alarm",
        "critical_alarm": "Critical alarm",
        "hushed": "Hushed",
    }
    for _attribute, key, _class, name in ALARM_CASES:
        assert (
            translations[f"component.{DOMAIN}.entity.binary_sensor.{key}.name"] == name
        )
        detail_key = f"{key}_status"
        assert (
            translations[f"component.{DOMAIN}.entity.sensor.{detail_key}.name"]
            == f"{name} status"
        )
        for state, label in expected_states.items():
            assert (
                translations[
                    f"component.{DOMAIN}.entity.sensor.{detail_key}.state.{state}"
                ]
                == label
            )
