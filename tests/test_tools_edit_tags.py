"""Tests for the tag write tools (add, remove, rename, set values, update)."""

import pytest
from py_l5x import AliasTag, load

from l5x_mcp.registry import ItemNotFoundError, L5XError
from l5x_mcp.tools.edit_tags import (
    add_tags,
    remove_tags,
    rename_tag,
    set_tag_values,
    update_tag,
)

EXAMPLE = "example.L5X"


def _read(editable, rel):
    return load(str(editable.root / rel))


class TestAddTags:
    def test_adds_base_alias_structure_and_array_tags(self, editable):
        result = add_tags(
            editable,
            tags=[
                {
                    "name": "NewDint",
                    "data_type": "DINT",
                    "value": 5,
                    "description": "d",
                },
                {"name": "NewAlias", "alias_for": "consumed_tag"},
                {"name": "NewTimer", "data_type": "TIMER", "value": {"PRE": 5000}},
                {
                    "name": "NewArr",
                    "data_type": "DINT",
                    "dimensions": [4],
                    "value": [1, 2, 3, 4],
                },
            ],
            output_path="out.L5X",
            path=EXAMPLE,
        )

        assert result["added"] == ["NewDint", "NewAlias", "NewTimer", "NewArr"]
        assert result["scope"] == "controller"
        tags = _read(editable, "out.L5X").controller_tags
        assert tags["NewDint"].data_type == "DINT"
        assert tags["NewDint"].value == 5
        assert tags["NewDint"].description == "d"
        assert isinstance(tags["NewAlias"], AliasTag)
        assert tags["NewAlias"].alias_for == "consumed_tag"
        assert tags["NewTimer"].data_type == "TIMER"
        assert tags["NewTimer"].to_python()["PRE"] == 5000
        assert tags["NewArr"].dimensions == (4,)
        assert list(tags["NewArr"].to_python()) == [1, 2, 3, 4]

    def test_adds_to_a_program_scope(self, editable):
        result = add_tags(
            editable,
            tags=[{"name": "ProgFlag", "data_type": "BOOL"}],
            scope="safetyprogram",
            output_path="out.L5X",
            path=EXAMPLE,
        )

        assert result["scope"] == "SafetyProgram"
        program = _read(editable, "out.L5X").programs["SafetyProgram"]
        assert program.tags["ProgFlag"].data_type == "BOOL"

    def test_unknown_data_type_writes_nothing(self, editable):
        with pytest.raises(L5XError, match="unknown data type 'NOTATYPE'"):
            add_tags(
                editable,
                tags=[{"name": "Bad", "data_type": "NOTATYPE"}],
                output_path="out.L5X",
                path=EXAMPLE,
            )
        assert not (editable.root / "out.L5X").exists()

    def test_one_bad_tag_writes_nothing(self, editable):
        with pytest.raises(L5XError, match="tag 'Bad'"):
            add_tags(
                editable,
                tags=[
                    {"name": "Good", "data_type": "DINT"},
                    {"name": "Bad", "data_type": "TIMER", "value": {"NOPE": 1}},
                ],
                output_path="out.L5X",
                path=EXAMPLE,
            )
        assert not (editable.root / "out.L5X").exists()

    def test_duplicate_name_is_refused(self, editable):
        with pytest.raises(L5XError, match="consumed_tag"):
            add_tags(
                editable,
                tags=[{"name": "consumed_tag", "data_type": "DINT"}],
                output_path="out.L5X",
                path=EXAMPLE,
            )

    def test_data_type_and_alias_are_exclusive(self, editable):
        with pytest.raises(L5XError, match="either data_type or alias_for"):
            add_tags(
                editable,
                tags=[
                    {"name": "Both", "data_type": "DINT", "alias_for": "consumed_tag"}
                ],
                output_path="out.L5X",
                path=EXAMPLE,
            )

    def test_empty_list_is_refused(self, editable):
        with pytest.raises(L5XError, match="at least one tag"):
            add_tags(editable, tags=[], output_path="out.L5X", path=EXAMPLE)

    def test_unknown_program_lists_programs(self, editable):
        with pytest.raises(ItemNotFoundError, match="MainProgram"):
            add_tags(
                editable,
                tags=[{"name": "X", "data_type": "DINT"}],
                scope="NoSuchProgram",
                output_path="out.L5X",
                path=EXAMPLE,
            )


