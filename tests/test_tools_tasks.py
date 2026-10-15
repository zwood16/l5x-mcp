"""Tests for tasks.py tools."""

from __future__ import annotations

import json

import pytest
from conftest import EXAMPLE

from l5x_mcp.registry import ItemNotFoundError
from l5x_mcp.tools.tasks import get_task, list_tasks


class TestListTasks:
    """Tests for list_tasks function."""

    def test_list_tasks_structure(self, registry):
        """list_tasks returns correct structure."""
        result = list_tasks(registry, EXAMPLE)

        assert "file" in result
        assert "tasks" in result
        assert result["file"] == EXAMPLE

    def test_list_tasks_count(self, registry):
        """list_tasks returns all 4 tasks."""
        result = list_tasks(registry, EXAMPLE)

        tasks = result["tasks"]
        assert len(tasks) == 4

    def test_list_tasks_names(self, registry):
        """list_tasks includes all task names."""
        result = list_tasks(registry, EXAMPLE)

        task_names = {t["name"] for t in result["tasks"]}
        expected = {"EventTask", "MainTask", "PeriodicTask", "SafetyTask"}
        assert task_names == expected

    def test_list_tasks_entry_structure(self, registry):
        """Each task entry has required keys."""
        result = list_tasks(registry, EXAMPLE)

        for task in result["tasks"]:
            assert "name" in task
            assert "type" in task
            # rate/description can be None/empty, so compact() removes them
            assert "priority" in task
            assert "watchdog" in task
            assert "programs" in task

    def test_list_tasks_event_task(self, registry):
        """EventTask entry is correct."""
        result = list_tasks(registry, EXAMPLE)

        event_task = next(t for t in result["tasks"] if t["name"] == "EventTask")
        assert event_task["type"] == "EVENT"
        assert event_task["rate"] == 10.0
        assert event_task["priority"] == 15
        assert event_task["watchdog"] == 500
        assert event_task["inhibited"] is True
        assert "EventProgram" in event_task["programs"]

    def test_list_tasks_main_task(self, registry):
        """MainTask entry is correct."""
        result = list_tasks(registry, EXAMPLE)

        main_task = next(t for t in result["tasks"] if t["name"] == "MainTask")
        assert main_task["type"] == "CONTINUOUS"
        # rate is None so compact() removes it
        assert "rate" not in main_task
        assert main_task["priority"] == 10
        assert set(main_task["programs"]) == {"MainProgram", "AnotherProgram", "Robot"}
        # inhibited should not be present if False (compact)
        assert "inhibited" not in main_task

    def test_list_tasks_description_first_line(self, registry):
        """Description is truncated to first line."""
        result = list_tasks(registry, EXAMPLE)

        periodic_task = next(t for t in result["tasks"] if t["name"] == "PeriodicTask")
        # Should not contain newlines
        assert "\n" not in periodic_task["description"]
        assert "10ms rate" in periodic_task["description"]

    def test_result_is_json_serializable(self, registry):
        """Result can be serialized to JSON."""
        result = list_tasks(registry, EXAMPLE)
        json_str = json.dumps(result)
        assert json_str


