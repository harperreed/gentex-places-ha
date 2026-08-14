# Copyright (c) 2026 Gentex
# ABOUTME: Exposes binary safety alarms from live Gentex PLACE device shadows.
# ABOUTME: Shared alarm metadata also drives the matching enum sensor platform.
"""Binary-sensor platform for Gentex PLACE."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast, override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from place import AlarmStatus, PlaceDevice

from .entity import GentexPlaceDeviceEntity

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import GentexPlaceConfigEntry
    from .coordinator import GentexPlaceCoordinator


@dataclass(frozen=True, slots=True)
class AlarmMetadata:
    """Describe one SDK alarm field shared by both entity platforms."""

    key: str
    device_class: BinarySensorDeviceClass
    value_fn: Callable[[PlaceDevice], AlarmStatus]


ALARM_METADATA: tuple[AlarmMetadata, ...] = (
    AlarmMetadata(
        key="smoke_alarm",
        device_class=BinarySensorDeviceClass.SMOKE,
        value_fn=lambda device: device.shadow.smoke_alarm_status,
    ),
    AlarmMetadata(
        key="co_alarm",
        device_class=BinarySensorDeviceClass.CO,
        value_fn=lambda device: device.shadow.co_alarm_status,
    ),
    AlarmMetadata(
        key="heat_alarm",
        device_class=BinarySensorDeviceClass.HEAT,
        value_fn=lambda device: device.shadow.heat_alarm_status,
    ),
    AlarmMetadata(
        key="air_quality_alarm",
        device_class=BinarySensorDeviceClass.SAFETY,
        value_fn=lambda device: device.shadow.aqi_alarm_status,
    ),
    AlarmMetadata(
        key="voc_alarm",
        device_class=BinarySensorDeviceClass.SAFETY,
        value_fn=lambda device: device.shadow.voc_alarm_status,
    ),
    AlarmMetadata(
        key="explosive_gas_alarm",
        device_class=BinarySensorDeviceClass.GAS,
        value_fn=lambda device: device.shadow.explosive_gas_alarm_status,
    ),
)


@dataclass(frozen=True, kw_only=True)
class GentexPlaceAlarmBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describe one PLACE binary safety alarm."""

    value_fn: Callable[[PlaceDevice], AlarmStatus]


ALARM_BINARY_SENSOR_DESCRIPTIONS = tuple(
    GentexPlaceAlarmBinarySensorEntityDescription(
        key=metadata.key,
        translation_key=metadata.key,
        device_class=metadata.device_class,
        value_fn=metadata.value_fn,
    )
    for metadata in ALARM_METADATA
)


class GentexPlaceAlarmBinarySensor(GentexPlaceDeviceEntity, BinarySensorEntity):
    """Represent one supported PLACE safety alarm."""

    @property
    def _alarm_status(self) -> AlarmStatus:
        """Return the alarm value from the live coordinator device."""
        description = cast(
            "GentexPlaceAlarmBinarySensorEntityDescription", self.entity_description
        )
        return description.value_fn(self.device)

    @property
    @override
    def is_on(  # pyright: ignore[reportIncompatibleVariableOverride]
        self,
    ) -> bool | None:
        """Return whether the supported alarm is active."""
        status = self._alarm_status
        if status is AlarmStatus.NOT_PRESENT:
            return None
        return status is not AlarmStatus.IDLE

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
    """Add every safety alarm for every discovered PLACE device."""
    coordinator: GentexPlaceCoordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            GentexPlaceAlarmBinarySensor(coordinator, device_key, description)
            for device_key in coordinator.data
            for description in ALARM_BINARY_SENSOR_DESCRIPTIONS
        ]
    )
