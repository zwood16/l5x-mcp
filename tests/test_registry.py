"""Tests for the L5X registry module."""

import os
import shutil
from pathlib import Path

import pytest

from l5x_mcp.registry import (
    AmbiguousProjectError,
    ItemNotFoundError,
    L5XError,
    ProjectNotFoundError,
    ProjectRegistry,
    lookup,
)


class TestLookup:
    """Tests for the lookup function."""

    def test_lookup_exact_match(self) -> None:
        """Test exact match lookup."""
        items = {"Program1": "value1", "Program2": "value2"}
        result = lookup(items, "Program1", "Program")
        assert result == "value1"

    def test_lookup_case_insensitive(self) -> None:
        """Test case-insensitive match when no exact match."""
        items = {"Program1": "value1", "Program2": "value2"}
        result = lookup(items, "program1", "Program")
        assert result == "value1"

    def test_lookup_not_found_empty(self) -> None:
        """Test error message for empty collection."""
        items: dict[str, str] = {}
        with pytest.raises(ItemNotFoundError) as exc_info:
            lookup(items, "NotFound", "Program")
        assert "This project has no programs" in str(exc_info.value)

    def test_lookup_not_found_with_available(self) -> None:
        """Test error message lists available items."""
        items = {"Program1": "v1", "Program2": "v2", "Program3": "v3"}
        with pytest.raises(ItemNotFoundError) as exc_info:
            lookup(items, "NotFound", "Program")
        error_msg = str(exc_info.value)
        assert "Available:" in error_msg
        assert "Program1" in error_msg
        assert "Program2" in error_msg
        assert "Program3" in error_msg

    def test_lookup_not_found_truncated(self) -> None:
        """Test error message truncates long lists."""
        items = {f"Item{i}": f"v{i}" for i in range(60)}
        with pytest.raises(ItemNotFoundError) as exc_info:
            lookup(items, "NotFound", "Tag")
        error_msg = str(exc_info.value)
        assert "... (10 more)" in error_msg


