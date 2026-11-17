"""Tests for get_spec and the UDT, AOI, program and description write tools."""

import pytest
from py_l5x import load

from l5x_mcp.registry import DEFAULT_OUTPUT_DIR, L5XError
from l5x_mcp.specs import from_py_spec
from l5x_mcp.tools.definitions import (
    add_aoi,
    add_data_type,
    add_program,
    get_spec,
    remove_aoi,
    remove_data_type,
    remove_program,
    rename_aoi,
    rename_data_type,
    rename_program,
    replace_aoi,
    replace_data_type,
    replace_program,
    schedule_program,
    set_description,
)
from l5x_mcp.tools.edit_logic import add_rungs

OUT_DIR = DEFAULT_OUTPUT_DIR
OUT = OUT_DIR + "/"
EXAMPLE = "example.L5X"


def _read(editable, rel):
    return load(str(editable.root / rel))


def _comparable(spec):
    """A spec with the metadata Studio re-stamps on every save removed."""
    spec = dict(spec)
    metadata = dict(spec.get("metadata") or {})
    metadata.pop("EditedBy", None)
    metadata.pop("EditedDate", None)
    if metadata:
        spec["metadata"] = metadata
    else:
        spec.pop("metadata", None)
    return spec


class TestGetSpec:
    def test_returns_spec_in_the_add_form(self, editable):
        result = get_spec(editable, kind="data_type", name="simple_udt", path=EXAMPLE)

        assert result["kind"] == "data_type"
        assert result["spec"]["name"] == "simple_udt"
        assert result["spec"]["members"][0] == {"name": "bool1", "data_type": "BOOL"}

    def test_values_can_be_left_out_of_program_specs(self, editable):
        with_values = get_spec(editable, kind="program", name="Robot", path=EXAMPLE)
        without = get_spec(
            editable,
            kind="program",
            name="Robot",
            include_values=False,
            path=EXAMPLE,
        )

        assert any("value" in t for t in with_values["spec"]["tags"])
        assert not any("value" in t for t in without["spec"]["tags"])

    def test_size_limit_is_an_error_not_a_truncation(self, editable):
        with pytest.raises(L5XError, match="over max_chars=1000") as info:
            get_spec(
                editable,
                kind="program",
                name="MainProgram",
                max_chars=1000,
                path=EXAMPLE,
            )
        assert "include_values=false" in str(info.value)

    def test_routine_spec_needs_its_program(self, editable):
        with pytest.raises(L5XError, match="program is required"):
            get_spec(editable, kind="routine", name="Logic", path=EXAMPLE)

    def test_routine_spec(self, editable):
        result = get_spec(
            editable,
            kind="routine",
            name="MainRoutine",
            program="MainProgram",
            path=EXAMPLE,
        )
        assert result["program"] == "MainProgram"
        assert result["spec"]["rungs"] == [{"text": "JSR(SequenceRoutine,0);"}]

    def test_tag_spec(self, editable):
        result = get_spec(editable, kind="tag", name="fromNormal_reset", path=EXAMPLE)
        assert result["spec"]["name"] == "fromNormal_reset"
        assert result["spec"]["data_type"] == "BOOL"

    def test_consumed_tags_have_no_spec(self, editable):
        with pytest.raises(L5XError, match="Consumed tags are not supported"):
            get_spec(editable, kind="tag", name="consumed_tag", path=EXAMPLE)


