# Copyright (c) 2026 Harper Reed
# ABOUTME: Shared Gentex PLACE keys, safe account labels, platforms, and timers.
# ABOUTME: Protocol field names remain in the standalone PLACE SDK.
"""Constants for the Gentex PLACE integration."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.const import Platform

if TYPE_CHECKING:
    from collections.abc import Iterable

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


def safe_entry_title(
    existing_titles: Iterable[str],
    *,
    current_title: str | None = None,
) -> str:
    """Keep a safe current label or return the lowest unused safe ordinal."""
    if current_title == ENTRY_TITLE:
        return current_title
    title_prefix = f"{ENTRY_TITLE} "
    if current_title is not None and current_title.startswith(title_prefix):
        suffix = current_title.removeprefix(title_prefix)
        if (
            suffix.isascii()
            and suffix.isdecimal()
            and not suffix.startswith("0")
            and suffix != "1"
        ):
            return current_title

    used_titles = set(existing_titles)
    ordinal = 1
    while True:
        candidate = ENTRY_TITLE if ordinal == 1 else f"{ENTRY_TITLE} {ordinal}"
        if candidate not in used_titles:
            return candidate
        ordinal += 1
