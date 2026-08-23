# Copyright (c) 2026 Harper Reed
# ABOUTME: Verifies the installed PLACE SDK exports every symbol the integration uses.
# ABOUTME: Runs unchanged under both direct and locked clean-install interpreters.
# ruff: noqa: F401, INP001
"""Validate the PLACE SDK's consumed public contract."""

from place import (
    AlarmStatus,
    CognitoAuth,
    DeviceEvent,
    MfaRequired,
    PlaceAuthError,
    PlaceClient,
    PlaceConfig,
    PlaceConnectionError,
    PlaceDevice,
    PlaceDiscoveryError,
    PlaceError,
    PlaceInvalidAuthError,
    PlaceTimeoutError,
    PlaceTransientAuthError,
    __version__,
)

if __version__ != "0.3.0":
    raise SystemExit(1)
