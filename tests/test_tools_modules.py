"""Tests for l5x_mcp.tools.modules against the refreshed example.L5X fixture."""

from __future__ import annotations

import json

import pytest

from l5x_mcp.registry import ItemNotFoundError, ProjectRegistry
from l5x_mcp.tools.modules import get_module, list_modules

#: Expected tree text, derived from the fixture's real topology.
EXPECTED_TREE = """\
Local [5069-L310ERMS3] @ slot 0
  Test_Input_Module [5069-IB16/A] @ slot 1
  Test_Safety_Input [5069-IB8S/A] @ slot 2
  Fast_Local_Input [5069-IB16F/A] @ slot 3
  ShopRobot [ETHERNET-MODULE] @ 192.168.0.3
  AnotherPLC [5069-L306ER] @ 192.168.1.4
  ValveBank [EX600-SEN7/8] @ 192.168.1.5
  Test_Servo_Drive [2198-H003-ERS2] @ 192.168.1.6
  PointIO [1734-AENTR/B] @ 192.168.1.7
    PointIO_Input [1734-IB8/C] @ slot 1
    PointIO_Output [1734-OB8/C] @ slot 2
    PointIO_AnalogInput [1734-IE2V/C] @ slot 3
    PointIO_AnalogOutput [1734-OE2V/C] @ slot 4
    PointIO_SafetyInput [1734-IB8S/B] @ slot 5
    PointIO_SafetyOutput [1734-OB8S/B] @ slot 6
  Compact5000_IO_Adapter [5069-AENTR] @ 192.168.1.8
    Remote_Output [5069-OB16/B] @ slot 1"""

#: Expected tag_prefix for every module in the fixture.
EXPECTED_TAG_PREFIX = {
    "Local": "Local",
    "Test_Input_Module": "Local:1",
    "Test_Safety_Input": "Local:2",
    "Fast_Local_Input": "Local:3",
    "ShopRobot": "ShopRobot",
    "AnotherPLC": "AnotherPLC",
    "ValveBank": "ValveBank",
    "Test_Servo_Drive": "Test_Servo_Drive",
    "PointIO": "PointIO",
    "PointIO_Input": "PointIO:1",
    "PointIO_Output": "PointIO:2",
    "PointIO_AnalogInput": "PointIO:3",
    "PointIO_AnalogOutput": "PointIO:4",
    "PointIO_SafetyInput": "PointIO:5",
    "PointIO_SafetyOutput": "PointIO:6",
    "Compact5000_IO_Adapter": "Compact5000_IO_Adapter",
    "Remote_Output": "Compact5000_IO_Adapter:1",
}


@pytest.fixture
def fixture_registry(registry: ProjectRegistry) -> ProjectRegistry:
    """Return the session registry pointing to fixtures."""
    return registry


def _modules_by_name(result: dict) -> dict[str, dict]:
    """Index list_modules output by module name."""
    return {m["name"]: m for m in result["modules"]}


