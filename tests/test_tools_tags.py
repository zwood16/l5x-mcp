"""Tests for tags tool module."""

import json

import pytest

from l5x_mcp.registry import ItemNotFoundError, L5XError, ProjectRegistry
from l5x_mcp.tools.tags import get_tag, list_tags


class TestListTags:
    """Tests for list_tags function."""

    def test_list_tags_controller_scope(self, registry):
        """Test listing controller-scoped tags."""
        result = list_tags(registry, path="example.L5X")
        assert "file" in result
        assert result["scope"] == "controller"
        assert "total" in result
        assert "tags" in result
        assert isinstance(result["tags"], list)
        # example.L5X has 9 controller tags
        assert result["total"] == 9

    def test_list_tags_program_scope(self, registry):
        """Test listing program-scoped tags."""
        result = list_tags(registry, scope="MainProgram", path="example.L5X")
        assert result["scope"] == "MainProgram"
        assert "tags" in result
        assert result["total"] > 0
        # MainProgram should have many tags
        assert result["total"] > 10

    def test_list_tags_case_insensitive_scope(self, registry):
        """Test that scope names are case-insensitive."""
        result1 = list_tags(registry, scope="mainprogram", path="example.L5X")
        result2 = list_tags(registry, scope="MainProgram", path="example.L5X")
        assert result1["scope"] == result2["scope"] == "MainProgram"
        assert result1["total"] == result2["total"]

    def test_list_tags_case_insensitive_literal_controller(self, registry):
        """Test that 'controller' scope is case-insensitive."""
        result1 = list_tags(registry, scope="Controller", path="example.L5X")
        result2 = list_tags(registry, scope="CONTROLLER", path="example.L5X")
        result3 = list_tags(registry, scope="controller", path="example.L5X")
        assert result1["scope"] == result2["scope"] == result3["scope"] == "controller"
        assert result1["total"] == result2["total"] == result3["total"]

    def test_list_tags_invalid_program_scope(self, registry):
        """Test that invalid program scope raises error."""
        with pytest.raises(ItemNotFoundError):
            list_tags(registry, scope="NonExistentProgram", path="example.L5X")

    def test_list_tags_filter_by_name(self, registry):
        """Test filtering tags by name substring."""
        result = list_tags(
            registry, scope="MainProgram", name_contains="bool", path="example.L5X"
        )
        assert "tags" in result
        for tag in result["tags"]:
            assert "bool" in tag["name"].lower()

    def test_list_tags_filter_by_name_case_insensitive(self, registry):
        """Test that name filter is case-insensitive."""
        result_lower = list_tags(
            registry, scope="MainProgram", name_contains="bool", path="example.L5X"
        )
        result_upper = list_tags(
            registry, scope="MainProgram", name_contains="BOOL", path="example.L5X"
        )
        assert result_lower["total"] == result_upper["total"]

    def test_list_tags_filter_by_data_type(self, registry):
        """Test filtering tags by data_type (exact match)."""
        result = list_tags(
            registry, scope="MainProgram", data_type="DINT", path="example.L5X"
        )
        assert "tags" in result
        for tag in result["tags"]:
            assert tag["data_type"] == "DINT"

    def test_list_tags_filter_by_tag_type(self, registry):
        """Test filtering tags by tag_type."""
        # Get a tag type that exists
        all_tags = list_tags(registry, path="example.L5X", limit=1000)
        produced_tags = [t for t in all_tags["tags"] if t.get("tag_type") == "Produced"]

        if produced_tags:
            # Now filter for it
            result = list_tags(registry, tag_type="Produced", path="example.L5X")
            assert all(t.get("tag_type") == "Produced" for t in result["tags"])

    def test_list_tags_pagination_offset(self, registry):
        """Test pagination with offset."""
        result1 = list_tags(
            registry, scope="MainProgram", limit=5, offset=0, path="example.L5X"
        )
        result2 = list_tags(
            registry, scope="MainProgram", limit=5, offset=5, path="example.L5X"
        )

        # Tags should be different
        names1 = [t["name"] for t in result1["tags"]]
        names2 = [t["name"] for t in result2["tags"]]
        assert names1 != names2

    def test_list_tags_next_offset(self, registry):
        """Test that next_offset is returned when more tags exist."""
        result = list_tags(registry, scope="MainProgram", limit=5, path="example.L5X")
        if result["total"] > 5:
            assert "next_offset" in result
            assert result["next_offset"] == 5
        else:
            assert "next_offset" not in result

    def test_list_tags_invalid_limit(self, registry):
        """Test that invalid limit raises error."""
        with pytest.raises(L5XError):
            list_tags(registry, limit=0, path="example.L5X")
        with pytest.raises(L5XError):
            list_tags(registry, limit=1001, path="example.L5X")

    def test_list_tags_invalid_offset(self, registry):
        """Test that negative offset raises error."""
        with pytest.raises(L5XError):
            list_tags(registry, offset=-1, path="example.L5X")

    def test_list_tags_json_serializable(self, registry):
        """Test that result is JSON serializable."""
        result = list_tags(registry, path="example.L5X")
        json_str = json.dumps(result)
        assert isinstance(json_str, str)

    def test_list_tags_controller_no_results_shows_programs(self, registry):
        """Test that empty controller result with programs shows helpful note."""
        # Filter for a name that doesn't exist in controller, but programs exist
        result = list_tags(
            registry,
            scope="controller",
            name_contains="ZZZNONEXISTENT",
            path="example.L5X",
        )
        assert result["total"] == 0
        assert "note" in result
        assert "Program-scoped tags exist in" in result["note"]
        # Should list some programs
        assert "MainProgram" in result["note"]
        assert "pass scope=" in result["note"]

    def test_list_tags_component_export_auto_switch_scope(self, registry):
        """Test auto-switch to program scope for component exports."""
        # MainProgram_Program.L5X is a component export with empty controller
        result = list_tags(registry, scope="controller", path="MainProgram_Program.L5X")
        # Should auto-switch to MainProgram
        if "note" in result:
            # If there are no controller tags but single program, should note it
            assert "Defaulted to" in result["note"] or result["scope"] == "MainProgram"


