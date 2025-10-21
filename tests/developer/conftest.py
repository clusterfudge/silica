"""Shared test fixtures for developer tests."""

import pytest


@pytest.fixture
def persona_base_dir(tmp_path):
    """Provide a temporary persona base directory for tests."""
    persona_dir = tmp_path / "persona"
    persona_dir.mkdir(exist_ok=True)
    return persona_dir
