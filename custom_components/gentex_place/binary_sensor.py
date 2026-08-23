# Copyright (c) 2026 Harper Reed
# ABOUTME: Exposes binary alarms and live status for Gentex PLACE devices.
# ABOUTME: Includes account connectivity and shared alarm metadata for sensors.
"""Binary-sensor platform for Gentex PLACE."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast, override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from place import AlarmStatus, PlaceDevice

from .entity import GentexPlaceAccountEntity, GentexPlaceDeviceEntity

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import GentexPlaceConfigEntry
    from .coordinator import GentexPlaceCoordinator


def health_problem(value: dict[str, object] | None) -> bool | None:
    """Evaluate a loosely typed SDK health map without coercing unknown values."""
    if not value:
        return None
    numeric = [item for item in value.values() if type(item) in (int, float)]
    if any(item != 0 for item in numeric):
        return True
    if len(numeric) != len(value):
        return None
    return False


def _numeric_alert(value: float | None) -> bool | None:
    """Map an optional numeric alert code to a binary state."""
    return None if value is None else value != 0


def _night_light_on(device: PlaceDevice) -> bool | None:
    """Return the optional reported night-light state."""
    if device.shadow.night_light is None:
        return None
    return device.shadow.night_light.on


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


@dataclass(frozen=True, kw_only=True)
class GentexPlaceStatusBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describe one PLACE device-status binary sensor."""

    value_fn: Callable[[GentexPlaceCoordinator, str], bool | None]
    attributes_fn: Callable[[PlaceDevice], dict[str, Any] | None] | None = None
    describes_connectivity: bool = False


DEVICE_STATUS_DESCRIPTIONS = (
    GentexPlaceStatusBinarySensorEntityDescription(
        key="connection",
        translation_key="connection",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda coordinator, device_key: coordinator.device_available(
            device_key
        ),
        describes_connectivity=True,
    ),
    GentexPlaceStatusBinarySensorEntityDescription(
        key="motion",
        translation_key="motion",
        device_class=BinarySensorDeviceClass.MOTION,
        value_fn=lambda coordinator, device_key: coordinator.motion_active(device_key),
    ),
    GentexPlaceStatusBinarySensorEntityDescription(
        key="battery_low_pre_warning",
        translation_key="battery_low_pre_warning",
        device_class=BinarySensorDeviceClass.BATTERY,
        value_fn=lambda coordinator, device_key: (
            coordinator.data[device_key].shadow.battery_low_pre_warning
        ),
    ),
    GentexPlaceStatusBinarySensorEntityDescription(
        key="chatty_mode",
        translation_key="chatty_mode",
        value_fn=lambda coordinator, device_key: (
            coordinator.data[device_key].shadow.in_chatty_mode
        ),
    ),
    GentexPlaceStatusBinarySensorEntityDescription(
        key="temperature_alert",
        translation_key="temperature_alert",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda coordinator, device_key: _numeric_alert(
            coordinator.data[device_key].shadow.temperature_alert_status
        ),
    ),
    GentexPlaceStatusBinarySensorEntityDescription(
        key="humidity_alert",
        translation_key="humidity_alert",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda coordinator, device_key: _numeric_alert(
            coordinator.data[device_key].shadow.humidity_alert_status
        ),
    ),
    GentexPlaceStatusBinarySensorEntityDescription(
        key="faults",
        translation_key="faults",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda coordinator, device_key: health_problem(
            coordinator.data[device_key].shadow.faults
        ),
        attributes_fn=lambda device: device.shadow.faults,
    ),
    GentexPlaceStatusBinarySensorEntityDescription(
        key="end_of_life",
        translation_key="end_of_life",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda coordinator, device_key: health_problem(
            coordinator.data[device_key].shadow.end_of_life
        ),
        attributes_fn=lambda device: device.shadow.end_of_life,
    ),
    GentexPlaceStatusBinarySensorEntityDescription(
        key="night_light",
        translation_key="night_light",
        device_class=BinarySensorDeviceClass.LIGHT,
        value_fn=lambda coordinator, device_key: _night_light_on(
            coordinator.data[device_key]
        ),
    ),
)


class GentexPlaceStatusBinarySensor(GentexPlaceDeviceEntity, BinarySensorEntity):
    """Represent one PLACE device status."""

    def __init__(
        self,
        coordinator: GentexPlaceCoordinator,
        device_key: str,
        entity_description: GentexPlaceStatusBinarySensorEntityDescription,
    ) -> None:
        """Bind one status description to a live PLACE device."""
        super().__init__(coordinator, device_key, entity_description)
        self._describes_connectivity = entity_description.describes_connectivity

    @property
    @override
    def is_on(  # pyright: ignore[reportIncompatibleVariableOverride]
        self,
    ) -> bool | None:
        """Return the live status value."""
        description = cast(
            "GentexPlaceStatusBinarySensorEntityDescription", self.entity_description
        )
        return description.value_fn(self.coordinator, self._device_key)

    @property
    @override
    def available(  # pyright: ignore[reportIncompatibleVariableOverride]
        self,
    ) -> bool:
        """Require device liveness and a supported value."""
        return super().available and self.is_on is not None

    @property
    @override
    def extra_state_attributes(  # pyright: ignore[reportIncompatibleVariableOverride]
        self,
    ) -> dict[str, Any] | None:
        """Return a shallow copy of raw health details when configured."""
        description = cast(
            "GentexPlaceStatusBinarySensorEntityDescription", self.entity_description
        )
        if description.attributes_fn is None:
            return None
        attributes = description.attributes_fn(self.device)
        return None if attributes is None else dict(attributes)


ACCOUNT_CONNECTIVITY_DESCRIPTION = BinarySensorEntityDescription(
    key="account_connection",
    translation_key="account_connection",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
)


class GentexPlaceAccountConnectivityBinarySensor(  # pyright: ignore[reportIncompatibleVariableOverride]
    GentexPlaceAccountEntity, BinarySensorEntity
):
    """Represent PLACE account connectivity while the entry remains loaded."""

    _describes_connectivity = True

    def __init__(self, coordinator: GentexPlaceCoordinator) -> None:
        """Bind the connectivity entity to one PLACE account."""
        super().__init__(coordinator, ACCOUNT_CONNECTIVITY_DESCRIPTION)

    @property
    @override
    def is_on(  # pyright: ignore[reportIncompatibleVariableOverride]
        self,
    ) -> bool:
        """Return the SDK account connection state."""
        return self.coordinator.client.connected


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: GentexPlaceConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add account connectivity, alarms, and status for each PLACE device."""
    coordinator: GentexPlaceCoordinator = entry.runtime_data.coordinator
    async_add_entities(
        [GentexPlaceAccountConnectivityBinarySensor(coordinator)]
        + [
            GentexPlaceAlarmBinarySensor(coordinator, device_key, description)
            for device_key in coordinator.data
            for description in ALARM_BINARY_SENSOR_DESCRIPTIONS
        ]
        + [
            GentexPlaceStatusBinarySensor(coordinator, device_key, description)
            for device_key in coordinator.data
            for description in DEVICE_STATUS_DESCRIPTIONS
        ]
    )