class TestProjectRegistry:
    """Tests for the ProjectRegistry class."""

    def test_init_default_root(self) -> None:
        """Test initialization with default root (cwd)."""
        registry = ProjectRegistry()
        assert registry.root == Path.cwd()

    def test_init_custom_root(self, tmp_path: Path) -> None:
        """Test initialization with custom root."""
        registry = ProjectRegistry(tmp_path)
        assert registry.root == tmp_path.resolve()

    def test_init_invalid_root(self) -> None:
        """Test initialization with non-existent root."""
        with pytest.raises(L5XError):
            ProjectRegistry("/nonexistent/path")

    def test_discover_finds_fixtures(self, fixtures_dir: Path) -> None:
        """Test discover finds all .L5X fixtures."""
        registry = ProjectRegistry(fixtures_dir)
        discovered = registry.discover()
        assert len(discovered) == 4
        names = {p.name for p in discovered}
        assert names == {
            "example.L5X",
            "simple_example.L5X",
            "Debounce_AOI.L5X",
            "MainProgram_Program.L5X",
        }

    def test_discover_sorted(self, fixtures_dir: Path) -> None:
        """Test discover returns sorted paths."""
        registry = ProjectRegistry(fixtures_dir)
        discovered = registry.discover()
        names = [p.name for p in discovered]
        assert names == sorted(names)

    def test_discover_skips_hidden_dirs(self, tmp_path: Path) -> None:
        """Test discover skips hidden directories."""
        hidden_dir = tmp_path / ".hidden"
        hidden_dir.mkdir()
        (hidden_dir / "test.L5X").touch()
        (tmp_path / "visible.L5X").touch()

        registry = ProjectRegistry(tmp_path)
        discovered = registry.discover()
        names = {p.name for p in discovered}
        assert names == {"visible.L5X"}

    def test_discover_skips_cache_dirs(self, tmp_path: Path) -> None:
        """Test discover skips __pycache__, node_modules, venv."""
        for cache_dir in ["__pycache__", "node_modules", "venv"]:
            cache_path = tmp_path / cache_dir
            cache_path.mkdir()
            (cache_path / "test.L5X").touch()

        (tmp_path / "visible.L5X").touch()

        registry = ProjectRegistry(tmp_path)
        discovered = registry.discover()
        names = {p.name for p in discovered}
        assert names == {"visible.L5X"}

    def test_discover_with_subdir(self, tmp_path: Path) -> None:
        """Test discover with subdirectory."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "test.L5X").touch()
        (tmp_path / "other.L5X").touch()

        registry = ProjectRegistry(tmp_path)
        discovered = registry.discover("subdir")
        names = {p.name for p in discovered}
        assert names == {"test.L5X"}

    def test_discover_subdir_escape(self, tmp_path: Path) -> None:
        """Test discover raises on subdir escape attempt."""
        registry = ProjectRegistry(tmp_path)
        with pytest.raises(L5XError) as exc_info:
            registry.discover("../escape")
        assert "escapes root" in str(exc_info.value)

    def test_resolve_auto_single_file(self, tmp_path: Path) -> None:
        """Test resolve auto-selects single discovered file."""
        test_file = tmp_path / "test.L5X"
        test_file.touch()

        registry = ProjectRegistry(tmp_path)
        resolved = registry.resolve(None)
        assert resolved == test_file.resolve()

    def test_resolve_auto_no_files(self, tmp_path: Path) -> None:
        """Test resolve raises when no files discovered."""
        registry = ProjectRegistry(tmp_path)
        with pytest.raises(ProjectNotFoundError) as exc_info:
            registry.resolve(None)
        assert "No .L5X files found" in str(exc_info.value)

    def test_resolve_auto_multiple_files(self, tmp_path: Path) -> None:
        """Test resolve raises on multiple discovered files."""
        (tmp_path / "test1.L5X").touch()
        (tmp_path / "test2.L5X").touch()

        registry = ProjectRegistry(tmp_path)
        with pytest.raises(AmbiguousProjectError) as exc_info:
            registry.resolve(None)
        error_msg = str(exc_info.value)
        assert "Multiple .L5X files found" in error_msg
        assert "test1.L5X" in error_msg
        assert "test2.L5X" in error_msg

    def test_resolve_relative_path(self, tmp_path: Path) -> None:
        """Test resolve with relative path."""
        test_file = tmp_path / "test.L5X"
        test_file.touch()

        registry = ProjectRegistry(tmp_path)
        resolved = registry.resolve("test.L5X")
        assert resolved == test_file.resolve()

    def test_resolve_absolute_path(self, tmp_path: Path) -> None:
        """Test resolve with absolute path."""
        test_file = tmp_path / "test.L5X"
        test_file.touch()

        other_root = tmp_path / "other"
        other_root.mkdir()
        registry = ProjectRegistry(other_root)

        resolved = registry.resolve(str(test_file))
        assert resolved == test_file.resolve()

    def test_resolve_tilde_expansion(self, tmp_path: Path) -> None:
        """Test resolve expands ~."""
        # Verify path is processed correctly (should expand ~)
        registry = ProjectRegistry(tmp_path)
        # Should fail since path doesn't exist, but it should expand ~
        with pytest.raises(ProjectNotFoundError):
            registry.resolve("~/nonexistent.L5X")

    def test_resolve_missing_file_lists_available(self, tmp_path: Path) -> None:
        """Test resolve error lists available files."""
        (tmp_path / "available.L5X").touch()

        registry = ProjectRegistry(tmp_path)
        with pytest.raises(ProjectNotFoundError) as exc_info:
            registry.resolve("missing.L5X")
        error_msg = str(exc_info.value)
        assert "available.L5X" in error_msg

    def test_get_basic(self, example_path: Path) -> None:
        """Test get loads a project."""
        registry = ProjectRegistry(example_path.parent)
        project = registry.get(str(example_path))
        assert hasattr(project, "target_type")
        assert hasattr(project, "target_name")

    def test_get_with_path_returns_tuple(self, example_path: Path) -> None:
        """Test get_with_path returns (path, project) tuple."""
        registry = ProjectRegistry(example_path.parent)
        path, project = registry.get_with_path(str(example_path))
        assert isinstance(path, Path)
        assert hasattr(project, "target_type")

    def test_cache_returns_same_object_unchanged(self, tmp_path: Path) -> None:
        """Test cache returns same object when file unchanged."""
        # Copy a fixture to tmp location
        src = Path(__file__).parent / "fixtures" / "example.L5X"
        dst = tmp_path / "test.L5X"
        shutil.copy2(src, dst)

        registry = ProjectRegistry(tmp_path)
        path1, project1 = registry.get_with_path("test.L5X")
        path2, project2 = registry.get_with_path("test.L5X")

        assert project1 is project2
        assert path1 == path2

    def test_cache_reloads_after_mtime_change(self, tmp_path: Path) -> None:
        """Test cache reloads when mtime changes."""
        # Copy fixture
        src = Path(__file__).parent / "fixtures" / "example.L5X"
        dst = tmp_path / "test.L5X"
        shutil.copy2(src, dst)

        registry = ProjectRegistry(tmp_path)
        path1, project1 = registry.get_with_path("test.L5X")

        # Update mtime
        os.utime(dst, None)

        path2, project2 = registry.get_with_path("test.L5X")
        assert project1 is not project2
        assert path1 == path2

    def test_cache_reloads_after_file_replace(self, tmp_path: Path) -> None:
        """Test cache reloads when file is replaced."""
        # Copy first fixture
        src1 = Path(__file__).parent / "fixtures" / "example.L5X"
        dst = tmp_path / "test.L5X"
        shutil.copy2(src1, dst)

        registry = ProjectRegistry(tmp_path)
        path1, project1 = registry.get_with_path("test.L5X")
        type1 = project1.target_type

        # Replace with different fixture
        src2 = Path(__file__).parent / "fixtures" / "Debounce_AOI.L5X"
        shutil.copy2(src2, dst)

        path2, project2 = registry.get_with_path("test.L5X")
        type2 = project2.target_type

        assert project1 is not project2
        assert type1 != type2

    def test_invalid_xml_raises_l5x_error(self, tmp_path: Path) -> None:
        """Test invalid XML file raises L5XError."""
        bad_file = tmp_path / "bad.L5X"
        bad_file.write_text("not valid xml")

        registry = ProjectRegistry(tmp_path)
        with pytest.raises(L5XError) as exc_info:
            registry.get("bad.L5X")
        assert "Failed to parse L5X file" in str(exc_info.value)
        assert "bad.L5X" in str(exc_info.value)

    def test_relpath_inside_root(self, tmp_path: Path) -> None:
        """Test relpath for file inside root."""
        test_file = tmp_path / "subdir" / "test.L5X"
        test_file.parent.mkdir()
        test_file.touch()

        registry = ProjectRegistry(tmp_path)
        rel = registry.relpath(test_file)
        assert rel == "subdir/test.L5X"

    def test_relpath_outside_root(self, tmp_path: Path) -> None:
        """Test relpath for file outside root returns absolute."""
        root = tmp_path / "root"
        root.mkdir()

        outside = tmp_path / "outside.L5X"
        outside.touch()

        registry = ProjectRegistry(root)
        rel = registry.relpath(outside)
        assert rel == str(outside.resolve())

    def test_relpath_uses_posix_style(self, tmp_path: Path) -> None:
        """Test relpath uses posix-style paths."""
        test_file = tmp_path / "a" / "b" / "c.L5X"
        test_file.parent.mkdir(parents=True)
        test_file.touch()

        registry = ProjectRegistry(tmp_path)
        rel = registry.relpath(test_file)
        # Should use forward slashes, not backslashes
        assert "/" in rel or rel.count(os.sep) == 0


class TestIntegration:
    """Integration tests with real fixture files."""

    def test_discover_all_fixtures(self, fixtures_dir: Path) -> None:
        """Test discovering all fixture files."""
        registry = ProjectRegistry(fixtures_dir)
        discovered = registry.discover()
        assert len(discovered) == 4

    def test_resolve_auto_picks_single_fixture(
        self, tmp_path: Path, fixtures_dir: Path
    ) -> None:
        """Test resolve auto-picks single fixture."""
        # Copy just one fixture
        src = fixtures_dir / "example.L5X"
        dst = tmp_path / "example.L5X"
        shutil.copy2(src, dst)

        registry = ProjectRegistry(tmp_path)
        resolved = registry.resolve()
        assert resolved.name == "example.L5X"

    def test_get_loads_real_fixture(self, example_path: Path) -> None:
        """Test get loads a real fixture successfully."""
        registry = ProjectRegistry(example_path.parent)
        project = registry.get(str(example_path))
        assert project.target_type == "Controller"
        assert hasattr(project, "programs")

    def test_lookup_in_real_project(self, example_path: Path) -> None:
        """Test lookup on real project collections."""
        registry = ProjectRegistry(example_path.parent)
        project = registry.get(str(example_path))

        # Should find exact match
        program = lookup(project.programs, "MainProgram", "Program")
        assert program is not None

        # Should find case-insensitive
        program = lookup(project.programs, "mainprogram", "Program")
        assert program is not None

        # Should raise for non-existent
        with pytest.raises(ItemNotFoundError):
            lookup(project.programs, "NonExistent", "Program")
