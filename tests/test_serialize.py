"""Tests for l5x_mcp.serialize module (py_l5x 0.3.x tag model)."""

import json
import xml.etree.ElementTree as ET

import py_l5x
import pytest
from py_l5x import (
    AOILocalTag,
    AOIParameter,
    ArrayNode,
    AtomicNode,
    BoolNode,
    DateTimeNode,
    FloatNode,
    IntegerNode,
    ModuleTagRef,
    StringNode,
    StructNode,
    TimeNode,
    UnknownTag,
)

from l5x_mcp.serialize import (
    compact,
    first_line,
    jsonable,
    node_to_dict,
    tag_detail,
    tag_node_to_dict,
    tag_summary,
)


@pytest.fixture
def project(example_path):
    """Load and return the example.L5X project."""
    return py_l5x.load(example_path)


@pytest.fixture
def main_tags(project):
    """Tags of MainProgram."""
    return project.programs["MainProgram"].tags


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


class TestNodeToDict:
    """Tests for node_to_dict() on each value-node kind."""

    def test_alias_name_kept_for_backward_compat(self):
        """tag_node_to_dict is the same function as node_to_dict."""
        assert tag_node_to_dict is node_to_dict

    def test_bool_node(self, main_tags):
        """BOOL nodes report value and their state text."""
        result = node_to_dict(main_tags["a_bool_with_properties"])

        assert result["kind"] == "scalar"
        assert result["data_type"] == "BOOL"
        assert result["state0"] == "Off"
        assert result["state1"] == "On"
        assert "value" in result
        assert "radix" not in result
        json.dumps(result)

    def test_integer_node(self, main_tags):
        """Integer nodes report value and radix, with no bit comments."""
        result = node_to_dict(main_tags["a_dint"])

        assert result["kind"] == "scalar"
        assert result["data_type"] == "DINT"
        assert result["value"] == 0
        assert result["radix"] == "Decimal"
        assert "bit_descriptions" not in result
        json.dumps(result)

    def test_float_node_with_limits_and_units(self, main_tags):
        """Float nodes report min/max; engineering units come from metadata."""
        result = node_to_dict(main_tags["a_real_with_properties"])

        assert result["kind"] == "scalar"
        assert result["data_type"] == "REAL"
        assert result["min"] == -10.0
        assert result["max"] == 400.0
        assert result["engineering_unit"] == "mm"
        assert result["radix"] == "Float"
        json.dumps(result)

    def test_time_node(self, main_tags):
        """TIME nodes report their literal and unit."""
        result = node_to_dict(main_tags["duration"])

        assert result["kind"] == "scalar"
        assert result["data_type"] == "TIME"
        assert result["value"] == "T#0us"
        assert result["unit"] == "us"
        assert "radix" not in result

    def test_datetime_node(self, main_tags):
        """DT nodes report their literal and unit."""
        result = node_to_dict(main_tags["datetime"])

        assert result["kind"] == "scalar"
        assert result["data_type"] == "DT"
        assert result["value"].startswith("DT#1970-01-01")
        assert result["unit"] == "us"

    def test_other_atomic_node(self, main_tags):
        """Atomic scalars without a specific node class get value and radix only."""
        member = main_tags["a_string"].members["DATA"]
        assert type(member) is AtomicNode

        result = node_to_dict(member)
        assert result["kind"] == "scalar"
        assert "value" in result
        assert not {"min", "max", "unit", "state0"} & set(result)

    def test_string_node_is_collapsed(self, main_tags):
        """STRING nodes collapse to value/len/max_length, without LEN/DATA."""
        result = node_to_dict(main_tags["a_string"])

        assert result["kind"] == "string"
        assert result["data_type"] == "STRING"
        assert result["value"] == ""
        assert result["len"] == 0
        assert result["max_length"] == 82
        assert "members" not in result
        assert "LEN" not in json.dumps(result)
        assert "DATA" not in json.dumps(result)
        json.dumps(result)

    def test_custom_string_collapses_with_udt_capacity(self, main_tags):
        """Custom string types report the capacity from their definition."""
        tag = main_tags["a_custom_string"]
        assert isinstance(tag, StringNode)

        result = node_to_dict(tag)
        assert result["kind"] == "string"
        assert result["data_type"] == "robotAlarmCode"
        assert result["max_length"] == tag.max_length

    def test_structure_node(self, main_tags):
        """Structures expose a members mapping keyed by member name."""
        tag = main_tags["a_udt_instance"]
        result = node_to_dict(tag, max_depth=2)

        assert result["kind"] == "structure"
        assert result["data_type"] == "A_UDT"
        members = result["members"]
        for name in ["a_Bool", "a_sint", "a_real", "an_array", "a_nested_UDT"]:
            assert name in members
        assert members["a_nested_UDT"]["kind"] == "structure"
        assert members["a_nested_UDT"]["members"]["bool1"]["kind"] == "scalar"
        json.dumps(result)

    def test_member_metadata(self, main_tags):
        """Member description, engineering unit and limits come through."""
        member = main_tags["a_udt_instance"].members["a_sint_with_props"]
        result = node_to_dict(member)

        assert result["description"] == "This is a SINT with extended properties"
        assert result["engineering_unit"] == "mm"
        assert result["min"] == 0
        assert result["max"] == 25

    def test_array_node_dimensions_and_count(self, main_tags):
        """Arrays report dimensions as a list of ints and their element count."""
        tag = main_tags["a_udt_instance"].members["an_array"]
        result = node_to_dict(tag, max_depth=2, max_elements=10)

        assert result["kind"] == "array"
        assert result["data_type"] == "REAL"
        assert result["dimensions"] == [4]
        assert result["element_count"] == 4
        assert [e["index"] for e in result["elements"]] == ["[0]", "[1]", "[2]", "[3]"]
        assert all(e["kind"] == "scalar" for e in result["elements"])
        assert "elements_truncated" not in result
        json.dumps(result)

    def test_2d_array_dimensions_and_index_labels(self, main_tags):
        """2-D arrays list [rows, cols] and label elements row-major as '[i,j]'."""
        result = node_to_dict(main_tags["a_2d_array"], max_elements=100)

        assert result["dimensions"] == [2, 3]
        assert result["element_count"] == 6
        labels = [e["index"] for e in result["elements"]]
        assert labels == ["[0,0]", "[0,1]", "[0,2]", "[1,0]", "[1,1]", "[1,2]"]
        assert "[1,2]" in labels

    def test_3d_array_index_labels(self, main_tags):
        """3-D arrays use three-part subscripts."""
        result = node_to_dict(main_tags["a_3d_array"], max_elements=100)

        assert result["dimensions"] == [2, 3, 4]
        assert result["element_count"] == 24
        labels = [e["index"] for e in result["elements"]]
        assert labels[0] == "[0,0,0]"
        assert "[1,2,3]" in labels

    def test_array_of_strings_elements(self, project):
        """Arrays of string-family elements serialize each element as a string."""
        tag = project.controller_tags["ALLOWABLE_ALARMS"]
        result = node_to_dict(tag, max_elements=2)

        assert result["dimensions"] == [20]
        assert result["element_count"] == 20
        assert result["elements"][0]["index"] == "[0]"
        assert result["elements"][0]["kind"] == "string"
        assert result["elements_truncated"] is True

    def test_bit_descriptions_on_commented_dint(self, main_tags):
        """Commented bits appear in bit_descriptions keyed by bit number."""
        result = node_to_dict(main_tags["a_commented_dint"])

        assert result["bit_descriptions"] == {
            "0": "this is bit 0",
            "1": "this is bit 1",
            "10": "this is bit 10",
        }
        assert result["description"] == "a dint with bit comments"

    def test_element_bit_descriptions_are_per_element(self, main_tags):
        """Bit comments on array elements belong to that element only."""
        result = node_to_dict(main_tags["a_2d_array"], max_elements=100)

        first, second = result["elements"][0], result["elements"][1]
        assert first["bit_descriptions"] == {"0": "element bit comment"}
        assert second["bit_descriptions"] == {"1": "different element bit comment"}

    def test_inherited_aoi_instance_bit_descriptions(self, main_tags):
        """AOI instance bits inherit comments from the AOI parameter definition."""
        state = node_to_dict(main_tags["sequence"])["members"]["state"]

        assert state["bit_descriptions"] == {
            "0": "running",
            "1": "complete",
            "2": "pausing",
            "3": "paused",
            "4": "restarting",
            "5": "aborting",
            "6": "aborted",
        }

    def test_constant_value_is_reported(self, main_tags):
        """Constant tags serialize their value and description."""
        result = node_to_dict(main_tags["A_CONSTANT"])

        assert result["value"] == 42
        assert result["description"] == "the answer to life the universe and everything"

    def test_scalar_value_always_present(self, main_tags):
        """Scalars keep the value key even when it is empty or zero."""
        assert node_to_dict(main_tags["a_dint"])["value"] == 0
        assert node_to_dict(main_tags["a_string"])["value"] == ""

    def test_metadata_fields_included(self, main_tags):
        """Every value node carries data_type and kind."""
        result = node_to_dict(main_tags["a_real_with_properties"])
        assert "data_type" in result
        assert "kind" in result

    def test_compact_applied_to_nodes(self, main_tags):
        """Empty and None values are removed, except for the scalar value."""
        result = node_to_dict(main_tags["a_dint"])

        for key, val in result.items():
            if key != "value":
                assert val is not None
                assert val != ""
                assert val != []
                assert val != {}


