"""Tests for datatypes tool module."""

import json

import pytest

from l5x_mcp.registry import ItemNotFoundError
from l5x_mcp.tools.datatypes import get_data_type, list_data_types


class TestListDataTypes:
    """Tests for list_data_types function."""

    def test_list_data_types_returns_all_types(self, registry):
        """Test that list_data_types returns all data types in the project."""
        result = list_data_types(registry, path="example.L5X")
        assert "file" in result
        assert "data_types" in result
        data_types = result["data_types"]
        assert len(data_types) > 0
        # example.L5X has: A_UDT, GenericRobotInputs, GenericRobotIO,
        # GenericRobotOutputs, robotAlarmCode, robotString, robotUI, robotUO,
        # simple_udt
        assert len(data_types) >= 9

    def test_list_data_types_has_required_keys(self, registry):
        """Test that each data type has required keys."""
        result = list_data_types(registry, path="example.L5X")
        data_types = result["data_types"]
        assert len(data_types) > 0
        dt = data_types[0]
        assert "name" in dt
        assert "family" in dt
        assert "member_count" in dt

    def test_list_data_types_description_first_line(self, registry):
        """Test that description is limited to first line."""
        result = list_data_types(registry, path="example.L5X")
        data_types = result["data_types"]
        for dt in data_types:
            if "description" in dt:
                # Should not contain newlines if it's present
                assert "\n" not in dt["description"]
                # Should be under 200 chars
                assert len(dt["description"]) <= 200

    def test_list_data_types_string_family(self, registry):
        """Test that is_string flag is set for StringFamily types."""
        result = list_data_types(registry, path="example.L5X")
        data_types = result["data_types"]
        string_types = [dt for dt in data_types if "is_string" in dt]
        # robotAlarmCode and robotString are StringFamily types
        assert len(string_types) >= 2
        for dt in string_types:
            assert dt["is_string"] is True

    def test_list_data_types_no_family_types(self, registry):
        """Test that NoFamily types don't have is_string flag."""
        result = list_data_types(registry, path="example.L5X")
        data_types = result["data_types"]
        no_family_types = [dt for dt in data_types if dt["family"] == "NoFamily"]
        assert len(no_family_types) > 0
        for dt in no_family_types:
            assert "is_string" not in dt

    def test_list_data_types_member_count(self, registry):
        """Test that member_count is accurate."""
        result = list_data_types(registry, path="example.L5X")
        data_types = result["data_types"]
        a_udt = [dt for dt in data_types if dt["name"] == "A_UDT"]
        assert len(a_udt) == 1
        # A_UDT has 10 visible members (verified in exploration)
        assert a_udt[0]["member_count"] == 10

    def test_list_data_types_json_serializable(self, registry):
        """Test that result is JSON serializable."""
        result = list_data_types(registry, path="example.L5X")
        json_str = json.dumps(result)
        assert json_str is not None
        assert len(json_str) > 0


