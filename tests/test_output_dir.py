"""Tests for the output folder: bare output names, auto-discovery, CLI."""

import shutil
from pathlib import Path

import pytest
from py_l5x import load

from l5x_mcp import parse_args
from l5x_mcp.registry import DEFAULT_OUTPUT_DIR, L5XError, ProjectRegistry
from l5x_mcp.tools.edit_tags import add_tags
from l5x_mcp.tools.project import list_l5x_files, project_overview

FIXTURES_DIR = Path(__file__).parent / "fixtures"
EXAMPLE = "example.L5X"
TAG = [{"name": "N1", "data_type": "DINT"}]


def _add(registry, out, path=EXAMPLE, **kw):
    return add_tags(registry, tags=TAG, output_path=out, path=path, **kw)


@pytest.fixture
def single(tmp_path):
    """A root holding exactly one source project."""
    shutil.copy2(FIXTURES_DIR / EXAMPLE, tmp_path / EXAMPLE)
    return ProjectRegistry(tmp_path)


class TestOutputLocation:
    def test_bare_name_goes_to_output_folder(self, editable):
        result = _add(editable, "step1.L5X")
        assert result["file"] == f"{DEFAULT_OUTPUT_DIR}/step1.L5X"
        assert (editable.root / DEFAULT_OUTPUT_DIR / "step1.L5X").is_file()
        assert not (editable.root / "step1.L5X").exists()

    def test_path_with_directory_is_root_relative(self, editable):
        result = _add(editable, "sub/x.L5X")
        assert result["file"] == "sub/x.L5X"
        assert (editable.root / "sub" / "x.L5X").is_file()

    def test_returned_file_chains_as_next_path(self, editable):
        first = _add(editable, "step1.L5X")
        second = add_tags(
            editable,
            tags=[{"name": "N2", "data_type": "DINT"}],
            output_path="step2.L5X",
            path=first["file"],
        )
        assert second["source"] == first["file"]
        tags = load(str(editable.root / second["file"])).controller_tags
        assert "N1" in tags
        assert "N2" in tags

    def test_returned_file_as_output_path_overwrites_same_file(self, editable):
        first = _add(editable, "step1.L5X")
        again = _add(editable, first["file"], overwrite=True)
        assert again["file"] == first["file"]

    def test_custom_output_dir(self, tmp_path):
        shutil.copy2(FIXTURES_DIR / EXAMPLE, tmp_path / EXAMPLE)
        registry = ProjectRegistry(tmp_path, output_dir="scratch/out")
        result = _add(registry, "a.L5X")
        assert result["file"] == "scratch/out/a.L5X"
        assert (tmp_path / "scratch" / "out" / "a.L5X").is_file()

    @pytest.mark.parametrize("bad", ["..", "../elsewhere", "."])
    def test_output_dir_outside_or_equal_to_root_raises(self, tmp_path, bad):
        root = tmp_path / "root"
        root.mkdir()
        with pytest.raises(L5XError, match="inside the server root"):
            ProjectRegistry(root, output_dir=bad)

    def test_absolute_output_dir_outside_root_raises(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        with pytest.raises(L5XError):
            ProjectRegistry(root, output_dir=tmp_path)
        with pytest.raises(L5XError):
            ProjectRegistry(root, output_dir=root)

    def test_folder_not_created_at_construction(self, tmp_path):
        ProjectRegistry(tmp_path)
        assert not (tmp_path / DEFAULT_OUTPUT_DIR).exists()


class TestAutoDiscovery:
    def test_outputs_are_skipped_when_picking_the_source(self, single):
        _add(single, "step1.L5X", path=None)
        overview = project_overview(single)
        assert overview["file"] == EXAMPLE

    def test_only_outputs_gives_helpful_error(self, single, tmp_path):
        _add(single, "step1.L5X")
        (tmp_path / EXAMPLE).unlink()
        with pytest.raises(L5XError, match="skipped by auto-discovery"):
            single.resolve(None)
        with pytest.raises(L5XError, match=DEFAULT_OUTPUT_DIR + "/"):
            single.resolve(None)

    def test_multiple_error_lists_only_sources(self, tmp_path):
        for name in ("a.L5X", "b.L5X"):
            shutil.copy2(FIXTURES_DIR / EXAMPLE, tmp_path / name)
        registry = ProjectRegistry(tmp_path)
        _add(registry, "o.L5X", path="a.L5X")
        with pytest.raises(L5XError) as exc:
            registry.resolve(None)
        assert "a.L5X" in str(exc.value)
        assert "o.L5X" not in str(exc.value)

    def test_list_l5x_files_flags_outputs(self, single):
        _add(single, "step1.L5X")
        files = {f["path"]: f for f in list_l5x_files(single)["files"]}
        assert files[f"{DEFAULT_OUTPUT_DIR}/step1.L5X"]["output"] is True
        assert "output" not in files[EXAMPLE]


class TestCli:
    def test_default_is_none(self, monkeypatch):
        monkeypatch.delenv("L5X_MCP_OUTPUT_DIR", raising=False)
        assert parse_args([]).output_dir is None

    def test_argument_and_env(self, monkeypatch):
        monkeypatch.setenv("L5X_MCP_OUTPUT_DIR", "from_env")
        assert parse_args([]).output_dir == "from_env"
        assert parse_args(["--output-dir", "arg"]).output_dir == "arg"

    @pytest.mark.parametrize("source", ["argument", "environment"])
    def test_rejects_unresolved_variable(self, monkeypatch, capsys, source):
        monkeypatch.delenv("L5X_MCP_OUTPUT_DIR", raising=False)
        value = "${workspaceFolder}/out"
        args = []
        if source == "environment":
            monkeypatch.setenv("L5X_MCP_OUTPUT_DIR", value)
        else:
            args = ["--output-dir", value]
        with pytest.raises(SystemExit):
            parse_args(args)
        assert "unresolved configuration variable" in capsys.readouterr().err
