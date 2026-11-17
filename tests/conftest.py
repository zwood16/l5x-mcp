import shutil
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


@pytest.fixture
def editable(tmp_path):
    """ProjectRegistry over a writable copy of the fixture projects in tmp_path.

    Write tools never modify their source, but tests also copy the files so
    that nothing under tests/fixtures can change. Pass path=EXAMPLE etc.
    """
    for src in FIXTURES_DIR.glob("*.L5X"):
        shutil.copy2(src, tmp_path / src.name)
    return ProjectRegistry(tmp_path)
