# Copyright (c) 2026 Gentex
# ABOUTME: Shared Gentex PLACE integration keys, platforms, and fixed timers.
# ABOUTME: Protocol field names remain in the standalone PLACE SDK.
"""Constants for the Gentex PLACE integration."""

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "gentex_place"
MANUFACTURER = "Gentex"
ENTRY_TITLE = "Gentex PLACE"
CONF_ACCOUNT_ID = "account_id"
CONF_REFRESH_TOKEN = "refresh_token"  # noqa: S105 - configuration key, not a secret
PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]
HEALTH_INTERVAL = timedelta(minutes=5)
STALE_AFTER_SECONDS = 15 * 60
MOTION_WINDOW_SECONDS = 30
STARTUP_TIMEOUT_SECONDS = 30
