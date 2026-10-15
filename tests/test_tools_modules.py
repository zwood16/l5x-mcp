"""Tests for l5x_mcp.tools.modules."""

from __future__ import annotations

import json

import pytest

from l5x_mcp.registry import ItemNotFoundError, ProjectRegistry
from l5x_mcp.tools.modules import get_module, list_modules


@pytest.fixture
def fixture_registry(registry: ProjectRegistry) -> ProjectRegistry:
    """Return the session registry pointing to fixtures."""
    return registry


class TestListModules:
    """Tests for list_modules function."""

    def test_list_modules_returns_dict_with_file_key(self, fixture_registry):
        """list_modules returns dict with 'file' as first key."""
        result = list_modules(fixture_registry, path="example.L5X")
        assert isinstance(result, dict)
        assert "file" in result
        assert result["file"] == "example.L5X"

    def test_list_modules_has_modules_key(self, fixture_registry):
        """list_modules includes 'modules' key with list."""
        result = list_modules(fixture_registry, path="example.L5X")
        assert "modules" in result
        assert isinstance(result["modules"], list)
        assert len(result["modules"]) > 0

    def test_list_modules_has_tree_key(self, fixture_registry):
        """list_modules includes 'tree' key with indented text."""
        result = list_modules(fixture_registry, path="example.L5X")
        assert "tree" in result
        assert isinstance(result["tree"], str)
        assert "Local" in result["tree"]
        assert "5069-L310ERMS3" in result["tree"]

    def test_list_modules_tree_contains_all_modules(self, fixture_registry):
        """Tree view includes all modules in the project (each exactly once)."""
        result = list_modules(fixture_registry, path="example.L5X")
        tree = result["tree"]
        modules = result["modules"]
        module_names = [m["name"] for m in modules]

        for name in module_names:
            count = tree.count(name)
            assert count == 1, (
                f"Module {name} appears {count} times in tree (expected 1)"
            )

    def test_list_modules_local_controller(self, fixture_registry):
        """Local (controller) module is listed with correct catalog and slot 0."""
        result = list_modules(fixture_registry, path="example.L5X")
        modules = {m["name"]: m for m in result["modules"]}

        assert "Local" in modules
        local = modules["Local"]
        assert local["catalog_number"] == "5069-L310ERMS3"
        assert local["parent_module"] == "Local"  # Controller points to itself
        assert local["address"] == "slot 0"

    def test_list_modules_shop_robot_address(self, fixture_registry):
        """ShopRobot has correct Ethernet address."""
        result = list_modules(fixture_registry, path="example.L5X")
        modules = {m["name"]: m for m in result["modules"]}

        assert "ShopRobot" in modules
        shop = modules["ShopRobot"]
        assert shop["catalog_number"] == "ETHERNET-MODULE"
        assert shop["address"] == "192.168.0.3"
        assert shop["parent_module"] == "Local"
        assert shop["parent_port"] == "3"

    def test_list_modules_test_input_module(self, fixture_registry):
        """Test_Input_Module is nested on Local with correct address (slot 1)."""
        result = list_modules(fixture_registry, path="example.L5X")
        modules = {m["name"]: m for m in result["modules"]}

        assert "Test_Input_Module" in modules
        test_input = modules["Test_Input_Module"]
        assert test_input["catalog_number"] == "5069-IB16/A"
        assert test_input["parent_module"] == "Local"
        assert test_input["parent_port"] == "1"
        assert test_input["address"] == "slot 1"

    def test_list_modules_test_safety_input(self, fixture_registry):
        """Test_Safety_Input has correct slot address."""
        result = list_modules(fixture_registry, path="example.L5X")
        modules = {m["name"]: m for m in result["modules"]}

        assert "Test_Safety_Input" in modules
        safety = modules["Test_Safety_Input"]
        assert safety["address"] == "slot 2"

    def test_list_modules_valve_bank_address(self, fixture_registry):
        """ValveBank has correct Ethernet address."""
        result = list_modules(fixture_registry, path="example.L5X")
        modules = {m["name"]: m for m in result["modules"]}

        assert "ValveBank" in modules
        valve = modules["ValveBank"]
        assert valve["address"] == "192.168.1.5"

    def test_list_modules_test_servo_drive_address(self, fixture_registry):
        """Test_Servo_Drive has correct Ethernet address."""
        result = list_modules(fixture_registry, path="example.L5X")
        modules = {m["name"]: m for m in result["modules"]}

        assert "Test_Servo_Drive" in modules
        servo = modules["Test_Servo_Drive"]
        assert servo["address"] == "192.168.1.6"

    def test_list_modules_tree_format(self, fixture_registry):
        """Tree output matches expected format (no duplicates, correct addresses)."""
        result = list_modules(fixture_registry, path="example.L5X")
        tree = result["tree"]
        lines = tree.split("\n")

        # Should have at least 7 modules (Local + 6 children)
        assert len(lines) >= 7, f"Tree has {len(lines)} lines, expected at least 7"

        # Local should be first with slot 0
        assert "Local [5069-L310ERMS3] @ slot 0" in tree

        # Check critical modules with addresses
        assert "Test_Input_Module [5069-IB16/A] @ slot 1" in tree
        assert "Test_Safety_Input [5069-IB8S/A] @ slot 2" in tree
        assert "ShopRobot [ETHERNET-MODULE] @ 192.168.0.3" in tree
        assert "ValveBank [EX600-SEN7/8] @ 192.168.1.5" in tree
        assert "Test_Servo_Drive [2198-H003-ERS2] @ 192.168.1.6" in tree
        """All expected modules with correct catalog numbers."""
        result = list_modules(fixture_registry, path="example.L5X")
        modules = {m["name"]: m for m in result["modules"]}

        expected = {
            "Local": "5069-L310ERMS3",
            "Test_Input_Module": "5069-IB16/A",
            "Test_Safety_Input": "5069-IB8S/A",
            "ShopRobot": "ETHERNET-MODULE",
            "AnotherPLC": "5069-L306ER",
            "ValveBank": "EX600-SEN7/8",
            "Test_Servo_Drive": "2198-H003-ERS2",
        }

        for name, catalog in expected.items():
            assert name in modules, f"Module {name} not found"
            assert modules[name]["catalog_number"] == catalog, (
                f"Module {name} has wrong catalog: {modules[name]['catalog_number']}"
            )

    def test_list_modules_inhibited_only_when_true(self, fixture_registry):
        """inhibited flag only present when True."""
        result = list_modules(fixture_registry, path="example.L5X")
        for mod in result["modules"]:
            # Check that inhibited is not present or is True
            if "inhibited" in mod:
                assert mod["inhibited"] is True

    def test_list_modules_json_serializable(self, fixture_registry):
        """Result is JSON serializable."""
        result = list_modules(fixture_registry, path="example.L5X")
        # Should not raise
        json_str = json.dumps(result)
        assert len(json_str) > 0


