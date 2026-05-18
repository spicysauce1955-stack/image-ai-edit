"""Shared pytest fixtures and config.

Kept deliberately tiny — most tests are pure-function unit tests on the
dataclasses and capability ABCs in :mod:`ai_edit.models`. Network-
dependent tests must be gated behind ``RUN_NETWORK_TESTS=1`` so the
default ``pytest`` invocation stays offline and fast.
"""

from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip ``@pytest.mark.network`` tests unless ``RUN_NETWORK_TESTS=1``."""
    if os.environ.get("RUN_NETWORK_TESTS") == "1":
        return
    skip_network = pytest.mark.skip(reason="set RUN_NETWORK_TESTS=1 to run network tests")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip_network)
