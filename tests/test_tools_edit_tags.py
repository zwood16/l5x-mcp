"""Tests for the tag write tools (add, remove, rename, set values, update)."""

import pytest
from py_l5x import AliasTag, load

from l5x_mcp.registry import DEFAULT_OUTPUT_DIR, ItemNotFoundError, L5XError
from l5x_mcp.tools.definitions import get_spec, rename_program
from l5x_mcp.tools.edit_logic import add_rungs
from l5x_mcp.tools.edit_tags import (
    add_tags,
    remove_tags,
    rename_tag,
    set_tag_values,
    update_tag,
)
from l5x_mcp.tools.search import find_references

OUT_DIR = DEFAULT_OUTPUT_DIR
OUT = OUT_DIR + "/"
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
        tags = _read(editable, OUT + "out.L5X").controller_tags
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
        program = _read(editable, OUT + "out.L5X").programs["SafetyProgram"]
        assert program.tags["ProgFlag"].data_type == "BOOL"

    def test_unknown_data_type_writes_nothing(self, editable):
        with pytest.raises(L5XError, match="unknown data type 'NOTATYPE'"):
            add_tags(
                editable,
                tags=[{"name": "Bad", "data_type": "NOTATYPE"}],
                output_path="out.L5X",
                path=EXAMPLE,
            )
        assert not (editable.root / OUT_DIR / "out.L5X").exists()

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
        assert not (editable.root / OUT_DIR / "out.L5X").exists()

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


