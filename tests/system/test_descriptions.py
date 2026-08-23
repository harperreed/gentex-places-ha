# Copyright (c) 2026 Harper Reed
# ABOUTME: Checks that packaged expectations cover every production entity description.
# ABOUTME: Prevents the isolated registry scenario from drifting as entities change.
"""Entity-description completeness checks for packaged test support."""

from custom_components.gentex_place.binary_sensor import (
    ACCOUNT_CONNECTIVITY_DESCRIPTION,
    ALARM_BINARY_SENSOR_DESCRIPTIONS,
    DEVICE_STATUS_DESCRIPTIONS,
)
from custom_components.gentex_place.sensor import (
    ALARM_SENSOR_DESCRIPTIONS,
    TELEMETRY_SENSOR_DESCRIPTIONS,
)
from tests.system.entity_contract import EXPECTED_ENTITY_KEYS


def test_packaged_entity_contract_covers_all_descriptions() -> None:
    actual = {
        ("binary_sensor", ACCOUNT_CONNECTIVITY_DESCRIPTION.key),
        *(("binary_sensor", item.key) for item in ALARM_BINARY_SENSOR_DESCRIPTIONS),
        *(("binary_sensor", item.key) for item in DEVICE_STATUS_DESCRIPTIONS),
        *(("sensor", item.key) for item in ALARM_SENSOR_DESCRIPTIONS),
        *(("sensor", item.key) for item in TELEMETRY_SENSOR_DESCRIPTIONS),
    }

    assert actual == EXPECTED_ENTITY_KEYS
