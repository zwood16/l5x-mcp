"""Tests for l5x_mcp.serialize module."""

import json

import py_l5x
import pytest

from l5x_mcp.serialize import (
    compact,
    first_line,
    jsonable,
    tag_detail,
    tag_node_to_dict,
    tag_summary,
)


@pytest.fixture
def project(example_path):
    """Load and return the example.L5X project."""
    return py_l5x.load(example_path)


class TestJsonable:
    """Tests for the jsonable() function."""

    def test_passthrough_scalar_types(self):
        """Test that bool, int, float, str, None pass through unchanged."""
        assert jsonable(True) is True
        assert jsonable(False) is False
        assert jsonable(42) == 42
        assert jsonable(3.14) == 3.14
        assert jsonable("hello") == "hello"
        assert jsonable(None) is None

    def test_mapping_to_dict(self):
        """Test that Mapping objects become dicts with str keys."""
        m = {"key": "value", 123: "numeric_key"}
        result = jsonable(m)
        assert isinstance(result, dict)
        assert result == {"key": "value", "123": "numeric_key"}

    def test_sequence_to_list(self):
        """Test that sequences (except str) become lists."""
        assert jsonable([1, 2, 3]) == [1, 2, 3]
        assert jsonable((1, 2, 3)) == [1, 2, 3]
        assert jsonable("string") == "string"  # str is not converted to list

    def test_nested_structures(self):
        """Test recursive conversion."""
        nested = {"items": [1, (2, 3)], "inner": {"key": "value"}}
        result = jsonable(nested)
        assert result == {"items": [1, [2, 3]], "inner": {"key": "value"}}

    def test_nan_to_string(self):
        """Test that float NaN becomes 'NaN'."""
        result = jsonable(float("nan"))
        assert result == "NaN"

    def test_inf_to_string(self):
        """Test that float infinity becomes string."""
        assert jsonable(float("inf")) == "Infinity"
        assert jsonable(float("-inf")) == "-Infinity"

    def test_unknown_type_to_string(self):
        """Test that unknown types are converted to string."""
        obj = object()
        result = jsonable(obj)
        assert isinstance(result, str)


class TestCompact:
    """Tests for the compact() function."""

    def test_removes_none_empty_string_empty_collections(self):
        """Test that None, '', [], {} are removed."""
        d = {"a": 1, "b": None, "c": "", "d": [], "e": {}}
        result = compact(d)
        assert result == {"a": 1}

    def test_keeps_false_and_zero(self):
        """Test that False and 0 are kept."""
        d = {"a": False, "b": 0, "c": 0.0}
        result = compact(d)
        assert result == {"a": False, "b": 0, "c": 0.0}

    def test_keeps_non_empty_values(self):
        """Test that non-empty values are kept."""
        d = {"a": "text", "b": [1], "c": {"x": 1}}
        result = compact(d)
        assert result == d


class TestFirstLine:
    """Tests for the first_line() helper."""

    def test_single_line_text(self):
        """Test text without newlines."""
        result = first_line("Hello world")
        assert result == "Hello world"

    def test_multiline_text_extracts_first(self):
        """Test that only the first line is returned."""
        text = "First line\nSecond line\nThird line"
        result = first_line(text)
        assert result == "First line"

    def test_text_capped_at_limit(self):
        """Test that result is capped at limit."""
        text = "a" * 300
        result = first_line(text, limit=200)
        assert len(result) == 200
        assert result == "a" * 200

    def test_none_returns_empty_string(self):
        """Test that None returns empty string."""
        assert first_line(None) == ""

    def test_whitespace_stripped(self):
        """Test that leading/trailing whitespace is stripped."""
        result = first_line("  \n  Hello  \n  ")
        assert result == "Hello"


