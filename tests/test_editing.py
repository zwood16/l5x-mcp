"""Tests for the shared write plumbing in l5x_mcp.editing."""

import os
from pathlib import Path

import pytest
from py_l5x import load

from l5x_mcp.editing import (
    Edit,
    check_data_type,
    edit_errors,
    resolve_output,
    write_project,
)
from l5x_mcp.registry import DEFAULT_OUTPUT_DIR, L5XError
from l5x_mcp.tools.components import create_tags_file
from l5x_mcp.tools.edit_tags import add_tags

OUT_DIR = DEFAULT_OUTPUT_DIR
OUT = OUT_DIR + "/"
EXAMPLE = "example.L5X"


class TestResolveOutput:
    """The output_path guards that every write tool shares."""

    def test_requires_output_path(self, editable):
        with pytest.raises(L5XError, match="output_path is required"):
            resolve_output(editable, "  ")

    def test_rejects_path_outside_root(self, editable, tmp_path):
        outside = tmp_path.parent / "elsewhere.L5X"
        with pytest.raises(L5XError, match="inside the server root"):
            resolve_output(editable, str(outside))
        with pytest.raises(L5XError, match="inside the server root"):
            resolve_output(editable, "../escape.L5X")

    def test_rejects_non_l5x_suffix(self, editable):
        with pytest.raises(L5XError, match="must end in .L5X"):
            resolve_output(editable, "out.xml")

    def test_rejects_the_source_file(self, editable):
        source = editable.resolve(EXAMPLE)
        with pytest.raises(L5XError, match="must differ from the source"):
            resolve_output(editable, str(source), source=source)

    def test_existing_file_needs_overwrite(self, editable):
        (editable.root / OUT_DIR).mkdir()
        (editable.root / OUT_DIR / "taken.L5X").write_text("x")
        with pytest.raises(L5XError, match="overwrite=true"):
            resolve_output(editable, "taken.L5X")
        with pytest.raises(L5XError, match="not written by a write tool"):
            resolve_output(editable, "taken.L5X", overwrite=True)

    def test_rejects_directory(self, editable):
        (editable.root / OUT_DIR / "folder.L5X").mkdir(parents=True)
        with pytest.raises(L5XError, match="is a directory"):
            resolve_output(editable, "folder.L5X")

    def test_relative_path_resolves_against_root(self, editable):
        out = resolve_output(editable, "nested/new.L5X")
        assert out == editable.root / "nested" / "new.L5X"


class TestEdit:
    """Load, change, write: the source must never change."""

    def test_source_is_byte_identical_after_edit(self, editable):
        source = editable.root / EXAMPLE
        before = source.read_bytes()

        result = add_tags(
            editable,
            tags=[{"name": "Probe", "data_type": "DINT"}],
            output_path="out.L5X",
            path=EXAMPLE,
        )

        assert source.read_bytes() == before
        assert result["source"] == EXAMPLE
        assert "Probe" in load(str(editable.root / OUT_DIR / "out.L5X")).controller_tags

    def test_edits_do_not_leak_into_the_read_cache(self, editable):
        cached = editable.get(EXAMPLE)
        add_tags(
            editable,
            tags=[{"name": "Probe", "data_type": "DINT"}],
            output_path="out.L5X",
            path=EXAMPLE,
        )

        assert "Probe" not in cached.controller_tags
        assert "Probe" not in editable.get(EXAMPLE).controller_tags

    def test_open_validates_output_before_loading(self, editable):
        with pytest.raises(L5XError, match="must end in .L5X"):
            Edit.open(editable, EXAMPLE, "out.txt")

    def test_save_reports_file_and_source(self, editable):
        edit = Edit.open(editable, EXAMPLE, "saved.L5X")
        result = edit.save({"extra": 1})
        assert result == {"file": OUT + "saved.L5X", "source": EXAMPLE, "extra": 1}
        assert (editable.root / OUT_DIR / "saved.L5X").exists()


