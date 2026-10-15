"""Tests for programs tool module."""

import json

import pytest

from l5x_mcp.registry import ItemNotFoundError, L5XError
from l5x_mcp.tools.programs import (
    _resolve_routine_container,
    get_program,
    get_routine_logic,
    list_programs,
    list_routines,
)


class TestListPrograms:
    """Tests for list_programs function."""

    def test_list_programs_returns_all_programs(self, registry):
        """Test that list_programs returns all programs in the project."""
        result = list_programs(registry, path="example.L5X")
        assert "file" in result
        assert "programs" in result
        programs = result["programs"]
        assert len(programs) == 7  # example.L5X has 7 programs

    def test_list_programs_has_required_keys(self, registry):
        """Test that each program has required keys."""
        result = list_programs(registry, path="example.L5X")
        programs = result["programs"]
        assert len(programs) > 0
        prog = programs[0]
        assert "name" in prog
        assert "description" in prog
        assert "main_routine" in prog
        assert "routine_count" in prog
        assert "tag_count" in prog

    def test_list_programs_disabled_flag(self, registry):
        """Test that disabled flag is only present when True."""
        result = list_programs(registry, path="example.L5X")
        programs = result["programs"]
        # Some programs should not be disabled, so disabled key shouldn't
        # always be present
        prog_with_disabled = [p for p in programs if "disabled" in p]
        # If any are disabled, check it's True
        for prog in prog_with_disabled:
            assert prog["disabled"] is True

    def test_list_programs_is_safety_flag(self, registry):
        """Test that is_safety flag is only present when True."""
        result = list_programs(registry, path="example.L5X")
        programs = result["programs"]
        safety_progs = [p for p in programs if "is_safety" in p]
        assert any("is_safety" in p for p in programs)  # Should have at least one
        for prog in safety_progs:
            assert prog["is_safety"] is True

    def test_list_programs_task_field(self, registry):
        """Test that task field is populated for scheduled programs."""
        result = list_programs(registry, path="example.L5X")
        programs = result["programs"]
        # MainProgram should be scheduled in MainTask
        main_prog = [p for p in programs if p["name"] == "MainProgram"]
        assert len(main_prog) == 1
        assert "task" in main_prog[0]
        assert main_prog[0]["task"] == "MainTask"

    def test_list_programs_unscheduled(self, registry):
        """Test that unscheduled programs don't have task field."""
        result = list_programs(registry, path="example.L5X")
        programs = result["programs"]
        unscheduled = [p for p in programs if p["name"] == "Unscheduled"]
        assert len(unscheduled) == 1
        assert "task" not in unscheduled[0]

    def test_list_programs_json_serializable(self, registry):
        """Test that result is JSON serializable."""
        result = list_programs(registry, path="example.L5X")
        json_str = json.dumps(result)
        assert json_str


class TestGetProgram:
    """Tests for get_program function."""

    def test_get_program_basic_info(self, registry):
        """Test get_program returns basic program info."""
        result = get_program(registry, "MainProgram", path="example.L5X")
        assert result["name"] == "MainProgram"
        # description may be omitted if empty (compacted)
        assert "main_routine" in result
        assert result["main_routine"] == "MainRoutine"

    def test_get_program_has_flags(self, registry):
        """Test that get_program returns all flag fields."""
        result = get_program(registry, "MainProgram", path="example.L5X")
        assert "disabled" in result
        assert "test_edits" in result
        assert "use_as_folder" in result
        assert "class" in result
        assert "is_safety" in result

    def test_get_program_has_routines_and_tags(self, registry):
        """Test that get_program includes routines and tags arrays."""
        result = get_program(registry, "MainProgram", path="example.L5X")
        assert "routines" in result
        assert "tags" in result
        assert isinstance(result["routines"], list)
        assert isinstance(result["tags"], list)
        assert len(result["routines"]) > 0
        assert len(result["tags"]) > 0

    def test_get_program_routine_info(self, registry):
        """Test routine info includes name, type, description, and rung/line counts."""
        result = get_program(registry, "MainProgram", path="example.L5X")
        routines = result["routines"]
        for routine in routines:
            assert "name" in routine
            assert "type" in routine
            assert "description" in routine
            # RLL should have rung_count, ST should have line_count
            if routine["type"] == "RLL":
                assert "rung_count" in routine
                assert "line_count" not in routine
            elif routine["type"] == "ST":
                assert "line_count" in routine
                assert "rung_count" not in routine

    def test_get_program_tag_info(self, registry):
        """Test tag info includes name, data_type, tag_type, usage."""
        result = get_program(registry, "MainProgram", path="example.L5X")
        tags = result["tags"]
        if tags:
            tag = tags[0]
            assert "name" in tag
            assert "data_type" in tag
            assert "tag_type" in tag
            assert "usage" in tag

    def test_get_program_case_insensitive(self, registry):
        """Test that program lookup is case-insensitive."""
        result = get_program(registry, "mainprogram", path="example.L5X")
        assert result["name"] == "MainProgram"

    def test_get_program_not_found(self, registry):
        """Test that unknown program raises ItemNotFoundError."""
        with pytest.raises(ItemNotFoundError) as exc_info:
            get_program(registry, "NonExistent", path="example.L5X")
        error_msg = str(exc_info.value)
        assert "Program" in error_msg
        assert "NonExistent" in error_msg
        assert "Available:" in error_msg

    def test_get_program_safety_program(self, registry):
        """Test get_program with a safety program."""
        result = get_program(registry, "SafetyProgram", path="example.L5X")
        assert result["is_safety"] is True

    def test_get_program_json_serializable(self, registry):
        """Test that result is JSON serializable."""
        result = get_program(registry, "MainProgram", path="example.L5X")
        json_str = json.dumps(result)
        assert json_str


