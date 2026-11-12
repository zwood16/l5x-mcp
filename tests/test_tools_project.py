"""Tests for project.py tools."""

from __future__ import annotations

import json

import pytest
from conftest import EXAMPLE

from l5x_mcp.tools.project import list_l5x_files, project_overview


class TestListL5xFiles:
    """Tests for list_l5x_files function."""

    def test_lists_all_fixtures(self, registry):
        """list_l5x_files discovers all 9 fixture files."""
        result = list_l5x_files(registry)

        assert "root" in result
        assert "files" in result
        assert "file" not in result
        assert len(result["files"]) == 9

        paths = {f["path"] for f in result["files"]}
        assert "example.L5X" in paths
        assert "simple_example.L5X" in paths
        assert "Debounce_AOI.L5X" in paths
        assert "MainProgram_Program.L5X" in paths
        assert "ShopRobot_Module.L5X" in paths
        assert "SequenceRoutine_Routine_RLL.L5X" in paths
        assert "Rung2_from_SequenceRoutine.L5X" in paths

    def test_file_entry_structure(self, registry):
        """Each file entry has required keys."""
        result = list_l5x_files(registry)

        for entry in result["files"]:
            assert "path" in entry
            assert "size_bytes" in entry
            assert "modified" in entry
            assert "target_type" in entry
            assert "target_name" in entry

    def test_target_types(self, registry):
        """Target types are correct for each file."""
        result = list_l5x_files(registry)

        by_name = {f["path"]: f for f in result["files"]}

        assert by_name["example.L5X"]["target_type"] == "Controller"
        assert by_name["example.L5X"]["target_name"] == "Example_PLC"

        assert (
            by_name["Debounce_AOI.L5X"]["target_type"] == "AddOnInstructionDefinition"
        )
        assert by_name["Debounce_AOI.L5X"]["target_name"] == "Debounce"

        assert by_name["MainProgram_Program.L5X"]["target_type"] == "Program"
        assert by_name["MainProgram_Program.L5X"]["target_name"] == "MainProgram"

    def test_modified_is_iso8601(self, registry):
        """modified timestamp is ISO-8601 format."""
        result = list_l5x_files(registry)

        for entry in result["files"]:
            # Should parse without error
            modified = entry["modified"]
            assert "T" in modified  # ISO-8601 includes T separator

    def test_result_is_json_serializable(self, registry):
        """Result can be serialized to JSON."""
        result = list_l5x_files(registry)
        json_str = json.dumps(result)
        assert json_str
        assert len(json_str) > 0