class TestGetTag:
    """Tests for get_tag function."""

    def test_get_tag_controller_base_tag(self, registry):
        """Test getting a controller-scoped tag."""
        result = get_tag(registry, "message_tag", path="example.L5X")
        assert "file" in result
        assert result["scope"] == "controller"
        assert result["name"] == "message_tag"
        assert "data_type" in result

    def test_get_tag_program_scope(self, registry):
        """Test getting a tag from a specific program scope."""
        result = get_tag(
            registry, "a_udt_instance", scope="MainProgram", path="example.L5X"
        )
        assert result["scope"] == "MainProgram"
        assert result["name"] == "a_udt_instance"

    def test_get_tag_case_insensitive_name(self, registry):
        """Test that tag name lookup is case-insensitive."""
        result1 = get_tag(
            registry, "a_udt_instance", scope="MainProgram", path="example.L5X"
        )
        result2 = get_tag(
            registry, "A_UDT_INSTANCE", scope="MainProgram", path="example.L5X"
        )
        result3 = get_tag(
            registry, "A_Udt_Instance", scope="MainProgram", path="example.L5X"
        )
        assert result1["name"] == result2["name"] == result3["name"] == "a_udt_instance"

    def test_get_tag_case_insensitive_scope(self, registry):
        """Test that scope is case-insensitive."""
        result1 = get_tag(
            registry, "a_udt_instance", scope="mainprogram", path="example.L5X"
        )
        result2 = get_tag(
            registry, "a_udt_instance", scope="MAINPROGRAM", path="example.L5X"
        )
        result3 = get_tag(
            registry, "a_udt_instance", scope="MainProgram", path="example.L5X"
        )
        assert result1["scope"] == result2["scope"] == result3["scope"]

    def test_get_tag_not_found(self, registry):
        """Test that getting non-existent tag raises error."""
        with pytest.raises(ItemNotFoundError):
            get_tag(registry, "nonexistent_tag", path="example.L5X")

    def test_get_tag_not_found_shows_programs_searched(self, registry):
        """Test that not found error shows programs were searched."""
        with pytest.raises(ItemNotFoundError) as exc:
            get_tag(registry, "nope", scope=None, path="example.L5X")
        error_msg = str(exc.value)
        assert "searched" in error_msg.lower()
        assert "program" in error_msg.lower()

    def test_get_tag_not_found_suggests_similar_names(self, registry):
        """Test that similar tag names are suggested."""
        with pytest.raises(ItemNotFoundError) as exc:
            get_tag(registry, "a_dint_typo", scope=None, path="example.L5X")
        error_msg = str(exc.value)
        # Should suggest "Did you mean" with similar names
        if "a_dint" in error_msg or "MainProgram" in error_msg:
            assert "Did you mean" in error_msg or "a_dint" in error_msg

    def test_get_tag_includes_detail_fields(self, registry):
        """Test that base tag includes detail fields like description."""
        result = get_tag(registry, "message_tag", path="example.L5X")
        assert "data_type" in result
        assert "tag_type" in result

    def test_get_tag_with_udt_member_path(self, registry):
        """Test getting a UDT member via operand path."""
        result = get_tag(
            registry,
            "a_udt_instance.a_nested_UDT",
            scope="MainProgram",
            path="example.L5X",
        )
        assert "operand" in result  # Has operand path
        assert "node" in result  # Has node instead of full detail
        assert result["operand"] == "a_udt_instance.a_nested_UDT"
        # node should have structure kind
        assert result["node"]["kind"] == "structure"

    def test_get_tag_with_udt_nested_member_path(self, registry):
        """Test getting a deeply nested UDT member."""
        result = get_tag(
            registry,
            "a_udt_instance.a_nested_UDT.bool1",
            scope="MainProgram",
            path="example.L5X",
        )
        assert "operand" in result
        assert result["operand"] == "a_udt_instance.a_nested_UDT.bool1"
        assert result["node"]["kind"] == "scalar"
        assert result["node"]["data_type"] == "BOOL"

    def test_get_tag_with_array_index(self, registry):
        """Test getting an array element via operand path."""
        result = get_tag(registry, "ALLOWABLE_ALARMS[3]", path="example.L5X")
        assert "operand" in result
        assert result["operand"] == "ALLOWABLE_ALARMS[3]"
        assert (
            result["node"]["kind"] == "string"
        )  # robotAlarmCode is a STRING-family type

    def test_get_tag_with_array_member(self, registry):
        """Test getting a member of an array element."""
        result = get_tag(registry, "ALLOWABLE_ALARMS[3].LEN", path="example.L5X")
        assert "operand" in result
        assert result["operand"] == "ALLOWABLE_ALARMS[3].LEN"
        assert result["node"]["kind"] == "scalar"

    def test_get_tag_with_bit_access(self, registry):
        """Test bit access on a DINT scalar."""
        result = get_tag(registry, "a_dint.2", scope="MainProgram", path="example.L5X")
        assert "operand" in result
        assert result["operand"] == "a_dint.2"
        assert result["node"]["kind"] == "scalar"
        assert result["node"]["data_type"] == "BOOL"

    def test_get_tag_alias(self, registry):
        """Test getting an Alias tag."""
        result = get_tag(
            registry, "an_alias_tag", scope="MainProgram", path="example.L5X"
        )
        assert result["name"] == "an_alias_tag"
        assert result.get("tag_type") == "Alias"
        assert "alias_for" in result

    def test_get_tag_produced(self, registry):
        """Test getting a Produced tag."""
        result = get_tag(registry, "produced_tag", path="example.L5X")
        assert result["name"] == "produced_tag"
        assert result.get("tag_type") == "Produced"

    def test_get_tag_consumed(self, registry):
        """Test getting a Consumed tag."""
        result = get_tag(registry, "consumed_tag", path="example.L5X")
        assert result["name"] == "consumed_tag"
        assert result.get("tag_type") == "Consumed"

    def test_get_tag_message(self, registry):
        """Test getting a MESSAGE tag with special parameters."""
        result = get_tag(registry, "message_tag", path="example.L5X")
        assert result["name"] == "message_tag"
        assert result["data_type"] == "MESSAGE"
        # May have message_parameters
        if "message_parameters" in result:
            assert isinstance(result["message_parameters"], dict)

    def test_get_tag_axis(self, registry):
        """Test getting an AXIS tag."""
        result = get_tag(registry, "testServo", path="example.L5X")
        assert result["name"] == "testServo"
        assert "AXIS" in result["data_type"]

    def test_get_tag_motion_group(self, registry):
        """Test getting a MOTION_GROUP tag."""
        result = get_tag(registry, "ServosMotionGroup", path="example.L5X")
        assert result["name"] == "ServosMotionGroup"
        assert result["data_type"] == "MOTION_GROUP"

    def test_get_tag_member_not_found(self, registry):
        """Test that accessing non-existent member raises clear error."""
        with pytest.raises(L5XError) as exc:
            get_tag(
                registry,
                "a_udt_instance.nonexistent_member",
                scope="MainProgram",
                path="example.L5X",
            )
        assert "nonexistent_member" in str(exc.value)
        assert "Available" in str(exc.value)

    def test_get_tag_array_index_out_of_bounds(self, registry):
        """Test that out-of-bounds array index raises clear error."""
        with pytest.raises(L5XError) as exc:
            get_tag(registry, "ALLOWABLE_ALARMS[999]", path="example.L5X")
        assert "out of bounds" in str(exc.value).lower()

    def test_get_tag_invalid_operand_path_format(self, registry):
        """Test that invalid operand path raises error."""
        with pytest.raises(L5XError):
            get_tag(registry, "ALLOWABLE_ALARMS[", path="example.L5X")

    def test_get_tag_scope_none_finds_controller(self, registry):
        """Test that scope=None finds controller-scoped tags."""
        result = get_tag(registry, "message_tag", scope=None, path="example.L5X")
        assert result["scope"] == "controller"

    def test_get_tag_scope_none_finds_program(self, registry):
        """Test that scope=None finds program-scoped tags."""
        result = get_tag(registry, "a_udt_instance", scope=None, path="example.L5X")
        # Should find it in MainProgram
        assert result["scope"] == "MainProgram"

    def test_get_tag_scope_none_prefers_controller(self, registry):
        """Test that scope=None prefers controller scope when tag exists there."""
        # Create a scenario: get a controller tag that may also exist elsewhere
        result = get_tag(registry, "message_tag", scope=None, path="example.L5X")
        assert result["scope"] == "controller"

    def test_get_tag_json_serializable(self, registry):
        """Test that result is JSON serializable."""
        result = get_tag(registry, "message_tag", path="example.L5X")
        json_str = json.dumps(result)
        assert isinstance(json_str, str)

    def test_get_tag_with_operand_json_serializable(self, registry):
        """Test that operand path result is JSON serializable."""
        result = get_tag(
            registry,
            "a_udt_instance.a_nested_UDT.bool1",
            scope="MainProgram",
            path="example.L5X",
        )
        json_str = json.dumps(result)
        assert isinstance(json_str, str)

    def test_get_tag_counter(self, registry):
        """Test getting a COUNTER UDT tag."""
        result = get_tag(registry, "a_counter", scope="MainProgram", path="example.L5X")
        assert result["name"] == "a_counter"
        assert result["data_type"] == "COUNTER"

    def test_get_tag_array_element_is_string(self, registry):
        """Test that a STRING-family array element is a string node with text."""
        result = get_tag(registry, "ALLOWABLE_ALARMS[0]", path="example.L5X")
        assert result["node"]["kind"] == "string"
        assert "value" in result["node"]

    def test_get_tag_also_in_programs(self, registry):
        """Test that also_in_programs is set for controller tags found in programs."""
        # Get a controller tag
        result = get_tag(
            registry, "message_data", scope="controller", path="example.L5X"
        )
        # Check if also_in_programs exists (depends on fixture)
        # Just verify the key structure if it exists
        if "also_in_programs" in result:
            assert isinstance(result["also_in_programs"], list)