class TestOverwriteOwnership:
    """overwrite=true only replaces unchanged files this server wrote."""

    def _add(self, editable, out, **kw):
        return add_tags(
            editable,
            tags=[{"name": "N1", "data_type": "DINT"}],
            output_path=out,
            path=EXAMPLE,
            **kw,
        )

    def test_own_output_can_be_overwritten(self, editable):
        self._add(editable, "out.L5X")
        self._add(editable, "out.L5X", overwrite=True)

    def test_changed_own_output_cannot_be_overwritten(self, editable):
        self._add(editable, "out.L5X")
        out = editable.root / OUT_DIR / "out.L5X"
        with out.open("ab") as f:
            f.write(b"\n")
        with pytest.raises(L5XError, match="not written by a write tool"):
            self._add(editable, "out.L5X", overwrite=True)

    def test_touched_own_output_cannot_be_overwritten(self, editable):
        self._add(editable, "out.L5X")
        out = editable.root / OUT_DIR / "out.L5X"
        st = out.stat()
        os.utime(out, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
        with pytest.raises(L5XError, match="not written by a write tool"):
            self._add(editable, "out.L5X", overwrite=True)

    def test_other_project_is_never_overwritten(self, editable):
        other = editable.root / "simple_example.L5X"
        before = other.read_bytes()
        with pytest.raises(L5XError, match="not written by a write tool"):
            self._add(editable, str(other), overwrite=True)
        assert other.read_bytes() == before

    def test_component_output_can_be_overwritten(self, editable):
        spec = [{"name": "CT", "data_type": "DINT"}]
        create_tags_file(editable, tags=spec, output_path="c.L5X")
        create_tags_file(editable, tags=spec, output_path="c.L5X", overwrite=True)


class TestWriteProject:
    """Atomic write semantics."""

    def test_written_file_gets_umask_permissions(self, editable):
        out = editable.root / OUT_DIR / "perm.L5X"
        write_project(editable, load(str(editable.root / EXAMPLE)), out)

        umask = os.umask(0)
        os.umask(umask)
        assert out.stat().st_mode & 0o777 == 0o666 & ~umask

    def test_failed_write_leaves_no_output_and_no_temp_file(self, editable):
        class Broken:
            def write(self, path):
                Path(path).write_text("partial")
                raise OSError("disk full")

        out = editable.root / OUT_DIR / "never.L5X"
        with pytest.raises(OSError, match="disk full"):
            write_project(editable, Broken(), out)

        assert not out.exists()
        assert list(editable.root.glob(".*.tmp")) == []

    def test_leaves_no_temp_files_after_success(self, editable):
        write_project(
            editable,
            load(str(editable.root / EXAMPLE)),
            editable.root / OUT_DIR / "ok.L5X",
        )
        assert list(editable.root.glob(".*.tmp")) == []


class TestEditErrors:
    """py_l5x exceptions become L5XError with a readable message."""

    @pytest.mark.parametrize(
        "exc", [ValueError("bad value"), TypeError("bad type"), IndexError("bad")]
    )
    def test_maps_value_type_and_index_errors(self, exc):
        with pytest.raises(L5XError, match=str(exc)), edit_errors("tag 'X'"):
            raise exc

    def test_prefixes_the_action(self):
        with (
            pytest.raises(L5XError, match="^tag 'X': bad value$"),
            edit_errors("tag 'X'"),
        ):
            raise ValueError("bad value")

    def test_maps_key_error_to_not_found(self):
        with pytest.raises(L5XError, match="not found: Missing"), edit_errors():
            raise KeyError("Missing")

    def test_passes_l5x_errors_through_unchanged(self):
        with pytest.raises(L5XError, match="^already mapped$"), edit_errors("x"):
            raise L5XError("already mapped")


class TestCheckDataType:
    """Tag data types must resolve: py_l5x writes names it cannot check."""

    @pytest.mark.parametrize(
        "name",
        [
            "BOOL",
            "REAL",
            "STRING",
            "TIMER",
            "MESSAGE",
            "AXIS_CIP_DRIVE",
            "robotAlarmCode",
            "Debounce",
        ],
    )
    def test_accepts_atomic_builtin_special_udt_and_aoi(self, example_path, name):
        check_data_type(load(str(example_path)), name)

    def test_rejects_unknown_type_with_guidance(self, example_path):
        with pytest.raises(L5XError, match="unknown data type 'NOTATYPE'") as info:
            check_data_type(load(str(example_path)), "NOTATYPE")
        assert "UDT or AOI" in str(info.value)
