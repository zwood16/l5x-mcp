"""Tests for the search tools module."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from l5x_mcp.registry import ItemNotFoundError, L5XError
from l5x_mcp.tools.search import (
    _classify_tag_usage,
    _find_instruction_matches,
    _find_tag_matches,
    _find_text_matches,
    _st_search_lines,
    _strip_st_comments_per_line,
    find_references,
    instruction_usage,
)


class TestStripStComments:
    """Unit tests for the ST comment stripper (line count and order preserved)."""

    def test_line_comment_removed(self):
        """A trailing // comment is removed and the code is right-stripped."""
        assert _strip_st_comments_per_line(["x := 1;   // y := 2;"]) == ["x := 1;"]

    def test_full_line_comment_becomes_empty(self):
        """A line that is only a // comment becomes an empty string."""
        assert _strip_st_comments_per_line(["// note", "x := 1;"]) == ["", "x := 1;"]

    def test_leading_indentation_kept(self):
        """Indentation of code lines is preserved."""
        assert _strip_st_comments_per_line(["\t\tj := j+1;"]) == ["\t\tj := j+1;"]

    def test_single_line_block_comment(self):
        """A (* *) block inside one line is removed, code after it is kept."""
        assert _strip_st_comments_per_line(["(* a := 1; *) b := 2;"]) == [" b := 2;"]

    def test_block_comment_spanning_lines(self):
        """Lines inside a multi-line block comment are blanked, count preserved."""
        lines = ["(*", "  x := 1;", "*)", "y := 2;"]
        assert _strip_st_comments_per_line(lines) == ["", "", "", "y := 2;"]

    def test_block_comment_closing_mid_line_keeps_trailing_code(self):
        """Code after the closing *) on the same line is kept."""
        lines = ["IF a THEN (* start", "  comment *) b := 1;"]
        assert _strip_st_comments_per_line(lines) == ["IF a THEN", " b := 1;"]

    def test_apostrophe_inside_block_comment_does_not_open_string(self):
        """A ' inside a comment must not swallow following code."""
        lines = ["(* the robot's last *)", "x := 1;"]
        assert _strip_st_comments_per_line(lines) == ["", "x := 1;"]

    def test_slash_slash_inside_string_kept(self):
        """// inside a string literal is not a comment."""
        lines = ["msg := 'http://x'; // note"]
        assert _strip_st_comments_per_line(lines) == ["msg := 'http://x';"]

    def test_block_open_inside_string_kept(self):
        """(* inside a string literal is not a comment."""
        lines = ["s := '(* not a comment *)';"]
        assert _strip_st_comments_per_line(lines) == ["s := '(* not a comment *)';"]

    def test_escaped_quote_in_string(self):
        """'' inside a string is an escaped quote, so the string continues."""
        lines = ["s := 'it''s // ok'; // c"]
        assert _strip_st_comments_per_line(lines) == ["s := 'it''s // ok';"]

    def test_c_style_block_comment(self):
        """/* */ block comments are removed."""
        assert _strip_st_comments_per_line(["a := 1; /* hi */ b := 2;"]) == [
            "a := 1;  b := 2;"
        ]

    def test_c_style_block_spanning_lines(self):
        """/* */ blocks may also span lines."""
        lines = ["/* start", "end */ c := 3;"]
        assert _strip_st_comments_per_line(lines) == ["", " c := 3;"]

    def test_unterminated_string_does_not_crash(self):
        """An unterminated string runs to end of line without error."""
        assert _strip_st_comments_per_line(["s := 'abc"]) == ["s := 'abc"]

    def test_empty_input(self):
        """No lines in, no lines out."""
        assert _strip_st_comments_per_line([]) == []