class TestSpecRoundTrip:
    """get_spec -> replace_* with no change must not change the object."""

    @pytest.mark.parametrize(
        "kind, name",
        [
            ("data_type", "simple_udt"),
            ("data_type", "robotUI"),
            ("aoi", "Debounce"),
            ("aoi", "FanucRobot"),
            ("program", "Robot"),
            ("program", "SafetyProgram"),
        ],
    )
    def test_replace_with_unchanged_spec_keeps_the_object(self, editable, kind, name):
        before = load(str(editable.root / EXAMPLE))
        spec = get_spec(editable, kind=kind, name=name, path=EXAMPLE)["spec"]
        replace = {
            "data_type": replace_data_type,
            "aoi": replace_aoi,
            "program": replace_program,
        }[kind]

        replace(editable, spec=spec, output_path="out.L5X", path=EXAMPLE)

        collection = {
            "data_type": "data_types",
            "aoi": "aois",
            "program": "programs",
        }[kind]
        original = getattr(before, collection)[name]
        written = getattr(_read(editable, OUT + "out.L5X"), collection)[name]
        assert _comparable(from_py_spec(written.to_spec())) == _comparable(
            from_py_spec(original.to_spec())
        )
        assert _read(editable, EXAMPLE).programs.keys() == before.programs.keys()

    def test_program_round_trip_without_values_also_holds(self, editable):
        spec = get_spec(
            editable, kind="program", name="Robot", include_values=False, path=EXAMPLE
        )["spec"]
        replace_program(editable, spec=spec, output_path="out.L5X", path=EXAMPLE)

        original = load(str(editable.root / EXAMPLE)).programs["Robot"]
        written = _read(editable, OUT + "out.L5X").programs["Robot"]
        assert from_py_spec(written.to_spec()) == from_py_spec(original.to_spec())


class TestDataTypes:
    def test_add_packs_bool_members_and_keeps_array_dimension(self, editable):
        add_data_type(
            editable,
            spec={
                "name": "NewUdt",
                "members": [
                    {"name": "Run", "data_type": "BOOL"},
                    {"name": "Count", "data_type": "DINT"},
                    {"name": "Timer", "data_type": "TIMER"},
                    {"name": "Arr", "data_type": "REAL", "dimension": 3},
                ],
            },
            output_path="out.L5X",
            path=EXAMPLE,
        )

        udt = _read(editable, OUT + "out.L5X").data_types["NewUdt"]
        assert set(udt.visible_members) == {"Run", "Count", "Timer", "Arr"}
        # py_l5x stores BOOL members as BIT bits on hidden SINT hosts.
        assert udt.visible_members["Run"].data_type == "BIT"
        assert udt.visible_members["Arr"].dimension == 3

    def test_add_and_replace_without_members_are_refused(self, editable):
        spec = {"name": "simple_udt", "members": []}
        with pytest.raises(L5XError, match="at least one member"):
            add_data_type(editable, spec=spec, output_path="o.L5X", path=EXAMPLE)
        with pytest.raises(L5XError, match="at least one member"):
            replace_data_type(editable, spec=spec, output_path="o.L5X", path=EXAMPLE)
        assert not (editable.root / OUT_DIR / "o.L5X").exists()

    def test_add_duplicate_name_is_refused(self, editable):
        with pytest.raises(L5XError, match="simple_udt"):
            add_data_type(
                editable,
                spec={
                    "name": "simple_udt",
                    "members": [{"name": "x", "data_type": "DINT"}],
                },
                output_path="out.L5X",
                path=EXAMPLE,
            )
        assert not (editable.root / OUT_DIR / "out.L5X").exists()

    def test_unknown_member_type_is_refused(self, editable):
        with pytest.raises(L5XError, match="NoSuchType"):
            add_data_type(
                editable,
                spec={
                    "name": "Bad",
                    "members": [{"name": "x", "data_type": "NoSuchType"}],
                },
                output_path="out.L5X",
                path=EXAMPLE,
            )

    def test_replace_changes_members(self, editable):
        spec = get_spec(editable, kind="data_type", name="simple_udt", path=EXAMPLE)[
            "spec"
        ]
        spec["members"].append(
            {"name": "extra", "data_type": "DINT", "description": "new"}
        )

        result = replace_data_type(
            editable, spec=spec, output_path="out.L5X", path=EXAMPLE
        )

        assert result["members"] == len(spec["members"])
        udt = _read(editable, OUT + "out.L5X").data_types["simple_udt"]
        assert udt.visible_members["extra"].description == "new"

    def test_replace_unknown_type_is_refused(self, editable):
        with pytest.raises(L5XError, match="Data type 'Nope' not found"):
            replace_data_type(
                editable,
                spec={"name": "Nope", "members": [{"name": "x", "data_type": "DINT"}]},
                output_path="out.L5X",
                path=EXAMPLE,
            )

    def test_rename_updates_tags_of_the_type(self, editable):
        result = rename_data_type(
            editable,
            name="simple_udt",
            new_name="Simple2",
            output_path="out.L5X",
            path=EXAMPLE,
        )

        assert result["renamed"] == {"from": "simple_udt", "to": "Simple2"}
        project = _read(editable, OUT + "out.L5X")
        assert "Simple2" in project.data_types
        assert project.programs["MainProgram"].tags[
            "a_simple_udt_instance"
        ].data_type == ("Simple2")

    def test_remove_refuses_while_in_use(self, editable):
        with pytest.raises(L5XError, match="in use by"):
            remove_data_type(
                editable, name="A_UDT", output_path="out.L5X", path=EXAMPLE
            )
        assert not (editable.root / OUT_DIR / "out.L5X").exists()

    def test_remove_with_force_deletes_the_type(self, editable):
        result = remove_data_type(
            editable, name="A_UDT", force=True, output_path="out.L5X", path=EXAMPLE
        )

        assert result["removed"] == "A_UDT"
        assert "A_UDT" not in _read(editable, OUT + "out.L5X").data_types


