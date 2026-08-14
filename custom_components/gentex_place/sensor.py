# Copyright (c) 2026 Gentex
# ABOUTME: Exposes detailed enum states for Gentex PLACE safety alarms.
# ABOUTME: Sensor descriptions derive from the binary platform's shared metadata.
"""Sensor platform for Gentex PLACE."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast, override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
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


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: GentexPlaceConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add every detailed safety alarm for every discovered PLACE device."""
    coordinator: GentexPlaceCoordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            GentexPlaceAlarmSensor(coordinator, device_key, description)
            for device_key in coordinator.data
            for description in ALARM_SENSOR_DESCRIPTIONS
        ]
    )