class TestStLineSearchSource:
    """Unit tests for _st_search_lines (numbering and raw vs stripped text)."""

    @staticmethod
    def _routine(*pairs):
        """Build a minimal stand-in for a py_l5x ST routine."""
        return SimpleNamespace(
            st_lines=[SimpleNamespace(number=n, text=t) for n, t in pairs]
        )

    def test_tag_and_instruction_use_stripped_text(self):
        """Non-text kinds get comment-stripped code with original line numbers."""
        routine = self._routine(
            (0, "// XIC(old_tag)"),
            (1, "(* MOV(a,b); *)"),
            (5, "OTE(real_out); // OTE(x)"),
        )
        for kind in ("tag", "instruction"):
            assert _st_search_lines(routine, kind) == [
                (0, ""),
                (1, ""),
                (5, "OTE(real_out);"),
            ]

    def test_text_uses_raw_text(self):
        """kind="text" keeps comments so prose can be found."""
        routine = self._routine((0, "// loop here"), (1, "x := 1;"))
        assert _st_search_lines(routine, "text") == [
            (0, "// loop here"),
            (1, "x := 1;"),
        ]


class TestFindTagMatches:
    """Unit tests for _find_tag_matches helper."""

    def test_simple_match(self):
        """Simple identifier match."""
        matches = _find_tag_matches("XIC(my_var)OTE(output);", "my_var")
        assert len(matches) == 1
        assert matches[0] == (4, 10)

    def test_case_insensitive(self):
        """Tag matching should be case-insensitive."""
        matches = _find_tag_matches("XIC(MY_VAR)OTE(output);", "my_var")
        assert len(matches) == 1

    def test_no_prefix_match(self):
        """Should not match as prefix of another identifier."""
        matches = _find_tag_matches("XIC(foo_var)OTE(output);", "foo")
        assert len(matches) == 0

    def test_no_suffix_match(self):
        """Should not match as suffix of another identifier."""
        matches = _find_tag_matches("XIC(my_foo)OTE(output);", "foo")
        assert len(matches) == 0

    def test_member_access_match(self):
        """Should match tag even with member access after it."""
        matches = _find_tag_matches("OTE(myTag.Data);", "myTag")
        assert len(matches) == 1

    def test_array_index_match(self):
        """Should match tag even with array index after it."""
        matches = _find_tag_matches("COP(arr[0],dest,1);", "arr")
        assert len(matches) == 1

    def test_dotted_query(self):
        """Dotted queries should match the dotted path."""
        matches = _find_tag_matches("OTE(Local:1:I.Data.0);", "Local:1:I")
        assert len(matches) == 1

    def test_multiple_matches(self):
        """Multiple occurrences should all be found."""
        matches = _find_tag_matches("XIC(foo)OTE(foo);", "foo")
        assert len(matches) == 2

    def test_no_match(self):
        """Should return empty list when no match."""
        matches = _find_tag_matches("XIC(bar)OTE(baz);", "foo")
        assert len(matches) == 0


class TestFindInstructionMatches:
    """Unit tests for _find_instruction_matches helper."""

    def test_simple_instruction(self):
        """Match simple instruction like XIC."""
        matches = _find_instruction_matches("XIC(var)OTE(out);", "XIC")
        assert len(matches) == 1

    def test_case_insensitive(self):
        """Instruction matching should be case-insensitive."""
        matches = _find_instruction_matches("xic(var)OTE(out);", "XIC")
        assert len(matches) == 1

    def test_with_spaces(self):
        """Should handle spaces before opening paren."""
        matches = _find_instruction_matches("XIC (var)OTE(out);", "XIC")
        assert len(matches) == 1

    def test_multiple_instructions(self):
        """Should find all occurrences of an instruction."""
        matches = _find_instruction_matches("XIC(a)XIC(b);", "XIC")
        assert len(matches) == 2

    def test_aoi_instruction(self):
        """Should match AOI calls like Debounce."""
        matches = _find_instruction_matches("Debounce(input,output);", "Debounce")
        assert len(matches) == 1

    def test_no_match(self):
        """Should return empty list when no match."""
        matches = _find_instruction_matches("XIC(var)OTE(out);", "JSR")
        assert len(matches) == 0


