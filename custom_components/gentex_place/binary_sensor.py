# Copyright (c) 2026 Gentex
# ABOUTME: Provides the Gentex PLACE binary-sensor platform entry point.
# ABOUTME: Entity definitions are added in the supported-entity tasks.
"""Binary-sensor platform for Gentex PLACE."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import GentexPlaceConfigEntry


async def async_setup_entry(
    _hass: HomeAssistant,
    _entry: GentexPlaceConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the PLACE binary-sensor platform without entities yet."""
    async_add_entities([])