class TestAOIs:
    AOI_SPEC = {
        "name": "NewAoi",
        "parameters": [
            {"name": "In1", "data_type": "BOOL", "usage": "Input"},
            {"name": "Out1", "data_type": "DINT", "usage": "Output"},
        ],
        "local_tags": [{"name": "Tmp", "data_type": "DINT", "default": 3}],
        "routines": [
            {
                "name": "Logic",
                "type": "RLL",
                "rungs": [{"text": "XIC(In1)MOV(1,Out1);"}],
            }
        ],
        "revision": "1.0",
        "description": "new aoi",
    }

    def test_add_creates_parameters_and_logic(self, editable):
        result = add_aoi(
            editable, spec=self.AOI_SPEC, output_path="out.L5X", path=EXAMPLE
        )

        assert result["parameters"] == 2
        aoi = _read(editable, OUT + "out.L5X").aois["NewAoi"]
        assert {"EnableIn", "EnableOut", "In1", "Out1"} <= set(aoi.parameters)
        assert aoi.description == "new aoi"
        assert aoi.routines["Logic"].rungs[0].text == "XIC(In1)MOV(1,Out1);"

    def test_add_without_logic_routine_is_refused(self, editable):
        spec = {**self.AOI_SPEC, "routines": []}
        with pytest.raises(L5XError, match="Logic"):
            add_aoi(editable, spec=spec, output_path="out.L5X", path=EXAMPLE)

    def test_replace_refuses_signature_change_while_called(self, editable):
        spec = get_spec(editable, kind="aoi", name="Debounce", path=EXAMPLE)["spec"]
        for param in spec["parameters"]:
            if param["name"] == "onDelay":
                param["required"] = True

        with pytest.raises(L5XError, match="call site"):
            replace_aoi(editable, spec=spec, output_path="out.L5X", path=EXAMPLE)
        assert not (editable.root / OUT_DIR / "out.L5X").exists()

        replace_aoi(
            editable,
            spec=spec,
            allow_signature_change=True,
            output_path="out.L5X",
            path=EXAMPLE,
        )
        assert _read(editable, OUT + "out.L5X").aois["Debounce"].parameters["onDelay"]

    def test_rename_rewrites_call_sites(self, editable):
        result = rename_aoi(
            editable,
            name="Debounce",
            new_name="Debounce2",
            output_path="out.L5X",
            path=EXAMPLE,
        )

        assert result["call_sites"] == 1
        project = _read(editable, OUT + "out.L5X")
        assert "Debounce2" in project.aois
        call = project.aois["GenericInput"].routines["Logic"].rungs[2].text
        assert "Debounce2(" in call

    def test_remove_refuses_while_in_use(self, editable):
        with pytest.raises(L5XError, match="in use by"):
            remove_aoi(
                editable, name="GenericInput", output_path="out.L5X", path=EXAMPLE
            )

    def test_remove_unused_aoi(self, editable):
        add_aoi(editable, spec=self.AOI_SPEC, output_path="one.L5X", path=EXAMPLE)

        result = remove_aoi(
            editable, name="NewAoi", output_path="two.L5X", path=OUT + "one.L5X"
        )

        assert result["removed"] == "NewAoi"
        assert "NewAoi" not in _read(editable, OUT + "two.L5X").aois


