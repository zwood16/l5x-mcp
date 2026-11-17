"""Tests for the component (Import Component) tools."""

import pytest
from py_l5x import load

from l5x_mcp.registry import DEFAULT_OUTPUT_DIR, L5XError
from l5x_mcp.tools.components import (
    create_aoi_file,
    create_data_type_file,
    create_program_file,
    create_routine_file,
    create_rungs_file,
    create_tags_file,
    export_component,
)

OUT_DIR = DEFAULT_OUTPUT_DIR
OUT = OUT_DIR + "/"
EXAMPLE = "example.L5X"


def _load(editable, rel):
    return load(str(editable.root / rel))


class TestExportComponent:
    def test_data_type_export_loads_as_datatype_component(self, editable):
        result = export_component(
            editable,
            kind="data_type",
            names=["simple_udt"],
            output_path="udt.L5X",
            path=EXAMPLE,
        )

        component = _load(editable, OUT + "udt.L5X")
        assert result["target_type"] == "DataType"
        assert component.target_type == "DataType"
        assert component.target.name == "simple_udt"

    def test_aoi_export_carries_the_aois_it_calls(self, editable):
        # FanucRobot has a SeqCtrl parameter, so SeqCtrl must come along.
        result = export_component(
            editable,
            kind="aoi",
            names=["FanucRobot"],
            output_path="aoi.L5X",
            path=EXAMPLE,
        )

        component = _load(editable, OUT + "aoi.L5X")
        assert component.target_type == "AddOnInstructionDefinition"
        assert component.target.name == "FanucRobot"
        assert "SeqCtrl" in component.aois
        assert "SeqCtrl" in result["context"]["aois"]

    def test_routine_export_carries_context(self, editable):
        result = export_component(
            editable,
            kind="routine",
            program="MainProgram",
            names=["SequenceRoutine"],
            output_path="routine.L5X",
            path=EXAMPLE,
        )

        component = _load(editable, OUT + "routine.L5X")
        assert result["target_type"] == "Routine"
        assert component.target_type == "Routine"
        assert component.target.name == "SequenceRoutine"
        assert "SeqCtrl" in component.aois

    def test_rung_export_targets_one_rung(self, editable):
        result = export_component(
            editable,
            kind="rungs",
            program="MainProgram",
            routine="MainRoutine",
            rungs=[0],
            output_path="rung.L5X",
            path=EXAMPLE,
        )

        component = _load(editable, OUT + "rung.L5X")
        assert result["target_type"] == "Rung"
        assert component.target_type == "Rung"
        assert component.target.text == "JSR(SequenceRoutine,0);"

    def test_program_scoped_tag_export(self, editable):
        result = export_component(
            editable,
            kind="tags",
            names=["input_ok"],
            program="SafetyProgram",
            output_path="tag.L5X",
            path=EXAMPLE,
        )

        component = _load(editable, OUT + "tag.L5X")
        assert result["target_type"] == "Tag"
        assert component.target_type == "Tag"
        assert component.target.name == "input_ok"

    def test_program_export_loads_as_program_component(self, editable):
        export_component(
            editable,
            kind="program",
            names=["MainProgram"],
            output_path="prog.L5X",
            path=EXAMPLE,
        )

        component = _load(editable, OUT + "prog.L5X")
        assert component.target_type == "Program"
        assert component.target.name == "MainProgram"

    def test_rung_out_of_range_is_refused(self, editable):
        with pytest.raises(L5XError, match="out of range"):
            export_component(
                editable,
                kind="rungs",
                program="MainProgram",
                routine="MainRoutine",
                rungs=[7],
                output_path="out.L5X",
                path=EXAMPLE,
            )

    def test_unknown_kind_is_refused(self, editable):
        with pytest.raises(L5XError, match="unknown kind 'bogus'"):
            export_component(
                editable, kind="bogus", names=["x"], output_path="out.L5X", path=EXAMPLE
            )

    def test_routine_kind_needs_program(self, editable):
        with pytest.raises(L5XError, match="program is required"):
            export_component(
                editable,
                kind="routine",
                names=["SequenceRoutine"],
                output_path="out.L5X",
                path=EXAMPLE,
            )

    def test_output_may_not_be_the_source(self, editable):
        before = (editable.root / EXAMPLE).read_bytes()
        with pytest.raises(L5XError, match="must differ from the source"):
            export_component(
                editable,
                kind="data_type",
                names=["simple_udt"],
                output_path=str(editable.root / EXAMPLE),
                overwrite=True,
                path=EXAMPLE,
            )
        assert (editable.root / EXAMPLE).read_bytes() == before