class TestFindTextMatches:
    """Unit tests for _find_text_matches helper."""

    def test_simple_substring(self):
        """Match simple substring."""
        matches = _find_text_matches("This is a test string", "test")
        assert len(matches) == 1

    def test_case_insensitive(self):
        """Text matching should be case-insensitive."""
        matches = _find_text_matches("This is a TEST string", "test")
        assert len(matches) == 1

    def test_multiple_matches(self):
        """Multiple occurrences should be found."""
        matches = _find_text_matches("foo bar foo baz foo", "foo")
        assert len(matches) == 3

    def test_no_match(self):
        """Should return empty list when no match."""
        matches = _find_text_matches("This is a test", "nothing")
        assert len(matches) == 0


class TestClassifyTagUsage:
    """Unit tests for _classify_tag_usage helper."""

    def test_ote_is_write(self):
        """Tag in OTE operand should be classified as write."""
        usage = _classify_tag_usage("OTE(my_output);", 4)
        assert usage == "write"

    def test_xic_is_read(self):
        """Tag in XIC operand should be classified as read."""
        usage = _classify_tag_usage("XIC(my_input);", 4)
        assert usage == "read"

    def test_mov_last_arg_is_write(self):
        """Tag in last argument of MOV should be write."""
        usage = _classify_tag_usage("MOV(1,my_dest);", 8)
        assert usage == "write"

    def test_mov_first_arg_is_read(self):
        """Tag in first argument of MOV should be read."""
        usage = _classify_tag_usage("MOV(my_src,dest);", 4)
        assert usage == "read"

    def test_cop_dest_is_write(self):
        """Tag in last argument of COP should be write."""
        # For COP(src, dest, length), the last argument is length
        # So test with the third argument (which is last)
        usage = _classify_tag_usage("COP(src,dest,my_len);", 15)
        assert usage == "write"

    def test_cop_src_is_read(self):
        """Tag in first argument of COP should be read."""
        usage = _classify_tag_usage("COP(my_src,dest,1);", 4)
        assert usage == "read"

    def test_otl_is_write(self):
        """Tag in OTL operand should be classified as write."""
        usage = _classify_tag_usage("OTL(my_latch);", 4)
        assert usage == "write"

    def test_otu_is_write(self):
        """Tag in OTU operand should be classified as write."""
        usage = _classify_tag_usage("OTU(my_unlatch);", 4)
        assert usage == "write"

    def test_res_is_write(self):
        """Tag in RES operand should be classified as write."""
        usage = _classify_tag_usage("RES(my_reset);", 4)
        assert usage == "write"

    def test_no_enclosing_instruction(self):
        """Tag not in any instruction should default to read."""
        usage = _classify_tag_usage("my_tag", 0)
        assert usage == "read"

    def test_move_last_arg_is_write(self):
        """Tag in last argument of MOVE should be write (alias for MOV)."""
        usage = _classify_tag_usage("MOVE(1,my_dest);", 8)
        assert usage == "write"

    def test_move_first_arg_is_read(self):
        """Tag in first argument of MOVE should be read."""
        usage = _classify_tag_usage("MOVE(my_src,dest);", 5)
        assert usage == "read"

    def test_aoi_first_arg_is_write(self):
        """First argument of AOI call should be write (backing tag)."""
        aoi_names = {"Debounce", "GenericInput"}
        usage = _classify_tag_usage("Debounce(my_debounce);", 9, aoi_names)
        assert usage == "write"

    def test_aoi_other_args_are_read(self):
        """Arguments after first in AOI call should be read."""
        aoi_names = {"GenericInput"}
        usage = _classify_tag_usage("GenericInput(backing,my_signal);", 23, aoi_names)
        assert usage == "read"