class TestRemoveTags:
    def test_removes_the_tag(self, editable):
        result = remove_tags(
            editable, names=["consumed_tag"], output_path="out.L5X", path=EXAMPLE
        )

        assert result["removed"] == [{"name": "consumed_tag", "scope": "controller"}]
        assert "consumed_tag" not in _read(editable, "out.L5X").controller_tags

    def test_reports_logic_still_using_the_tag(self, editable):
        result = remove_tags(
            editable, names=["input_ok"], output_path="out.L5X", path=EXAMPLE
        )

        refs = result["references"]["input_ok"]
        assert refs["total"] >= 3
        assert "SafetyProgram/Inputs rung 0" in refs["locations"]

    def test_unused_tag_has_no_references_key(self, editable):
        result = remove_tags(
            editable, names=["consumed_tag"], output_path="out.L5X", path=EXAMPLE
        )
        assert "references" not in result

    def test_unknown_name_is_reported(self, editable):
        with pytest.raises(ItemNotFoundError, match="Tag 'nope' not found"):
            remove_tags(editable, names=["nope"], output_path="out.L5X", path=EXAMPLE)

    def test_module_io_tags_are_refused(self, editable):
        with pytest.raises(L5XError, match="not a plain tag name"):
            remove_tags(
                editable, names=["Local:1:I"], output_path="out.L5X", path=EXAMPLE
            )


class TestRenameTag:
    def test_renames_and_reports_logic_references(self, editable):
        result = rename_tag(
            editable,
            name="input_ok",
            new_name="input_ok2",
            output_path="out.L5X",
            path=EXAMPLE,
        )

        assert result["renamed"] == {"from": "input_ok", "to": "input_ok2"}
        program = _read(editable, "out.L5X").programs["SafetyProgram"]
        assert "input_ok2" in program.tags
        assert "input_ok" not in program.tags
        assert result["references"]["total"] >= 3

    def test_case_only_rename_reports_no_references(self, editable):
        result = rename_tag(
            editable,
            name="input_ok",
            new_name="INPUT_OK",
            output_path="out.L5X",
            path=EXAMPLE,
        )
        assert result["renamed"]["to"] == "INPUT_OK"
        assert "references" not in result

    def test_unknown_tag_lists_available_names(self, editable):
        with pytest.raises(ItemNotFoundError, match="Available controller tags"):
            rename_tag(
                editable, name="nope", new_name="x", output_path="out.L5X", path=EXAMPLE
            )

    def test_duplicate_new_name_is_refused(self, editable):
        with pytest.raises(L5XError, match="ALLOWABLE_ALARMS"):
            rename_tag(
                editable,
                name="consumed_tag",
                new_name="ALLOWABLE_ALARMS",
                output_path="out.L5X",
                path=EXAMPLE,
            )
        assert not (editable.root / "out.L5X").exists()


