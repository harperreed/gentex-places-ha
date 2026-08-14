# Copyright (c) 2026 Gentex
# ABOUTME: Verifies all PLACE numeric telemetry sensor contracts and live updates.
# ABOUTME: Tests preserve raw SDK values and exercise real Home Assistant states.
"""Tests for Gentex PLACE numeric telemetry sensors."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    STATE_UNAVAILABLE,
    EntityCategory,
    UnitOfRatio,
    UnitOfTemperature,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.translation import async_get_translations
from place import NightLight, PlaceDevice
from place.models import PlaceDeviceShadow

from custom_components.gentex_place.const import DOMAIN
from custom_components.gentex_place.coordinator import GentexPlaceCoordinator
from custom_components.gentex_place.sensor import (
    TELEMETRY_SENSOR_DESCRIPTIONS,
    GentexPlaceTelemetrySensor,
    GentexPlaceTelemetrySensorEntityDescription,
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

type NativeUnit = UnitOfRatio | UnitOfTemperature | str | None
type TelemetryCase = tuple[
    str,
    SensorDeviceClass | None,
    NativeUnit,
    SensorStateClass | None,
    EntityCategory | None,
    str,
]

_RAW_BATTERY_STATUS = 87.5

TELEMETRY_CASES: tuple[TelemetryCase, ...] = (
    (
        "co_ppm",
        SensorDeviceClass.CO,
        UnitOfRatio.PARTS_PER_MILLION,
        SensorStateClass.MEASUREMENT,
        None,
        "Carbon monoxide",
    ),
    (
        "methane_ppm",
        None,
        UnitOfRatio.PARTS_PER_MILLION,
        SensorStateClass.MEASUREMENT,
        None,
        "Methane",
    ),
    (
        "temperature_c",
        SensorDeviceClass.TEMPERATURE,
        UnitOfTemperature.CELSIUS,
        SensorStateClass.MEASUREMENT,
        None,
        "Temperature",
    ),
    (
        "board_temp_c",
        SensorDeviceClass.TEMPERATURE,
        UnitOfTemperature.CELSIUS,
        SensorStateClass.MEASUREMENT,
        EntityCategory.DIAGNOSTIC,
        "Board temperature",
    ),
    (
        "humidity",
        SensorDeviceClass.HUMIDITY,
        PERCENTAGE,
        SensorStateClass.MEASUREMENT,
        None,
        "Humidity",
    ),
    (
        "wifi_signal_strength",
        SensorDeviceClass.SIGNAL_STRENGTH,
        SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        SensorStateClass.MEASUREMENT,
        None,
        "Wi-Fi signal strength",
    ),
    (
        "co_accumulation",
        None,
        None,
        None,
        None,
        "Carbon monoxide accumulation",
    ),
    (
        "blue_front_scatter",
        None,
        None,
        None,
        EntityCategory.DIAGNOSTIC,
        "Blue front scatter",
    ),
    (
        "blue_back_scatter",
        None,
        None,
        None,
        EntityCategory.DIAGNOSTIC,
        "Blue back scatter",
    ),
    (
        "ir_front_scatter",
        None,
        None,
        None,
        EntityCategory.DIAGNOSTIC,
        "Infrared front scatter",
    ),
    (
        "ir_back_scatter",
        None,
        None,
        None,
        EntityCategory.DIAGNOSTIC,
        "Infrared back scatter",
    ),
    (
        "battery_status",
        None,
        None,
        None,
        EntityCategory.DIAGNOSTIC,
        "Battery status",
    ),
    (
        "motion_sensitivity",
        None,
        None,
        None,
        EntityCategory.DIAGNOSTIC,
        "Motion sensitivity",
    ),
    (
        "temperature_alert_status",
        None,
        None,
        None,
        EntityCategory.DIAGNOSTIC,
        "Temperature alert status",
    ),
    (
        "humidity_alert_status",
        None,
        None,
        None,
        EntityCategory.DIAGNOSTIC,
        "Humidity alert status",
    ),
    (
        "night_light_red",
        None,
        None,
        None,
        EntityCategory.DIAGNOSTIC,
        "Night light red",
    ),
    (
        "night_light_green",
        None,
        None,
        None,
        EntityCategory.DIAGNOSTIC,
        "Night light green",
    ),
    (
        "night_light_blue",
        None,
        None,
        None,
        EntityCategory.DIAGNOSTIC,
        "Night light blue",
    ),
    (
        "night_light_alpha",
        None,
        None,
        None,
        EntityCategory.DIAGNOSTIC,
        "Night light alpha",
    ),
)


def make_device(*, thing_name: str = "thing-1") -> PlaceDevice:
    """Build one live real SDK device for telemetry tests."""
    return PlaceDevice(
        thing_name=thing_name,
        shadow=PlaceDeviceShadow(),
        device_id=f"device-{thing_name}",
        name="Hallway",
        model="PL1AS",
        firmware_version="1.2.3",
        location="Hallway",
        last_shadow_at=100.0,
    )


def make_coordinator(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    *devices: PlaceDevice,
) -> GentexPlaceCoordinator:
    """Build the real coordinator around the public hand-written SDK fake."""
    monkeypatch.setattr(
        "custom_components.gentex_place.coordinator.time.monotonic", lambda: 100.0
    )
    client = FakePlaceClient(
        device_registry={device.thing_name: device for device in devices},
        connected=True,
    )
    return GentexPlaceCoordinator(hass, make_entry(), cast("PlaceClient", client))


def description(key: str) -> GentexPlaceTelemetrySensorEntityDescription:
    """Return one generated telemetry description by key."""
    return next(item for item in TELEMETRY_SENSOR_DESCRIPTIONS if item.key == key)


def entity(
    coordinator: GentexPlaceCoordinator,
    key: str,
    *,
    device_key: str = "thing-1",
) -> GentexPlaceTelemetrySensor:
    """Build one concrete telemetry sensor."""
    return GentexPlaceTelemetrySensor(coordinator, device_key, description(key))


def set_telemetry_value(device: PlaceDevice, key: str, value: float | None) -> None:
    """Set one direct or nested real SDK telemetry value."""
    if key.startswith("night_light_"):
        device.shadow.night_light = NightLight()
        setattr(device.shadow.night_light, key.removeprefix("night_light_"), value)
        return
    setattr(device.shadow, key, value)


def unique_id(thing_name: str, key: str) -> str:
    """Build the expected account-scoped telemetry entity unique ID."""
    return f"identity-1_{thing_name}_{key.replace('_', '%5F')}"


def loaded_state(
    hass: HomeAssistant,
    registry: er.EntityRegistry,
    unique: str,
) -> tuple[er.RegistryEntry, State]:
    """Return one loaded telemetry registry entry and state."""
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique)
    assert entity_id is not None
    registry_entry = registry.async_get(entity_id)
    state = hass.states.get(entity_id)
    assert registry_entry is not None
    assert state is not None
    return registry_entry, state


def test_telemetry_descriptions_match_exact_supported_allow_list() -> None:
    assert tuple(item.key for item in TELEMETRY_SENSOR_DESCRIPTIONS) == tuple(
        telemetry_case[0] for telemetry_case in TELEMETRY_CASES
    )


@pytest.mark.parametrize("telemetry_case", TELEMETRY_CASES)
@pytest.mark.parametrize("value", [0.0, None])
def test_telemetry_field_contract_preserves_zero_and_none(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    telemetry_case: TelemetryCase,
    value: float | None,
) -> None:
    key, device_class, unit, state_class, category, _name = telemetry_case
    device = make_device()
    set_telemetry_value(device, key, value)
    telemetry = entity(make_coordinator(hass, monkeypatch, device), key)

    assert telemetry.device_class is device_class
    assert telemetry.native_unit_of_measurement == unit
    assert telemetry.state_class is state_class
    assert telemetry.entity_category is category
    assert telemetry.entity_description.entity_registry_enabled_default is True
    assert telemetry.native_value == value
    assert telemetry.available is (value is not None)


def test_absent_night_light_block_makes_every_channel_unavailable(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = make_device()
    device.shadow.night_light = None
    coordinator = make_coordinator(hass, monkeypatch, device)

    for key in (
        "night_light_red",
        "night_light_green",
        "night_light_blue",
        "night_light_alpha",
    ):
        channel = entity(coordinator, key)
        assert channel.native_value is None
        assert channel.available is False


def test_battery_status_is_raw_not_percentage(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = make_device()
    device.shadow.battery_status = _RAW_BATTERY_STATUS
    battery = entity(make_coordinator(hass, monkeypatch, device), "battery_status")

    assert battery.device_class is None
    assert battery.native_unit_of_measurement is None
    assert battery.state_class is None
    assert battery.native_value == _RAW_BATTERY_STATUS


async def test_loaded_entry_creates_enabled_telemetry_for_two_absent_devices(
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
        for device in devices:
            for key, _class, _unit, _state_class, _category, name in TELEMETRY_CASES:
                registry_entry, state = loaded_state(
                    hass, registry, unique_id(device.thing_name, key)
                )
                assert registry_entry.disabled_by is None
                assert registry_entry.original_name == name
                assert state.state == STATE_UNAVAILABLE
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id) is True
    assert harness.client.stop_completed is True


async def test_loaded_telemetry_follows_pushes_without_changing_sibling(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = make_place_device(last_shadow_at=100.0)
    sibling = make_place_device(
        thing_name="thing-2", device_id="device-2", last_shadow_at=100.0
    )
    device.shadow.co_ppm = 0.0
    sibling.shadow.co_ppm = 7.5
    harness = install_runtime_fakes(monkeypatch, devices=[device, sibling])
    monkeypatch.setattr(
        "custom_components.gentex_place.coordinator.time.monotonic", lambda: 100.0
    )
    entry = make_entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id) is True
    registry = er.async_get(hass)
    try:
        assert (
            loaded_state(hass, registry, unique_id("thing-1", "co_ppm"))[1].state
            == "0.0"
        )
        assert (
            loaded_state(hass, registry, unique_id("thing-2", "co_ppm"))[1].state
            == "7.5"
        )

        device.shadow.co_ppm = None
        harness.client.emit_update(device)
        await hass.async_block_till_done()
        assert (
            loaded_state(hass, registry, unique_id("thing-1", "co_ppm"))[1].state
            == STATE_UNAVAILABLE
        )
        assert (
            loaded_state(hass, registry, unique_id("thing-2", "co_ppm"))[1].state
            == "7.5"
        )

        device.shadow.co_ppm = 12.75
        harness.client.emit_update(device)
        await hass.async_block_till_done()
        assert (
            loaded_state(hass, registry, unique_id("thing-1", "co_ppm"))[1].state
            == "12.75"
        )
        assert (
            loaded_state(hass, registry, unique_id("thing-2", "co_ppm"))[1].state
            == "7.5"
        )
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id) is True
    assert harness.client.stop_completed is True


async def test_english_telemetry_names_are_translated(hass: HomeAssistant) -> None:
    translations = await async_get_translations(
        hass, "en", "entity", integrations={DOMAIN}
    )

    for key, _class, _unit, _state_class, _category, name in TELEMETRY_CASES:
        assert translations[f"component.{DOMAIN}.entity.sensor.{key}.name"] == name
