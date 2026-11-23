"""Tests for aois tool module."""

import json

import pytest

from l5x_mcp.registry import ItemNotFoundError, L5XError
from l5x_mcp.tools.aois import get_aoi, list_aois
from l5x_mcp.tools.programs import MAX_CHARS_DEFAULT


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


class TestAOIParameterDetails:
    """Typed vs plain AOI parameters and their value-level fields."""

    def test_typed_input_has_min_max_and_engineering_unit(self, registry):
        """Typed Input params expose min/max/engineering_unit; min 0 is kept."""
        result = get_aoi(registry, "Debounce", path="example.L5X")
        on_delay = next(p for p in result["parameters"] if p["name"] == "onDelay")
        assert on_delay["usage"] == "Input"
        assert on_delay["min"] == 0
        assert on_delay["max"] == 2147483647
        assert on_delay["engineering_unit"] == "ms"

    def test_typed_bool_output_has_state_labels(self, registry):
        """Typed BOOL params expose state0/state1."""
        result = get_aoi(registry, "Debounce", path="example.L5X")
        state = next(p for p in result["parameters"] if p["name"] == "state")
        assert state["usage"] == "Output"
        assert state["state0"] == "off"
        assert state["state1"] == "on"

    def test_enable_in_has_no_value_fields(self, registry):
        """EnableIn/EnableOut (plain params) omit value-only fields."""
        result = get_aoi(registry, "Debounce", path="example.L5X")
        enable_in = next(p for p in result["parameters"] if p["name"] == "EnableIn")
        for key in ("min", "max", "state0", "state1", "engineering_unit"):
            assert key not in enable_in
        assert enable_in["radix"] == "Decimal"
        assert "dimensions" not in enable_in

    def test_inout_parameter_is_plain_without_value_fields(self, registry):
        """InOut parameters are plain and have no min/max/state fields."""
        result = get_aoi(registry, "FanucRobot", path="example.L5X")
        seq = next(p for p in result["parameters"] if p["name"] == "seq")
        assert seq["usage"] == "InOut"
        assert seq["data_type"] == "SeqCtrl"
        assert seq["required"] is True
        for key in ("min", "max", "state0", "state1", "engineering_unit"):
            assert key not in seq

    def test_inout_parameter_operand_comments(self, registry):
        """InOut operand comments (per-member faults) are exposed."""
        result = get_aoi(registry, "FanucRobot", path="example.L5X")
        seq = next(p for p in result["parameters"] if p["name"] == "seq")
        assert seq["operand_comments"][".FAULT.0"] == (
            "Robot fault did not reset when running"
        )
        assert seq["operand_comments"][".FAULT.11"] == "Robot did not Hold (pause)"

    def test_typed_parameter_operand_comments(self, registry):
        """Typed params expose operand comments such as enumerated state labels."""
        result = get_aoi(registry, "SeqCtrl", path="example.L5X")
        state = next(p for p in result["parameters"] if p["name"] == "state")
        assert state["operand_comments"][".0"] == "running"
        assert state["operand_comments"][".6"] == "aborted"

    def test_parameter_without_comments_omits_operand_comments(self, registry):
        """No operand_comments key when a parameter has none."""
        result = get_aoi(registry, "Debounce", path="example.L5X")
        on_delay = next(p for p in result["parameters"] if p["name"] == "onDelay")
        assert "operand_comments" not in on_delay

    def test_inout_array_parameter_dimensions(self, registry):
        """An InOut array parameter reports its dimensions as a list of ints."""
        result = get_aoi(registry, "FanucRobot", path="example.L5X")
        alarms = next(p for p in result["parameters"] if p["name"] == "allowableAlarms")
        assert alarms["dimensions"] == [20]
        assert alarms["data_type"] == "robotAlarmCode"

    def test_full_result_with_parameters_is_json_serializable(self, registry):
        """get_aoi output for an AOI with mixed parameter types is JSON-safe."""
        result = get_aoi(registry, "FanucRobot", path="example.L5X")
        json.dumps(result)
        assert len(result["parameters"]) == 13


def _logic_size(logic: dict) -> int:
    return len(json.dumps(logic, separators=(",", ":"), ensure_ascii=False))