class TestAddTagsValidation:
    def _add(self, editable, tags, **kw):
        return add_tags(editable, tags=tags, output_path="out.L5X", path=EXAMPLE, **kw)

    def _refused(self, editable, tags, match, **kw):
        with pytest.raises(L5XError, match=match):
            self._add(editable, tags, **kw)
        assert not (editable.root / OUT_DIR / "out.L5X").exists()

    def test_invalid_metadata_key_is_refused(self, editable):
        self._refused(
            editable,
            [{"name": "T1", "data_type": "DINT", "metadata": {"bad name": "x"}}],
            "not a valid XML attribute name",
        )

    def test_clashing_metadata_key_is_refused(self, editable):
        self._refused(
            editable,
            [{"name": "T1", "data_type": "DINT", "metadata": {"DataType": "NOPE"}}],
            "DataType",
        )

    def test_valid_metadata_is_written(self, editable):
        self._add(
            editable,
            [{"name": "T1", "data_type": "DINT", "metadata": {"OpcUaAccess": "None"}}],
        )
        text = (editable.root / OUT_DIR / "out.L5X").read_text()
        assert '<Tag Name="T1"' in text
        line = next(x for x in text.splitlines() if x.startswith('<Tag Name="T1"'))
        assert 'OpcUaAccess="None"' in line

    def test_alias_keeps_radix_and_external_access(self, editable):
        self._add(
            editable,
            [
                {
                    "name": "Al",
                    "alias_for": "consumed_tag",
                    "radix": "Hex",
                    "external_access": "Read Only",
                    "description": "d",
                }
            ],
        )
        text = (editable.root / OUT_DIR / "out.L5X").read_text()
        line = next(x for x in text.splitlines() if x.startswith('<Tag Name="Al"'))
        assert 'Radix="Hex"' in line
        assert 'ExternalAccess="Read Only"' in line
        tag = _read(editable, OUT + "out.L5X").controller_tags["Al"]
        assert tag.alias_for == "consumed_tag"

    @pytest.mark.parametrize(
        ("extra", "match"),
        [
            ({"constant": True}, "constant"),
            ({"value": 1}, "value"),
            ({"operand_comments": {".1": "x"}}, "operand comments"),
            ({"data_type": "DINT"}, "not both"),
        ],
    )
    def test_alias_rejects_base_only_fields(self, editable, extra, match):
        self._refused(
            editable,
            [{"name": "Al", "alias_for": "consumed_tag", **extra}],
            match,
        )

    def test_alias_to_missing_tag_is_refused(self, editable):
        self._refused(editable, [{"name": "Al", "alias_for": "NoSuchTag"}], "NoSuchTag")

    @pytest.mark.parametrize(
        "target",
        [
            "consumed_tag",
            "consumed_tag.3",
            "ALLOWABLE_ALARMS[2]",
            "Local:1:I.Pt01.Data",
        ],
    )
    def test_alias_to_existing_targets_is_accepted(self, editable, target):
        self._add(editable, [{"name": "Al", "alias_for": target}])
        tag = _read(editable, OUT + "out.L5X").controller_tags["Al"]
        assert tag.alias_for == target

    def test_alias_to_bad_member_is_refused(self, editable):
        self._refused(
            editable,
            [{"name": "Al", "alias_for": "ALLOWABLE_ALARMS[1].nope"}],
            "Member 'nope'",
        )

    def test_program_alias_to_controller_tag_is_accepted(self, editable):
        self._add(
            editable,
            [{"name": "Al", "alias_for": "consumed_tag"}],
            scope="MainProgram",
        )
        program = _read(editable, OUT + "out.L5X").programs["MainProgram"]
        assert program.tags["Al"].alias_for == "consumed_tag"

    def test_program_alias_to_program_tag_is_accepted(self, editable):
        self._add(
            editable,
            [{"name": "Al", "alias_for": "an_input_param"}],
            scope="MainProgram",
        )

    def test_forward_reference_within_one_call_is_accepted(self, editable):
        self._add(
            editable,
            [
                {"name": "Al", "alias_for": "NewBase"},
                {"name": "Al2", "alias_for": "NewArr[1]"},
                {"name": "NewBase", "data_type": "DINT"},
                {"name": "NewArr", "data_type": "DINT", "dimensions": 4},
            ],
        )
        tags = _read(editable, OUT + "out.L5X").controller_tags
        assert tags["Al"].alias_for == "NewBase"

    def test_self_alias_is_refused(self, editable):
        self._refused(editable, [{"name": "Me", "alias_for": "Me"}], "alias cycle")

    def test_alias_cycle_in_one_call_is_refused(self, editable):
        self._refused(
            editable,
            [{"name": "A", "alias_for": "B"}, {"name": "B", "alias_for": "A"}],
            "alias cycle A -> B -> A",
        )

    def test_alias_chain_ending_in_batch_base_tag_is_accepted(self, editable):
        self._add(
            editable,
            [
                {"name": "A", "alias_for": "B"},
                {"name": "B", "alias_for": "C"},
                {"name": "C", "data_type": "DINT"},
            ],
        )

    def test_alias_chain_ending_in_missing_tag_is_refused(self, editable):
        self._refused(
            editable,
            [{"name": "A", "alias_for": "B"}, {"name": "B", "alias_for": "Nope"}],
            "alias 'A': target 'Nope' not found",
        )

    def test_missing_target_error_does_not_list_the_alias(self, editable):
        with pytest.raises(L5XError) as exc:
            self._add(editable, [{"name": "Dangling", "alias_for": "NoSuchTag"}])
        assert "Dangling" not in str(exc.value).replace("alias 'Dangling'", "")

    def test_get_spec_of_an_alias_round_trips(self, editable):
        spec = get_spec(editable, kind="tag", name="an_alias_tag", path=EXAMPLE)
        spec = spec.get("spec", spec)
        spec = {**spec, "name": "CopiedAlias"}
        self._add(editable, [spec], scope="MainProgram")
        program = _read(editable, OUT + "out.L5X").programs["MainProgram"]
        assert program.tags["CopiedAlias"].alias_for == "Local:1:I.Pt01.Data"