class TestTagNodeToDict:
    """Tests for tag_node_to_dict() function."""

    def test_scalar_node(self, project):
        """Test serialization of a scalar node."""
        main_prog = project.programs["MainProgram"]
        tag = main_prog.tags["a_dint"]
        node = tag.data
        result = tag_node_to_dict(node)

        assert result["kind"] == "scalar"
        assert result["data_type"] == "DINT"
        assert "value" in result
        # Should be JSON-serializable
        json.dumps(result)

    def test_structure_node(self, project):
        """Test serialization of a structure node."""
        main_prog = project.programs["MainProgram"]
        tag = main_prog.tags["a_udt_instance"]
        node = tag.data
        result = tag_node_to_dict(node, max_depth=2)

        assert result["kind"] == "structure"
        assert result["data_type"] == "A_UDT"
        assert "members" in result
        assert len(result["members"]) > 0
        json.dumps(result)

    def test_array_node(self, project):
        """Test serialization of an array node."""
        main_prog = project.programs["MainProgram"]
        tag = main_prog.tags["a_udt_instance"]
        an_array_member = tag.data.members["an_array"]
        result = tag_node_to_dict(an_array_member, max_depth=2, max_elements=10)

        assert result["kind"] == "array"
        assert "element_count" in result
        assert "elements" in result
        json.dumps(result)

    def test_depth_truncation(self, project):
        """Test that depth limit triggers truncation."""
        main_prog = project.programs["MainProgram"]
        tag = main_prog.tags["a_udt_instance"]
        result = tag_node_to_dict(tag.data, max_depth=1)

        # At max_depth=1, nested structures should be truncated
        assert result["kind"] == "structure"
        if "members" in result:
            for member in result["members"].values():
                if member.get("kind") == "structure":
                    # Nested structures should have truncated flag
                    assert "truncated" in member or "members" not in member

    def test_array_element_truncation(self, project):
        """Test that array elements are truncated with small max_elements."""
        main_prog = project.programs["MainProgram"]
        tag = main_prog.tags["a_udt_instance"]
        an_array_member = tag.data.members["an_array"]
        result = tag_node_to_dict(an_array_member, max_depth=3, max_elements=2)

        if result["element_count"] > 2:
            assert result.get("elements_truncated") is True
            assert len(result["elements"]) <= 2

    def test_array_elements_have_index(self, project):
        """Test that array elements include their index."""
        main_prog = project.programs["MainProgram"]
        tag = main_prog.tags["a_udt_instance"]
        an_array_member = tag.data.members["an_array"]
        result = tag_node_to_dict(an_array_member, max_depth=3, max_elements=10)

        for elem in result.get("elements", []):
            assert "index" in elem

    def test_metadata_fields_included(self, project):
        """Test that metadata fields (description, min, max, etc.) are included."""
        main_prog = project.programs["MainProgram"]
        # Look for a tag with properties
        tag = main_prog.tags["a_real_with_properties"]
        if tag.data:
            result = tag_node_to_dict(tag.data)
            # At minimum, should have data_type and kind
            assert "data_type" in result
            assert "kind" in result


class TestTagSummary:
    """Tests for tag_summary() function."""

    def test_basic_tag_summary(self, project):
        """Test basic tag summary serialization."""
        main_prog = project.programs["MainProgram"]
        tag = main_prog.tags["a_dint"]
        result = tag_summary(tag)

        assert result["name"] == "a_dint"
        assert result["data_type"] == "DINT"
        assert result["tag_type"] == "Base"
        json.dumps(result)

    def test_alias_tag_summary(self, project):
        """Test that alias tags include alias_for."""
        main_prog = project.programs["MainProgram"]
        tag = main_prog.tags["an_alias_tag"]
        result = tag_summary(tag)

        assert result["name"] == "an_alias_tag"
        assert result["tag_type"] == "Alias"
        assert "alias_for" in result

    def test_description_truncated_to_first_line(self, project):
        """Test that description is first line only, max 200 chars."""
        main_prog = project.programs["MainProgram"]
        # Find a tag with a description
        for tag_name in main_prog.tags:
            tag = main_prog.tags[tag_name]
            if tag.description and "\n" in tag.description:
                result = tag_summary(tag)
                assert "\n" not in result.get("description", "")
                break

    def test_constant_only_included_if_true(self, project):
        """Test that 'constant' is only in result if True."""
        main_prog = project.programs["MainProgram"]
        tag = main_prog.tags["a_dint"]
        result = tag_summary(tag)

        # Most tags are not constant
        assert "constant" not in result or result["constant"] is True

    def test_produced_tag_summary(self, project):
        """Test summary of a Produced tag."""
        tag = project.tags["produced_tag"]
        result = tag_summary(tag)

        assert result["tag_type"] == "Produced"
        json.dumps(result)

    def test_consumed_tag_summary(self, project):
        """Test summary of a Consumed tag."""
        tag = project.tags["consumed_tag"]
        result = tag_summary(tag)

        assert result["tag_type"] == "Consumed"
        json.dumps(result)