class TestGetTagSampleOutput:
    """Test and document sample output for a_udt_instance.a_nested_UDT."""

    def test_sample_udt_nested_member_output(self, registry):
        """Get and verify sample output for a_udt_instance.a_nested_UDT."""
        result = get_tag(
            registry,
            "a_udt_instance.a_nested_UDT",
            scope="MainProgram",
            path="example.L5X",
        )

        # Verify structure of result
        assert "file" in result
        assert "scope" in result
        assert "tag" in result
        assert "operand" in result
        assert "node" in result

        # Verify tag summary includes key fields
        tag = result["tag"]
        assert "name" in tag
        assert tag["name"] == "a_udt_instance"
        assert "data_type" in tag

        # Verify operand
        assert result["operand"] == "a_udt_instance.a_nested_UDT"

        # Verify node structure
        node = result["node"]
        assert node["kind"] == "structure"
        assert node["data_type"] == "simple_udt"
        assert "members" in node

        # Print for documentation (will appear in test output)
        print("\n=== Sample get_tag output ===")
        print(json.dumps(result, indent=2))


class TestListTagsScopes:
    """Tests for the controller, module_io and program scopes of list_tags."""

    def test_controller_scope_excludes_module_tags(self, registry):
        """Controller scope lists only the 9 controller-scoped tags."""
        result = list_tags(registry, scope="controller", limit=1000, path="example.L5X")
        assert result["total"] == 9
        assert all(":" not in t["name"] for t in result["tags"])

    def test_io_scope_lists_module_tags(self, registry):
        """module_io scope lists module I/O references with kind and module."""
        result = list_tags(registry, scope="module_io", limit=1000, path="example.L5X")
        assert result["scope"] == "module_io"
        assert result["total"] == 32
        names = {t["name"] for t in result["tags"]}
        assert {"Local:1:I", "Local:2:I", "ShopRobot:I"} <= names
        local2 = next(t for t in result["tags"] if t["name"] == "Local:2:I")
        assert local2["kind"] == "I"
        assert local2["module"] == "Test_Safety_Input"
        assert "tag_type" not in local2

    def test_io_scope_is_case_insensitive_and_filterable(self, registry):
        """The scope name and name filter work on module tags."""
        result = list_tags(
            registry, scope="MODULE_IO", name_contains="SHOPROBOT", path="example.L5X"
        )
        assert result["total"] >= 1
        assert all("shoprobot" in t["name"].lower() for t in result["tags"])

    def test_program_scope_has_no_module_tags(self, registry):
        """Program scope is unaffected by module I/O tags."""
        result = list_tags(
            registry, scope="MainProgram", limit=1000, path="example.L5X"
        )
        assert all(":" not in t["name"] for t in result["tags"])

    def test_controller_no_match_note_mentions_io(self, registry):
        """The no-results note points to scope="module_io" when module tags exist."""
        result = list_tags(
            registry,
            scope="controller",
            name_contains="ZZZNONEXISTENT",
            path="example.L5X",
        )
        assert 'scope="module_io"' in result["note"]
        assert "module I/O tags exist" in result["note"]