class TestNodeTruncation:
    """Depth and element limits on node_to_dict()."""

    def test_depth_truncation_on_structures(self, main_tags):
        """A nested structure past max_depth lists member names only."""
        result = node_to_dict(main_tags["a_udt_instance"], max_depth=1)

        assert result["kind"] == "structure"
        nested = result["members"]["a_nested_UDT"]
        assert nested["truncated"] is True
        assert "members" not in nested
        assert nested["member_names"] == [
            "bool1",
            "bool2",
            "bool3",
            "bool4",
            "Dint",
            "real",
            "lint",
        ]

    def test_depth_truncation_on_arrays(self, main_tags):
        """An array past max_depth keeps counts but omits elements."""
        result = node_to_dict(main_tags["a_udt_instance"], max_depth=1)

        array = result["members"]["an_array"]
        assert array["truncated"] is True
        assert array["element_count"] == 4
        assert array["dimensions"] == [4]
        assert "elements" not in array

    def test_array_element_truncation(self, main_tags):
        """Only max_elements elements are emitted, and the flag is set."""
        result = node_to_dict(
            main_tags["a_udt_instance"].members["an_array"], max_elements=2
        )

        assert result["element_count"] == 4
        assert len(result["elements"]) == 2
        assert result["elements_truncated"] is True
        assert [e["index"] for e in result["elements"]] == ["[0]", "[1]"]

    def test_no_truncation_flag_when_all_elements_shown(self, main_tags):
        """Exactly max_elements elements is not truncated."""
        result = node_to_dict(
            main_tags["a_udt_instance"].members["an_array"], max_elements=4
        )

        assert len(result["elements"]) == 4
        assert "elements_truncated" not in result


