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

    def test_routine_file_carries_new_program_tag(self, editable):
        result = create_routine_file(
            editable,
            program="MainProgram",
            routine={
                "name": "CompRtn",
                "type": "RLL",
                "rungs": [{"text": "XIC(an_int)OTE(NewBit);"}],
            },
            tags=[{"name": "NewBit", "data_type": "BOOL"}],
            context_path=EXAMPLE,
            output_path="rtn.L5X",
        )

        component = _load(editable, OUT + "rtn.L5X")
        assert "NewBit" in component.programs["MainProgram"].tags
        assert "warnings" not in result

    def test_routine_file_unreferenced_new_tag_warns(self, editable):
        result = create_routine_file(
            editable,
            program="MainProgram",
            routine={
                "name": "CompRtn",
                "type": "RLL",
                "rungs": [{"text": "XIC(an_int)OTE(NewBit);"}],
            },
            tags=[
                {"name": "NewBit", "data_type": "BOOL"},
                {"name": "Unused", "data_type": "DINT"},
            ],
            context_path=EXAMPLE,
            output_path="rtn.L5X",
        )

        component = _load(editable, OUT + "rtn.L5X")
        assert "Unused" not in component.programs["MainProgram"].tags
        assert len(result["warnings"]) == 1
        assert "Unused" in result["warnings"][0]
        assert "NewBit" not in result["warnings"][0]

    def test_routine_file_new_tag_name_must_be_free(self, editable):
        with pytest.raises(L5XError, match="already exists"):
            create_routine_file(
                editable,
                program="MainProgram",
                routine={"name": "CompRtn", "type": "RLL"},
                tags=[{"name": "an_int", "data_type": "DINT"}],
                context_path=EXAMPLE,
                output_path="rtn.L5X",
            )
        assert not (editable.root / OUT_DIR / "rtn.L5X").exists()

    def test_rungs_file_carries_new_program_tag_and_type(self, editable):
        create_rungs_file(
            editable,
            program="MainProgram",
            routine="MainRoutine",
            rungs=[{"text": "XIC(an_int)OTE(NewSeq.fault);"}],
            tags=[{"name": "NewSeq", "data_type": "SeqCtrl"}],
            context_path=EXAMPLE,
            output_path="rungs.L5X",
        )

        component = _load(editable, OUT + "rungs.L5X")
        assert "NewSeq" in component.programs["MainProgram"].tags
        assert "SeqCtrl" in component.aois

    def test_rungs_file_without_tags_is_unchanged(self, editable):
        result = create_rungs_file(
            editable,
            program="MainProgram",
            routine="MainRoutine",
            rungs=[{"text": "XIC(an_int)OTE(an_int_out);"}],
            context_path=EXAMPLE,
            output_path="rungs.L5X",
        )
        assert "warnings" not in result

    def test_tags_file_program_scope(self, editable):
        result = create_tags_file(
            editable,
            tags=[{"name": "NewTag", "data_type": "DINT", "value": 4}],
            program="SafetyProgram",
            context_path=EXAMPLE,
            output_path="ptags.L5X",
        )

        component = _load(editable, OUT + "ptags.L5X")
        assert result["target_type"] == "Tag"
        assert result["targets"] == ["SafetyProgram/NewTag"]
        assert component.target.name == "NewTag"
        assert component.programs["SafetyProgram"].tags["NewTag"].value == 4
        assert "NewTag" not in component.controller_tags
        assert "warnings" not in result

    def test_tags_file_unknown_program_warns(self, editable):
        # Studio skips program tags of a program the target lacks, silently
        # (SDK-verified on v37/v38), so the tool must say so.
        result = create_tags_file(
            editable,
            tags=[{"name": "onlyCount", "data_type": "DINT", "value": 3}],
            program="TagsOnlyProg",
            context_path=EXAMPLE,
            output_path="ptags_new.L5X",
        )

        assert result["targets"] == ["TagsOnlyProg/onlyCount"]
        assert any(
            "'TagsOnlyProg' is not in context_path" in w and "skipped" in w
            for w in result["warnings"]
        )

    def test_tags_file_program_tag_name_must_be_free(self, editable):
        with pytest.raises(L5XError, match="already exists"):
            create_tags_file(
                editable,
                tags=[{"name": "input_ok", "data_type": "BOOL"}],
                program="SafetyProgram",
                context_path=EXAMPLE,
                output_path="ptags.L5X",
            )

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


PROTECTED = "example.L5X"
AOI_WARNING = "AOI 'SeqCtrl_Protected' is source-protected; its encoded definition"
ROUTINE_WARNING = (
    "routine 'SequenceRoutine_Protected' is source-protected; tags and AOIs it "
    "uses could not be determined and are not included as context"
)


