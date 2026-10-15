"""Tests for tags tool module."""

import json

import pytest

from l5x_mcp.registry import ItemNotFoundError, L5XError
from l5x_mcp.tools.tags import (
    _flatten_multi_dim_index,
    _parse_operand_path,
    get_tag,
    list_tags,
)


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


class TestParseOperandPath:
    """Tests for _parse_operand_path function."""

    def test_parse_simple_member_path(self):
        """Test parsing a simple member access path."""
        segments = _parse_operand_path("a_udt_instance.a_nested_UDT.bool1")
        assert segments == ["a_udt_instance", "a_nested_UDT", "bool1"]

    def test_parse_array_index(self):
        """Test parsing array index."""
        segments = _parse_operand_path("ALLOWABLE_ALARMS[3]")
        assert segments == ["ALLOWABLE_ALARMS", 3]

    def test_parse_array_index_with_member(self):
        """Test parsing array index followed by member."""
        segments = _parse_operand_path("ALLOWABLE_ALARMS[3].LEN")
        assert segments == ["ALLOWABLE_ALARMS", 3, "LEN"]

    def test_parse_bit_access(self):
        """Test parsing bit access on scalar."""
        segments = _parse_operand_path("a_dint.2")
        assert segments == ["a_dint", 2]

    def test_parse_multi_dimensional_index(self):
        """Test parsing multi-dimensional array index."""
        segments = _parse_operand_path("arr[1,2,3]")
        assert segments == ["arr", (1, 2, 3)]

    def test_parse_member_after_multi_dim(self):
        """Test parsing member access after multi-dim index."""
        segments = _parse_operand_path("arr[1,2].member")
        assert segments == ["arr", (1, 2), "member"]

    def test_parse_invalid_path_empty(self):
        """Test that empty path raises error."""
        with pytest.raises(L5XError):
            _parse_operand_path("")

    def test_parse_invalid_path_bad_name(self):
        """Test that paths with invalid syntax raise error."""
        # A path starting with invalid characters
        with pytest.raises(L5XError):
            _parse_operand_path("@invalid")

    def test_parse_invalid_path_unclosed_bracket(self):
        """Test that unclosed bracket raises error."""
        with pytest.raises(L5XError):
            _parse_operand_path("arr[1")

    def test_parse_invalid_path_bad_index(self):
        """Test that non-integer index raises error."""
        with pytest.raises(L5XError):
            _parse_operand_path("arr[abc]")


class TestFlattenMultiDimIndex:
    """Tests for _flatten_multi_dim_index function."""

    def test_flatten_2d_index(self):
        """Test flattening 2D index (row-major)."""
        # 2x3 array, [0,1] should be flat 1, [1,0] should be flat 3
        flat = _flatten_multi_dim_index((0, 1), [2, 3])
        assert flat == 1

        flat = _flatten_multi_dim_index((1, 0), [2, 3])
        assert flat == 3

    def test_flatten_3d_index(self):
        """Test flattening 3D index."""
        # 2x3x4 array
        flat = _flatten_multi_dim_index((0, 0, 0), [2, 3, 4])
        assert flat == 0

        flat = _flatten_multi_dim_index((1, 2, 3), [2, 3, 4])
        assert flat == 1 * 12 + 2 * 4 + 3

    def test_flatten_index_out_of_bounds(self):
        """Test that out-of-bounds index raises error."""
        with pytest.raises(L5XError):
            _flatten_multi_dim_index((2, 0), [2, 3])

    def test_flatten_dimension_mismatch(self):
        """Test that dimension mismatch raises error."""
        with pytest.raises(L5XError):
            _flatten_multi_dim_index((1, 2, 3), [2, 3])


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
            result["node"]["kind"] == "structure"
        )  # robotAlarmCode array elements are structures

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

    def test_get_tag_array_element_has_members(self, registry):
        """Test that array element is structure with accessible members."""
        result = get_tag(registry, "ALLOWABLE_ALARMS[0]", path="example.L5X")
        assert result["node"]["kind"] == "structure"
        # The structure should have members
        if "members" in result["node"]:
            assert len(result["node"]["members"]) > 0

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