class TestPrograms:
    PROGRAM_SPEC = {
        "name": "NewProg",
        "tags": [{"name": "Speed", "data_type": "REAL", "value": 1.5}],
        "routines": [
            {"name": "Main", "type": "RLL", "rungs": [{"text": "JSR(NewRtn,0);"}]},
            {"name": "NewRtn", "type": "ST", "lines": ["x := 1;"]},
        ],
        "main_routine": "Main",
    }

    def test_add_schedules_the_program_in_the_task(self, editable):
        result = add_program(
            editable,
            spec=self.PROGRAM_SPEC,
            task="MainTask",
            output_path="out.L5X",
            path=EXAMPLE,
        )

        assert result["task"] == "MainTask"
        project = _read(editable, OUT + "out.L5X")
        assert "NewProg" in project.tasks["MainTask"].programs
        assert project.programs["NewProg"].tags["Speed"].value == 1.5
        assert project.programs["NewProg"].main_routine_name == "Main"

    def test_add_without_task_is_unscheduled(self, editable):
        result = add_program(
            editable, spec=self.PROGRAM_SPEC, output_path="out.L5X", path=EXAMPLE
        )

        assert result["task"] is None
        project = _read(editable, OUT + "out.L5X")
        assert "NewProg" in project.programs
        assert all("NewProg" not in t.programs for t in project.tasks.values())

    def test_unknown_task_lists_tasks(self, editable):
        with pytest.raises(L5XError, match="MainTask"):
            add_program(
                editable,
                spec=self.PROGRAM_SPEC,
                task="NoSuchTask",
                output_path="out.L5X",
                path=EXAMPLE,
            )

    def test_add_with_alias_to_missing_tag_is_refused(self, editable):
        spec = {**self.PROGRAM_SPEC, "tags": [{"name": "Al", "alias_for": "NoTag"}]}
        with pytest.raises(L5XError, match="NoTag"):
            add_program(editable, spec=spec, output_path="out.L5X", path=EXAMPLE)
        assert not (editable.root / OUT_DIR / "out.L5X").exists()

    def test_add_with_alias_to_controller_or_same_spec_tag(self, editable):
        spec = {
            **self.PROGRAM_SPEC,
            "tags": [
                {"name": "A1", "alias_for": "consumed_tag"},
                {"name": "A2", "alias_for": "Base"},
                {"name": "Base", "data_type": "DINT"},
            ],
        }
        add_program(editable, spec=spec, output_path="out.L5X", path=EXAMPLE)
        assert "A2" in _read(editable, OUT + "out.L5X").programs["NewProg"].tags

    def test_replace_removes_tags_not_in_the_spec(self, editable):
        add_program(
            editable, spec=self.PROGRAM_SPEC, output_path="added.L5X", path=EXAMPLE
        )
        spec = {**self.PROGRAM_SPEC, "tags": []}
        replace_program(
            editable, spec=spec, output_path="out.L5X", path=OUT + "added.L5X"
        )

        program = _read(editable, OUT + "out.L5X").programs["NewProg"]
        assert len(program.tags) == 0
        assert len(program.routines) == 2

    def test_rename_follows_task_schedule_and_reports_references(self, editable):
        add_rungs(
            editable,
            program="MainProgram",
            routine="MainRoutine",
            rungs=[{"text": "XIC(\\PeriodicProgram.test_bool)OTE(an_int_out);"}],
            output_path="step1.L5X",
            path=EXAMPLE,
        )

        result = rename_program(
            editable,
            name="PeriodicProgram",
            new_name="Periodic2",
            output_path="step2.L5X",
            path=OUT + "step1.L5X",
        )

        assert result["references"]["locations"] == ["MainProgram/MainRoutine rung 1"]
        project = _read(editable, OUT + "step2.L5X")
        assert "Periodic2" in project.programs
        assert "Periodic2" in project.tasks["PeriodicTask"].programs

    def test_remove_program_also_leaves_its_task(self, editable):
        result = remove_program(
            editable, name="PeriodicProgram", output_path="out.L5X", path=EXAMPLE
        )

        assert result["removed"] == "PeriodicProgram"
        project = _read(editable, OUT + "out.L5X")
        assert "PeriodicProgram" not in project.programs
        assert "PeriodicProgram" not in project.tasks["PeriodicTask"].programs

    def test_schedule_moves_then_unschedules(self, editable):
        moved = schedule_program(
            editable,
            name="PeriodicProgram",
            task="MainTask",
            output_path="moved.L5X",
            path=EXAMPLE,
        )
        assert moved["previous_task"] == "PeriodicTask"
        project = _read(editable, OUT + "moved.L5X")
        assert "PeriodicProgram" in project.tasks["MainTask"].programs
        assert "PeriodicProgram" not in project.tasks["PeriodicTask"].programs

        unscheduled = schedule_program(
            editable,
            name="PeriodicProgram",
            output_path="free.L5X",
            path=OUT + "moved.L5X",
        )
        assert unscheduled["previous_task"] == "MainTask"
        assert all(
            "PeriodicProgram" not in t.programs
            for t in _read(editable, OUT + "free.L5X").tasks.values()
        )

    def test_schedule_unknown_task_is_refused(self, editable):
        with pytest.raises(L5XError, match="NoSuchTask"):
            schedule_program(
                editable,
                name="PeriodicProgram",
                task="NoSuchTask",
                output_path="out.L5X",
                path=EXAMPLE,
            )