class TestTagSummary:
    """Tests for tag_summary() on controller/program tags."""

    def test_basic_tag_summary(self, main_tags):
        """Basic tags report name, type, and tag kind; constant is omitted."""
        result = tag_summary(main_tags["a_dint"])

        assert result == {
            "name": "a_dint",
            "data_type": "DINT",
            "description": "a standard double integer",
            "tag_type": "Base",
            "external_access": "Read/Write",
        }
        json.dumps(result)

    def test_alias_tag_summary(self, main_tags):
        """Alias tags report alias_for and the Alias tag type."""
        result = tag_summary(main_tags["an_alias_tag"])

        assert result["name"] == "an_alias_tag"
        assert result["tag_type"] == "Alias"
        assert result["alias_for"] == "Local:1:I.Pt01.Data"
        assert "data_type" not in result

    def test_constant_reported_only_when_true(self, main_tags):
        """constant appears only for constant tags."""
        assert tag_summary(main_tags["A_CONSTANT"])["constant"] is True
        assert "constant" not in tag_summary(main_tags["a_dint"])

    def test_usage_reported(self, main_tags):
        """Program parameter usage is reported."""
        assert tag_summary(main_tags["a_public_param"])["usage"] == "Output"

    def test_array_dimensions_reported(self, main_tags):
        """Array tags report their dimensions as a list."""
        assert tag_summary(main_tags["a_2d_array"])["dimensions"] == [2, 3]
        assert tag_summary(main_tags["a_dint"]).get("dimensions") is None

    def test_description_first_line_only(self, main_tags):
        """Summary descriptions are reduced to their first line."""
        tag = main_tags["a_commented_dint"]
        result = tag_summary(tag)
        assert result["description"] == first_line(tag.description, 200)
        assert "\n" not in result["description"]

    def test_produced_tag_summary(self, project):
        """Produced tags report the Produced tag type."""
        result = tag_summary(project.tags["produced_tag"])
        assert result["tag_type"] == "Produced"
        json.dumps(result)

    def test_consumed_tag_summary(self, project):
        """Consumed tags report the Consumed tag type."""
        result = tag_summary(project.tags["consumed_tag"])
        assert result["tag_type"] == "Consumed"
        json.dumps(result)

    def test_string_summary_has_no_dimensions(self, main_tags):
        """String tags have no dimensions key."""
        assert "dimensions" not in tag_summary(main_tags["a_string"])