class TestCreateComponents:
    def test_create_data_type_with_context_includes_used_udt(self, editable):
        spec = {
            "name": "CompUdt",
            "members": [
                {"name": "Go", "data_type": "BOOL"},
                {"name": "Inner", "data_type": "A_UDT"},
            ],
        }
        result = create_data_type_file(
            editable, spec=spec, context_path=EXAMPLE, output_path="cr.L5X"
        )

        component = _load(editable, OUT + "cr.L5X")
        assert result["target_type"] == "DataType"
        assert component.target.name == "CompUdt"
        assert "A_UDT" in component.data_types
        assert "A_UDT" in result["context"]["data_types"]

    def test_create_data_type_without_context_rejects_unknown_member_type(
        self, editable
    ):
        with pytest.raises(L5XError, match="unresolvable data type 'A_UDT'"):
            create_data_type_file(
                editable,
                spec={"name": "Solo", "members": [{"name": "x", "data_type": "A_UDT"}]},
                output_path="out.L5X",
            )
        assert not (editable.root / OUT_DIR / "out.L5X").exists()

    def test_create_data_type_without_members_is_refused(self, editable):
        with pytest.raises(L5XError, match="at least one member"):
            create_data_type_file(
                editable, spec={"name": "Empty", "members": []}, output_path="e.L5X"
            )
        assert not (editable.root / OUT_DIR / "e.L5X").exists()

    @pytest.mark.parametrize(
        "call",
        [
            lambda r, o: create_data_type_file(
                r, spec={"name": "", "members": 5}, output_path=o
            ),
            lambda r, o: create_aoi_file(r, spec={"bogus": 1}, output_path=o),
            lambda r, o: create_program_file(r, spec={"bogus": 1}, output_path=o),
            lambda r, o: create_tags_file(r, tags=[], output_path=o),
            lambda r, o: create_routine_file(
                r, program="P", routine={"bogus": 1}, output_path=o
            ),
            lambda r, o: create_rungs_file(
                r, program="P", routine="R", rungs=[], output_path=o
            ),
            lambda r, o: export_component(r, kind="nope", output_path=o, path=EXAMPLE),
        ],
    )
    def test_output_path_is_checked_before_the_spec(self, editable, call):
        with pytest.raises(L5XError, match="output_path must end in .L5X"):
            call(editable, "x.txt")

    def test_existing_name_in_context_is_refused(self, editable):
        with pytest.raises(L5XError, match="already exists"):
            create_data_type_file(
                editable,
                spec={
                    "name": "simple_udt",
                    "members": [{"name": "x", "data_type": "DINT"}],
                },
                context_path=EXAMPLE,
                output_path="out.L5X",
            )

    def test_create_aoi_file(self, editable):
        spec = {
            "name": "NewAoi",
            "parameters": [{"name": "In1", "data_type": "BOOL", "usage": "Input"}],
            "routines": [
                {"name": "Logic", "type": "RLL", "rungs": [{"text": "XIC(In1)OTE(x);"}]}
            ],
        }
        result = create_aoi_file(
            editable, spec=spec, context_path=EXAMPLE, output_path="aoi.L5X"
        )

        component = _load(editable, OUT + "aoi.L5X")
        assert result["target_type"] == "AddOnInstructionDefinition"
        assert component.target.name == "NewAoi"
        assert component.target.routines["Logic"].rungs[0].text == "XIC(In1)OTE(x);"

    def test_create_program_file(self, editable):
        spec = {
            "name": "NewProg",
            "tags": [{"name": "Speed", "data_type": "REAL", "value": 2.5}],
            "routines": [
                {"name": "Main", "type": "RLL", "rungs": [{"text": "NOP();"}]}
            ],
            "main_routine": "Main",
        }
        result = create_program_file(editable, spec=spec, output_path="prog.L5X")

        component = _load(editable, OUT + "prog.L5X")
        assert result["target_type"] == "Program"
        assert component.target.name == "NewProg"
        assert component.programs["NewProg"].tags["Speed"].value == 2.5

    def test_create_tags_alias_carries_its_target(self, editable):
        result = create_tags_file(
            editable,
            tags=[
                {"name": "CompTag", "data_type": "DINT", "value": 3},
                {"name": "CompAlias", "alias_for": "produced_tag"},
            ],
            context_path=EXAMPLE,
            output_path="tags.L5X",
        )

        component = _load(editable, OUT + "tags.L5X")
        assert result["target_type"] == "Tag"
        assert component.controller_tags["CompTag"].value == 3
        assert "produced_tag" in component.controller_tags
        assert "produced_tag" in result["context"]["tags"]

    def test_create_tags_alias_to_tag_in_same_list(self, editable):
        create_tags_file(
            editable,
            tags=[
                {"name": "CompAlias", "alias_for": "CompTag"},
                {"name": "CompTag", "data_type": "DINT"},
            ],
            output_path="tags.L5X",
        )
        assert "CompAlias" in _load(editable, OUT + "tags.L5X").controller_tags

    def test_create_tags_alias_to_missing_tag_needs_context(self, editable):
        with pytest.raises(L5XError, match="context_path"):
            create_tags_file(
                editable,
                tags=[{"name": "CompAlias", "alias_for": "produced_tag"}],
                output_path="tags.L5X",
            )
        assert not (editable.root / OUT_DIR / "tags.L5X").exists()

    def test_create_tags_alias_to_missing_tag_in_context_is_refused(self, editable):
        with pytest.raises(L5XError, match="NoSuchTag"):
            create_tags_file(
                editable,
                tags=[{"name": "CompAlias", "alias_for": "NoSuchTag"}],
                context_path=EXAMPLE,
                output_path="tags.L5X",
            )

    def test_create_program_file_alias_to_missing_tag_is_refused(self, editable):
        spec = {
            "name": "NewProg",
            "tags": [{"name": "Al", "alias_for": "NoSuchTag"}],
        }
        with pytest.raises(L5XError, match="NoSuchTag"):
            create_program_file(
                editable, spec=spec, context_path=EXAMPLE, output_path="p.L5X"
            )

    @pytest.mark.parametrize(
        "tags",
        [
            [{"name": "Me", "alias_for": "Me"}],
            [{"name": "A", "alias_for": "B"}, {"name": "B", "alias_for": "A"}],
        ],
    )
    def test_create_tags_alias_cycles_are_refused(self, editable, tags):
        with pytest.raises(L5XError, match="alias cycle"):
            create_tags_file(editable, tags=tags, output_path="tags.L5X")

    def test_create_tags_rejects_unknown_type(self, editable):
        with pytest.raises(L5XError, match="NOTATYPE"):
            create_tags_file(
                editable,
                tags=[{"name": "X", "data_type": "NOTATYPE"}],
                output_path="out.L5X",
            )
        assert not (editable.root / OUT_DIR / "out.L5X").exists()

    def test_create_routine_file_targets_named_program(self, editable):
        result = create_routine_file(
            editable,
            program="MainProgram",
            routine={
                "name": "CompRtn",
                "type": "RLL",
                "rungs": [{"text": "XIC(an_int)OTE(an_int_out);"}],
            },
            output_path="rtn.L5X",
        )

        component = _load(editable, OUT + "rtn.L5X")
        assert result["targets"] == ["MainProgram/CompRtn"]
        assert component.target_type == "Routine"
        assert component.target.name == "CompRtn"

    def test_create_rungs_file_counts_rungs(self, editable):
        result = create_rungs_file(
            editable,
            program="MainProgram",
            routine="MainRoutine",
            rungs=[{"text": "XIC(an_int)OTE(an_int_out);", "comment": "x"}],
            output_path="rungs.L5X",
        )

        component = _load(editable, OUT + "rungs.L5X")
        assert result["target_type"] == "Rung"
        assert component.target_type == "Rung"
        assert component.target.comment == "x"

    def test_context_project_is_never_modified(self, editable):
        before = (editable.root / EXAMPLE).read_bytes()

        create_tags_file(
            editable,
            tags=[{"name": "CompTag", "data_type": "DINT"}],
            context_path=EXAMPLE,
            output_path="tags.L5X",
        )

        assert (editable.root / EXAMPLE).read_bytes() == before

    def test_output_may_not_overwrite_the_context_project(self, editable):
        before = (editable.root / EXAMPLE).read_bytes()

        with pytest.raises(L5XError, match="must differ from the source"):
            create_tags_file(
                editable,
                tags=[{"name": "CompTag", "data_type": "DINT"}],
                context_path=EXAMPLE,
                output_path=str(editable.root / EXAMPLE),
                overwrite=True,
            )

        assert (editable.root / EXAMPLE).read_bytes() == before