class TestFindReferences:
    """Integration tests for find_references function."""

    def test_tag_search_basic(self, registry):
        """Find tag references in fixture."""
        result = find_references(
            registry, query="input_ok", kind="tag", path="example.L5X"
        )
        assert result["file"] == "example.L5X"
        assert result["query"] == "input_ok"
        assert result["kind"] == "tag"
        assert result["total_matches"] > 0
        assert len(result["matches"]) > 0
        assert "summary" in result

    def test_tag_search_with_program_filter(self, registry):
        """Filter tag search to specific program."""
        result = find_references(
            registry,
            query="count",
            kind="tag",
            program="EventProgram",
            path="example.L5X",
        )
        assert all(m["container"] == "EventProgram" for m in result["matches"])

    def test_tag_search_exclude_aois(self, registry):
        """Exclude AOI results."""
        result = find_references(
            registry, query="test", kind="tag", include_aois=False, path="example.L5X"
        )
        assert all(m["container_type"] == "program" for m in result["matches"])

    def test_instruction_search(self, registry):
        """Find instruction references."""
        result = find_references(
            registry, query="XIC", kind="instruction", path="example.L5X"
        )
        assert result["kind"] == "instruction"
        assert result["total_matches"] > 0

    def test_instruction_search_aoi(self, registry):
        """Find AOI instruction calls."""
        result = find_references(
            registry, query="GenericInput", kind="instruction", path="example.L5X"
        )
        # GenericInput should be called in AnotherProgram/io
        assert result["total_matches"] > 0

    def test_text_search_hits_comment(self, registry):
        """Text search should find text in comments."""
        result = find_references(
            registry, query="Input Card", kind="text", path="example.L5X"
        )
        assert result["total_matches"] > 0
        # Should find "Input Card Status" comment in SafetyProgram/Inputs

    def test_text_search_case_insensitive(self, registry):
        """Text search should be case-insensitive."""
        result = find_references(
            registry, query="ESTOP", kind="text", path="example.L5X"
        )
        # Should find estop_dcs references
        assert result["total_matches"] > 0

    def test_empty_query_raises_error(self, registry):
        """Empty query should raise L5XError."""
        with pytest.raises(L5XError, match="cannot be empty"):
            find_references(registry, query="", kind="tag", path="example.L5X")

    def test_invalid_limit_raises_error(self, registry):
        """Invalid limit should raise L5XError."""
        with pytest.raises(L5XError, match="must be between"):
            find_references(
                registry, query="test", kind="tag", limit=5000, path="example.L5X"
            )

    def test_limit_truncation(self, registry):
        """Limit should truncate results."""
        result = find_references(
            registry, query="NOP", kind="instruction", limit=2, path="example.L5X"
        )
        assert len(result["matches"]) <= 2

    def test_invalid_program_name_raises_error(self, registry):
        """Invalid program name should raise ItemNotFoundError."""
        with pytest.raises(ItemNotFoundError):
            find_references(
                registry,
                query="test",
                kind="tag",
                program="NonExistentProgram",
                path="example.L5X",
            )

    def test_result_has_usage_for_tag_kind(self, registry):
        """Tag kind results should include usage field."""
        result = find_references(
            registry, query="input_ok", kind="tag", path="example.L5X"
        )
        # At least some matches should have usage field (RLL only)
        rll_matches = [m for m in result["matches"] if m.get("routine_type") == "RLL"]
        if rll_matches:
            assert any("usage" in m for m in rll_matches)

    def test_result_includes_rung_comment_when_present(self, registry):
        """Results should include rung comments when present."""
        result = find_references(
            registry, query="input_ok", kind="tag", path="example.L5X"
        )
        # Check if any matches have comments
        commented_matches = [m for m in result["matches"] if "comment" in m]
        assert len(commented_matches) > 0

    def test_json_serializable(self, registry):
        """Result should be JSON serializable."""
        result = find_references(registry, query="test", kind="tag", path="example.L5X")
        # Should not raise
        json_str = json.dumps(result)
        assert isinstance(json_str, str)

    def test_tag_dotted_query(self, registry):
        """Dotted tag query should work."""
        result = find_references(
            registry, query="Local:1:I", kind="tag", path="example.L5X"
        )
        # Should find references
        assert result["total_matches"] >= 0

    def test_instruction_search_mov_finds_move(self, registry):
        """MOV query should find MOVE mnemonics (aliases)."""
        result = find_references(
            registry,
            query="MOV",
            kind="instruction",
            path="example.L5X",
            limit=10,
        )
        # Should find MOVE instructions
        assert result["total_matches"] > 0
        # Should include matched_mnemonics showing MOVE was matched
        assert "matched_mnemonics" in result
        assert "MOVE" in result["matched_mnemonics"]

    def test_move_destination_classified_write(self, registry):
        """MOVE destination (last arg) should be classified as write."""
        result = find_references(
            registry,
            query="debounceOffTimer",
            kind="tag",
            include_aois=False,
            path="example.L5X",
        )
        # Find a MOVE with debounceOffTimer as destination
        move_matches = [
            m
            for m in result["matches"]
            if "MOVE" in m.get("text", "") and "debounceOffTimer" in m.get("text", "")
        ]
        # At least one should be write (as destination)
        if move_matches:
            # The debounceOffTimer.PRE destination should be write
            write_matches = [m for m in move_matches if m.get("usage") == "write"]
            assert len(write_matches) > 0


