from pathlib import Path

import pytest

from l5x_mcp.registry import ProjectRegistry

FIXTURES_DIR = Path(__file__).parent / "fixtures"
EXAMPLE = "example.L5X"


@pytest.fixture(scope="session")
def fixtures_dir():
    """Return the fixtures directory path."""
    return FIXTURES_DIR


@pytest.fixture
def example_path():
    """Return the path to example.L5X fixture."""
    return FIXTURES_DIR / EXAMPLE


@pytest.fixture(scope="session")
def registry():
    """ProjectRegistry rooted at the fixtures dir (pass path=EXAMPLE etc.)."""
    return ProjectRegistry(FIXTURES_DIR)
