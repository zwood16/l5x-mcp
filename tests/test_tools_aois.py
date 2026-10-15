"""Tests for aois tool module."""

import json

import pytest

from l5x_mcp.registry import ItemNotFoundError
from l5x_mcp.tools.aois import get_aoi, list_aois


class TestListAOIs:
    """Tests for list_aois function."""

    def test_list_aois_returns_all_aois(self, registry):
        """Test that list_aois returns all AOIs in the project."""
        result = list_aois(registry, path="example.L5X")
        assert "file" in result
        assert "aois" in result
        aois = result["aois"]
        assert len(aois) > 0
        # example.L5X has at least: Debounce, GenericInput, FanucAlarmLookup,
        # FanucPNS, SeqCtrl, FanucRobot
        assert len(aois) >= 6

    def test_list_aois_has_required_keys(self, registry):
        """Test that each AOI has required keys."""
        result = list_aois(registry, path="example.L5X")
        aois = result["aois"]
        assert len(aois) > 0
        aoi = aois[0]
        assert "name" in aoi
        assert "revision" in aoi
        assert "parameter_count" in aoi
        assert "routines" in aoi

    def test_list_aois_description_first_line(self, registry):
        """Test that description is limited to first line."""
        result = list_aois(registry, path="example.L5X")
        aois = result["aois"]
        for aoi in aois:
            if "description" in aoi:
                # Should not contain newlines if it's present
                assert "\n" not in aoi["description"]
                # Should be under 200 chars
                assert len(aoi["description"]) <= 200

    def test_list_aois_parameter_count(self, registry):
        """Test that parameter_count is correct."""
        result = list_aois(registry, path="example.L5X")
        aois = result["aois"]
        debounce = [a for a in aois if a["name"] == "Debounce"]
        assert len(debounce) == 1
        # Debounce has 5 parameters: EnableIn, EnableOut, state, onDelay, offDelay
        assert debounce[0]["parameter_count"] == 5

    def test_list_aois_routines(self, registry):
        """Test that routines list is populated."""
        result = list_aois(registry, path="example.L5X")
        aois = result["aois"]
        debounce = [a for a in aois if a["name"] == "Debounce"]
        assert len(debounce) == 1
        # Debounce has at least 2 routines
        assert len(debounce[0]["routines"]) >= 2

    def test_list_aois_json_serializable(self, registry):
        """Test that result is JSON serializable."""
        result = list_aois(registry, path="example.L5X")
        json_str = json.dumps(result)
        assert json_str is not None
        assert len(json_str) > 0