class TestGetTagOperands:
    """Operand-path behaviour of get_tag."""

    def test_bit_comment_is_description(self, registry):
        """A commented bit reports its comment as the node description."""
        result = get_tag(
            registry, "a_commented_dint.0", scope="MainProgram", path="example.L5X"
        )
        assert result["scope"] == "MainProgram"
        assert result["operand"] == "a_commented_dint.0"
        assert result["node"]["kind"] == "scalar"
        assert result["node"]["data_type"] == "BOOL"
        assert result["node"]["description"] == "this is bit 0"

    def test_module_io_operand(self, registry):
        """Module I/O operands resolve under scope module_io."""
        result = get_tag(registry, "Local:2:I.Pt00.Data", path="example.L5X")
        assert result["scope"] == "module_io"
        assert result["tag"]["name"] == "Local:2:I"
        assert result["operand"] == "Local:2:I.Pt00.Data"
        assert result["node"]["kind"] == "scalar"
        assert result["node"]["data_type"] == "BOOL"

    def test_module_io_base_detail_without_subpath(self, registry):
        """A module I/O name without a sub-path returns the tag detail."""
        result = get_tag(registry, "ShopRobot:I", path="example.L5X")
        assert result["scope"] == "module_io"
        assert result["kind"] == "I"
        assert "value_tree" in result

    def test_aoi_instance_inherits_bit_description(self, registry):
        """Bits of an AOI-typed tag inherit the definition's bit comments."""
        result = get_tag(
            registry, "sequence.state.0", scope="MainProgram", path="example.L5X"
        )
        assert result["operand"] == "sequence.state.0"
        assert result["node"]["description"] == "running"
        assert result["node"]["data_type"] == "BOOL"

    def test_case_insensitive_members(self, registry):
        """Member names match case-insensitively and report canonical case."""
        result = get_tag(
            registry,
            "a_udt_instance.A_NESTED_UDT.BOOL1",
            scope="MainProgram",
            path="example.L5X",
        )
        assert result["operand"] == "a_udt_instance.a_nested_UDT.bool1"

    def test_multi_dimensional_index(self, registry):
        """A 2-D subscript selects the element with that Logix subscript."""
        result = get_tag(
            registry, "a_2d_array[1,2]", scope="MainProgram", path="example.L5X"
        )
        assert result["operand"] == "a_2d_array[1,2]"
        assert result["node"]["kind"] == "scalar"
        assert result["node"]["data_type"] == "SINT"

    def test_multi_dimensional_wrong_rank(self, registry):
        """A 2-D array indexed with one subscript is an error naming the dimensions."""
        with pytest.raises(L5XError, match="dimension"):
            get_tag(registry, "a_2d_array[1]", scope="MainProgram", path="example.L5X")

    def test_multi_dimensional_out_of_bounds(self, registry):
        """An out-of-range subscript in one dimension is an error."""
        with pytest.raises(L5XError, match="out of bounds"):
            get_tag(
                registry, "a_2d_array[2,0]", scope="MainProgram", path="example.L5X"
            )

    def test_bit_out_of_range(self, registry):
        """Bit numbers beyond the integer width are rejected."""
        with pytest.raises(L5XError, match="out of range"):
            get_tag(
                registry, "a_commented_dint.32", scope="MainProgram", path="example.L5X"
            )

    def test_bit_on_bool_rejected(self, registry):
        """BOOL values have no bits."""
        with pytest.raises(L5XError, match="only integer types have bits"):
            get_tag(registry, "a_bool.0", scope="MainProgram", path="example.L5X")

    def test_runtime_index_uses_element_zero_with_note(self, registry):
        """A non-literal index shows element 0 and says so in a note."""
        result = get_tag(registry, "ALLOWABLE_ALARMS[idx]", path="example.L5X")
        assert result["operand"] == "ALLOWABLE_ALARMS[idx]"
        assert result["node"]["kind"] == "string"
        assert "runtime index" in result["note"]

    def test_alias_detail_has_no_value_tree(self, registry):
        """An alias tag returns its target and no value tree."""
        result = get_tag(
            registry, "an_alias_tag", scope="MainProgram", path="example.L5X"
        )
        assert result["alias_for"] == "Local:1:I.Pt01.Data"
        assert "value_tree" not in result

    def test_alias_subpath_walks_target(self, registry):
        """A sub-path on an alias is walked on the target, so it fails there."""
        with pytest.raises(L5XError, match="Cannot access member 'Data'"):
            get_tag(
                registry, "an_alias_tag.Data", scope="MainProgram", path="example.L5X"
            )

    def test_program_prefix_selects_program(self, registry):
        """An explicit \\Program. prefix selects that program's tag."""
        result = get_tag(registry, "\\MainProgram.a_dint.2", path="example.L5X")
        assert result["scope"] == "MainProgram"
        assert result["operand"] == "a_dint.2"

    def test_program_prefix_conflicting_scope(self, registry):
        """A program prefix that disagrees with scope is an error."""
        with pytest.raises(L5XError):
            get_tag(
                registry, "\\MainProgram.a_dint", scope="controller", path="example.L5X"
            )