class TestRemoveTags:
    def test_removes_the_tag(self, editable):
        result = remove_tags(
            editable, names=["consumed_tag"], output_path="out.L5X", path=EXAMPLE
        )

        assert result["removed"] == [{"name": "consumed_tag", "scope": "controller"}]
        assert "consumed_tag" not in _read(editable, OUT + "out.L5X").controller_tags

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
        program = _read(editable, OUT + "out.L5X").programs["SafetyProgram"]
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
        assert not (editable.root / OUT_DIR / "out.L5X").exists()


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
            path=OUT + "base.L5X",
        )

        assert set(result["set"]) == {
            "consumed_tag",
            "Delay",
            "\\PeriodicProgram.test_dint",
        }
        project = _read(editable, OUT + "out.L5X")
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
            path=OUT + "base.L5X",
        )

        tags = load(str(editable.root / OUT_DIR / "out.L5X")).controller_tags
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
        assert not (editable.root / OUT_DIR / "out.L5X").exists()

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
            _read(editable, OUT + "set.L5X").controller_tags[name].description
            == "Documented"
        )

        result = update_tag(
            editable,
            name=name,
            description="",
            output_path="clear.L5X",
            path=OUT + "set.L5X",
        )
        assert result["changed"] == ["description"]
        assert (
            _read(editable, OUT + "clear.L5X").controller_tags[name].description == ""
        )

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
            path=OUT + "base.L5X",
        )

        assert result["changed"] == ["comment .DN", "engineering_unit .PRE"]
        tag = _read(editable, OUT + "out.L5X").controller_tags["Delay"]
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


