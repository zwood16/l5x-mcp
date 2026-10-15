"""Test fixtures are available and can be loaded."""

import py_l5x


def test_example_l5x_exists(example_path):
    """Test that example.L5X fixture exists."""
    assert example_path.exists()


def test_simple_example_l5x_exists(fixtures_dir):
    """Test that simple_example.L5X fixture exists."""
    path = fixtures_dir / "simple_example.L5X"
    assert path.exists()


def test_debounce_aoi_l5x_exists(fixtures_dir):
    """Test that Debounce_AOI.L5X fixture exists."""
    path = fixtures_dir / "Debounce_AOI.L5X"
    assert path.exists()


def test_mainprogram_program_l5x_exists(fixtures_dir):
    """Test that MainProgram_Program.L5X fixture exists."""
    path = fixtures_dir / "MainProgram_Program.L5X"
    assert path.exists()


def test_example_l5x_loads(example_path):
    """Test that example.L5X can be loaded with py_l5x."""
    project = py_l5x.load(str(example_path))
    assert project.controller.name is not None
    assert len(project.controller.name) > 0


def test_simple_example_l5x_loads(fixtures_dir):
    """Test that simple_example.L5X can be loaded with py_l5x."""
    path = fixtures_dir / "simple_example.L5X"
    project = py_l5x.load(str(path))
    assert project.controller.name is not None
    assert len(project.controller.name) > 0


def test_debounce_aoi_l5x_loads(fixtures_dir):
    """Test that Debounce_AOI.L5X can be loaded with py_l5x."""
    path = fixtures_dir / "Debounce_AOI.L5X"
    project = py_l5x.load(str(path))
    assert project.controller.name is not None
    assert len(project.controller.name) > 0


def test_mainprogram_program_l5x_loads(fixtures_dir):
    """Test that MainProgram_Program.L5X can be loaded with py_l5x."""
    path = fixtures_dir / "MainProgram_Program.L5X"
    project = py_l5x.load(str(path))
    assert project.controller.name is not None
    assert len(project.controller.name) > 0
