# Copyright (c) 2026 Gentex
# ABOUTME: Enables Home Assistant's custom-integration pytest fixtures and loader.
# ABOUTME: Shared Gentex PLACE fixtures live under the component test package.
"""Shared pytest configuration for the Gentex PLACE integration."""

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Allow tests to load integrations from this repository."""
    _ = enable_custom_integrations
