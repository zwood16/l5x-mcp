"""Tests for programs tool module."""

import json
from pathlib import Path

import pytest

from l5x_mcp.operand_resolver import OperandResolver
from l5x_mcp.registry import ItemNotFoundError, L5XError, ProjectRegistry
from l5x_mcp.tools.programs import (
    MAX_CHARS_DEFAULT,
    VALUES_NOTE,
    OutputBudget,
    _Candidate,
    _OperandLedger,
    _resolve_routine_container,
    _rung_candidates,
    _select_items,
    _shrink_to_fit,
    get_program,
    get_routine_logic,
    json_size,
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
        """Test that get_program includes routines and, when asked, tags arrays."""
        result = get_program(
            registry, "MainProgram", include_tags=True, path="example.L5X"
        )
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
        """Tag info comes from tag_summary: name and data_type are always set."""
        result = get_program(
            registry, "MainProgram", include_tags=True, path="example.L5X"
        )
        tags = result["tags"]
        assert tags
        for tag in tags:
            assert "name" in tag
            assert tag["tag_type"]
        input_param = next(t for t in tags if t["name"] == "an_input_param")
        assert input_param["tag_type"] == "Base"
        assert input_param["usage"] == "Input"
        # Empty values are omitted rather than emitted as ""
        assert "description" not in input_param

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
        assert "code" not in result
        assert isinstance(result["lines"], list)

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

    def test_get_routine_logic_st_has_no_code_key(self, registry):
        """ST lines are returned once; there is no duplicated joined 'code' key."""
        result = get_routine_logic(
            registry,
            routine="StructuredTextRoutine",
            program="AnotherProgram",
            path="example.L5X",
        )
        assert "code" not in result
        assert [line["number"] for line in result["lines"]] == list(range(24))

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


class TestRoutineComponentExports:
    """Routine and Rung component exports (program context wrapper)."""

    def test_routine_export_auto_detects_program(self, registry):
        """Routine export: the single context program is the container."""
        result = list_routines(registry, path="SequenceRoutine_Routine_RLL.L5X")
        assert result["container"] == {"kind": "program", "name": "MainProgram"}
        assert [r["name"] for r in result["routines"]] == ["SequenceRoutine"]
        assert result["routines"][0]["type"] == "RLL"
        assert result["routines"][0]["rung_count"] == 10

    def test_routine_export_get_routine_logic(self, registry):
        """Routine export: rungs are readable with auto-detected container."""
        result = get_routine_logic(
            registry,
            routine="SequenceRoutine",
            path="SequenceRoutine_Routine_RLL.L5X",
        )
        assert result["type"] == "RLL"
        assert result["total_rungs"] == 10
        assert result["rungs"][0]["number"] == 0

    def test_rung_export_type_inferred_from_rllcontent(self, registry):
        """Rung export: the routine has no Type attribute but is RLL."""
        listed = list_routines(registry, path="Rung2_from_SequenceRoutine.L5X")
        assert listed["routines"][0]["type"] == "RLL"
        assert listed["routines"][0]["rung_count"] == 1

    def test_rung_export_get_routine_logic(self, registry):
        """Rung export: the single target rung is returned, not 'unsupported'."""
        result = get_routine_logic(
            registry,
            routine="SequenceRoutine",
            path="Rung2_from_SequenceRoutine.L5X",
        )
        assert result["type"] == "RLL"
        assert "note" not in result
        assert result["total_rungs"] == 1
        assert result["rungs"][0]["number"] == 2
        assert result["rungs"][0]["text"] == "SeqCtrl(sequence,1,0);"


def _compact_size(result: dict) -> int:
    """Compact JSON size, as measured by the max_chars budget."""
    return len(json.dumps(result, separators=(",", ":"), ensure_ascii=False))


def _all_items(registry, key, **kwargs):
    """Follow next_start_rung until the routine is fully read; return items."""
    items = []
    start = 0
    for _ in range(100):  # guard against a loop that never advances
        result = get_routine_logic(registry, start_rung=start, **kwargs)
        items.extend(result[key])
        if not result.get("truncated"):
            return items
        assert result["next_start_rung"] > start
        start = result["next_start_rung"]
    raise AssertionError("pagination did not finish")


class TestGetProgramTags:
    """get_program omits the tag list by default."""

    def test_default_omits_tags_and_hints_list_tags(self, registry):
        result = get_program(registry, "MainProgram", path="example.L5X")
        assert "tags" not in result
        assert result["tag_count"] > 0
        assert 'list_tags(scope="MainProgram")' in result["note"]

    def test_include_tags_returns_full_list(self, registry):
        result = get_program(
            registry, "MainProgram", include_tags=True, path="example.L5X"
        )
        assert len(result["tags"]) == result["tag_count"]
        assert "note" not in result


class TestRoutineLogicDetail:
    """The full, outline and logic detail modes of get_routine_logic."""

    def test_full_rung_has_number_comment_and_text(self, registry):
        result = get_routine_logic(
            registry,
            routine="SequenceRoutine",
            program="MainProgram",
            start_rung=1,
            end_rung=1,
            path="example.L5X",
        )
        assert result["detail"] == "full"
        rung = result["rungs"][0]
        assert rung["number"] == 1
        assert rung["comment"].startswith("//////////   Prescan")
        assert rung["text"]

    def test_outline_rung_has_number_and_comment_only(self, registry):
        result = get_routine_logic(
            registry,
            routine="SequenceRoutine",
            program="MainProgram",
            detail="outline",
            path="example.L5X",
        )
        assert [r["number"] for r in result["rungs"]] == list(range(10))
        for rung in result["rungs"]:
            assert set(rung) <= {"number", "comment"}
        assert result["rungs"][1]["comment"].startswith("//////////   Prescan")

    def test_outline_rung_without_comment_is_number_only(self, registry):
        result = get_routine_logic(
            registry,
            routine="MainRoutine",
            program="MainProgram",
            detail="outline",
            path="example.L5X",
        )
        assert result["rungs"] == [{"number": 0}]

    def test_logic_rung_has_number_and_text_only(self, registry):
        result = get_routine_logic(
            registry,
            routine="SequenceRoutine",
            program="MainProgram",
            detail="logic",
            path="example.L5X",
        )
        assert [r["number"] for r in result["rungs"]] == list(range(10))
        for rung in result["rungs"]:
            assert set(rung) == {"number", "text"}
            assert rung["text"]

    def test_logic_is_much_smaller_than_full(self, registry):
        full = get_routine_logic(
            registry,
            routine="SequenceRoutine",
            program="MainProgram",
            path="example.L5X",
        )
        logic = get_routine_logic(
            registry,
            routine="SequenceRoutine",
            program="MainProgram",
            detail="logic",
            path="example.L5X",
        )
        assert _compact_size(logic) * 4 < _compact_size(full)

    def test_invalid_detail_lists_options(self, registry):
        with pytest.raises(L5XError) as exc_info:
            get_routine_logic(
                registry,
                routine="SequenceRoutine",
                program="MainProgram",
                detail="text",
                path="example.L5X",
            )
        message = str(exc_info.value)
        assert "'full'" in message
        assert "'outline'" in message
        assert "'logic'" in message

    def test_st_full_lines_as_written(self, registry):
        result = get_routine_logic(
            registry,
            routine="StructuredTextRoutine",
            program="AnotherProgram",
            path="example.L5X",
        )
        assert result["detail"] == "full"
        assert result["lines"][0] == {"number": 0, "text": "(*"}
        assert result["lines"][8]["text"] == "// loop here"

    def test_st_outline_only_lines_with_comments(self, registry):
        result = get_routine_logic(
            registry,
            routine="StructuredTextRoutine",
            program="AnotherProgram",
            detail="outline",
            path="example.L5X",
        )
        # Lines 0-1, 3-4 and 6 are inside a multi-line (* ... *) block
        assert [line["number"] for line in result["lines"]] == [
            0,
            1,
            3,
            4,
            6,
            8,
            16,
            19,
            20,
        ]
        assert result["lines"][6]["text"] == "// multiline if"

    def test_st_logic_strips_comments_and_keeps_line_numbers(self, registry):
        result = get_routine_logic(
            registry,
            routine="StructuredTextRoutine",
            program="AnotherProgram",
            detail="logic",
            path="example.L5X",
        )
        numbers = [line["number"] for line in result["lines"]]
        assert 8 not in numbers  # "// loop here" is comment only
        assert 9 in numbers
        line_9 = next(line for line in result["lines"] if line["number"] == 9)
        assert line_9["text"] == "j := 0;"
        for line in result["lines"]:
            assert line["text"]
            assert "//" not in line["text"]
            assert "(*" not in line["text"]

    @pytest.mark.parametrize(
        ("routine", "program"),
        [
            ("SequenceRoutine", "MainProgram"),
            ("StructuredTextRoutine", "AnotherProgram"),
        ],
    )
    @pytest.mark.parametrize("detail", ["full", "outline", "logic"])
    def test_detail_modes_return_all_items_when_under_budget(
        self, registry, routine, program, detail
    ):
        """Under the default budget nothing is cut and no resume keys appear."""
        result = get_routine_logic(
            registry,
            routine=routine,
            program=program,
            detail=detail,
            path="example.L5X",
        )
        assert "truncated" not in result
        assert "next_start_rung" not in result
        assert _compact_size(result) <= MAX_CHARS_DEFAULT


class TestRoutineLogicBudget:
    """The max_chars budget of get_routine_logic."""

    @pytest.mark.parametrize(
        ("routine", "program"),
        [
            ("SequenceRoutine", "MainProgram"),
            ("StructuredTextRoutine", "AnotherProgram"),
        ],
    )
    @pytest.mark.parametrize("detail", ["full", "outline", "logic"])
    @pytest.mark.parametrize("max_chars", [1000, 2000, 8000])
    def test_response_within_max_chars(
        self, registry, routine, program, detail, max_chars
    ):
        result = get_routine_logic(
            registry,
            routine=routine,
            program=program,
            detail=detail,
            max_chars=max_chars,
            path="example.L5X",
        )
        assert _compact_size(result) <= max_chars

    def test_truncation_reports_resume_point(self, registry):
        result = get_routine_logic(
            registry,
            routine="SequenceRoutine",
            program="MainProgram",
            detail="outline",
            max_chars=1000,
            path="example.L5X",
        )
        assert result["truncated"] is True
        assert result["returned_rungs"] == len(result["rungs"])
        assert 0 < result["returned_rungs"] < 10
        assert result["next_start_rung"] == result["rungs"][-1]["number"] + 1
        assert "outline" in result["note"]
        assert "start_rung" in result["note"]

    def test_resume_from_next_start_rung_covers_all_rungs_once(self, registry):
        numbers = [
            rung["number"]
            for rung in _all_items(
                registry,
                "rungs",
                routine="SequenceRoutine",
                program="MainProgram",
                detail="outline",
                max_chars=1000,
                path="example.L5X",
            )
        ]
        assert numbers == list(range(10))

    def test_resume_st_lines_covers_all_lines_once(self, registry):
        numbers = [
            line["number"]
            for line in _all_items(
                registry,
                "lines",
                routine="StructuredTextRoutine",
                program="AnotherProgram",
                detail="full",
                max_chars=1000,
                path="example.L5X",
            )
        ]
        assert numbers == list(range(24))

    def test_single_oversized_rung_is_cut_and_flagged(self, registry):
        full = get_routine_logic(
            registry,
            routine="SequenceRoutine",
            program="MainProgram",
            start_rung=0,
            end_rung=0,
            path="example.L5X",
        )["rungs"][0]["comment"]
        result = get_routine_logic(
            registry,
            routine="SequenceRoutine",
            program="MainProgram",
            start_rung=0,
            end_rung=0,
            max_chars=1000,
            path="example.L5X",
        )
        assert len(result["rungs"]) == 1  # always at least one rung
        rung = result["rungs"][0]
        assert rung["comment_truncated"] is True
        assert 0 < len(rung["comment"]) < len(full)
        assert full.startswith(rung["comment"])
        assert "text_truncated" not in rung
        assert result["truncated"] is True
        assert "next_start_rung" not in result  # nothing was omitted
        assert _compact_size(result) <= 1000

    def test_range_under_budget_is_not_truncated(self, registry):
        result = get_routine_logic(
            registry,
            routine="SequenceRoutine",
            program="MainProgram",
            detail="logic",
            start_rung=2,
            end_rung=4,
            max_chars=1000,
            path="example.L5X",
        )
        assert [r["number"] for r in result["rungs"]] == [2, 3, 4]
        assert "truncated" not in result

    def test_cap_still_applies_with_budget(self, registry, monkeypatch):
        import l5x_mcp.tools.programs as programs_module

        monkeypatch.setattr(programs_module, "MAX_RUNGS_DEFAULT", 2)
        result = get_routine_logic(
            registry,
            routine="SequenceRoutine",
            program="MainProgram",
            detail="logic",
            path="example.L5X",
        )
        assert len(result["rungs"]) == 2
        assert result["returned_rungs"] == 2
        assert result["next_start_rung"] == 2
        assert "(cap)" in result["note"]

    @pytest.mark.parametrize("max_chars", [999, 100001, 0, "8000", True, None])
    def test_invalid_max_chars_rejected(self, registry, max_chars):
        with pytest.raises(L5XError) as exc_info:
            get_routine_logic(
                registry,
                routine="SequenceRoutine",
                program="MainProgram",
                max_chars=max_chars,
                path="example.L5X",
            )
        assert "max_chars must be an integer from 1000 to 100000" in str(exc_info.value)

    @pytest.mark.parametrize("max_chars", [1000, 100000])
    def test_boundary_max_chars_accepted(self, registry, max_chars):
        result = get_routine_logic(
            registry,
            routine="SequenceRoutine",
            program="MainProgram",
            max_chars=max_chars,
            path="example.L5X",
        )
        assert _compact_size(result) <= max_chars


class TestShrinkToFit:
    """Cutting one oversized item so it fits the budget."""

    def _budget(self, max_chars):
        return OutputBudget(base_size=json_size({"rungs": []}), max_chars=max_chars)

    def test_comment_then_text_are_cut(self):
        budget = self._budget(1000)
        item = {"number": 3, "comment": "c" * 2000, "text": "t" * 2000}
        cut = _shrink_to_fit(item, budget)
        assert cut["number"] == 3
        assert cut["comment_truncated"] is True
        assert cut["text_truncated"] is True
        assert budget.fits(json_size(cut))

    def test_text_only_item_is_cut(self):
        budget = self._budget(1000)
        cut = _shrink_to_fit({"number": 0, "text": "t" * 5000}, budget)
        assert cut["text_truncated"] is True
        assert "comment_truncated" not in cut
        assert 0 < len(cut["text"]) < 5000
        assert budget.fits(json_size(cut))

    def test_cut_is_longest_prefix_that_fits(self):
        budget = self._budget(1000)
        cut = _shrink_to_fit({"number": 0, "text": "t" * 5000}, budget)
        longer = {
            "number": 0,
            "text": "t" * (len(cut["text"]) + 1),
            "text_truncated": True,
        }
        assert not budget.fits(json_size(longer))

    def test_comment_only_item_keeps_text_key_absent(self):
        budget = self._budget(1000)
        cut = _shrink_to_fit({"number": 5, "comment": "c" * 5000}, budget)
        assert cut["comment_truncated"] is True
        assert "comment" in cut and 0 < len(cut["comment"]) < 5000
        assert "text" not in cut
        assert budget.fits(json_size(cut))


LONG_DESCRIPTION = "abcdefghij" * 2000  # 20000 chars, prefixes are identifiable


def _set_description(registry, monkeypatch, program, routine, text):
    """Give a fixture routine a description for this test only (restored after)."""
    _, project = registry.get_with_path("example.L5X")
    rtn = project.programs[program].routines[routine]
    monkeypatch.setattr(rtn, "description", text)


class TestDescriptionBudget:
    """The routine description counts toward max_chars and is cut if needed."""

    def test_short_description_is_untouched(self, registry, monkeypatch):
        _set_description(
            registry, monkeypatch, "MainProgram", "SequenceRoutine", "Short."
        )
        result = get_routine_logic(
            registry,
            routine="SequenceRoutine",
            program="MainProgram",
            detail="logic",
            path="example.L5X",
        )
        assert result["description"] == "Short."
        assert "description_truncated" not in result

    def test_long_description_is_cut_to_a_prefix_and_flagged(
        self, registry, monkeypatch
    ):
        _set_description(
            registry, monkeypatch, "MainProgram", "SequenceRoutine", LONG_DESCRIPTION
        )
        result = get_routine_logic(
            registry,
            routine="SequenceRoutine",
            program="MainProgram",
            detail="logic",
            max_chars=1000,
            path="example.L5X",
        )
        assert result["description_truncated"] is True
        assert 0 < len(result["description"]) < len(LONG_DESCRIPTION)
        assert LONG_DESCRIPTION.startswith(result["description"])
        assert _compact_size(result) <= 1000
        assert len(result["rungs"]) >= 1

    @pytest.mark.parametrize("detail", ["full", "outline", "logic"])
    def test_huge_description_still_within_budget_with_items(
        self, registry, monkeypatch, detail
    ):
        """Even a description far over budget leaves room for an item."""
        _set_description(
            registry, monkeypatch, "MainProgram", "SequenceRoutine", LONG_DESCRIPTION
        )
        result = get_routine_logic(
            registry,
            routine="SequenceRoutine",
            program="MainProgram",
            detail=detail,
            max_chars=1000,
            path="example.L5X",
        )
        assert result["description_truncated"] is True
        assert _compact_size(result) <= 1000
        assert len(result["rungs"]) >= 1
        assert result["truncated"] is True

    def test_huge_st_description_within_budget(self, registry, monkeypatch):
        _set_description(
            registry,
            monkeypatch,
            "AnotherProgram",
            "StructuredTextRoutine",
            LONG_DESCRIPTION,
        )
        result = get_routine_logic(
            registry,
            routine="StructuredTextRoutine",
            program="AnotherProgram",
            detail="full",
            max_chars=1000,
            path="example.L5X",
        )
        assert result["description_truncated"] is True
        assert _compact_size(result) <= 1000
        assert len(result["lines"]) >= 1


FIXTURE_FILE = Path(__file__).parent / "fixtures" / "example.L5X"


class TestRoutineOperands:
    """The operands map of get_routine_logic (include_operands / include_values)."""

    def test_operands_present_by_default(self, registry):
        result = get_routine_logic(
            registry,
            routine="SequenceRoutine",
            program="MainProgram",
            detail="logic",
            path="example.L5X",
        )
        entry = result["operands"]["sequence.currentStep"]
        assert entry["desc"] == "Active Step Number"
        assert entry["type"] == "DINT"
        assert "value" not in entry  # values are off by default
        assert "values_note" not in result

    def test_include_operands_false_omits_map(self, registry):
        result = get_routine_logic(
            registry,
            routine="SequenceRoutine",
            program="MainProgram",
            include_operands=False,
            path="example.L5X",
        )
        assert "operands" not in result
        assert len(result["rungs"]) == 10

    def test_outline_has_no_operands(self, registry):
        result = get_routine_logic(
            registry,
            routine="SequenceRoutine",
            program="MainProgram",
            detail="outline",
            path="example.L5X",
        )
        assert "operands" not in result
        assert "operands_unparsed" not in result

    def test_include_values_adds_values_and_note(self, registry):
        result = get_routine_logic(
            registry,
            routine="SequenceRoutine",
            program="MainProgram",
            detail="logic",
            include_values=True,
            path="example.L5X",
        )
        assert result["operands"]["sequence.currentStep"]["value"] == 7000
        assert result["values_note"] == VALUES_NOTE

    def test_values_note_absent_when_no_value_is_shown(self, registry):
        # Rung 2 references only the sequence structure, which has no scalar value
        result = get_routine_logic(
            registry,
            routine="SequenceRoutine",
            program="MainProgram",
            detail="logic",
            start_rung=2,
            end_rung=2,
            include_values=True,
            path="example.L5X",
        )
        assert "values_note" not in result
        assert all("value" not in e for e in result["operands"].values())

    def test_include_values_requires_include_operands(self, registry):
        with pytest.raises(L5XError, match="requires include_operands"):
            get_routine_logic(
                registry,
                routine="SequenceRoutine",
                program="MainProgram",
                include_operands=False,
                include_values=True,
                path="example.L5X",
            )

    def test_constant_shows_value_from_a_program_reference(self, tmp_path):
        """A_CONSTANT is unused in the fixture; add a reference in a copy."""
        text = FIXTURE_FILE.read_text(encoding="utf-8")
        old = "<![CDATA[JSR(SequenceRoutine,0);]]>"
        assert text.count(old) >= 1
        edited = text.replace(old, "<![CDATA[MOVE(A_CONSTANT,a_dint);]]>", 1)
        (tmp_path / "edited.L5X").write_text(edited, encoding="utf-8")

        result = get_routine_logic(
            ProjectRegistry(tmp_path),
            routine="MainRoutine",
            program="MainProgram",
            path="edited.L5X",
        )
        assert result["rungs"][0]["text"] == "MOVE(A_CONSTANT,a_dint);"
        entry = result["operands"]["A_CONSTANT"]
        assert entry["const"] is True
        assert entry["value"] == 42
        assert entry["desc"] == "the answer to life the universe and everything"
        assert "values_note" not in result  # a constant is not a live value

    def test_module_io_operand_has_module_scope(self, registry):
        result = get_routine_logic(
            registry,
            routine="io",
            program="AnotherProgram",
            detail="logic",
            path="example.L5X",
        )
        entry = result["operands"]["Local:1:I.Pt00.Data"]
        assert entry["scope"] == "module_io"
        assert entry["type"] == "BOOL"

    def test_aoi_operand_described_from_operand_comment(self, registry):
        result = get_routine_logic(
            registry,
            routine="Logic",
            aoi="FanucRobot",
            detail="logic",
            path="example.L5X",
        )
        assert result["operands"]["seq.fault.0"]["desc"] == (
            "Robot fault did not reset when running"
        )

    def test_st_operands_come_from_comment_stripped_code(self, registry):
        """Words inside comments are not operands; full and logic agree."""
        full = get_routine_logic(
            registry,
            routine="StructuredTextRoutine",
            program="AnotherProgram",
            detail="full",
            path="example.L5X",
        )
        logic = get_routine_logic(
            registry,
            routine="StructuredTextRoutine",
            program="AnotherProgram",
            detail="logic",
            path="example.L5X",
        )
        assert full["operands"]["j"]["type"] == "DINT"
        assert full["operands"] == logic["operands"]
        assert "loop" not in full["operands"]

    def test_unparsed_rung_is_listed_and_does_not_fail(self, registry, monkeypatch):
        _, project = registry.get_with_path("example.L5X")
        rung = project.programs["MainProgram"].routines["SequenceRoutine"].rungs[2]
        monkeypatch.setattr(rung, "text", "EQ(sequence.currentStep,0")

        result = get_routine_logic(
            registry,
            routine="SequenceRoutine",
            program="MainProgram",
            detail="logic",
            path="example.L5X",
        )
        assert result["operands_unparsed"] == [2]
        assert [r["number"] for r in result["rungs"]] == list(range(10))
        assert result["rungs"][2]["text"] == "EQ(sequence.currentStep,0"

    def test_operands_map_only_covers_returned_rungs(self, registry):
        result = get_routine_logic(
            registry,
            routine="SequenceRoutine",
            program="MainProgram",
            detail="full",
            max_chars=2000,
            path="example.L5X",
        )
        assert result["truncated"] is True
        assert 0 < len(result["rungs"]) < 10
        expected: set[str] = set()
        for rung in result["rungs"]:
            single = get_routine_logic(
                registry,
                routine="SequenceRoutine",
                program="MainProgram",
                detail="full",
                start_rung=rung["number"],
                end_rung=rung["number"],
                path="example.L5X",
            )
            expected |= set(single.get("operands", {}))
        assert set(result.get("operands", {})) == expected

    @pytest.mark.parametrize(
        ("routine", "program"),
        [
            ("SequenceRoutine", "MainProgram"),
            ("StructuredTextRoutine", "AnotherProgram"),
        ],
    )
    @pytest.mark.parametrize("detail", ["full", "logic"])
    @pytest.mark.parametrize("max_chars", [1000, 2000, 8000])
    def test_response_within_max_chars_with_operands(
        self, registry, routine, program, detail, max_chars
    ):
        result = get_routine_logic(
            registry,
            routine=routine,
            program=program,
            detail=detail,
            max_chars=max_chars,
            include_values=True,
            path="example.L5X",
        )
        assert _compact_size(result) <= max_chars

    def test_resume_is_gapless_with_operands(self, registry):
        numbers = [
            rung["number"]
            for rung in _all_items(
                registry,
                "rungs",
                routine="SequenceRoutine",
                program="MainProgram",
                detail="logic",
                max_chars=1000,
                path="example.L5X",
            )
        ]
        assert numbers == list(range(10))


class TestOperandBudgetAccounting:
    """Operand bookkeeping is charged exactly to the size budget."""

    def test_budget_matches_serialized_size(self, registry):
        """The running size equals the size of the serialized response."""
        _, project = registry.get_with_path("example.L5X")
        rtn = project.programs["MainProgram"].routines["SequenceRoutine"]
        resolver = OperandResolver(project, "program", "MainProgram")
        budget = OutputBudget(json_size({"rungs": [], "operands": {}}), 10**6)

        selection = _select_items(
            _rung_candidates(rtn, "logic", 0, None, resolver), budget, 200
        )
        response = {"rungs": selection.items, "operands": selection.ledger.entries}
        assert budget.size == json_size(response)

    def test_shared_operand_is_charged_once(self):
        ledger = _OperandLedger()
        first = _Candidate(0, {"number": 0}, {"x": {"type": "DINT"}})
        second = _Candidate(1, {"number": 1}, {"x": {"type": "DINT"}})
        ledger.commit(ledger.plan(first, keep=True))
        plan = ledger.plan(second, keep=True)
        assert plan.delta == 0
        assert plan.entries == {}

    def test_first_item_operands_left_out_before_text_is_cut(self):
        operands = {f"op{i}": {"desc": "d" * 100, "type": "DINT"} for i in range(20)}
        cand = _Candidate(4, {"number": 4, "text": "x" * 50}, operands)
        budget = OutputBudget(json_size({"rungs": [], "operands": {}}), 1000)

        selection = _select_items(iter([cand]), budget, 200)
        assert selection.items == [{"number": 4, "text": "x" * 50}]
        assert selection.ledger.omitted == [4]
        assert selection.ledger.entries == {}
        assert selection.content_truncated is False
        assert json_size({"rungs": selection.items}) <= 1000