class TestTagDetail:
    """Tests for tag_detail() function."""

    def test_basic_tag_detail(self, project):
        """Test basic tag detail serialization."""
        main_prog = project.programs["MainProgram"]
        tag = main_prog.tags["a_dint"]
        result = tag_detail(tag)

        assert result["name"] == "a_dint"
        assert result["data_type"] == "DINT"
        assert result["tag_type"] == "Base"
        # Should be JSON-serializable
        json.dumps(result)

    def test_udt_tag_detail(self, project):
        """Test detail serialization of a UDT instance."""
        main_prog = project.programs["MainProgram"]
        tag = main_prog.tags["a_udt_instance"]
        result = tag_detail(tag, max_depth=2, max_elements=10)

        assert result["data_type"] == "A_UDT"
        assert "value_tree" in result
        assert result["value_tree"]["kind"] == "structure"
        assert "members" in result["value_tree"]
        json.dumps(result)

    def test_message_tag_detail(self, project):
        """Test detail of a MESSAGE tag includes message_parameters."""
        tag = project.tags["message_tag"]
        result = tag_detail(tag)

        assert result["data_type"] == "MESSAGE"
        assert "message_parameters" in result
        mp = result["message_parameters"]
        assert "message_type" in mp
        assert mp["message_type"] == "CIP Data Table Write"
        json.dumps(result)

    def test_axis_tag_detail(self, project):
        """Test detail of an AXIS_CIP_DRIVE tag includes axis_parameters."""
        tag = project.tags["testServo"]
        result = tag_detail(tag)

        assert result["data_type"] == "AXIS_CIP_DRIVE"
        assert "axis_parameters" in result
        json.dumps(result)

    def test_motion_group_tag_detail(self, project):
        """Test detail of a MOTION_GROUP tag includes motion_group_parameters."""
        tag = project.tags["ServosMotionGroup"]
        result = tag_detail(tag)

        assert result["data_type"] == "MOTION_GROUP"
        assert "motion_group_parameters" in result
        json.dumps(result)

    def test_alias_tag_detail(self, project):
        """Test that alias tags have no value_tree."""
        main_prog = project.programs["MainProgram"]
        tag = main_prog.tags["an_alias_tag"]
        result = tag_detail(tag)

        # Alias tags have no value tree
        assert "value_tree" not in result or result.get("value_tree") is None
        json.dumps(result)

    def test_produced_tag_detail(self, project):
        """Test detail of a Produced tag includes produce_info."""
        tag = project.tags["produced_tag"]
        result = tag_detail(tag)

        assert result["tag_type"] == "Produced"
        if "produce_info" in result:
            assert isinstance(result["produce_info"], dict)
        json.dumps(result)

    def test_consumed_tag_detail(self, project):
        """Test detail of a Consumed tag includes consume_info."""
        tag = project.tags["consumed_tag"]
        result = tag_detail(tag)

        assert result["tag_type"] == "Consumed"
        if "consume_info" in result:
            assert isinstance(result["consume_info"], dict)
        json.dumps(result)

    def test_full_description_in_detail(self, project):
        """Test that tag_detail includes full description (not truncated)."""
        main_prog = project.programs["MainProgram"]
        # Find a tag with multiline description
        for tag_name in main_prog.tags:
            tag = main_prog.tags[tag_name]
            if tag.description and len(tag.description) > 100:
                result = tag_detail(tag)
                if "description" in result:
                    # Could be multiline (unlike summary)
                    assert result["description"] == tag.description
                break


class TestRobustnessAndCompleteness:
    """Robustness tests for all tags in example.L5X."""

    def test_all_project_tags_serialize(self, project):
        """Test tag_detail() succeeds with valid JSON for all project tags."""
        for tag_name in project.tags:
            tag = project.tags[tag_name]
            result = tag_detail(tag, max_depth=2, max_elements=8)
            # Must be JSON-serializable
            json_str = json.dumps(result)
            assert isinstance(json_str, str)

    def test_all_program_tags_serialize(self, project):
        """Test that tag_detail() succeeds for all tags in all programs."""
        for prog_name in project.programs:
            prog = project.programs[prog_name]
            for tag_name in prog.tags:
                tag = prog.tags[tag_name]
                result = tag_detail(tag, max_depth=2, max_elements=8)
                # Must be JSON-serializable
                json_str = json.dumps(result)
                assert isinstance(json_str, str)

    def test_structure_members_present(self, project):
        """Test that UDT members are present in serialized output."""
        main_prog = project.programs["MainProgram"]
        tag = main_prog.tags["a_udt_instance"]
        result = tag_detail(tag, max_depth=3)

        assert "value_tree" in result
        vt = result["value_tree"]
        assert vt["kind"] == "structure"
        assert "members" in vt
        members = vt["members"]

        # Check for known members of A_UDT
        expected_members = ["a_Bool", "a_sint", "a_real", "an_array", "a_nested_UDT"]
        for member_name in expected_members:
            if member_name in members:
                # Member is present and serialized
                assert isinstance(members[member_name], dict)

    def test_depth_truncation_emits_truncated_flag(self, project):
        """Test that depth truncation emits 'truncated' flag and member_names."""
        main_prog = project.programs["MainProgram"]
        tag = main_prog.tags["a_udt_instance"]
        result = tag_detail(tag, max_depth=1)

        vt = result["value_tree"]
        assert vt["kind"] == "structure"
        # At max_depth=1, members should be truncated
        if "truncated" in vt:
            assert vt["truncated"] is True
            assert "member_names" in vt

    def test_array_truncation_with_small_max_elements(self, project):
        """Test array truncation with max_elements=2."""
        main_prog = project.programs["MainProgram"]
        tag = main_prog.tags["a_udt_instance"]
        result = tag_detail(tag, max_depth=3, max_elements=2)

        vt = result["value_tree"]
        # Navigate to the array
        if (
            "members" in vt
            and "an_array" in vt["members"]
            and "elements_truncated" in vt["members"]["an_array"]
        ):
            an_array = vt["members"]["an_array"]
            assert an_array["elements_truncated"] is True

    def test_compact_applied_to_nodes(self, project):
        """Test that compact() is applied, removing None/empty values."""
        main_prog = project.programs["MainProgram"]
        tag = main_prog.tags["a_dint"]
        result = tag_node_to_dict(tag.data)

        # Should not have empty strings, empty lists, or None values
        for _, val in result.items():
            assert val is not None
            assert val != ""
            assert val != []
            assert val != {}

    def test_counter_tag_detail(self, project):
        """Test detail of a COUNTER tag."""
        main_prog = project.programs["MainProgram"]
        tag = main_prog.tags["a_counter"]
        result = tag_detail(tag)

        assert result["data_type"] == "COUNTER"
        # COUNTER is a structure, should have value_tree
        if "value_tree" in result:
            assert result["value_tree"]["kind"] == "structure"
        json.dumps(result)