class TestGetAOILogicBudget:
    """max_chars budget for get_aoi(include_logic=True)."""

    def test_whole_response_within_default_budget(self, registry):
        result = get_aoi(registry, "FanucRobot", include_logic=True, path="example.L5X")
        assert _logic_size(result) <= MAX_CHARS_DEFAULT
        # FanucRobot's Logic routine does not fit next to its parameters.
        assert result["logic"] == {}
        assert result["logic_omitted"] == ["Logic"]
        assert 'get_routine_logic(routine=<name>, aoi="FanucRobot")' in result["note"]

    def test_logic_included_when_it_fits(self, registry):
        result = get_aoi(
            registry,
            "FanucRobot",
            include_logic=True,
            max_chars=20000,
            path="example.L5X",
        )
        assert list(result["logic"]) == ["Logic"]
        assert "logic_omitted" not in result
        assert "note" not in result
        assert _logic_size(result) <= 20000

    def test_routines_included_in_order_until_budget(self, registry):
        # Debounce has EnableInFalse then the larger Logic routine; with a budget
        # just above the non-logic part only the first routine fits.
        base = _logic_size(get_aoi(registry, "Debounce", path="example.L5X"))
        result = get_aoi(
            registry,
            "Debounce",
            include_logic=True,
            max_chars=base + 1000,
            path="example.L5X",
        )
        assert list(result["logic"]) == ["EnableInFalse"]
        assert result["logic_omitted"] == ["Logic"]
        assert _logic_size(result) <= base + 1000

    @pytest.mark.parametrize("max_chars", [1000, 2000, 8000, 30000])
    @pytest.mark.parametrize(
        "aoi", ["Debounce", "GenericInput", "SeqCtrl", "FanucRobot"]
    )
    def test_response_never_exceeds_budget(self, registry, aoi, max_chars):
        result = get_aoi(
            registry, aoi, include_logic=True, max_chars=max_chars, path="example.L5X"
        )
        base = _logic_size(get_aoi(registry, aoi, path="example.L5X"))
        if base + 400 <= max_chars:
            assert _logic_size(result) <= max_chars
        else:
            assert result["logic"] == {}

    def test_no_budget_keys_without_include_logic(self, registry):
        result = get_aoi(registry, "Debounce", path="example.L5X")
        assert "logic" not in result
        assert "logic_omitted" not in result

    @pytest.mark.parametrize("max_chars", [999, 100001, "8000"])
    def test_invalid_max_chars_rejected(self, registry, max_chars):
        with pytest.raises(L5XError):
            get_aoi(
                registry,
                "Debounce",
                include_logic=True,
                max_chars=max_chars,
                path="example.L5X",
            )


PROTECTED = "example.L5X"


class TestProtectedAois:
    """The source-protected AOI SeqCtrl_Protected (EncodedData) in example.L5X."""

    def test_list_aois_flags_protected(self, registry):
        result = list_aois(registry, path=PROTECTED)
        by_name = {a["name"]: a for a in result["aois"]}
        assert by_name["SeqCtrl_Protected"] == {
            "name": "SeqCtrl_Protected",
            "protected": True,
            "revision": "3.3",
            "parameter_count": 34,
        }
        # The readable SeqCtrl is a normal AOI.
        assert "protected" not in by_name["SeqCtrl"]
        assert "routines" in by_name["SeqCtrl"]

    def test_get_aoi_protected_renders_parameters(self, registry):
        result = get_aoi(registry, "seqctrl_protected", path=PROTECTED)
        assert result["protected"] is True
        assert result["revision"] == "3.3"
        assert result["class"] == "Standard"
        assert result["signature_id"]
        assert result["software_revision"] == "v37.00"
        assert "edited_date" in result
        assert len(result["parameters"]) == 34
        param = next(p for p in result["parameters"] if p["name"] == "autoModeOverride")
        assert param["data_type"] == "BOOL"
        assert param["usage"] == "Output"
        assert param["description"].startswith("Optional bit to externally")
        enable_in = next(p for p in result["parameters"] if p["name"] == "EnableIn")
        assert enable_in["visible"] is False
        assert "source-protected" in result["note"]
        assert "routines" not in result
        assert "local_tags" not in result

    def test_get_aoi_protected_include_logic_gives_no_logic(self, registry):
        result = get_aoi(
            registry, "SeqCtrl_Protected", include_logic=True, path=PROTECTED
        )
        assert "logic" not in result
        assert "not readable" in result["note"]

    def test_get_aoi_protected_parameters_match_normal_serialization(self, registry):
        """Protected parameters use the same fields as a normal AOI's."""
        normal = get_aoi(registry, "SeqCtrl", path=PROTECTED)["parameters"]
        protected = get_aoi(registry, "SeqCtrl_Protected", path=PROTECTED)["parameters"]
        assert set(protected[0]) <= set().union(*(p.keys() for p in normal))