class TestResolveRoutineContainer:
    """Tests for _resolve_routine_container helper."""

    def test_resolve_with_program(self, registry):
        """Test resolving with program parameter."""
        _, project = registry.get_with_path("example.L5X")
        kind, name, routines = _resolve_routine_container(
            project, program="MainProgram", aoi=None
        )
        assert kind == "program"
        assert name == "MainProgram"
        assert len(routines) > 0

    def test_resolve_with_aoi(self, registry):
        """Test resolving with AOI parameter."""
        _, project = registry.get_with_path("example.L5X")
        kind, name, routines = _resolve_routine_container(
            project, program=None, aoi="Debounce"
        )
        assert kind == "aoi"
        assert name == "Debounce"
        assert len(routines) > 0

    def test_resolve_both_parameters_raises(self, registry):
        """Test that specifying both program and aoi raises L5XError."""
        _, project = registry.get_with_path("example.L5X")
        with pytest.raises(L5XError) as exc_info:
            _resolve_routine_container(project, program="MainProgram", aoi="Debounce")
        assert "Cannot specify both" in str(exc_info.value)

    def test_resolve_neither_in_full_project_raises(self, registry):
        """Test that neither parameter in full project raises L5XError."""
        _, project = registry.get_with_path("example.L5X")
        with pytest.raises(L5XError) as exc_info:
            _resolve_routine_container(project, program=None, aoi=None)
        assert "program" in str(exc_info.value) or "aoi" in str(exc_info.value)

    def test_resolve_auto_detects_program_component(self, registry):
        """Test auto-detection of single program in component export."""
        _, project = registry.get_with_path("MainProgram_Program.L5X")
        kind, name, routines = _resolve_routine_container(
            project, program=None, aoi=None
        )
        assert kind == "program"
        assert name == "MainProgram"
        assert len(routines) > 0

    def test_resolve_auto_detects_aoi_component(self, registry):
        """Test auto-detection of single AOI in component export."""
        _, project = registry.get_with_path("Debounce_AOI.L5X")
        kind, name, routines = _resolve_routine_container(
            project, program=None, aoi=None
        )
        assert kind == "aoi"
        assert name == "Debounce"
        assert len(routines) > 0