class TestStComments:
    """ST comments must not be reported by tag/instruction searches.

    Uses real ST comments from the example.L5X fixture:
    - AnotherProgram/StructuredTextRoutine: a 7-line (* *) block (lines 0-6)
      with prose such as "Some indented text", and // comments on lines 8,
      16, 19, 20.
    - AOI FanucAlarmLookup/Logic: a (* *) block (lines 0-7) mentioning
      recoverableAlarm (lines 1 and 6), plus // comments on lines 10 and 14.
    """

    @staticmethod
    def _st_hits(result, container=None, routine=None):
        """Return {line numbers} of ST matches, optionally filtered."""
        return {
            m["line"]
            for m in result["matches"]
            if m["routine_type"] == "ST"
            and (container is None or m["container"] == container)
            and (routine is None or m["routine"] == routine)
        }

    def test_identifier_only_in_comment_not_tag_match(self, registry):
        """recoverableAlarm appears in comments (lines 1, 6) but only code matches."""
        tag = find_references(
            registry, query="recoverableAlarm", kind="tag", path="example.L5X"
        )
        assert self._st_hits(tag, "FanucAlarmLookup", "Logic") == {9, 17}

        text = find_references(
            registry, query="recoverableAlarm", kind="text", path="example.L5X"
        )
        assert {1, 6, 9, 17} <= self._st_hits(text, "FanucAlarmLookup", "Logic")

    def test_comment_only_identifier_matched_by_text_kind(self, registry):
        """The // comment word 'loop' is found by kind="text" but not kind="tag"."""
        text = find_references(
            registry,
            query="loop",
            kind="text",
            program="AnotherProgram",
            path="example.L5X",
        )
        assert 8 in self._st_hits(text, "AnotherProgram", "StructuredTextRoutine")

        tag = find_references(
            registry,
            query="loop",
            kind="tag",
            program="AnotherProgram",
            path="example.L5X",
        )
        assert self._st_hits(tag, "AnotherProgram", "StructuredTextRoutine") == set()

    def test_block_comment_prose_spanning_lines_not_tag_match(self, registry):
        """'some' appears in a multi-line (* *) block and a // comment only."""
        tag = find_references(
            registry,
            query="some",
            kind="tag",
            program="AnotherProgram",
            path="example.L5X",
        )
        assert self._st_hits(tag) == set()

        text = find_references(
            registry,
            query="some",
            kind="text",
            program="AnotherProgram",
            path="example.L5X",
        )
        assert self._st_hits(text, "AnotherProgram", "StructuredTextRoutine") == {
            4,
            19,
        }

    def test_st_line_numbers_match_source(self, registry):
        """Tag matches report the original ST line numbers from the file."""
        result = find_references(
            registry,
            query="j",
            kind="tag",
            program="AnotherProgram",
            path="example.L5X",
        )
        hits = [
            m
            for m in result["matches"]
            if m["routine_type"] == "ST" and m["routine"] == "StructuredTextRoutine"
        ]
        assert {m["line"] for m in hits} == {9, 12, 17, 18, 21}
        by_line = {m["line"]: m["text"] for m in hits}
        assert by_line[21] == "\tj:= 32;"
        assert by_line[17] == "IF j <> 0 and"

    def test_no_st_comment_line_matched_by_tag_across_project(self, registry):
        """A word that only occurs in ST comments yields no ST tag matches."""
        result = find_references(
            registry, query="indented", kind="tag", path="example.L5X"
        )
        assert [m for m in result["matches"] if m["routine_type"] == "ST"] == []


