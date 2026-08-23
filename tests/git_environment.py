# Copyright (c) 2026 Harper Reed
# ABOUTME: Isolates disposable Git repositories from machine-level configuration.
# ABOUTME: Disables ambient hooks and signing without changing the developer's setup.
"""Controlled environment for Git commands that operate on disposable test repos."""

from __future__ import annotations

import os

_CONFIG_OVERRIDES = (
    ("core.hooksPath", os.devnull),
    ("commit.gpgsign", "false"),
    ("tag.gpgsign", "false"),
)


def isolated_git_environment() -> dict[str, str]:
    """Return an environment isolated from ambient Git config and hooks."""
    environment = dict(os.environ)
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    environment["GIT_CONFIG_GLOBAL"] = os.devnull
    environment.pop("GIT_CONFIG", None)
    environment.pop("GIT_CONFIG_PARAMETERS", None)
    for name in tuple(environment):
        if name.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")):
            del environment[name]
    environment["GIT_CONFIG_COUNT"] = str(len(_CONFIG_OVERRIDES))
    for index, (key, value) in enumerate(_CONFIG_OVERRIDES):
        environment[f"GIT_CONFIG_KEY_{index}"] = key
        environment[f"GIT_CONFIG_VALUE_{index}"] = value
    return environment