class TestGetAOI:
    """Tests for get_aoi function."""

    def test_get_aoi_basic_fields(self, registry):
        """Test that get_aoi returns all required fields."""
        result = get_aoi(registry, "Debounce", path="example.L5X")
        assert "file" in result
        assert "name" in result
        assert result["name"] == "Debounce"
        assert "revision" in result
        assert "parameters" in result
        assert "local_tags" in result
        assert "routines" in result
        assert "call_signature" in result
        assert "instances" in result

    def test_get_aoi_not_found(self, registry):
        """Test that unknown AOI raises ItemNotFoundError."""
        with pytest.raises(ItemNotFoundError):
            get_aoi(registry, "NonExistentAOI", path="example.L5X")

    def test_get_aoi_metadata(self, registry):
        """Test AOI metadata fields."""
        result = get_aoi(registry, "Debounce", path="example.L5X")
        assert result["revision"] == "1.2"
        assert "created_date" in result
        assert "created_by" in result
        assert "edited_date" in result
        assert "edited_by" in result
        assert "software_revision" in result

    def test_get_aoi_execution_flags(self, registry):
        """Test that execution flags are present."""
        result = get_aoi(registry, "Debounce", path="example.L5X")
        assert "execute_prescan" in result
        assert "execute_postscan" in result
        assert "execute_enable_in_false" in result
        assert isinstance(result["execute_prescan"], bool)
        assert isinstance(result["execute_postscan"], bool)
        assert isinstance(result["execute_enable_in_false"], bool)

    def test_get_aoi_parameters(self, registry):
        """Test that parameters have correct structure."""
        result = get_aoi(registry, "Debounce", path="example.L5X")
        params = result["parameters"]
        assert len(params) == 5
        # Check EnableIn parameter
        enable_in = [p for p in params if p["name"] == "EnableIn"]
        assert len(enable_in) == 1
        param = enable_in[0]
        assert param["data_type"] == "BOOL"
        assert param["usage"] == "Input"
        assert param["required"] is False
        assert param["visible"] is False

    def test_get_aoi_parameter_required(self, registry):
        """Test that required parameters are marked."""
        result = get_aoi(registry, "Debounce", path="example.L5X")
        params = result["parameters"]
        # onDelay and offDelay are not marked required
        on_delay = [p for p in params if p["name"] == "onDelay"]
        assert len(on_delay) == 1
        assert on_delay[0]["required"] is False
        assert on_delay[0]["visible"] is True

    def test_get_aoi_parameter_min_max(self, registry):
        """Test that min/max constraints are captured."""
        result = get_aoi(registry, "Debounce", path="example.L5X")
        params = result["parameters"]
        on_delay = [p for p in params if p["name"] == "onDelay"]
        assert len(on_delay) == 1
        assert on_delay[0]["min"] == 0
        assert on_delay[0]["max"] == 2147483647

    def test_get_aoi_local_tags(self, registry):
        """Test that local tags are present."""
        result = get_aoi(registry, "Debounce", path="example.L5X")
        local_tags = result["local_tags"]
        # Debounce has 2 local tags: debounceOnTimer, debounceOffTimer
        assert len(local_tags) >= 2
        # Check structure
        for tag in local_tags:
            assert "name" in tag
            assert "data_type" in tag

    def test_get_aoi_routines(self, registry):
        """Test that routines have correct structure."""
        result = get_aoi(registry, "Debounce", path="example.L5X")
        routines = result["routines"]
        assert len(routines) >= 2
        # Each routine should have name and type
        for routine in routines:
            assert "name" in routine
            assert "type" in routine
            assert routine["type"] in ("RLL", "ST")
            # RLL routines should have rung_count
            if routine["type"] == "RLL":
                assert "rung_count" in routine

    def test_get_aoi_call_signature(self, registry):
        """Test that call_signature is correct."""
        result = get_aoi(registry, "Debounce", path="example.L5X")
        call_sig = result["call_signature"]
        # Should start with AOI name
        assert call_sig.startswith("Debounce(")
        # Should include instance placeholder
        assert "<instance>" in call_sig
        # Should be a valid-looking signature
        assert call_sig.endswith(")")

    def test_get_aoi_call_signature_format(self, registry):
        """Test call_signature format matches expected operand order."""
        result = get_aoi(registry, "Debounce", path="example.L5X")
        call_sig = result["call_signature"]
        # Format should be: Debounce(<instance>, onDelay, offDelay, state)
        # (required visible parameters after instance)
        assert "Debounce(" in call_sig
        # Instance should be first
        parts = call_sig.split("(")[1].rstrip(")").split(", ")
        assert parts[0] == "<instance>"

    def test_get_aoi_instances(self, registry):
        """Test that instances are found and have correct structure."""
        result = get_aoi(registry, "Debounce", path="example.L5X")
        instances = result["instances"]
        assert isinstance(instances, list)
        # Each instance should have container_type, container, routine, and rung or line
        for instance in instances:
            assert "container_type" in instance
            assert instance["container_type"] in ("program", "aoi")
            assert "container" in instance
            assert "routine" in instance
            assert "rung" in instance or "line" in instance

    def test_get_aoi_instance_count(self, registry):
        """Test that instance_count is present and accurate."""
        result = get_aoi(registry, "Debounce", path="example.L5X")
        assert "instance_count" in result
        instance_count = result["instance_count"]
        assert isinstance(instance_count, int)
        assert instance_count >= 0
        # instance_count should be >= len(instances) since instances is capped at 50
        assert instance_count >= len(result["instances"])

    def test_debounce_instances_include_aoi(self, registry):
        """Test that Debounce instances include calls from nested AOIs."""
        result = get_aoi(registry, "Debounce", path="example.L5X")
        instances = result["instances"]
        # GenericInput's Logic routine calls Debounce (rung 2)
        aoi_calls = [i for i in instances if i.get("container_type") == "aoi"]
        # Should have at least the GenericInput call
        assert len(aoi_calls) > 0
        # Check for GenericInput specifically
        generic_input_calls = [i for i in aoi_calls if i["container"] == "GenericInput"]
        assert len(generic_input_calls) > 0

    def test_get_aoi_no_include_logic(self, registry):
        """Test that logic is not included by default."""
        result = get_aoi(registry, "Debounce", path="example.L5X")
        assert "logic" not in result

    def test_get_aoi_include_logic(self, registry):
        """Test that logic is included when requested."""
        result = get_aoi(registry, "Debounce", path="example.L5X", include_logic=True)
        assert "logic" in result
        logic = result["logic"]
        # Should have entries for each routine
        assert isinstance(logic, dict)
        assert len(logic) >= 2

    def test_get_aoi_logic_text(self, registry):
        """Test that logic text is valid RLL/ST text."""
        result = get_aoi(registry, "Debounce", path="example.L5X", include_logic=True)
        logic = result["logic"]
        # Each routine should have some text or None
        for _routine_name, text in logic.items():
            if text is not None:
                assert isinstance(text, str)
                # RLL routines should have some content
                assert len(text) > 0

    def test_get_aoi_json_serializable(self, registry):
        """Test that result is JSON serializable."""
        result = get_aoi(registry, "Debounce", path="example.L5X")
        json_str = json.dumps(result)
        assert json_str is not None
        assert len(json_str) > 0

    def test_get_aoi_json_serializable_with_logic(self, registry):
        """Test that result with logic is JSON serializable."""
        result = get_aoi(registry, "Debounce", path="example.L5X", include_logic=True)
        json_str = json.dumps(result)
        assert json_str is not None
        assert len(json_str) > 0

    def test_get_aoi_generic_input(self, registry):
        """Test get_aoi with another AOI type."""
        result = get_aoi(registry, "GenericInput", path="example.L5X")
        assert result["name"] == "GenericInput"
        assert len(result["parameters"]) > 0
        assert len(result["routines"]) > 0
        assert "call_signature" in result

    def test_get_aoi_all_aois_found(self, registry):
        """Test that all AOIs from list_aois can be fetched."""
        list_result = list_aois(registry, path="example.L5X")
        aois = list_result["aois"]
        for aoi_info in aois:
            aoi_name = aoi_info["name"]
            result = get_aoi(registry, aoi_name, path="example.L5X")
            assert result["name"] == aoi_name


