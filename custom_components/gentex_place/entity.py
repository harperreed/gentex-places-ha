# Copyright (c) 2026 Gentex
# ABOUTME: Defines shared PLACE entity identity, metadata, and availability.
# ABOUTME: Registry identifiers include the account so entries cannot collide.
"""Shared entity bases for Gentex PLACE."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast, override

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ACCOUNT_ID, DOMAIN, MANUFACTURER
from .coordinator import GentexPlaceCoordinator

if TYPE_CHECKING:
    from homeassistant.helpers.entity import EntityDescription
    from place import PlaceDevice

    from . import GentexPlaceConfigEntry


def stable_device_id(device: PlaceDevice) -> str:
    """Return the required PLACE thing name used for stable identity."""
    return device.thing_name


def _escape_identifier_component(value: str) -> str:
    """Escape reserved separators in one opaque registry-ID component."""
    return value.replace("%", "%25").replace("_", "%5F").replace(":", "%3A")


def _entity_unique_id(*components: str) -> str:
    """Join escaped opaque components into an injective entity unique ID."""
    return "_".join(_escape_identifier_component(value) for value in components)


def _account_id(coordinator: GentexPlaceCoordinator) -> str:
    """Return the loaded entry's stable PLACE account identity."""
    config_entry = cast("GentexPlaceConfigEntry", coordinator.config_entry)
    return config_entry.data[CONF_ACCOUNT_ID]


class GentexPlaceDeviceEntity(CoordinatorEntity[GentexPlaceCoordinator]):
    """Represent one value reported by a physical PLACE device."""

    _attr_has_entity_name = True
    _describes_connectivity = False

    def __init__(
        self,
        coordinator: GentexPlaceCoordinator,
        device_key: str,
        entity_description: EntityDescription,
    ) -> None:
        """Bind the entity to one account-scoped device and description."""
        super().__init__(coordinator, context=device_key)
        self.entity_description = entity_description
        self._device_key = device_key
        self._account_id = _account_id(coordinator)
        self._stable_device_id = stable_device_id(self.device)
        self._attr_unique_id = _entity_unique_id(
            self._account_id, self._stable_device_id, entity_description.key
        )
        device = self.device
        self._attr_device_info = DeviceInfo(
            identifiers={
                (
                    DOMAIN,
                    ":".join(
                        _escape_identifier_component(value)
                        for value in (self._account_id, self._stable_device_id)
                    ),
                )
            },
            manufacturer=MANUFACTURER,
            name=device.name or f"PLACE device {self._stable_device_id[-4:]}",
            model=device.model,
            sw_version=device.firmware_version,
            suggested_area=device.location,
        )

    @property
    def device(self) -> PlaceDevice:
        """Return the live SDK object from the coordinator's device registry."""
        return self.coordinator.data[self._device_key]

    @property
    @override
    def available(self) -> bool:
        """Return liveness, except when this entity itself describes liveness."""
        return self._describes_connectivity or self.coordinator.device_available(
            self._device_key
        )


class GentexPlaceAccountEntity(CoordinatorEntity[GentexPlaceCoordinator]):
    """Represent one account-level value without a physical HA device."""

    _attr_has_entity_name = True
    _describes_connectivity = False

    def __init__(
        self,
        coordinator: GentexPlaceCoordinator,
        entity_description: EntityDescription,
    ) -> None:
        """Bind the entity description to the loaded PLACE account."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        account_id = _account_id(coordinator)
        self._attr_unique_id = _entity_unique_id(account_id, entity_description.key)

    @property
    @override
    def available(self) -> bool:
        """Return account connection, except for the connection-state entity."""
        return self._describes_connectivity or self.coordinator.client.connected