class TestListModules:
    """Tests for list_modules function."""

    def test_list_modules_returns_dict_with_file_key(self, fixture_registry):
        """list_modules returns dict with 'file' as first key."""
        result = list_modules(fixture_registry, path="example.L5X")
        assert isinstance(result, dict)
        assert "file" in result
        assert result["file"] == "example.L5X"

    def test_list_modules_has_all_seventeen_modules(self, fixture_registry):
        """Every module in the refreshed fixture is listed."""
        result = list_modules(fixture_registry, path="example.L5X")
        assert set(_modules_by_name(result)) == set(EXPECTED_TAG_PREFIX)
        assert len(result["modules"]) == 17

    def test_tree_text_matches_topology(self, fixture_registry):
        """The tree matches the fixture topology exactly."""
        result = list_modules(fixture_registry, path="example.L5X")
        assert result["tree"] == EXPECTED_TREE

    def test_each_module_appears_once_in_tree(self, fixture_registry):
        """Each module is rendered as exactly one tree line."""
        result = list_modules(fixture_registry, path="example.L5X")
        lines = [line.strip() for line in result["tree"].split("\n")]
        # Name is the text before any " [" catalog or " @" address.
        names = [line.split(" [")[0].split(" @")[0] for line in lines]
        for name in EXPECTED_TAG_PREFIX:
            assert names.count(name) == 1, f"{name} not listed exactly once"
        assert len(names) == len(EXPECTED_TAG_PREFIX)

    def test_tree_omits_empty_catalog_brackets(self, fixture_registry):
        """No module renders empty brackets (every fixture module has a catalog)."""
        result = list_modules(fixture_registry, path="example.L5X")
        assert "ValveBank [EX600-SEN7/8] @ 192.168.1.5" in result["tree"]
        assert "[]" not in result["tree"]

    def test_remote_rack_nests_under_adapter(self, fixture_registry):
        """Remote_Output is indented under Compact5000_IO_Adapter with slot 1."""
        result = list_modules(fixture_registry, path="example.L5X")
        lines = result["tree"].split("\n")
        adapter = lines.index("  Compact5000_IO_Adapter [5069-AENTR] @ 192.168.1.8")
        assert lines[adapter + 1] == "    Remote_Output [5069-OB16/B] @ slot 1"

    def test_ethernet_devices_show_ip_in_tree(self, fixture_registry):
        """Ethernet-attached modules show their IP address in the tree."""
        result = list_modules(fixture_registry, path="example.L5X")
        tree = result["tree"]
        assert "ShopRobot [ETHERNET-MODULE] @ 192.168.0.3" in tree
        assert "Test_Servo_Drive [2198-H003-ERS2] @ 192.168.1.6" in tree
        assert "PointIO [1734-AENTR/B] @ 192.168.1.7" in tree

    @pytest.mark.parametrize(
        ("name", "expected"),
        sorted(EXPECTED_TAG_PREFIX.items()),
    )
    def test_tag_prefix_per_module(self, fixture_registry, name, expected):
        """Each module reports the prefix of its I/O tag names."""
        modules = _modules_by_name(list_modules(fixture_registry, path="example.L5X"))
        assert modules[name]["tag_prefix"] == expected

    def test_list_modules_local_controller(self, fixture_registry):
        """Local (controller) is listed with its catalog and slot 0."""
        modules = _modules_by_name(list_modules(fixture_registry, path="example.L5X"))
        local = modules["Local"]
        assert local["catalog_number"] == "5069-L310ERMS3"
        assert local["parent_module"] == "Local"  # Controller points to itself
        assert local["address"] == "slot 0"

    def test_list_modules_shop_robot_address(self, fixture_registry):
        """ShopRobot has its Ethernet address and parent port 3."""
        modules = _modules_by_name(list_modules(fixture_registry, path="example.L5X"))
        shop = modules["ShopRobot"]
        assert shop["catalog_number"] == "ETHERNET-MODULE"
        assert shop["address"] == "192.168.0.3"
        assert shop["parent_module"] == "Local"
        assert shop["parent_port"] == "3"

    def test_list_modules_remote_module_address(self, fixture_registry):
        """Remote_Output's parent is the adapter and its address is its slot."""
        modules = _modules_by_name(list_modules(fixture_registry, path="example.L5X"))
        remote = modules["Remote_Output"]
        assert remote["parent_module"] == "Compact5000_IO_Adapter"
        assert remote["parent_port"] == "1"
        assert remote["address"] == "slot 1"

    def test_inhibited_only_when_true(self, fixture_registry):
        """inhibited / major_fault keys only appear when True."""
        result = list_modules(fixture_registry, path="example.L5X")
        for mod in result["modules"]:
            if "inhibited" in mod:
                assert mod["inhibited"] is True
            if "major_fault" in mod:
                assert mod["major_fault"] is True

    def test_list_modules_json_serializable(self, fixture_registry):
        """Result is JSON serializable."""
        result = list_modules(fixture_registry, path="example.L5X")
        assert len(json.dumps(result)) > 0