class TestSetDescription:
    @pytest.mark.parametrize(
        "kind, name, program, reader",
        [
            ("program", "MainProgram", None, lambda p: p.programs["MainProgram"]),
            (
                "routine",
                "MainRoutine",
                "MainProgram",
                lambda p: p.programs["MainProgram"].routines["MainRoutine"],
            ),
            ("data_type", "A_UDT", None, lambda p: p.data_types["A_UDT"]),
            ("aoi", "Debounce", None, lambda p: p.aois["Debounce"]),
        ],
    )
    def test_sets_and_clears_description(self, editable, kind, name, program, reader):
        set_description(
            editable,
            kind=kind,
            name=name,
            description="Documented",
            program=program,
            output_path="set.L5X",
            path=EXAMPLE,
        )
        assert reader(_read(editable, OUT + "set.L5X")).description == "Documented"

        set_description(
            editable,
            kind=kind,
            name=name,
            description="",
            program=program,
            output_path="clear.L5X",
            path=OUT + "set.L5X",
        )
        assert not reader(_read(editable, OUT + "clear.L5X")).description

    def test_routine_needs_its_program(self, editable):
        with pytest.raises(L5XError, match="program is required"):
            set_description(
                editable,
                kind="routine",
                name="MainRoutine",
                description="x",
                output_path="out.L5X",
                path=EXAMPLE,
            )
