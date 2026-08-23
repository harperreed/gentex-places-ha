# Copyright (c) 2026 Harper Reed
# ABOUTME: Exposes detailed safety alarms and numeric PLACE device telemetry.
# ABOUTME: Data-driven descriptions keep SDK values live and preserve raw readings.
"""Sensor platform for Gentex PLACE."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast, override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfRatio,
    UnitOfTemperature,
)
from place import AlarmStatus, PlaceDevice

from .binary_sensor import ALARM_METADATA
from .entity import GentexPlaceDeviceEntity

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import GentexPlaceConfigEntry
    from .coordinator import GentexPlaceCoordinator

ALARM_OPTIONS = [
    "idle",
    "test",
    "pre_alarm",
    "alarm",
    "critical_alarm",
    "hushed",
]


@dataclass(frozen=True, kw_only=True)
class GentexPlaceAlarmSensorEntityDescription(SensorEntityDescription):
    """Describe one PLACE detailed safety alarm."""

    value_fn: Callable[[PlaceDevice], AlarmStatus]


ALARM_SENSOR_DESCRIPTIONS = tuple(
    GentexPlaceAlarmSensorEntityDescription(
        key=f"{metadata.key}_status",
        translation_key=f"{metadata.key}_status",
        device_class=SensorDeviceClass.ENUM,
        options=ALARM_OPTIONS,
        value_fn=metadata.value_fn,
    )
    for metadata in ALARM_METADATA
)


class GentexPlaceAlarmSensor(GentexPlaceDeviceEntity, SensorEntity):
    """Represent one detailed PLACE safety alarm state."""

    @property
    def _alarm_status(self) -> AlarmStatus:
        """Return the alarm value from the live coordinator device."""
        description = cast(
            "GentexPlaceAlarmSensorEntityDescription", self.entity_description
        )
        return description.value_fn(self.device)

    @property
    @override
    def native_value(  # pyright: ignore[reportIncompatibleVariableOverride]
        self,
    ) -> str | None:
        """Return the supported SDK enum name in Home Assistant form."""
        status = self._alarm_status
        if status is AlarmStatus.NOT_PRESENT:
            return None
        return status.name.lower()

    @property
    @override
    def available(  # pyright: ignore[reportIncompatibleVariableOverride]
        self,
    ) -> bool:
        """Require both device liveness and support for this alarm field."""
        return super().available and self._alarm_status is not AlarmStatus.NOT_PRESENT


@dataclass(frozen=True, kw_only=True)
class GentexPlaceTelemetrySensorEntityDescription(SensorEntityDescription):
    """Describe one PLACE numeric telemetry sensor."""

    value_fn: Callable[[PlaceDevice], float | None]


TELEMETRY_SENSOR_DESCRIPTIONS = (
    GentexPlaceTelemetrySensorEntityDescription(
        key="co_ppm",
        translation_key="co_ppm",
        device_class=SensorDeviceClass.CO,
        native_unit_of_measurement=UnitOfRatio.PARTS_PER_MILLION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: device.shadow.co_ppm,
    ),
    GentexPlaceTelemetrySensorEntityDescription(
        key="methane_ppm",
        translation_key="methane_ppm",
        native_unit_of_measurement=UnitOfRatio.PARTS_PER_MILLION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: device.shadow.methane_ppm,
    ),
    GentexPlaceTelemetrySensorEntityDescription(
        key="temperature_c",
        translation_key="temperature_c",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: device.shadow.temperature_c,
    ),
    GentexPlaceTelemetrySensorEntityDescription(
        key="board_temp_c",
        translation_key="board_temp_c",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: device.shadow.board_temp_c,
    ),
    GentexPlaceTelemetrySensorEntityDescription(
        key="humidity",
        translation_key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: device.shadow.humidity,
    ),
    GentexPlaceTelemetrySensorEntityDescription(
        key="wifi_signal_strength",
        translation_key="wifi_signal_strength",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: device.shadow.wifi_signal_strength,
    ),
    GentexPlaceTelemetrySensorEntityDescription(
        key="co_accumulation",
        translation_key="co_accumulation",
        value_fn=lambda device: device.shadow.co_accumulation,
    ),
    GentexPlaceTelemetrySensorEntityDescription(
        key="blue_front_scatter",
        translation_key="blue_front_scatter",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: device.shadow.blue_front_scatter,
    ),
    GentexPlaceTelemetrySensorEntityDescription(
        key="blue_back_scatter",
        translation_key="blue_back_scatter",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: device.shadow.blue_back_scatter,
    ),
    GentexPlaceTelemetrySensorEntityDescription(
        key="ir_front_scatter",
        translation_key="ir_front_scatter",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: device.shadow.ir_front_scatter,
    ),
    GentexPlaceTelemetrySensorEntityDescription(
        key="ir_back_scatter",
        translation_key="ir_back_scatter",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: device.shadow.ir_back_scatter,
    ),
    GentexPlaceTelemetrySensorEntityDescription(
        key="battery_status",
        translation_key="battery_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: device.shadow.battery_status,
    ),
    GentexPlaceTelemetrySensorEntityDescription(
        key="motion_sensitivity",
        translation_key="motion_sensitivity",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: device.shadow.motion_sensitivity,
    ),
    GentexPlaceTelemetrySensorEntityDescription(
        key="temperature_alert_status",
        translation_key="temperature_alert_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: device.shadow.temperature_alert_status,
    ),
    GentexPlaceTelemetrySensorEntityDescription(
        key="humidity_alert_status",
        translation_key="humidity_alert_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: device.shadow.humidity_alert_status,
    ),
    GentexPlaceTelemetrySensorEntityDescription(
        key="night_light_red",
        translation_key="night_light_red",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: (
            None if device.shadow.night_light is None else device.shadow.night_light.red
        ),
    ),
    GentexPlaceTelemetrySensorEntityDescription(
        key="night_light_green",
        translation_key="night_light_green",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: (
            None
            if device.shadow.night_light is None
            else device.shadow.night_light.green
        ),
    ),
    GentexPlaceTelemetrySensorEntityDescription(
        key="night_light_blue",
        translation_key="night_light_blue",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: (
            None
            if device.shadow.night_light is None
            else device.shadow.night_light.blue
        ),
    ),
    GentexPlaceTelemetrySensorEntityDescription(
        key="night_light_alpha",
        translation_key="night_light_alpha",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: (
            None
            if device.shadow.night_light is None
            else device.shadow.night_light.alpha
        ),
    ),
)


class GentexPlaceTelemetrySensor(GentexPlaceDeviceEntity, SensorEntity):
    """Represent one live PLACE numeric telemetry value."""

    @property
    @override
    def native_value(  # pyright: ignore[reportIncompatibleVariableOverride]
        self,
    ) -> float | None:
        """Return the unmodified live SDK value."""
        description = cast(
            "GentexPlaceTelemetrySensorEntityDescription", self.entity_description
        )
        return description.value_fn(self.device)

    @property
    @override
    def available(  # pyright: ignore[reportIncompatibleVariableOverride]
        self,
    ) -> bool:
        """Require device liveness and a reported telemetry value."""
        return super().available and self.native_value is not None


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: GentexPlaceConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add detailed alarms and telemetry for every PLACE device."""
    coordinator: GentexPlaceCoordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            GentexPlaceAlarmSensor(coordinator, device_key, description)
            for device_key in coordinator.data
            for description in ALARM_SENSOR_DESCRIPTIONS
        ]
        + [
            GentexPlaceTelemetrySensor(coordinator, device_key, description)
            for device_key in coordinator.data
            for description in TELEMETRY_SENSOR_DESCRIPTIONS
        ]
    )