class TestSetTagValues:
    def test_sets_scalars_program_tags_and_structure_members(self, editable):
        add_tags(
            editable,
            tags=[{"name": "Delay", "data_type": "TIMER"}],
            output_path="base.L5X",
            path=EXAMPLE,
        )

        result = set_tag_values(
            editable,
            values={
                "consumed_tag": 42,
                "Delay": {"PRE": 1500},
                "\\PeriodicProgram.test_dint": 7,
            },
            output_path="out.L5X",
            path="base.L5X",
        )

        assert set(result["set"]) == {
            "consumed_tag",
            "Delay",
            "\\PeriodicProgram.test_dint",
        }
        project = _read(editable, "out.L5X")
        assert project.controller_tags["consumed_tag"].value == 42
        assert project.controller_tags["Delay"].to_python()["PRE"] == 1500
        assert project.programs["PeriodicProgram"].tags["test_dint"].value == 7

    def test_sets_sub_paths_of_tags_added_without_data(self, editable):
        add_tags(
            editable,
            tags=[
                {"name": "Arr", "data_type": "DINT", "dimensions": 4},
                {"name": "T1", "data_type": "TIMER"},
            ],
            output_path="base.L5X",
            path=EXAMPLE,
        )

        set_tag_values(
            editable,
            values={"Arr[2]": 9, "T1.PRE": 500},
            output_path="out.L5X",
            path="base.L5X",
        )

        tags = load(str(editable.root / "out.L5X")).controller_tags
        assert tags["Arr"].to_python() == [0, 0, 9, 0]
        assert tags["T1"].to_python()["PRE"] == 500

    def test_out_of_range_value_writes_nothing(self, editable):
        with pytest.raises(L5XError, match="out of range for USINT"):
            set_tag_values(
                editable,
                values={"consumed_tag": 1, "\\MainProgram.an_unsigned_sint": 100000},
                output_path="out.L5X",
                path=EXAMPLE,
            )
        assert not (editable.root / "out.L5X").exists()

    def test_unknown_operand_is_reported(self, editable):
        with pytest.raises(ItemNotFoundError, match="Tag 'nope' not found"):
            set_tag_values(
                editable, values={"nope": 1}, output_path="out.L5X", path=EXAMPLE
            )

    def test_empty_values_are_refused(self, editable):
        with pytest.raises(L5XError, match="at least one operand"):
            set_tag_values(editable, values={}, output_path="out.L5X", path=EXAMPLE)


class TestUpdateTag:
    @pytest.mark.parametrize(
        "name",
        [
            "consumed_tag",
            "fromNormal_reset",
            "ALLOWABLE_ALARMS",
            "message_tag",
            "testServo",
            "ServosMotionGroup",
        ],
    )
    def test_sets_and_clears_description_on_every_tag_class(self, editable, name):
        update_tag(
            editable,
            name=name,
            description="Documented",
            output_path="set.L5X",
            path=EXAMPLE,
        )
        assert (
            _read(editable, "set.L5X").controller_tags[name].description == "Documented"
        )

        result = update_tag(
            editable, name=name, description="", output_path="clear.L5X", path="set.L5X"
        )
        assert result["changed"] == ["description"]
        assert _read(editable, "clear.L5X").controller_tags[name].description == ""

    def test_sets_operand_comments_and_metadata(self, editable):
        add_tags(
            editable,
            tags=[{"name": "Delay", "data_type": "TIMER"}],
            output_path="base.L5X",
            path=EXAMPLE,
        )

        result = update_tag(
            editable,
            name="Delay",
            operand_comments={".DN": "Motor started"},
            operand_metadata={".PRE": {"engineering_unit": "ms"}},
            output_path="out.L5X",
            path="base.L5X",
        )

        assert result["changed"] == ["comment .DN", "engineering_unit .PRE"]
        tag = _read(editable, "out.L5X").controller_tags["Delay"]
        assert tag.operand_comments[".DN"] == "Motor started"
        assert tag.operand_metadata[".PRE"]["engineering_unit"] == "ms"

    def test_alias_tags_reject_operand_comments(self, editable):
        with pytest.raises(L5XError, match="alias tags have no operand comments"):
            update_tag(
                editable,
                name="an_alias_tag",
                scope="MainProgram",
                operand_comments={".0": "x"},
                output_path="out.L5X",
                path=EXAMPLE,
            )

    def test_requires_something_to_change(self, editable):
        with pytest.raises(L5XError, match="nothing to change"):
            update_tag(
                editable, name="consumed_tag", output_path="out.L5X", path=EXAMPLE
            )

    def test_module_io_tags_are_refused(self, editable):
        with pytest.raises(L5XError, match="not a plain tag name"):
            update_tag(
                editable,
                name="Local:1:I",
                description="x",
                output_path="out.L5X",
                path=EXAMPLE,
            )