class TestProtectedComponents:
    def test_create_routine_file_copies_encoded_aoi_with_warning(self, editable):
        result = create_routine_file(
            editable,
            program="AnotherProgram",
            routine={
                "name": "CompRtn",
                "type": "RLL",
                "rungs": [
                    {
                        "text": (
                            "XIC(TestInput)MOVE(5,seqCtrl_Protected_Instance.nextStep);"
                        )
                    }
                ],
            },
            context_path=PROTECTED,
            output_path="rtn.L5X",
        )

        component = _load(editable, OUT + "rtn.L5X")
        assert "SeqCtrl_Protected" in component.protected_aois
        assert len(result["warnings"]) == 1
        assert result["warnings"][0].startswith(AOI_WARNING)
        assert "SeqCtrl_Protected (protected)" in result["context"]["aois"]

    def test_export_routine_copies_encoded_aoi_with_warning(self, editable):
        result = export_component(
            editable,
            kind="routine",
            program="AnotherProgram",
            names=["Main"],
            output_path="routine.L5X",
            path=PROTECTED,
        )

        assert (
            "SeqCtrl_Protected" in _load(editable, OUT + "routine.L5X").protected_aois
        )
        assert [w[: len(AOI_WARNING)] for w in result["warnings"]] == [AOI_WARNING]

    def test_export_program_with_protected_routine_gives_both_warnings(self, editable):
        result = export_component(
            editable,
            kind="program",
            names=["AnotherProgram"],
            output_path="prog.L5X",
            path=PROTECTED,
        )

        assert ROUTINE_WARNING in result["warnings"]
        assert any(w.startswith(AOI_WARNING) for w in result["warnings"])
        assert len(result["warnings"]) == 2

    def test_export_protected_aoi_is_refused(self, editable):
        with pytest.raises(L5XError, match="source-protected.*cannot be exported"):
            export_component(
                editable,
                kind="aoi",
                names=["seqctrl_protected"],
                output_path="aoi.L5X",
                path=PROTECTED,
            )
        assert not (editable.root / OUT_DIR / "aoi.L5X").exists()

    def test_export_protected_routine_is_refused(self, editable):
        with pytest.raises(L5XError, match="source-protected.*cannot be exported"):
            export_component(
                editable,
                kind="routine",
                program="AnotherProgram",
                names=["SequenceRoutine_Protected"],
                output_path="r.L5X",
                path=PROTECTED,
            )
        assert not (editable.root / OUT_DIR / "r.L5X").exists()

    def test_no_warning_without_protected_content(self, editable):
        result = export_component(
            editable,
            kind="routine",
            program="MainProgram",
            names=["SequenceRoutine"],
            output_path="routine.L5X",
            path=EXAMPLE,
        )
        assert "warnings" not in result


class TestCopyFromAndProtectedTags:
    def test_program_tags_file_carries_copied_and_set_data(self, editable):
        create_tags_file(
            editable,
            program="AnotherProgram",
            tags=[
                {
                    "name": "protValue",
                    "data_type": "SeqCtrl_Protected",
                    "value": {"startupStep": 4321, "mode": True},
                },
                {
                    "name": "protCopy",
                    "copy_from": "seqCtrl_Protected_Instance",
                    "value": {"startupStep": 1234},
                },
            ],
            output_path="t.L5X",
            context_path=EXAMPLE,
        )

        tags = _load(editable, OUT + "t.L5X").programs["AnotherProgram"].tags
        assert tags["protValue"].to_python()["startupStep"] == 4321
        copy = tags["protCopy"]
        assert copy.to_python()["startupStep"] == 1234
        formats = {d.get("Format") for d in copy._element.findall("Data")}
        assert formats == {"L5K", "Decorated"}
        assert "7000,7000" in "".join(copy._element.find("Data").itertext())

    def test_controller_tags_file_copy_from(self, editable):
        create_tags_file(
            editable,
            tags=[
                {
                    "name": "protCtl",
                    "copy_from": "\\AnotherProgram.seqCtrl_Protected_Instance",
                }
            ],
            output_path="t.L5X",
            context_path=EXAMPLE,
        )

        tag = _load(editable, OUT + "t.L5X").controller_tags["protCtl"]
        formats = {d.get("Format") for d in tag._element.findall("Data")}
        assert formats == {"L5K", "Decorated"}

    def test_copy_from_missing_source(self, editable):
        with pytest.raises(L5XError, match="copy_from tag 'nope' not found"):
            create_tags_file(
                editable,
                tags=[{"name": "x", "copy_from": "nope"}],
                output_path="t.L5X",
                context_path=EXAMPLE,
            )

    def test_routine_file_with_new_protected_tag(self, editable):
        create_routine_file(
            editable,
            program="AnotherProgram",
            routine={
                "name": "ProtUse",
                "type": "RLL",
                "rungs": [{"text": "SeqCtrl_Protected(newProtInst,0,0);"}],
            },
            tags=[
                {
                    "name": "newProtInst",
                    "data_type": "SeqCtrl_Protected",
                    "external_access": "Read/Write",
                }
            ],
            output_path="r.L5X",
            context_path=EXAMPLE,
        )

        prog = _load(editable, OUT + "r.L5X").programs["AnotherProgram"]
        assert prog.tags["newProtInst"].data_type == "SeqCtrl_Protected"

    def test_routine_file_tag_copy_from(self, editable):
        create_routine_file(
            editable,
            program="AnotherProgram",
            routine={
                "name": "ProtUse",
                "type": "RLL",
                "rungs": [{"text": "SeqCtrl_Protected(newProtInst,0,0);"}],
            },
            tags=[{"name": "newProtInst", "copy_from": "seqCtrl_Protected_Instance"}],
            output_path="r.L5X",
            context_path=EXAMPLE,
        )

        tag = (
            _load(editable, OUT + "r.L5X")
            .programs["AnotherProgram"]
            .tags["newProtInst"]
        )
        assert {d.get("Format") for d in tag._element.findall("Data")} == {
            "L5K",
            "Decorated",
        }