class TestTagDetail:
    """Tests for tag_detail() on controller/program tags."""

    def test_basic_tag_detail(self, main_tags):
        """Detail includes the summary fields plus radix and value_tree."""
        result = tag_detail(main_tags["a_dint"])

        assert result["name"] == "a_dint"
        assert result["data_type"] == "DINT"
        assert result["tag_type"] == "Base"
        assert result["radix"] == "Decimal"
        assert result["value_tree"]["kind"] == "scalar"
        json.dumps(result)

    def test_commented_dint_detail(self, main_tags):
        """Operand comments and bit descriptions both appear in detail."""
        result = tag_detail(main_tags["a_commented_dint"])

        assert result["operand_comments"] == {
            ".0": "this is bit 0",
            ".1": "this is bit 1",
            ".10": "this is bit 10",
        }
        assert result["value_tree"]["bit_descriptions"]["0"] == "this is bit 0"
        assert "min" not in result
        assert "max" not in result
        assert "is_safety" not in result
        json.dumps(result)

    def test_limits_and_engineering_unit_in_detail(self, main_tags):
        """Min/max and engineering unit come from the tag's value node."""
        result = tag_detail(main_tags["a_real_with_properties"])

        assert result["min"] == -10.0
        assert result["max"] == 400.0
        assert result["engineering_unit"] == "mm"

    def test_detail_description_is_full_text(self, project):
        """Detail keeps the whole description; summary keeps only the first line."""
        param = project.aois["SeqCtrl"].parameters["state"]
        full = param.description
        assert len(full) > 0

        assert tag_detail(param)["description"] == full
        assert tag_summary(param)["description"] == first_line(full, 200)

    def test_udt_tag_detail(self, main_tags):
        """Detail of a UDT instance includes a structure value_tree."""
        result = tag_detail(main_tags["a_udt_instance"], max_depth=2, max_elements=10)

        assert result["data_type"] == "A_UDT"
        assert result["value_tree"]["kind"] == "structure"
        assert "members" in result["value_tree"]
        json.dumps(result)

    def test_constant_detail(self, main_tags):
        """Constant tags show constant in detail as well."""
        result = tag_detail(main_tags["A_CONSTANT"])
        assert result["constant"] is True
        assert result["value_tree"]["value"] == 42

    def test_alias_tag_detail(self, main_tags):
        """Alias tags have an alias_for and no value_tree."""
        result = tag_detail(main_tags["an_alias_tag"])

        assert result["alias_for"] == "Local:1:I.Pt01.Data"
        assert "value_tree" not in result
        json.dumps(result)

    def test_string_detail(self, main_tags):
        """String tags emit the collapsed string value tree."""
        result = tag_detail(main_tags["a_string"])
        assert result["value_tree"]["kind"] == "string"
        assert result["value_tree"]["max_length"] == 82

    def test_timer_detail(self, main_tags):
        """Timer structures serialize their members (PRE, ACC, EN, TT, DN)."""
        result = tag_detail(main_tags["a_timer"])
        members = result["value_tree"]["members"]
        assert list(members) == ["PRE", "ACC", "EN", "TT", "DN"]

    def test_counter_detail(self, main_tags):
        """COUNTER is a structure value tree."""
        result = tag_detail(main_tags["a_counter"])
        assert result["data_type"] == "COUNTER"
        assert result["value_tree"]["kind"] == "structure"

    def test_produced_tag_detail(self, project):
        """Produced tags carry typed ProduceInfo fields and raw attributes."""
        result = tag_detail(project.tags["produced_tag"])

        produced = result["produced"]
        assert produced["produce_count"] == 1
        assert produced["minimum_rpi"] == 0.2
        assert produced["attributes"]["ProduceCount"] == "1"
        json.dumps(result)

    def test_consumed_tag_detail(self, project):
        """Consumed tags carry typed ConsumeInfo fields and raw attributes."""
        result = tag_detail(project.tags["consumed_tag"])

        consumed = result["consumed"]
        assert consumed["producer"] == "AnotherPLC"
        assert consumed["remote_tag"] == "fake_other_tag"
        assert consumed["rpi"] == 20
        assert consumed["unicast"] is True
        assert consumed["attributes"]["RemoteTag"] == "fake_other_tag"
        json.dumps(result)

    def test_full_description_in_detail(self, main_tags):
        """Detail descriptions are the full text, not truncated."""
        tag = main_tags["a_commented_dint"]
        assert tag_detail(tag)["description"] == tag.description