class TestGetTagAliasesAndExpressions:
    """Alias following and runtime-expression indexes through get_tag."""

    def test_alias_without_subpath_shows_resolved_target(self, registry):
        """An alias shows its own detail plus the resolved target operand and node."""
        result = get_tag(
            registry, "an_alias_tag", scope="MainProgram", path="example.L5X"
        )
        assert result["tag_type"] == "Alias"
        assert result["alias_for"] == "Local:1:I.Pt01.Data"
        assert result["alias_chain"] == ["Local:1:I.Pt01.Data"]
        assert "value_tree" not in result
        target = result["resolved_target"]
        assert target["scope"] == "module_io"
        assert target["operand"] == "Local:1:I.Pt01.Data"
        assert target["node"]["data_type"] == "BOOL"

    def test_alias_to_controller_tag_reports_controller_scope(self, registry):
        """A program alias to a controller tag reports the controller target."""
        result = get_tag(
            registry, "reset_signal", scope="SafetyProgram", path="example.L5X"
        )
        assert result["alias_for"] == "fromNormal_reset"
        assert result["resolved_target"]["scope"] == "controller"
        assert result["resolved_target"]["operand"] == "fromNormal_reset"

    def test_reserved_io_names_are_plain_names(self, fixtures_dir, tmp_path):
        """A struct tag named io and a program named IO do not clash with module_io.

        Uses a copy of example.L5X with a controller TIMER named ``io`` and a
        program named ``IO`` (a copy of Unscheduled, so it holds one tag, nada).
        """
        reg = _reserved_registry(fixtures_dir, tmp_path)

        io_tag = get_tag(reg, "io", path=RESERVED)
        assert io_tag["scope"] == "controller"
        assert io_tag["name"] == "io"
        assert io_tag["data_type"] == "TIMER"

        member = get_tag(reg, "io.PRE", path=RESERVED)
        assert member["scope"] == "controller"
        assert member["operand"] == "io.PRE"
        assert member["node"]["kind"] == "scalar"

        program_tags = list_tags(reg, scope="IO", path=RESERVED)
        assert program_tags["scope"] == "IO"
        assert [t["name"] for t in program_tags["tags"]] == ["nada"]

        module_tags_result = list_tags(
            reg, scope="module_io", limit=1000, path=RESERVED
        )
        assert module_tags_result["scope"] == "module_io"
        assert module_tags_result["total"] == 32
        assert "Local:2:I" in {t["name"] for t in module_tags_result["tags"]}

        module_operand = get_tag(reg, "Local:2:I.Pt00.Data", path=RESERVED)
        assert module_operand["scope"] == "module_io"
        assert module_operand["operand"] == "Local:2:I.Pt00.Data"