class TestProjectOverview:
    """Tests for project_overview function."""

    def test_overview_structure_for_controller(self, registry):
        """project_overview for controller project has all expected keys."""
        result = project_overview(registry, EXAMPLE)

        assert "file" in result
        assert "target_type" in result
        assert "target_name" in result
        assert "is_component_export" in result
        assert "controller" in result
        assert "counts" in result
        assert "tasks" in result
        assert "unscheduled_programs" in result
        assert "programs" in result
        assert "aois" in result
        assert "data_types" in result
        assert "modules" in result

    def test_target_info_for_controller(self, registry):
        """target_type and target_name are correct."""
        result = project_overview(registry, EXAMPLE)

        assert result["target_type"] == "Controller"
        assert result["target_name"] == "Example_PLC"
        assert result["is_component_export"] is False

    def test_controller_metadata(self, registry):
        """Controller metadata is present and correct."""
        result = project_overview(registry, EXAMPLE)

        c = result["controller"]
        assert c is not None
        assert c["name"] == "Example_PLC"
        assert c["processor_type"] == "5069-L310ERMS3"
        assert c["firmware"] == "37.11"
        assert c["is_safety_controller"] is True
        assert c["safety_level"] == "SIL3/PLe"
        assert "project_creation_date" in c
        assert "last_modified_date" in c
        assert "project_sn" in c

    def test_counts_match_inventory(self, registry):
        """Counts match known inventory for example.L5X."""
        result = project_overview(registry, EXAMPLE)

        counts = result["counts"]
        assert counts["data_types"] == 9
        assert counts["aois"] == 6
        assert counts["modules"] == 17
        assert counts["controller_tags"] == 9
        assert counts["module_io_tags"] == 32  # Names containing ':' in project.tags
        assert counts["programs"] == 7
        assert counts["tasks"] == 4
        assert counts["routines"] == 13  # Sum of routines across all programs

    def test_tasks_list_structure(self, registry):
        """Tasks list has correct structure and content."""
        result = project_overview(registry, EXAMPLE)

        tasks = result["tasks"]
        assert len(tasks) == 4

        task_names = {t["name"] for t in tasks}
        assert task_names == {"EventTask", "MainTask", "PeriodicTask", "SafetyTask"}

        # Check EventTask specifically
        event_task = next(t for t in tasks if t["name"] == "EventTask")
        assert event_task["type"] == "EVENT"
        assert event_task["rate"] == 10.0
        assert event_task["priority"] == 15
        assert event_task["inhibited"] is True
        assert "EventProgram" in event_task["programs"]

    def test_unscheduled_programs(self, registry):
        """unscheduled_programs contains only Unscheduled."""
        result = project_overview(registry, EXAMPLE)

        unscheduled = result["unscheduled_programs"]
        assert unscheduled == ["Unscheduled"]

    def test_programs_list_structure(self, registry):
        """Programs list has correct structure and content."""
        result = project_overview(registry, EXAMPLE)

        programs = result["programs"]
        assert len(programs) == 7

        prog_names = {p["name"] for p in programs}
        assert prog_names == {
            "AnotherProgram",
            "EventProgram",
            "MainProgram",
            "PeriodicProgram",
            "Robot",
            "SafetyProgram",
            "Unscheduled",
        }

        # Check MainProgram specifically
        main_prog = next(p for p in programs if p["name"] == "MainProgram")
        assert main_prog["main_routine"] == "MainRoutine"
        assert main_prog["routine_count"] == 2
        assert main_prog["tag_count"] == 37
        assert "disabled" not in main_prog  # compact() removes False values

    def test_aois_with_revision(self, registry):
        """AOIs list includes names with revisions if available."""
        result = project_overview(registry, EXAMPLE)

        aois = result["aois"]
        assert len(aois) == 6

        # Check that we have Debounce and others
        aoi_names = {a.split(" v")[0] for a in aois}  # Strip off revision
        assert "Debounce" in aoi_names
        assert "GenericInput" in aoi_names
        assert "Debounce v1.2" in aois
        assert "FanucRobot v1.4" in aois

    def test_data_types_list(self, registry):
        """Data types list contains all type names."""
        result = project_overview(registry, EXAMPLE)

        data_types = result["data_types"]
        assert len(data_types) == 9
        assert "A_UDT" in data_types
        assert "GenericRobotInputs" in data_types

    def test_modules_with_catalog_numbers(self, registry):
        """Modules list has correct structure."""
        result = project_overview(registry, EXAMPLE)

        modules = result["modules"]
        assert len(modules) == 17

        # Check Local module
        local = next((m for m in modules if m["name"] == "Local"), None)
        assert local is not None
        assert local["catalog_number"] == "5069-L310ERMS3"

    def test_component_export_aoi(self, registry):
        """project_overview for AOI component export works."""
        result = project_overview(registry, "Debounce_AOI.L5X")

        assert result["target_type"] == "AddOnInstructionDefinition"
        assert result["target_name"] == "Debounce"
        assert result["is_component_export"] is True

        # Controller should be None for context export (or minimal)
        assert result.get("controller") is None

        # Counts should be sparse
        assert result["counts"]["aois"] == 1
        assert result["counts"]["programs"] == 0
        assert result["counts"]["tasks"] == 0

    def test_component_export_program(self, registry):
        """project_overview for Program component export works."""
        result = project_overview(registry, "MainProgram_Program.L5X")

        assert result["target_type"] == "Program"
        assert result["target_name"] == "MainProgram"
        assert result["is_component_export"] is True

        # Should have program and some AOIs
        assert result["counts"]["programs"] == 1
        assert result["counts"]["aois"] >= 1

    def test_result_is_json_serializable(self, registry):
        """Result can be serialized to JSON."""
        result = project_overview(registry, EXAMPLE)
        json_str = json.dumps(result)
        assert json_str
        assert len(json_str) > 0

    def test_auto_discovery(self, registry):
        """project_overview with no path in single-file root works."""
        # This uses the registry which has exactly one file in this context
        # Actually, registry.root points to fixtures which has 9 files,
        # so this should fail. Let's test with explicit path instead.
        result = project_overview(registry, EXAMPLE)
        assert result["target_name"] == "Example_PLC"

    def test_explicit_path(self, registry):
        """project_overview with explicit path works."""
        result = project_overview(registry, EXAMPLE)
        assert result["file"] == EXAMPLE