class TestSpecialtyTags:
    """Tests for MESSAGE, AXIS and MOTION_GROUP tags."""

    def test_message_tag_detail(self, project):
        """MESSAGE tags include message_parameters with typed fields."""
        result = tag_detail(project.tags["message_tag"])

        assert result["data_type"] == "MESSAGE"
        mp = result["message_parameters"]
        assert mp["message_type"] == "CIP Data Table Write"
        assert mp["remote_element"] == "fake_tag"
        assert mp["requested_length"] == 1
        assert mp["connected"] is True
        assert "attributes" not in mp
        json.dumps(result)

    def test_message_tag_has_no_special_data_or_value_tree(self, project):
        """Specialty tags with a wrapper emit no special_data_* and no value_tree."""
        result = tag_detail(project.tags["message_tag"])

        assert "special_data_format" not in result
        assert "special_data_attributes" not in result
        assert "value_tree" not in result

    def test_axis_tag_detail(self, project):
        """AXIS_CIP_DRIVE tags include axis_parameters with typed fields."""
        result = tag_detail(project.tags["testServo"])

        assert result["data_type"] == "AXIS_CIP_DRIVE"
        axis = result["axis_parameters"]
        assert axis["motion_group"] == "ServosMotionGroup"
        assert axis["feedback1_type"] == "Hiperface DSL"
        assert "extra_attributes" in axis
        assert "attributes" not in axis
        assert "special_data_attributes" not in result
        json.dumps(result)

    def test_motion_group_tag_detail(self, project):
        """MOTION_GROUP tags include motion_group_parameters."""
        result = tag_detail(project.tags["ServosMotionGroup"])

        assert result["data_type"] == "MOTION_GROUP"
        mg = result["motion_group_parameters"]
        assert mg["coarse_update_period"] == 2000
        assert mg["general_fault_type"] == "Non Major Fault"
        json.dumps(result)

    def test_unknown_special_data_tag(self):
        """Tags with an unrecognised <Data> format report it verbatim."""
        element = ET.fromstring(
            '<Tag Name="Mystery" TagType="Base" DataType="FOO">'
            '<Data Format="Foo" Note="x"/></Tag>'
        )
        tag = UnknownTag(element, None)

        result = tag_detail(tag)
        assert result["special_data_format"] == "Foo"
        assert result["special_data_attributes"] == {"Format": "Foo", "Note": "x"}
        assert "value_tree" not in result
        json.dumps(result)


class TestOperandComments:
    """Tests for operand_comments on tags, AOI parameters and AOI locals."""

    def test_typed_parameter_comments(self, project):
        """Typed AOI parameters report their per-bit comments."""
        param = project.aois["SeqCtrl"].parameters["state"]
        result = tag_detail(param)

        assert result["operand_comments"][".0"] == "running"
        assert result["operand_comments"][".6"] == "aborted"
        assert len(result["operand_comments"]) == 7
        assert "value_tree" in result

    def test_plain_inout_parameter_comments(self, project):
        """InOut parameters without a value tree still report comments."""
        param = project.aois["FanucRobot"].parameters["seq"]
        result = tag_detail(param)

        assert type(param) is AOIParameter
        assert result["usage"] == "InOut"
        assert result["operand_comments"][".FAULT.0"] == (
            "Robot fault did not reset when running"
        )
        assert "value_tree" not in result
        assert "min" not in result
        json.dumps(result)

    def test_aoi_local_tags_detail_value_tree(self, project):
        """AOI local TIMER structures produce a value tree."""
        local = project.aois["Debounce"].local_tags["debounceOnTimer"]
        result = tag_detail(local)

        assert result["data_type"] == "TIMER"
        assert result["value_tree"]["kind"] == "structure"
        assert "tag_type" not in result
        assert "usage" not in result