class TestGetModule:
    """Tests for get_module function."""

    def test_get_module_returns_dict_with_file_key(self, fixture_registry):
        """get_module returns dict with 'file' as first key."""
        result = get_module(fixture_registry, "ShopRobot", path="example.L5X")
        assert isinstance(result, dict)
        assert "file" in result
        assert result["file"] == "example.L5X"

    def test_get_module_shoprobot_basic_info(self, fixture_registry):
        """get_module ShopRobot returns identity, hierarchy and tag prefix."""
        result = get_module(fixture_registry, "ShopRobot", path="example.L5X")

        assert result["name"] == "ShopRobot"
        assert result["catalog_number"] == "ETHERNET-MODULE"
        assert result["revision"] == "1.1"
        assert result["parent_module"] == "Local"
        assert result["parent_port"] == "3"
        assert result["address"] == "192.168.0.3"
        assert result["tag_prefix"] == "ShopRobot"

    def test_get_module_shoprobot_ports(self, fixture_registry):
        """get_module ShopRobot has its Ethernet port marked upstream."""
        result = get_module(fixture_registry, "ShopRobot", path="example.L5X")

        port_2 = next(p for p in result["ports"] if p["id"] == 2)
        assert port_2["type"] == "Ethernet"
        assert port_2["address"] == "192.168.0.3"
        assert port_2["upstream"] is True

    def test_get_module_shoprobot_io_tag_names(self, fixture_registry):
        """ShopRobot exposes its config, input and output tags by global name."""
        result = get_module(fixture_registry, "ShopRobot", path="example.L5X")

        io_tags = result["io_tags"]
        assert [t["name"] for t in io_tags] == [
            "ShopRobot:C",
            "ShopRobot:I",
            "ShopRobot:O",
        ]
        assert [t["kind"] for t in io_tags] == ["C", "I", "O"]

    def test_get_module_shoprobot_io_tag_connections(self, fixture_registry):
        """Config tag has no connection; input and output belong to Standard."""
        io_tags = {
            t["name"]: t
            for t in get_module(fixture_registry, "ShopRobot", path="example.L5X")[
                "io_tags"
            ]
        }
        assert "connection" not in io_tags["ShopRobot:C"]
        assert io_tags["ShopRobot:I"]["connection"] == "Standard"
        assert io_tags["ShopRobot:O"]["connection"] == "Standard"

    def test_get_module_shoprobot_io_tag_summaries(self, fixture_registry):
        """Without include_data, io tags give data_type and member/element summaries."""
        io_tags = {
            t["name"]: t
            for t in get_module(fixture_registry, "ShopRobot", path="example.L5X")[
                "io_tags"
            ]
        }
        assert io_tags["ShopRobot:I"]["data_type"] == (
            "AB:ETHERNET_MODULE_SINT_260Bytes:I:0"
        )
        assert io_tags["ShopRobot:I"]["members"] == ["Data"]
        assert io_tags["ShopRobot:O"]["members"] == ["Data"]
        assert io_tags["ShopRobot:C"]["element_count"] == 400
        for tag in io_tags.values():
            assert "value_tree" not in tag

    def test_get_module_shoprobot_connection(self, fixture_registry):
        """The Standard connection carries timing and sizes, and names its io tags."""
        result = get_module(fixture_registry, "ShopRobot", path="example.L5X")

        assert result["communications"]["config_tag"] == "ShopRobot:C"
        connections = result["communications"]["connections"]
        assert len(connections) == 1
        standard = connections[0]
        assert standard["name"] == "Standard"
        assert standard["type"] == "Output"
        assert standard["rpi"] == 10000
        assert standard["unicast"] is True
        assert standard["input_size"] == 260
        assert standard["output_size"] == 52
        assert standard["io_tags"] == ["ShopRobot:I", "ShopRobot:O"]

    def test_get_module_connection_tags_are_not_duplicated(self, fixture_registry):
        """Connections reference io tags by name and carry no tag data."""
        result = get_module(
            fixture_registry, "ShopRobot", include_data=True, path="example.L5X"
        )
        standard = result["communications"]["connections"][0]
        assert all(isinstance(name, str) for name in standard["io_tags"])
        assert "value_tree" not in standard
        assert "data_type" not in standard

    def test_get_module_connection_refs_resolve_to_io_tags(self, fixture_registry):
        """Every connection's io_tags name is one of the module's io tags."""
        for name in _all_module_names(fixture_registry):
            result = get_module(fixture_registry, name, path="example.L5X")
            io_names = {t["name"] for t in result.get("io_tags", [])}
            comms = result.get("communications") or {}
            refs = [comms.get("config_tag")]
            for conn in comms.get("connections", []):
                refs += conn.get("io_tags", [])
            for ref in refs:
                if ref is not None:
                    assert ref in io_names, f"{name}: {ref} not in io_tags"

    def test_get_module_without_include_data(self, fixture_registry):
        """Without include_data, io tags have no value_tree."""
        result = get_module(
            fixture_registry, "ShopRobot", include_data=False, path="example.L5X"
        )
        for tag in result["io_tags"]:
            assert "value_tree" not in tag

    def test_get_module_with_include_data(self, fixture_registry):
        """With include_data, every io tag carries a value_tree."""
        result = get_module(
            fixture_registry,
            "ShopRobot",
            include_data=True,
            max_depth=2,
            max_elements=32,
            path="example.L5X",
        )
        for tag in result["io_tags"]:
            assert "value_tree" in tag
            assert "kind" in tag["value_tree"]
            assert "data_type" in tag["value_tree"]

        input_tree = next(
            t["value_tree"] for t in result["io_tags"] if t["name"] == "ShopRobot:I"
        )
        assert input_tree["kind"] == "structure"
        assert "Data" in input_tree["members"]

    def test_get_module_value_tree_for_every_module_with_io_tags(
        self, fixture_registry
    ):
        """include_data gives a value_tree for every io tag of every module."""
        checked = 0
        for name in _all_module_names(fixture_registry):
            result = get_module(
                fixture_registry, name, include_data=True, path="example.L5X"
            )
            for tag in result.get("io_tags", []):
                assert "value_tree" in tag, f"{name} {tag['name']} has no value_tree"
                checked += 1
        assert checked > 0

    def test_get_module_local_controller(self, fixture_registry):
        """get_module Local (controller) works correctly."""
        result = get_module(fixture_registry, "Local", path="example.L5X")

        assert result["name"] == "Local"
        assert result["catalog_number"] == "5069-L310ERMS3"
        assert result["parent_module"] == "Local"
        assert result["parent_port"] == "1"
        assert result["address"] == "slot 0"
        assert result["tag_prefix"] == "Local"
        assert "io_tags" not in result  # Controller has no I/O tags

    def test_get_module_local_children(self, fixture_registry):
        """get_module Local lists all direct child modules."""
        result = get_module(fixture_registry, "Local", path="example.L5X")

        assert result["children"] == sorted(
            [
                "Test_Input_Module",
                "Test_Safety_Input",
                "Fast_Local_Input",
                "ShopRobot",
                "AnotherPLC",
                "ValveBank",
                "Test_Servo_Drive",
                "PointIO",
                "Compact5000_IO_Adapter",
            ]
        )

    def test_get_module_adapter_children(self, fixture_registry):
        """A remote adapter lists its remote rack module as a child."""
        result = get_module(
            fixture_registry, "Compact5000_IO_Adapter", path="example.L5X"
        )
        assert result["children"] == ["Remote_Output"]
        assert result["tag_prefix"] == "Compact5000_IO_Adapter"

    def test_get_module_test_input_module(self, fixture_registry):
        """get_module Test_Input_Module has io tags on local slot 1."""
        result = get_module(fixture_registry, "Test_Input_Module", path="example.L5X")

        assert result["name"] == "Test_Input_Module"
        assert result["catalog_number"] == "5069-IB16/A"
        assert result["tag_prefix"] == "Local:1"
        assert [t["name"] for t in result["io_tags"]] == [
            "Local:1:C",
            "Local:1:I",
        ]

    def test_get_module_remote_io_tag_names(self, fixture_registry):
        """Remote rack module I/O tags use the adapter-and-slot prefix."""
        result = get_module(fixture_registry, "Remote_Output", path="example.L5X")

        assert result["tag_prefix"] == "Compact5000_IO_Adapter:1"
        assert [t["name"] for t in result["io_tags"]] == [
            "Compact5000_IO_Adapter:1:C",
            "Compact5000_IO_Adapter:1:I",
            "Compact5000_IO_Adapter:1:O",
        ]

    def test_get_module_case_insensitive(self, fixture_registry):
        """get_module lookup is case-insensitive."""
        result1 = get_module(fixture_registry, "ShopRobot", path="example.L5X")
        result2 = get_module(fixture_registry, "shoprobot", path="example.L5X")

        assert result1["name"] == result2["name"]

    def test_get_module_unknown_name_raises(self, fixture_registry):
        """get_module raises ItemNotFoundError for unknown module."""
        with pytest.raises(ItemNotFoundError):
            get_module(fixture_registry, "NonexistentModule", path="example.L5X")

    @pytest.mark.parametrize("include_data", [True, False])
    def test_get_module_all_modules(self, fixture_registry, include_data):
        """Every module works with include_data True and False, and is JSON-safe."""
        names = _all_module_names(fixture_registry)
        assert len(names) == 17
        for name in names:
            detail = get_module(
                fixture_registry,
                name,
                include_data=include_data,
                path="example.L5X",
            )
            assert detail["name"] == name
            assert detail["tag_prefix"] == EXPECTED_TAG_PREFIX[name]
            assert len(json.dumps(detail)) > 0

    def test_get_module_json_serializable(self, fixture_registry):
        """Result is JSON serializable."""
        result = get_module(
            fixture_registry, "ShopRobot", include_data=True, path="example.L5X"
        )
        assert len(json.dumps(result)) > 0

    def test_get_module_vendor_and_codes(self, fixture_registry):
        """get_module includes vendor and product codes as strings."""
        result = get_module(fixture_registry, "ShopRobot", path="example.L5X")

        assert result["vendor"] == "1"
        assert result["product_type"] == "0"
        assert result["product_code"] == "18"

    def test_get_module_safety_enabled_field(self, fixture_registry):
        """Safety status is a bool when the module reports it."""
        result = get_module(fixture_registry, "Test_Safety_Input", path="example.L5X")
        if "safety_enabled" in result:
            assert isinstance(result["safety_enabled"], bool)

    def test_get_module_ports_are_listed(self, fixture_registry):
        """Ports carry id, type and upstream; bus_size is an int when present."""
        result = get_module(fixture_registry, "Local", path="example.L5X")

        assert len(result["ports"]) > 0
        for port in result["ports"]:
            assert isinstance(port["id"], int)
            assert isinstance(port["type"], str)
            if "bus_size" in port:
                assert isinstance(port["bus_size"], int)


def _all_module_names(registry: ProjectRegistry) -> list[str]:
    """Return every module name in the fixture, in tree order."""
    return [m["name"] for m in list_modules(registry, path="example.L5X")["modules"]]