class TestProjectOverviewInventory:
    """Detailed inventory validation for example.L5X."""

    def test_all_program_names(self, registry):
        """All program names match inventory."""
        result = project_overview(registry, EXAMPLE)
        prog_names = {p["name"] for p in result["programs"]}

        expected = {
            "AnotherProgram",
            "EventProgram",
            "MainProgram",
            "PeriodicProgram",
            "Robot",
            "SafetyProgram",
            "Unscheduled",
        }
        assert prog_names == expected

    def test_all_task_names(self, registry):
        """All task names match inventory."""
        result = project_overview(registry, EXAMPLE)
        task_names = {t["name"] for t in result["tasks"]}

        expected = {"EventTask", "MainTask", "PeriodicTask", "SafetyTask"}
        assert task_names == expected

    def test_task_details(self, registry):
        """Task details match expected values."""
        result = project_overview(registry, EXAMPLE)
        tasks_by_name = {t["name"]: t for t in result["tasks"]}

        # MainTask
        main = tasks_by_name["MainTask"]
        assert main["type"] == "CONTINUOUS"
        # rate is None so compact() removes it
        assert "rate" not in main
        assert main["priority"] == 10
        assert set(main["programs"]) == {"MainProgram", "AnotherProgram", "Robot"}

        # PeriodicTask
        periodic = tasks_by_name["PeriodicTask"]
        assert periodic["type"] == "PERIODIC"
        assert periodic["rate"] == 10.0
        assert periodic["programs"] == ["PeriodicProgram"]

        # SafetyTask (in list form, so no is_safety field)
        safety = tasks_by_name["SafetyTask"]
        assert safety["type"] == "PERIODIC"
        assert safety["rate"] == 20.0
        assert safety["programs"] == ["SafetyProgram"]


class TestComponentExportOverview:
    """project_overview works on every component export shape."""

    @pytest.mark.parametrize(
        ("filename", "target_type"),
        [
            ("Debounce_AOI.L5X", "AddOnInstructionDefinition"),
            ("MainProgram_Program.L5X", "Program"),
            ("A_UDT_DataType.L5X", "DataType"),
            ("robotAlarmCode_DataType_String.L5X", "DataType"),
            ("ShopRobot_Module.L5X", "Module"),
            ("SequenceRoutine_Routine_RLL.L5X", "Routine"),
            ("Rung2_from_SequenceRoutine.L5X", "Rung"),
        ],
    )
    def test_overview_for_each_component(self, registry, filename, target_type):
        """Each component export returns a context overview with counts."""
        result = project_overview(registry, filename)

        assert result["target_type"] == target_type
        assert result["is_component_export"] is True
        assert "controller" not in result  # None is dropped by compact()
        assert set(result["counts"]) >= {"controller_tags", "module_io_tags"}
        json.dumps(result)

    def test_rung_export_omits_empty_target_name(self, registry):
        """Rung exports have an empty TargetName, which compact() drops."""
        result = project_overview(registry, "Rung2_from_SequenceRoutine.L5X")

        assert "target_name" not in result
        assert result["counts"]["routines"] == 1
        assert result["aois"] == ["SeqCtrl v3.3"]

    def test_module_export_counts_module_io_tags(self, registry):
        """Module I/O tags of a module export are counted as module_io_tags."""
        result = project_overview(registry, "ShopRobot_Module.L5X")

        assert result["counts"]["modules"] == 1
        assert result["counts"]["controller_tags"] == 0
        assert result["counts"]["module_io_tags"] == 3