class TestAOIComponent:
    """Tests for AOI functionality with component exports."""

    def test_get_aoi_from_component_export(self, registry):
        """Test getting AOI from a component export (Debounce_AOI.L5X)."""
        # Debounce_AOI.L5X should have just the Debounce AOI
        result = get_aoi(registry, "Debounce", path="Debounce_AOI.L5X")
        assert result["name"] == "Debounce"
        assert result["revision"] == "1.2"
        assert len(result["parameters"]) == 5
        assert len(result["local_tags"]) >= 2
        assert len(result["routines"]) >= 2

    def test_list_aois_in_component_export(self, registry):
        """Test listing AOIs from a component export."""
        result = list_aois(registry, path="Debounce_AOI.L5X")
        aois = result["aois"]
        # Should have exactly the Debounce AOI
        assert len(aois) == 1
        assert aois[0]["name"] == "Debounce"


class TestAOICallSignature:
    """Tests for AOI call signature generation."""

    def test_call_signature_format(self, registry):
        """Test that call signature is correctly formatted."""
        result = get_aoi(registry, "GenericInput", path="example.L5X")
        call_sig = result["call_signature"]
        # GenericInput has one required parameter: physicalInput
        # So signature should be: GenericInput(<instance>, physicalInput)
        assert call_sig.startswith("GenericInput(")
        assert "<instance>" in call_sig
        assert "physicalInput" in call_sig
        assert call_sig.endswith(")")

    def test_debounce_call_signature(self, registry):
        """Test Debounce call signature (no required parameters)."""
        result = get_aoi(registry, "Debounce", path="example.L5X")
        call_sig = result["call_signature"]
        # Debounce has no required parameters, so just the instance
        assert call_sig == "Debounce(<instance>)"

    def test_call_signature_ignores_hidden_parameters(self, registry):
        """Test that call signature ignores hidden parameters."""
        result = get_aoi(registry, "GenericInput", path="example.L5X")
        call_sig = result["call_signature"]
        # Hidden parameters like risingEdge, fallingEdge should not be in signature
        assert "risingEdge" not in call_sig
        assert "fallingEdge" not in call_sig
        # EnableIn/EnableOut should also not be present
        assert "EnableIn" not in call_sig
        assert "EnableOut" not in call_sig