class TestTagReferences:
    """Remaining-reference reports of remove_tags and rename_tag."""

    def _build(self, editable):
        """Program tag PX in MainProgram, referenced as \\MainProgram.PX."""
        add_tags(
            editable,
            tags=[{"name": "PX", "data_type": "DINT"}],
            scope="MainProgram",
            output_path="s1.L5X",
            path=EXAMPLE,
        )
        add_rungs(
            editable,
            program="PeriodicProgram",
            routine="main",
            rungs=[{"text": "XIC(\\MainProgram.PX)OTE(test_bool);"}],
            output_path="s2.L5X",
            path=OUT + "s1.L5X",
        )
        return OUT + "s2.L5X"

    def test_program_tag_referenced_from_another_program(self, editable):
        src = self._build(editable)
        renamed = rename_tag(
            editable,
            name="PX",
            new_name="PY",
            scope="MainProgram",
            output_path="r.L5X",
            path=src,
        )
        assert any(
            loc.startswith("PeriodicProgram/main")
            for loc in renamed["references"]["locations"]
        )
        removed = remove_tags(
            editable,
            names=["PX"],
            scope="MainProgram",
            output_path="d.L5X",
            path=src,
        )
        locs = removed["references"]["PX"]["locations"]
        assert any(loc.startswith("PeriodicProgram/main") for loc in locs)

    def test_shadowed_controller_tag_skips_the_shadowing_program(self, editable):
        add_tags(
            editable,
            tags=[{"name": "Shared", "data_type": "DINT"}],
            output_path="a.L5X",
            path=EXAMPLE,
        )
        add_tags(
            editable,
            tags=[{"name": "Shared", "data_type": "DINT"}],
            scope="PeriodicProgram",
            output_path="b.L5X",
            path=OUT + "a.L5X",
        )
        add_rungs(
            editable,
            program="PeriodicProgram",
            routine="main",
            rungs=[{"text": "XIC(Shared)OTE(test_bool);"}],
            output_path="c.L5X",
            path=OUT + "b.L5X",
        )
        add_rungs(
            editable,
            program="MainProgram",
            routine="MainRoutine",
            rungs=[{"text": "XIC(Shared)OTE(an_int_out);"}],
            output_path="d.L5X",
            path=OUT + "c.L5X",
        )
        add_tags(
            editable,
            tags=[
                {"name": "AliasHere", "alias_for": "Shared"},
            ],
            scope="MainProgram",
            output_path="e1.L5X",
            path=OUT + "d.L5X",
        )
        add_tags(
            editable,
            tags=[{"name": "AliasShadowed", "alias_for": "Shared"}],
            scope="PeriodicProgram",
            output_path="e.L5X",
            path=OUT + "e1.L5X",
        )
        result = remove_tags(
            editable,
            names=["Shared"],
            scope="controller",
            output_path="f.L5X",
            path=OUT + "e.L5X",
        )

        refs = result["references"]["Shared"]
        assert any(
            loc.startswith("MainProgram/MainRoutine") for loc in refs["locations"]
        )
        assert not any(loc.startswith("PeriodicProgram/") for loc in refs["locations"])
        assert "MainProgram/AliasHere" in refs["aliases"]
        assert "PeriodicProgram/AliasShadowed" not in refs["aliases"]

    def test_aoi_logic_with_same_named_parameter_is_not_listed(self, editable):
        found = find_references(editable, "onDelay", path=EXAMPLE)
        assert any(m["container_type"] == "aoi" for m in found["matches"])
        add_tags(
            editable,
            tags=[{"name": "onDelay", "data_type": "DINT"}],
            output_path="a.L5X",
            path=EXAMPLE,
        )
        result = rename_tag(
            editable,
            name="onDelay",
            new_name="onDelay2",
            output_path="b.L5X",
            path=OUT + "a.L5X",
        )
        refs = result.get("references") or {}
        aoi_names = {n.lower() for n in _read(editable, EXAMPLE).aois}
        assert aoi_names
        for loc in refs.get("locations", []):
            assert loc.split("/")[0].lower() not in aoi_names

    def test_alias_to_removed_controller_tag_is_listed(self, editable):
        add_tags(
            editable,
            tags=[{"name": "AliasCt", "alias_for": "consumed_tag"}],
            output_path="a.L5X",
            path=EXAMPLE,
        )
        result = remove_tags(
            editable,
            names=["consumed_tag"],
            output_path="b.L5X",
            path=OUT + "a.L5X",
        )
        assert "controller/AliasCt" in result["references"]["consumed_tag"]["aliases"]

    def test_alias_with_program_prefix_is_listed_on_program_tag_removal(self, editable):
        add_tags(
            editable,
            tags=[{"name": "PX", "data_type": "DINT"}],
            scope="MainProgram",
            output_path="a.L5X",
            path=EXAMPLE,
        )
        add_tags(
            editable,
            tags=[{"name": "AliasPx", "alias_for": "\\MainProgram.PX"}],
            scope="PeriodicProgram",
            output_path="b.L5X",
            path=OUT + "a.L5X",
        )
        result = remove_tags(
            editable,
            names=["PX"],
            scope="MainProgram",
            output_path="c.L5X",
            path=OUT + "b.L5X",
        )
        assert result["references"]["PX"]["aliases"] == ["PeriodicProgram/AliasPx"]

    def test_rename_program_lists_aliases_using_the_old_name(self, editable):
        add_tags(
            editable,
            tags=[{"name": "PX", "data_type": "DINT"}],
            scope="MainProgram",
            output_path="a.L5X",
            path=EXAMPLE,
        )
        add_tags(
            editable,
            tags=[{"name": "AliasPx", "alias_for": "\\MainProgram.PX"}],
            output_path="b.L5X",
            path=OUT + "a.L5X",
        )
        result = rename_program(
            editable,
            name="MainProgram",
            new_name="NewMain",
            output_path="c.L5X",
            path=OUT + "b.L5X",
        )
        assert result["references"]["aliases"] == ["controller/AliasPx"]


class TestAliasWarnings:
    def test_member_of_tag_without_value_tree_warns(self, editable):
        result = add_tags(
            editable,
            tags=[{"name": "AliasMsg", "alias_for": "message_tag.DN"}],
            output_path="a.L5X",
            path=EXAMPLE,
        )
        assert len(result["warnings"]) == 1
        assert "MESSAGE tag 'message_tag'" in result["warnings"][0]
        assert "'message_tag.DN'" in result["warnings"][0]

    def test_verified_member_has_no_warnings_key(self, editable):
        result = add_tags(
            editable,
            tags=[{"name": "AliasBit", "alias_for": "consumed_tag.3"}],
            output_path="a.L5X",
            path=EXAMPLE,
        )
        assert "warnings" not in result