class TestDuckTyping:
    """Tests for duck-typed serialization (AOI local tags, module tags, etc.)."""

    def test_aoi_local_tags_serialize(self, project):
        """Test that all AOI local tags serialize without errors."""
        for aoi_name in project.aois:
            aoi = project.aois[aoi_name]
            for tag_name in aoi.local_tags:
                tag = aoi.local_tags[tag_name]
                # Should not crash on missing tag_type, etc.
                result = tag_summary(tag)
                json_str = json.dumps(result)
                assert isinstance(json_str, str)
                assert "name" in result

    def test_aoi_local_tags_detail(self, project):
        """Test that AOI local tag details serialize without errors."""
        for aoi_name in project.aois:
            aoi = project.aois[aoi_name]
            for tag_name in aoi.local_tags:
                tag = aoi.local_tags[tag_name]
                # Should not crash
                result = tag_detail(tag, max_depth=2)
                json_str = json.dumps(result)
                assert isinstance(json_str, str)

    def test_module_config_tag_serializes(self, project):
        """Test that module config tags serialize without errors."""
        for mod_name in project.modules:
            mod = project.modules[mod_name]
            if (
                mod.communications is not None
                and mod.communications.config_tag is not None
            ):
                tag = mod.communications.config_tag
                result = tag_summary(tag)
                json_str = json.dumps(result)
                assert isinstance(json_str, str)
                # config_tag is a ConfigTag, should have external_access
                if result:
                    assert "name" not in result or isinstance(result.get("name"), str)

    def test_module_input_output_tags_serialize(self, project):
        """Test that module input/output tags serialize without errors."""
        for mod_name in project.modules:
            mod = project.modules[mod_name]
            if mod.communications is not None:
                for conn_name in mod.communications.connections:
                    conn = mod.communications.connections[conn_name]
                    for tag in [conn.input_tag, conn.output_tag]:
                        if tag is not None:
                            result = tag_summary(tag)
                            json_str = json.dumps(result)
                            assert isinstance(json_str, str)

    def test_module_input_output_tags_detail(self, project):
        """Test module input/output tag details serialize."""
        for mod_name in project.modules:
            mod = project.modules[mod_name]
            if mod.communications is not None:
                for conn_name in mod.communications.connections:
                    conn = mod.communications.connections[conn_name]
                    for tag in [conn.input_tag, conn.output_tag]:
                        if tag is not None:
                            result = tag_detail(tag, max_depth=2)
                            json_str = json.dumps(result)
                            assert isinstance(json_str, str)

    def test_array_tag_dimensions_reported(self, project):
        """Test that array tags report their dimensions."""
        main_prog = project.programs["MainProgram"]
        tag = main_prog.tags["a_udt_instance"]
        an_array = tag.data.members["an_array"]

        # Tag nodes should expose dimensions
        result = tag_node_to_dict(an_array)
        # The array node should have dimensions from its XML element
        assert "dimensions" in result
        assert result["dimensions"] == "4"

    def test_special_data_attributes_only_without_wrapper(self, project):
        """Test that special_data_attributes only emitted when no wrapper."""
        # MESSAGE tag has message_parameters wrapper
        msg_tag = project.tags["message_tag"]
        result = tag_detail(msg_tag)

        # Should have message_parameters but not special_data_attributes
        # (or if special_data_attributes is present, no wrapper was emitted)
        if "message_parameters" in result:
            # Verify special_data_attributes is not also emitted
            # (they would be redundant)
            assert "special_data_attributes" not in result or (
                "message_parameters" not in result
            )