class TestGetTask:
    """Tests for get_task function."""

    def test_get_task_structure(self, registry):
        """get_task returns correct structure."""
        result = get_task(registry, "MainTask", EXAMPLE)

        assert "file" in result
        assert "name" in result
        assert "type" in result
        assert "priority" in result
        assert "watchdog" in result
        assert "disable_update_outputs" in result
        assert "inhibit_task" in result
        assert "class" in result
        assert "is_safety" in result
        assert "scheduled_programs" in result
        # description and rate may not be present if empty/None (compact)

    def test_get_task_main_task_details(self, registry):
        """get_task returns correct details for MainTask."""
        result = get_task(registry, "MainTask", EXAMPLE)

        assert result["name"] == "MainTask"
        assert result["type"] == "CONTINUOUS"
        # rate is None so compact() removes it
        assert "rate" not in result
        assert result["priority"] == 10
        assert result["watchdog"] == 500
        assert result["class"] == "Standard"
        assert result["is_safety"] is False

    def test_get_task_scheduled_programs(self, registry):
        """scheduled_programs includes program details."""
        result = get_task(registry, "MainTask", EXAMPLE)

        programs = result["scheduled_programs"]
        assert len(programs) == 3

        prog_names = {p["name"] for p in programs}
        assert prog_names == {"MainProgram", "AnotherProgram", "Robot"}

        # Check MainProgram details
        main_prog = next(p for p in programs if p["name"] == "MainProgram")
        assert main_prog["main_routine"] == "MainRoutine"
        assert main_prog["routine_count"] == 2
        # tag_count is not in get_task's scheduled_programs (only in project_overview)
        assert "tag_count" not in main_prog

    def test_get_task_safety_task(self, registry):
        """get_task returns safety task info."""
        result = get_task(registry, "SafetyTask", EXAMPLE)

        assert result["name"] == "SafetyTask"
        assert result["class"] == "Safety"
        assert result["is_safety"] is True

    def test_get_task_event_info_present(self, registry):
        """get_task includes event_info for EVENT tasks."""
        result = get_task(registry, "EventTask", EXAMPLE)

        assert "event_info" in result
        event_info = result["event_info"]
        assert event_info is not None
        assert "event_trigger" in event_info
        assert "enable_timeout" in event_info

    def test_get_task_event_info_absent_for_continuous(self, registry):
        """get_task omits event_info for non-EVENT tasks."""
        result = get_task(registry, "MainTask", EXAMPLE)

        # event_info should not be present or be None
        event_info = result.get("event_info")
        assert event_info is None

    def test_get_task_case_insensitive(self, registry):
        """get_task lookup is case-insensitive."""
        result1 = get_task(registry, "MainTask", EXAMPLE)
        result2 = get_task(registry, "maintask", EXAMPLE)
        result3 = get_task(registry, "MAINTASK", EXAMPLE)

        assert result1["name"] == result2["name"] == result3["name"] == "MainTask"

    def test_get_task_not_found(self, registry):
        """get_task raises ItemNotFoundError for unknown task."""
        with pytest.raises(ItemNotFoundError) as exc_info:
            get_task(registry, "NonexistentTask", EXAMPLE)

        error_msg = str(exc_info.value)
        assert "NonexistentTask" in error_msg
        assert "EventTask" in error_msg  # Available names should be listed

    def test_get_task_inhibited_flag(self, registry):
        """inhibit_task flag is preserved."""
        result = get_task(registry, "EventTask", EXAMPLE)
        assert result["inhibit_task"] is True

        result2 = get_task(registry, "MainTask", EXAMPLE)
        assert result2["inhibit_task"] is False

    def test_result_is_json_serializable(self, registry):
        """Result can be serialized to JSON."""
        result = get_task(registry, "MainTask", EXAMPLE)
        json_str = json.dumps(result)
        assert json_str


class TestGetTaskInventory:
    """Detailed inventory validation for get_task."""

    def test_all_tasks_retrievable(self, registry):
        """All 4 tasks can be retrieved by name."""
        task_names = ["EventTask", "MainTask", "PeriodicTask", "SafetyTask"]

        for task_name in task_names:
            result = get_task(registry, task_name, EXAMPLE)
            assert result["name"] == task_name

    def test_periodic_task_details(self, registry):
        """PeriodicTask has correct rate and programs."""
        result = get_task(registry, "PeriodicTask", EXAMPLE)

        assert result["type"] == "PERIODIC"
        assert result["rate"] == 10.0
        assert result["priority"] == 10
        assert result["watchdog"] == 500
        assert len(result["scheduled_programs"]) == 1
        assert result["scheduled_programs"][0]["name"] == "PeriodicProgram"

    def test_event_task_details(self, registry):
        """EventTask has correct event_info."""
        result = get_task(registry, "EventTask", EXAMPLE)

        assert result["type"] == "EVENT"
        assert result["rate"] == 10.0
        assert result["priority"] == 15
        assert result["watchdog"] == 500
        assert result["inhibit_task"] is True
        assert result["disable_update_outputs"] is True

        # Event info should be populated
        assert result["event_info"] is not None
        assert "event_trigger" in result["event_info"]