class TestAOISummaries:
    """Tests for tag_summary() and tag_detail() on AOI tags."""

    def test_typed_parameter_summary(self, project):
        """Typed AOI parameters report type, tag kind and usage."""
        result = tag_summary(project.aois["SeqCtrl"].parameters["state"])

        assert result["name"] == "state"
        assert result["data_type"] == "DINT"
        assert result["tag_type"] == "Base"
        assert result["usage"] == "Output"

    def test_plain_parameter_summary(self, project):
        """Value-less AOI parameters (EnableIn) still summarize."""
        result = tag_summary(project.aois["SeqCtrl"].parameters["EnableIn"])

        assert type(project.aois["SeqCtrl"].parameters["EnableIn"]) is AOIParameter
        assert result["name"] == "EnableIn"
        assert result["data_type"] == "BOOL"
        assert result["usage"] == "Input"

    def test_local_tag_summary(self, project):
        """AOI local tags have no tag_type or usage."""
        local = project.aois["Debounce"].local_tags["debounceOnTimer"]
        result = tag_summary(local)

        assert isinstance(local, AOILocalTag)
        assert result["name"] == "debounceOnTimer"
        assert result["data_type"] == "TIMER"
        assert "tag_type" not in result
        assert "usage" not in result

    def test_plain_parameter_detail_has_no_value_fields(self, project):
        """Value-less AOI parameters have no min, max, or value tree."""
        param = project.aois["SeqCtrl"].parameters["EnableIn"]
        result = tag_detail(param)

        assert "value_tree" not in result
        assert "min" not in result
        assert "max" not in result
        json.dumps(result)


class TestModuleTags:
    """Tests for module I/O references (ModuleTagRef) in project.tags."""

    def test_module_array_summary(self, project):
        """Module array tags report kind, module and dimensions."""
        ref = project.tags["ShopRobot:C"]
        assert isinstance(ref, ModuleTagRef)

        result = tag_summary(ref)
        assert result["name"] == "ShopRobot:C"
        assert result["kind"] == "C"
        assert result["module"] == "ShopRobot"
        assert result["data_type"] == "AB:ETHERNET_MODULE:C:0"
        assert result["dimensions"] == [400]
        json.dumps(result)

    def test_module_structure_detail(self, project):
        """Module structure references serialize their value tree via .data."""
        ref = project.tags["ShopRobot:I"]
        result = tag_detail(ref, max_depth=2, max_elements=4)

        assert result["kind"] == "I"
        assert result["module"] == "ShopRobot"
        assert result["value_tree"]["kind"] == "structure"
        assert "members" in result["value_tree"]
        json.dumps(result)

    def test_safety_module_tag_detail(self, project):
        """Safety connection tags report class Safety and is_safety."""
        result = tag_detail(project.tags["Local:2:I"])

        assert result["module"] == "Test_Safety_Input"
        assert result["class"] == "Safety"
        assert result["is_safety"] is True
        assert result["value_tree"]["kind"] == "structure"

    def test_standard_module_tag_has_no_is_safety(self, project):
        """Standard module tags carry class but not is_safety."""
        result = tag_detail(project.tags["Local:1:I"])

        assert result["class"] == "Standard"
        assert "is_safety" not in result