class TestGetModule:
    """Tests for get_module function."""

    def test_get_module_returns_dict_with_file_key(self, fixture_registry):
        """get_module returns dict with 'file' as first key."""
        result = get_module(fixture_registry, "ShopRobot", path="example.L5X")
        assert isinstance(result, dict)
        assert "file" in result
        assert result["file"] == "example.L5X"

    def test_get_module_shoprobot_basic_info(self, fixture_registry):
        """get_module ShopRobot returns correct basic info."""
        result = get_module(fixture_registry, "ShopRobot", path="example.L5X")

        assert result["name"] == "ShopRobot"
        assert result["catalog_number"] == "ETHERNET-MODULE"
        assert result["parent_module"] == "Local"
        assert result["parent_port"] == "3"
        assert result["address"] == "192.168.0.3"

    def test_get_module_shoprobot_ports(self, fixture_registry):
        """get_module ShopRobot has correct port info."""
        result = get_module(fixture_registry, "ShopRobot", path="example.L5X")

        assert "ports" in result
        ports = result["ports"]
        assert len(ports) > 0

        # Port 2 should have the Ethernet address
        port_2 = next((p for p in ports if p["id"] == 2), None)
        assert port_2 is not None
        assert port_2["type"] == "Ethernet"
        assert port_2["address"] == "192.168.0.3"
        assert port_2["upstream"] is True

    def test_get_module_shoprobot_communications(self, fixture_registry):
        """get_module ShopRobot has communications section."""
        result = get_module(fixture_registry, "ShopRobot", path="example.L5X")

        assert "communications" in result
        comms = result["communications"]
        assert comms is not None
        assert "connections" in comms

        # Should have at least one connection
        connections = comms["connections"]
        assert len(connections) > 0

        # Check Standard connection
        standard = next((c for c in connections if c["name"] == "Standard"), None)
        assert standard is not None
        assert standard["type"] == "Output"
        assert standard["rpi"] == 10000
        assert standard["unicast"] is True

    def test_get_module_shoprobot_input_output_tags(self, fixture_registry):
        """get_module ShopRobot connection has input/output tags."""
        result = get_module(fixture_registry, "ShopRobot", path="example.L5X")

        connections = result["communications"]["connections"]
        standard = next(c for c in connections if c["name"] == "Standard")

        assert "input_tag" in standard
        assert standard["input_tag"] is not None
        assert "data_type" in standard["input_tag"]

        assert "output_tag" in standard
        assert standard["output_tag"] is not None
        assert "data_type" in standard["output_tag"]

    def test_get_module_without_include_data(self, fixture_registry):
        """Without include_data, tags show data_type but no value_tree."""
        result = get_module(
            fixture_registry, "ShopRobot", include_data=False, path="example.L5X"
        )

        connections = result["communications"]["connections"]
        standard = next(c for c in connections if c["name"] == "Standard")

        # Should have data_type
        assert "data_type" in standard["input_tag"]

        # Should NOT have value_tree
        assert "value_tree" not in standard["input_tag"]

    def test_get_module_with_include_data(self, fixture_registry):
        """With include_data, tags include value_tree."""
        result = get_module(
            fixture_registry,
            "ShopRobot",
            include_data=True,
            max_depth=2,
            max_elements=32,
            path="example.L5X",
        )

        connections = result["communications"]["connections"]
        standard = next(c for c in connections if c["name"] == "Standard")

        # Should have value_tree
        assert "value_tree" in standard["input_tag"]
        value_tree = standard["input_tag"]["value_tree"]
        assert "kind" in value_tree
        assert "data_type" in value_tree

    def test_get_module_local_controller(self, fixture_registry):
        """get_module Local (controller) works correctly."""
        result = get_module(fixture_registry, "Local", path="example.L5X")

        assert result["name"] == "Local"
        assert result["catalog_number"] == "5069-L310ERMS3"
        assert result["parent_module"] == "Local"
        assert result["parent_port"] == "1"
        assert result["address"] == "slot 0"

    def test_get_module_local_children(self, fixture_registry):
        """get_module Local lists all child modules."""
        result = get_module(fixture_registry, "Local", path="example.L5X")

        assert "children" in result
        children = result["children"]
        expected_children = {
            "Test_Input_Module",
            "Test_Safety_Input",
            "ShopRobot",
            "AnotherPLC",
            "ValveBank",
            "Test_Servo_Drive",
        }
        assert set(children) == expected_children

    def test_get_module_test_input_module(self, fixture_registry):
        """get_module Test_Input_Module works correctly."""
        result = get_module(fixture_registry, "Test_Input_Module", path="example.L5X")

        assert result["name"] == "Test_Input_Module"
        assert result["catalog_number"] == "5069-IB16/A"

        # Should have communications
        assert "communications" in result
        comms = result["communications"]
        assert comms is not None

    def test_get_module_case_insensitive(self, fixture_registry):
        """get_module lookup is case-insensitive."""
        result1 = get_module(fixture_registry, "ShopRobot", path="example.L5X")
        result2 = get_module(fixture_registry, "shoprobot", path="example.L5X")

        assert result1["name"] == result2["name"]

    def test_get_module_unknown_name_raises(self, fixture_registry):
        """get_module raises ItemNotFoundError for unknown module."""
        with pytest.raises(ItemNotFoundError):
            get_module(fixture_registry, "NonexistentModule", path="example.L5X")

    def test_get_module_all_modules_include_data_true(self, fixture_registry):
        """Every module works with include_data=True."""
        result = list_modules(fixture_registry, path="example.L5X")
        for mod in result["modules"]:
            name = mod["name"]
            # Should not raise
            mod_detail = get_module(
                fixture_registry, name, include_data=True, path="example.L5X"
            )
            assert mod_detail["name"] == name

    def test_get_module_all_modules_include_data_false(self, fixture_registry):
        """Every module works with include_data=False."""
        result = list_modules(fixture_registry, path="example.L5X")
        for mod in result["modules"]:
            name = mod["name"]
            # Should not raise
            mod_detail = get_module(
                fixture_registry, name, include_data=False, path="example.L5X"
            )
            assert mod_detail["name"] == name

    def test_get_module_json_serializable(self, fixture_registry):
        """Result is JSON serializable."""
        result = get_module(
            fixture_registry, "ShopRobot", include_data=True, path="example.L5X"
        )
        # Should not raise
        json_str = json.dumps(result)
        assert len(json_str) > 0

    def test_get_module_test_servo_drive(self, fixture_registry):
        """get_module Test_Servo_Drive with multiple connections."""
        result = get_module(fixture_registry, "Test_Servo_Drive", path="example.L5X")

        assert result["name"] == "Test_Servo_Drive"
        assert result["catalog_number"] == "2198-H003-ERS2"

        # Should have communications with multiple connections
        assert "communications" in result
        comms = result["communications"]
        connections = comms["connections"]
        assert (
            len(connections) >= 3
        )  # AMotionDiagnostics, BMotionSync, CSafety_Output, DSafety_Input

    def test_get_module_vendor_and_codes(self, fixture_registry):
        """get_module includes vendor and product codes."""
        result = get_module(fixture_registry, "ShopRobot", path="example.L5X")

        # These fields might be empty but should be present or compact()d away
        assert "vendor" not in result or isinstance(result["vendor"], str)
        assert "product_type" not in result or isinstance(result["product_type"], str)
        assert "product_code" not in result or isinstance(result["product_code"], str)

    def test_get_module_revision_format(self, fixture_registry):
        """get_module revision is in major.minor format."""
        result = get_module(fixture_registry, "ShopRobot", path="example.L5X")

        if "revision" in result:
            assert isinstance(result["revision"], str)
            # Should be like "1.1" if both major and minor present
            if "." in result["revision"]:
                parts = result["revision"].split(".")
                assert len(parts) == 2

    def test_get_module_safety_enabled_field(self, fixture_registry):
        """get_module includes safety_enabled if present."""
        result = get_module(fixture_registry, "Test_Safety_Input", path="example.L5X")

        # safety_enabled might be present, None, or omitted
        if "safety_enabled" in result:
            assert result["safety_enabled"] in [True, False, None]

    def test_get_module_ekey_state_field(self, fixture_registry):
        """get_module includes ekey_state."""
        result = get_module(fixture_registry, "ShopRobot", path="example.L5X")

        # ekey_state might be empty or present
        if "ekey_state" in result:
            assert isinstance(result["ekey_state"], str)

    def test_get_module_tag_member_names_without_data(self, fixture_registry):
        """Without include_data, structure tags show member_names."""
        result = get_module(
            fixture_registry, "ShopRobot", include_data=False, path="example.L5X"
        )

        connections = result["communications"]["connections"]
        standard = next(c for c in connections if c["name"] == "Standard")

        # Input tag should show member_names if structure
        input_tag = standard["input_tag"]
        if input_tag and "member_names" in input_tag:
            assert isinstance(input_tag["member_names"], list)

    def test_get_module_port_with_bus_size(self, fixture_registry):
        """get_module ports include bus_size when available."""
        result = get_module(fixture_registry, "Local", path="example.L5X")

        ports = result["ports"]
        assert len(ports) > 0

        # Ports might have bus_size or not
        for port in ports:
            if "bus_size" in port:
                assert port["bus_size"] is None or isinstance(port["bus_size"], int)