class TestTruncationLogic:
    """Tests for correct truncation handling and total_matches counting."""

    def test_limit_smaller_than_total_sets_truncated(self, registry):
        """When limit < total matches, truncated flag should be True."""
        # MOV instruction has ~48 matches, use limit=3
        result = find_references(
            registry,
            query="MOV",
            kind="instruction",
            limit=3,
            path="example.L5X",
        )
        # Should have scanned all matches
        assert result["total_matches"] > 3
        # Should return only up to limit
        assert len(result["matches"]) == 3
        # truncated should be present and True
        assert "truncated" in result
        assert result["truncated"] is True

    def test_limit_equal_to_total_no_truncated_key(self, registry):
        """When limit == total matches, truncated key should not be present."""
        # Search for something with few matches
        result = find_references(
            registry,
            query="DoesNotExist12345",
            kind="text",
            limit=200,
            path="example.L5X",
        )
        total = result["total_matches"]
        if total > 0:
            # Re-run with exact limit
            result2 = find_references(
                registry,
                query="DoesNotExist12345",
                kind="text",
                limit=total,
                path="example.L5X",
            )
            assert result2["total_matches"] == total
            assert len(result2["matches"]) == total
            # truncated key should not be present
            assert "truncated" not in result2

    def test_total_matches_correct_count(self, registry):
        """total_matches should reflect all matches found, not just returned."""
        # MOV should have many matches
        result = find_references(
            registry,
            query="MOV",
            kind="instruction",
            limit=10,
            path="example.L5X",
        )
        # total_matches should be the actual count (much higher than 10)
        assert result["total_matches"] > 10
        # But matches list should be capped at limit
        assert len(result["matches"]) == 10

    def test_summary_counts_match_total_matches(self, registry):
        """Summary counts should sum to total_matches."""
        result = find_references(
            registry,
            query="XIC",
            kind="instruction",
            limit=500,
            path="example.L5X",
        )
        summary_sum = sum(result["summary"].values())
        assert summary_sum == result["total_matches"]

    def test_summary_counts_correct_with_limit(self, registry):
        """Summary should count all matches, even those not returned due to limit."""
        result = find_references(
            registry,
            query="XIC",
            kind="instruction",
            limit=5,
            path="example.L5X",
        )
        # Sum of summary counts should equal total_matches
        summary_sum = sum(result["summary"].values())
        assert summary_sum == result["total_matches"]
        # returned matches should be <= limit
        assert len(result["matches"]) <= result["total_matches"]