class TestTruncationThroughTagDetail:
    """Depth and element limits applied through tag_detail()."""

    def test_depth_truncation_emits_truncated_flag(self, main_tags):
        """Depth 1 truncates nested structures and keeps member names."""
        result = tag_detail(main_tags["a_udt_instance"], max_depth=1)

        vt = result["value_tree"]
        assert vt["kind"] == "structure"
        assert vt["members"]["a_nested_UDT"]["truncated"] is True
        assert "member_names" in vt["members"]["a_nested_UDT"]

    def test_array_truncation_with_small_max_elements(self, main_tags):
        """max_elements=2 flags the nested array as truncated."""
        result = tag_detail(main_tags["a_udt_instance"], max_depth=3, max_elements=2)

        an_array = result["value_tree"]["members"]["an_array"]
        assert an_array["elements_truncated"] is True
        assert len(an_array["elements"]) == 2

    def test_sequence_detail_at_depth_one(self, main_tags):
        """Sample: shallow detail of an AOI instance keeps scalar members."""
        result = tag_detail(main_tags["sequence"], max_depth=1)

        members = result["value_tree"]["members"]
        assert members["state"]["kind"] == "scalar"
        assert members["state"]["bit_descriptions"]["0"] == "running"
        assert "operand_comments" not in result
        json.dumps(result)


class TestRobustnessAndCompleteness:
    """Every tag and AOI member in example.L5X must serialize cleanly."""

    def test_all_controller_tags_serialize(self, project):
        """Summary and detail of every controller tag are JSON-serializable."""
        for name in project.controller_tags:
            tag = project.controller_tags[name]
            summary = tag_summary(tag)
            detail = tag_detail(tag, max_depth=2, max_elements=8)
            assert summary["name"] == name
            json.dumps(summary)
            json.dumps(detail)

    def test_all_program_tags_serialize(self, project):
        """Summary and detail of every program tag are JSON-serializable."""
        for prog_name in project.programs:
            tags = project.programs[prog_name].tags
            for name in tags:
                tag = tags[name]
                json.dumps(tag_summary(tag))
                json.dumps(tag_detail(tag, max_depth=2, max_elements=8))

    def test_all_aoi_local_tags_serialize(self, project):
        """Summary and detail of every AOI local tag are JSON-serializable."""
        for aoi_name in project.aois:
            locals_ = project.aois[aoi_name].local_tags
            for name in locals_:
                tag = locals_[name]
                assert tag_summary(tag)["name"] == name
                json.dumps(tag_summary(tag))
                json.dumps(tag_detail(tag, max_depth=2))

    def test_all_aoi_parameters_serialize(self, project):
        """Summary and detail of every AOI parameter (plain and typed) serialize."""
        for aoi_name in project.aois:
            params = project.aois[aoi_name].parameters
            for name in params:
                param = params[name]
                assert isinstance(param, AOIParameter)
                assert tag_summary(param)["name"] == name
                json.dumps(tag_summary(param))
                json.dumps(tag_detail(param, max_depth=2))

    def test_all_project_tags_serialize(self, project):
        """Summary and detail of every project.tags entry (incl. modules) serialize."""
        for name in project.tags:
            tag = project.tags[name]
            summary = tag_summary(tag)
            detail = tag_detail(tag, max_depth=2, max_elements=8)
            assert summary["name"] == name
            json.dumps(summary)
            json.dumps(detail)

    def test_module_refs_are_covered(self, project):
        """project.tags includes module references, and they report kind/module."""
        refs = [project.tags[n] for n in project.tags if ":" in n]
        assert refs
        for ref in refs:
            assert isinstance(ref, ModuleTagRef)
            summary = tag_summary(ref)
            assert summary["kind"] == ref.kind
            assert summary["module"] == ref.module_name

    def test_value_nodes_are_known_classes(self, project):
        """Every value tree produced for project tags uses a known kind label."""
        kinds = {"scalar", "string", "structure", "array"}
        for name in project.tags:
            detail = tag_detail(project.tags[name], max_depth=1, max_elements=4)
            if "value_tree" in detail:
                assert detail["value_tree"]["kind"] in kinds

    def test_node_classes_are_isinstance_dispatched(self, main_tags):
        """Each typed node class maps to the expected kind label."""
        cases = {
            "a_bool": ("scalar", BoolNode),
            "a_dint": ("scalar", IntegerNode),
            "a_real": ("scalar", FloatNode),
            "duration": ("scalar", TimeNode),
            "datetime": ("scalar", DateTimeNode),
            "a_string": ("string", StringNode),
            "a_udt_instance": ("structure", StructNode),
            "a_2d_array": ("array", ArrayNode),
        }
        for name, (kind, cls) in cases.items():
            assert isinstance(main_tags[name], cls)
            assert node_to_dict(main_tags[name])["kind"] == kind
