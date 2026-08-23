# Copyright (c) 2026 Harper Reed
# ABOUTME: Defines the complete entity key contract used by packaged system tests.
# ABOUTME: Unit checks keep this test support synchronized with production descriptions.
"""Shared expected entity keys for the packaged Gentex PLACE scenario."""

from __future__ import annotations

type EntityKey = tuple[str, str]

EXPECTED_ENTITY_KEYS: frozenset[EntityKey] = frozenset(
    {
        ("binary_sensor", "account_connection"),
        ("binary_sensor", "smoke_alarm"),
        ("binary_sensor", "co_alarm"),
        ("binary_sensor", "heat_alarm"),
        ("binary_sensor", "air_quality_alarm"),
        ("binary_sensor", "voc_alarm"),
        ("binary_sensor", "explosive_gas_alarm"),
        ("binary_sensor", "connection"),
        ("binary_sensor", "motion"),
        ("binary_sensor", "battery_low_pre_warning"),
        ("binary_sensor", "chatty_mode"),
        ("binary_sensor", "temperature_alert"),
        ("binary_sensor", "humidity_alert"),
        ("binary_sensor", "faults"),
        ("binary_sensor", "end_of_life"),
        ("binary_sensor", "night_light"),
        ("sensor", "smoke_alarm_status"),
        ("sensor", "co_alarm_status"),
        ("sensor", "heat_alarm_status"),
        ("sensor", "air_quality_alarm_status"),
        ("sensor", "voc_alarm_status"),
        ("sensor", "explosive_gas_alarm_status"),
        ("sensor", "co_ppm"),
        ("sensor", "methane_ppm"),
        ("sensor", "temperature_c"),
        ("sensor", "board_temp_c"),
        ("sensor", "humidity"),
        ("sensor", "wifi_signal_strength"),
        ("sensor", "co_accumulation"),
        ("sensor", "blue_front_scatter"),
        ("sensor", "blue_back_scatter"),
        ("sensor", "ir_front_scatter"),
        ("sensor", "ir_back_scatter"),
        ("sensor", "battery_status"),
        ("sensor", "motion_sensitivity"),
        ("sensor", "temperature_alert_status"),
        ("sensor", "humidity_alert_status"),
        ("sensor", "night_light_red"),
        ("sensor", "night_light_green"),
        ("sensor", "night_light_blue"),
        ("sensor", "night_light_alpha"),
    }
)