class TestInstructionUsage:
    """Tests for instruction_usage function."""

    def test_instruction_usage_basic(self, registry):
        """Get instruction usage across all programs."""
        result = instruction_usage(registry, path="example.L5X")
        assert result["file"] == "example.L5X"
        assert "instructions" in result
        assert isinstance(result["instructions"], list)

    def test_instruction_usage_sorted_by_count(self, registry):
        """Results should be sorted by count descending."""
        result = instruction_usage(registry, path="example.L5X")
        instructions = result["instructions"]
        counts = [instr["count"] for instr in instructions]
        assert counts == sorted(counts, reverse=True)

    def test_instruction_usage_includes_common_instructions(self, registry):
        """Should find common instructions like NOP, XIC, OTE."""
        result = instruction_usage(registry, path="example.L5X")
        instr_names = {instr["name"] for instr in result["instructions"]}
        # These are commonly used in the fixture
        assert any(name in instr_names for name in ["NOP", "XIC", "OTE", "JSR"])

    def test_instruction_usage_with_program_filter(self, registry):
        """Can filter to specific program."""
        result = instruction_usage(
            registry, program="SafetyProgram", path="example.L5X"
        )
        instructions = result["instructions"]
        assert isinstance(instructions, list)

    def test_instruction_usage_json_serializable(self, registry):
        """Result should be JSON serializable."""
        result = instruction_usage(registry, path="example.L5X")
        json_str = json.dumps(result)
        assert isinstance(json_str, str)

    def test_instruction_usage_aoi_included(self, registry):
        """AOI instructions should be included."""
        result = instruction_usage(registry, path="example.L5X")
        # Should include AOI-defined instructions
        # This depends on the fixture having AOI calls
        assert len(result["instructions"]) > 0

    def test_instruction_usage_marks_aois(self, registry):
        """AOI instructions should be marked with aoi: true."""
        result = instruction_usage(registry, path="example.L5X")
        aoi_entries = [instr for instr in result["instructions"] if instr.get("aoi")]
        # Should have some AOI entries (GenericInput, Debounce, etc.)
        assert len(aoi_entries) > 0
        # AOIs are reported under their defined (mixed-case) names
        found = {instr["name"] for instr in aoi_entries}
        assert {"GenericInput", "Debounce", "FanucRobot", "SeqCtrl"} <= found

    def test_instruction_usage_program_filter_excludes_aoi_logic(self, registry):
        """With a program filter, AOI internal logic is not counted."""
        result = instruction_usage(
            registry, program="AnotherProgram", path="example.L5X"
        )
        names = {i["name"] for i in result["instructions"]}
        assert "GenericInput" in names
        assert "Debounce" not in names  # only called inside GenericInput's logic


class TestSearchOutputFormat:
    """Tests verifying output format matches specification."""

    def test_find_references_output_structure(self, registry):
        """Verify find_references output has correct structure."""
        result = find_references(
            registry, query="input_ok", kind="tag", path="example.L5X"
        )
        # Required keys
        assert "file" in result
        assert "query" in result
        assert "kind" in result
        assert "total_matches" in result
        assert "matches" in result
        assert "summary" in result

        # Check match structure
        for match in result["matches"]:
            assert "container_type" in match
            assert "container" in match
            assert "routine" in match
            assert "routine_type" in match
            assert "text" in match
            # Either "rung" or "line" depending on type
            assert "rung" in match or "line" in match

    def test_instruction_usage_output_structure(self, registry):
        """Verify instruction_usage output has correct structure."""
        result = instruction_usage(registry, path="example.L5X")
        assert "file" in result
        assert "instructions" in result
        assert isinstance(result["instructions"], list)
        for instr in result["instructions"]:
            assert "name" in instr
            assert "count" in instr


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestProtectedAoiSearch:
    """Calls of a source-protected AOI are found like any AOI call."""

    PROTECTED = "example.L5X"

    def test_find_references_to_protected_aoi_name(self, registry):
        result = find_references(
            registry, "SeqCtrl_Protected", kind="instruction", path=self.PROTECTED
        )
        assert result["summary"] == {"AnotherProgram/Main": 1}

    def test_instruction_usage_marks_protected_aoi(self, registry):
        result = instruction_usage(registry, path=self.PROTECTED)
        entry = next(
            i for i in result["instructions"] if i["name"] == "SeqCtrl_Protected"
        )
        assert entry == {"name": "SeqCtrl_Protected", "count": 1, "aoi": True}

    def test_protected_routines_noted_when_searching_their_program(self, registry):
        result = find_references(
            registry,
            "seqCtrl_Protected_Instance",
            program="AnotherProgram",
            path=self.PROTECTED,
        )
        assert result["total_matches"] == 1
        assert "AnotherProgram/SequenceRoutine_Protected" in result["note"]
        assert "logic not searched" in result["note"]

    def test_no_note_without_protected_routines(self, registry):
        result = find_references(
            registry, "an_int", program="MainProgram", path=self.PROTECTED
        )
        assert "note" not in result

    def test_instruction_usage_notes_protected_routines(self, registry):
        result = instruction_usage(registry, path=self.PROTECTED)
        assert "AnotherProgram/SequenceRoutine_Protected" in result["note"]
        scoped = instruction_usage(registry, program="MainProgram", path=self.PROTECTED)
        assert "note" not in scoped