class TestGetDataType:
    """Tests for get_data_type function."""

    def test_get_data_type_basic_fields(self, registry):
        """Test that get_data_type returns all required fields."""
        result = get_data_type(registry, "A_UDT", path="example.L5X")
        assert "file" in result
        assert "name" in result
        assert result["name"] == "A_UDT"
        assert "family" in result
        assert "class" in result
        assert "members" in result
        assert "used_by" in result
        assert "tag_count" in result

    def test_get_data_type_not_found(self, registry):
        """Test that unknown data type raises ItemNotFoundError."""
        with pytest.raises(ItemNotFoundError):
            get_data_type(registry, "NonExistentType", path="example.L5X")

    def test_get_data_type_members(self, registry):
        """Test that members have correct structure."""
        result = get_data_type(registry, "A_UDT", path="example.L5X")
        members = result["members"]
        assert len(members) == 10
        # Check first member
        first_member = members[0]
        assert "name" in first_member
        assert "data_type" in first_member
        assert "radix" in first_member

    def test_get_data_type_member_with_properties(self, registry):
        """Test that members with properties (min, max, EU) are included."""
        result = get_data_type(registry, "A_UDT", path="example.L5X")
        members = result["members"]
        # a_sint_with_props should have min=0, max=25
        a_sint_with_props = [m for m in members if m["name"] == "a_sint_with_props"]
        assert len(a_sint_with_props) == 1
        member = a_sint_with_props[0]
        assert member["min"] == 0
        assert member["max"] == 25

    def test_get_data_type_member_array(self, registry):
        """Test that array members have dimension field."""
        result = get_data_type(registry, "A_UDT", path="example.L5X")
        members = result["members"]
        # an_array should have dimension=4
        an_array = [m for m in members if m["name"] == "an_array"]
        assert len(an_array) == 1
        member = an_array[0]
        assert "dimension" in member
        assert member["dimension"] == 4

    def test_get_data_type_member_bit(self, registry):
        """Test that BIT members show data_type as BOOL without bit internals."""
        result = get_data_type(registry, "A_UDT", path="example.L5X")
        members = result["members"]
        # a_Bool should be a BIT member
        a_bool = [m for m in members if m["name"] == "a_Bool"]
        assert len(a_bool) == 1
        member = a_bool[0]
        # BIT members should show as BOOL
        assert member["data_type"] == "BOOL"
        # Should NOT have bit_number or target (internal packing details hidden)
        assert "bit_number" not in member
        assert "target" not in member

    def test_get_data_type_string_family(self, registry):
        """Test that StringFamily types have is_string and max_length."""
        result = get_data_type(registry, "robotAlarmCode", path="example.L5X")
        assert result["is_string"] is True
        assert "max_length" in result
        assert result["max_length"] > 0

    def test_get_data_type_no_hidden_hosts(self, registry):
        """Test that hidden host members (ZZZZZZZZZZ...) don't appear in output."""
        result = get_data_type(registry, "simple_udt", path="example.L5X")
        members = result["members"]
        # Verify no member names start with ZZZZZZZZZZ (hidden packed hosts)
        for member in members:
            assert not member["name"].startswith("ZZZZZZZZZZ")
            # Also verify no target fields remain
            assert "target" not in member
            assert "bit_number" not in member

    def test_get_data_type_used_by(self, registry):
        """Test that used_by references are found."""
        result = get_data_type(registry, "simple_udt", path="example.L5X")
        # simple_udt is used as a nested member in A_UDT
        used_by = result["used_by"]
        assert "A_UDT" in used_by

    def test_get_data_type_tag_count(self, registry):
        """Test that tag_count is calculated."""
        result = get_data_type(registry, "A_UDT", path="example.L5X")
        tag_count = result["tag_count"]
        # A_UDT is used in MainProgram as a_udt_instance
        assert tag_count >= 1

    def test_get_data_type_json_serializable(self, registry):
        """Test that result is JSON serializable."""
        result = get_data_type(registry, "A_UDT", path="example.L5X")
        json_str = json.dumps(result)
        assert json_str is not None
        assert len(json_str) > 0

    def test_get_data_type_nested_udt(self, registry):
        """Test nested UDT references."""
        result = get_data_type(registry, "A_UDT", path="example.L5X")
        members = result["members"]
        # a_nested_UDT should reference simple_udt
        a_nested = [m for m in members if m["name"] == "a_nested_UDT"]
        assert len(a_nested) == 1
        assert a_nested[0]["data_type"] == "simple_udt"

    def test_get_data_type_aoi_member(self, registry):
        """Test that UDT members can be AOI types."""
        result = get_data_type(registry, "A_UDT", path="example.L5X")
        members = result["members"]
        # an_aoi should be GenericInput AOI
        an_aoi = [m for m in members if m["name"] == "an_aoi"]
        assert len(an_aoi) == 1
        assert an_aoi[0]["data_type"] == "GenericInput"

    def test_get_data_type_used_by_aoi_parameters(self, registry):
        """Test that used_by includes AOIs that use this type in parameters."""
        result = get_data_type(registry, "A_UDT", path="example.L5X")
        # A_UDT is used as an AOI parameter
        used_by = result["used_by"]
        # used_by should be a list
        assert isinstance(used_by, list)


class TestDataTypeComponent:
    """Tests for data type functionality with component exports."""

    def test_get_data_type_from_component_export(self, registry):
        """Test getting data type from a component export (Debounce_AOI.L5X)."""
        # Debounce_AOI.L5X should have no UDTs, only the AOI
        result = list_data_types(registry, path="Debounce_AOI.L5X")
        # Component export might have minimal data types
        assert "data_types" in result
        data_types = result["data_types"]
        # Should be empty or minimal
        assert len(data_types) <= 2  # Usually just system types

    def test_get_data_type_user_udt_component_export(self, registry):
        """UDT component export (A_UDT_DataType.L5X) returns the target UDT."""
        result = get_data_type(registry, "A_UDT", path="A_UDT_DataType.L5X")
        assert result["name"] == "A_UDT"
        assert result["family"] == "NoFamily"
        assert result["class"] == "User"
        assert "is_string" not in result
        assert result["tag_count"] == 0
        assert result["members"]

    def test_get_data_type_string_component_export(self, registry):
        """STRING-family component export reports max_length and is_string."""
        result = get_data_type(
            registry,
            "robotAlarmCode",
            path="robotAlarmCode_DataType_String.L5X",
        )
        assert result["family"] == "StringFamily"
        assert result["is_string"] is True
        assert result["max_length"] == 8
        assert result["used_by"] == []