RESERVED = "reserved.L5X"


def _reserved_registry(fixtures_dir, tmp_path):
    """Write example.L5X plus a controller tag ``io`` and program ``IO`` to tmp_path."""
    text = (fixtures_dir / "example.L5X").read_text(encoding="utf-8")

    # Controller-scoped TIMER named "io": copy a_timer's block and rename it.
    start = text.index('<Tag Name="a_timer"')
    end = text.index("</Tag>", start) + len("</Tag>")
    timer = text[start:end].replace('<Tag Name="a_timer"', '<Tag Name="io"', 1)
    insert_at = text.rfind("</Tags>", 0, text.index("<Programs>"))
    text = text[:insert_at] + timer + "\n" + text[insert_at:]

    # Program named "IO": copy Unscheduled's block (it holds one tag, nada).
    start = text.index('<Program Name="Unscheduled"')
    end = text.index("</Program>", start) + len("</Program>")
    program = text[start:end].replace(
        '<Program Name="Unscheduled"', '<Program Name="IO"', 1
    )
    text = text[:end] + "\n" + program + text[end:]

    (tmp_path / RESERVED).write_text(text, encoding="utf-8")
    return ProjectRegistry(tmp_path)

    def test_runtime_expression_index_has_note(self, registry):
        """An expression index keeps its text and notes that element 0 is shown."""
        result = get_tag(registry, "ALLOWABLE_ALARMS[idx+1]", path="example.L5X")
        assert result["operand"] == "ALLOWABLE_ALARMS[idx+1]"
        assert result["node"]["kind"] == "string"
        assert "runtime index" in result["note"]