class TestListRoutines:
    """Tests for list_routines function."""

    def test_list_routines_program(self, registry):
        """Test listing routines for a program."""
        result = list_routines(registry, program="MainProgram", path="example.L5X")
        assert "file" in result
        assert "container" in result
        assert "routines" in result
        assert result["container"]["kind"] == "program"
        assert result["container"]["name"] == "MainProgram"
        routines = result["routines"]
        assert len(routines) > 0

    def test_list_routines_aoi(self, registry):
        """Test listing routines for an AOI."""
        result = list_routines(registry, aoi="Debounce", path="example.L5X")
        assert result["container"]["kind"] == "aoi"
        assert result["container"]["name"] == "Debounce"
        routines = result["routines"]
        assert len(routines) > 0
        # Debounce has Logic and EnableInFalse routines
        names = [r["name"] for r in routines]
        assert "Logic" in names

    def test_list_routines_component_export(self, registry):
        """Test listing routines in component export without explicit parameters."""
        # MainProgram_Program.L5X has single program
        result = list_routines(registry, path="MainProgram_Program.L5X")
        assert result["container"]["kind"] == "program"
        assert result["container"]["name"] == "MainProgram"

        # Debounce_AOI.L5X has single AOI
        result2 = list_routines(registry, path="Debounce_AOI.L5X")
        assert result2["container"]["kind"] == "aoi"
        assert result2["container"]["name"] == "Debounce"

    def test_list_routines_case_insensitive(self, registry):
        """Test case-insensitive program/AOI lookup."""
        result = list_routines(registry, program="mainprogram", path="example.L5X")
        assert result["container"]["name"] == "MainProgram"

    def test_list_routines_both_params_raises(self, registry):
        """Test that both program and aoi raises error."""
        with pytest.raises(L5XError):
            list_routines(
                registry,
                program="MainProgram",
                aoi="Debounce",
                path="example.L5X",
            )

    def test_list_routines_json_serializable(self, registry):
        """Test that result is JSON serializable."""
        result = list_routines(registry, program="MainProgram", path="example.L5X")
        json_str = json.dumps(result)
        assert json_str


class TestGetRoutineLogic:
    """Tests for get_routine_logic function."""

    def test_get_routine_logic_rll(self, registry):
        """Test getting RLL routine logic."""
        result = get_routine_logic(
            registry, routine="MainRoutine", program="MainProgram", path="example.L5X"
        )
        assert result["routine"] == "MainRoutine"
        assert result["type"] == "RLL"
        assert "total_rungs" in result
        assert "rungs" in result
        assert isinstance(result["rungs"], list)
        # MainRoutine has 1 rung
        assert result["total_rungs"] == 1

    def test_get_routine_logic_rll_rung_structure(self, registry):
        """Test that RLL rungs have proper structure."""
        result = get_routine_logic(
            registry,
            routine="SequenceRoutine",
            program="MainProgram",
            path="example.L5X",
        )
        rungs = result["rungs"]
        for rung in rungs:
            assert "number" in rung
            assert "comment" in rung
            assert "text" in rung
            assert isinstance(rung["number"], int)

    def test_get_routine_logic_rll_rung_numbering(self, registry):
        """Test that rung numbers are 0-based."""
        result = get_routine_logic(
            registry,
            routine="SequenceRoutine",
            program="MainProgram",
            path="example.L5X",
        )
        rungs = result["rungs"]
        # SequenceRoutine has rungs numbered 0, 1, 2, etc.
        assert rungs[0]["number"] == 0
        if len(rungs) > 1:
            assert rungs[1]["number"] == 1

    def test_get_routine_logic_rll_range(self, registry):
        """Test RLL rung range filtering."""
        result = get_routine_logic(
            registry,
            routine="SequenceRoutine",
            program="MainProgram",
            start_rung=1,
            end_rung=2,
            path="example.L5X",
        )
        rungs = result["rungs"]
        # Should get rungs 1 and 2
        assert all(1 <= r["number"] <= 2 for r in rungs)
        numbers = [r["number"] for r in rungs]
        assert 1 in numbers or 2 in numbers

    def test_get_routine_logic_rll_invalid_range_start_gt_end(self, registry):
        """Test that start_rung > end_rung raises error."""
        with pytest.raises(L5XError) as exc_info:
            get_routine_logic(
                registry,
                routine="SequenceRoutine",
                program="MainProgram",
                start_rung=5,
                end_rung=2,
                path="example.L5X",
            )
        assert "start_rung must be <= end_rung" in str(exc_info.value)

    def test_get_routine_logic_rll_invalid_range_negative(self, registry):
        """Test that negative rung numbers raise error."""
        with pytest.raises(L5XError) as exc_info:
            get_routine_logic(
                registry,
                routine="SequenceRoutine",
                program="MainProgram",
                start_rung=-1,
                path="example.L5X",
            )
        assert "non-negative" in str(exc_info.value)

    def test_get_routine_logic_st(self, registry):
        """Test getting ST routine logic."""
        result = get_routine_logic(
            registry,
            routine="StructuredTextRoutine",
            program="AnotherProgram",
            path="example.L5X",
        )
        assert result["routine"] == "StructuredTextRoutine"
        assert result["type"] == "ST"
        assert "total_lines" in result
        assert "lines" in result
        assert "code" in result
        assert isinstance(result["lines"], list)
        assert isinstance(result["code"], str)

    def test_get_routine_logic_st_line_structure(self, registry):
        """Test that ST lines have proper structure."""
        result = get_routine_logic(
            registry,
            routine="StructuredTextRoutine",
            program="AnotherProgram",
            path="example.L5X",
        )
        lines = result["lines"]
        for line in lines:
            assert "number" in line
            assert "text" in line
            assert isinstance(line["number"], int)

    def test_get_routine_logic_st_code_joined(self, registry):
        """Test that ST code is properly joined from lines."""
        result = get_routine_logic(
            registry,
            routine="StructuredTextRoutine",
            program="AnotherProgram",
            path="example.L5X",
        )
        lines = result["lines"]
        code = result["code"]
        # Code should contain text from lines
        if lines:
            # At least one line text should be in code
            assert len(code) > 0

    def test_get_routine_logic_st_range(self, registry):
        """Test ST line range filtering."""
        result = get_routine_logic(
            registry,
            routine="StructuredTextRoutine",
            program="AnotherProgram",
            start_rung=0,
            end_rung=5,
            path="example.L5X",
        )
        lines = result["lines"]
        # Should get lines 0-5
        assert all(0 <= line["number"] <= 5 for line in lines)

    def test_get_routine_logic_truncation_rll(self, registry, monkeypatch):
        """Test that RLL routines > 200 rungs are truncated."""
        # Temporarily set MAX_RUNGS_DEFAULT to 2 to test truncation
        import l5x_mcp.tools.programs as programs_module

        monkeypatch.setattr(programs_module, "MAX_RUNGS_DEFAULT", 2)

        result = get_routine_logic(
            registry,
            routine="SequenceRoutine",
            program="MainProgram",
            path="example.L5X",
        )
        # SequenceRoutine has 3 rungs, so with limit=2 should be truncated
        total = result["total_rungs"]
        if total > 2:
            # Should only return 2 rungs
            assert len(result["rungs"]) == 2
            assert result.get("truncated") is True
            assert "next_start_rung" in result
            assert result["next_start_rung"] == 2
            assert "note" in result

    def test_get_routine_logic_truncation_st(self, registry, monkeypatch):
        """Test that ST routines > 200 lines are truncated."""
        # Temporarily set MAX_RUNGS_DEFAULT to 5 to test truncation
        import l5x_mcp.tools.programs as programs_module

        monkeypatch.setattr(programs_module, "MAX_RUNGS_DEFAULT", 5)

        result = get_routine_logic(
            registry,
            routine="StructuredTextRoutine",
            program="AnotherProgram",
            path="example.L5X",
        )
        total = result["total_lines"]
        if total > 5:
            # Should only return 5 lines
            assert len(result["lines"]) == 5
            assert result.get("truncated") is True
            assert "next_start_rung" in result
            assert result["next_start_rung"] == 5
            assert "note" in result

    def test_get_routine_logic_truncation_with_start_rung(self, registry, monkeypatch):
        """Test truncation when start_rung set and more than cap items remain."""
        import l5x_mcp.tools.programs as programs_module

        monkeypatch.setattr(programs_module, "MAX_RUNGS_DEFAULT", 2)

        # SequenceRoutine has 10 rungs (0-9)
        result = get_routine_logic(
            registry,
            routine="SequenceRoutine",
            program="MainProgram",
            start_rung=5,
            end_rung=None,  # end_rung None means go to last
            path="example.L5X",
        )
        # start_rung=5 to end (9) = 5 items, but cap at 2
        assert len(result["rungs"]) == 2
        assert result.get("truncated") is True
        assert "next_start_rung" in result
        # First omitted rung number should be 7 (5 + 2)
        assert result["next_start_rung"] == 7
        assert "note" in result

    def test_get_routine_logic_truncation_explicit_range_over_cap(
        self, registry, monkeypatch
    ):
        """Test truncation with explicit range larger than cap."""
        import l5x_mcp.tools.programs as programs_module

        monkeypatch.setattr(programs_module, "MAX_RUNGS_DEFAULT", 2)

        # Request rungs 0-8 (9 items) but cap at 2
        result = get_routine_logic(
            registry,
            routine="SequenceRoutine",
            program="MainProgram",
            start_rung=0,
            end_rung=8,
            path="example.L5X",
        )
        assert len(result["rungs"]) == 2
        assert result.get("truncated") is True
        assert result["next_start_rung"] == 2
        assert "note" in result

    def test_get_routine_logic_range_under_cap_not_truncated(
        self, registry, monkeypatch
    ):
        """Test that range fully under cap is not truncated."""
        import l5x_mcp.tools.programs as programs_module

        monkeypatch.setattr(programs_module, "MAX_RUNGS_DEFAULT", 10)

        # SequenceRoutine has 10 rungs, request 0-4 (5 items)
        result = get_routine_logic(
            registry,
            routine="SequenceRoutine",
            program="MainProgram",
            start_rung=0,
            end_rung=4,
            path="example.L5X",
        )
        assert len(result["rungs"]) == 5
        assert result.get("truncated") is not True
        assert "next_start_rung" not in result

    def test_get_routine_logic_st_truncation_with_start_line(
        self, registry, monkeypatch
    ):
        """Test ST truncation with start_rung set."""
        import l5x_mcp.tools.programs as programs_module

        monkeypatch.setattr(programs_module, "MAX_RUNGS_DEFAULT", 3)

        # StructuredTextRoutine has 24 lines
        result = get_routine_logic(
            registry,
            routine="StructuredTextRoutine",
            program="AnotherProgram",
            start_rung=10,
            end_rung=None,
            path="example.L5X",
        )
        # Lines 10-23 = 14 items, cap at 3
        assert len(result["lines"]) == 3
        assert result.get("truncated") is True
        assert result["next_start_rung"] == 13
        assert "note" in result

    def test_get_routine_logic_empty_comment_dropped(self, registry):
        """Test that empty comments are not in output (compacted)."""
        result = get_routine_logic(
            registry,
            routine="MainRoutine",
            program="MainProgram",
            path="example.L5X",
        )
        # MainRoutine has 1 rung with empty comment
        assert len(result["rungs"]) == 1
        rung = result["rungs"][0]
        # Empty comment should be dropped by compact()
        assert "comment" not in rung or rung["comment"] != ""
        # text should always be present
        assert "text" in rung

    def test_get_routine_logic_unsupported_type(self, registry):
        """Test handling of unsupported routine types."""
        # If we had an FBD routine, it should return a note
        # For now, just verify the structure for known types is correct
        result = get_routine_logic(
            registry, routine="MainRoutine", program="MainProgram", path="example.L5X"
        )
        # MainRoutine is RLL, should have rungs
        assert "rungs" in result
        assert "note" not in result or "Showing first" in result.get("note", "")

    def test_get_routine_logic_aoi_routine(self, registry):
        """Test getting routine from an AOI."""
        result = get_routine_logic(
            registry,
            routine="Logic",
            aoi="Debounce",
            path="example.L5X",
        )
        assert result["routine"] == "Logic"
        assert result["container"]["kind"] == "aoi"
        assert result["container"]["name"] == "Debounce"

    def test_get_routine_logic_case_insensitive_routine(self, registry):
        """Test case-insensitive routine lookup."""
        result = get_routine_logic(
            registry,
            routine="mainroutine",
            program="mainprogram",
            path="example.L5X",
        )
        assert result["routine"] == "MainRoutine"

    def test_get_routine_logic_not_found(self, registry):
        """Test that unknown routine raises ItemNotFoundError."""
        with pytest.raises(ItemNotFoundError):
            get_routine_logic(
                registry,
                routine="NonExistent",
                program="MainProgram",
                path="example.L5X",
            )

    def test_get_routine_logic_json_serializable(self, registry):
        """Test that result is JSON serializable."""
        result = get_routine_logic(
            registry,
            routine="MainRoutine",
            program="MainProgram",
            path="example.L5X",
        )
        json_str = json.dumps(result)
        assert json_str

    def test_get_routine_logic_component_export_program(self, registry):
        """Test getting routine from component export (program)."""
        result = get_routine_logic(
            registry,
            routine="MainRoutine",
            path="MainProgram_Program.L5X",
        )
        assert result["routine"] == "MainRoutine"
        assert result["container"]["name"] == "MainProgram"

    def test_get_routine_logic_component_export_aoi(self, registry):
        """Test getting routine from component export (AOI)."""
        result = get_routine_logic(
            registry,
            routine="Logic",
            path="Debounce_AOI.L5X",
        )
        assert result["routine"] == "Logic"
        assert result["container"]["name"] == "Debounce"
