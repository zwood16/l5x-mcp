"""Tests for the operands module: RLL/ST operand candidate extraction."""

import pytest

from l5x_mcp.operand_paths import parse_operand
from l5x_mcp.operands import (
    InstructionCall,
    extract_rll_operands,
    extract_st_operands,
    parse_rll,
    strip_st_comments,
)


@pytest.fixture(scope="module")
def project(registry):
    """The parsed example.L5X project."""
    return registry.get("example.L5X")


def _names(text):
    return [call.name for call in parse_rll(text)]


# --- parse_rll -------------------------------------------------------------


def test_parse_rll_sequence_and_subscripts():
    calls = parse_rll("XIC(a)OTE(b.c[1].2);")
    assert calls == [
        InstructionCall("XIC", ("a",)),
        InstructionCall("OTE", ("b.c[1].2",)),
    ]


def test_parse_rll_branches_are_not_subscripts():
    assert _names("[XIC(a) ,XIO(b) ]OTE(c);") == ["XIC", "XIO", "OTE"]


def test_parse_rll_nested_branches_and_instructions_without_comma():
    text = "[[XIC(c1) ,XIC(c2) ] MOVE(0,n) ,XIC(p) MOVE(5,n) ];"
    assert _names(text) == ["XIC", "XIC", "MOVE", "XIC", "MOVE"]


def test_parse_rll_string_literal_with_commas_and_parens():
    calls = parse_rll("MSG('a,(b)c$'d',x)OTE(y);")
    assert calls[0] == InstructionCall("MSG", ("'a,(b)c$'d'", "x"))
    assert calls[1] == InstructionCall("OTE", ("y",))


def test_parse_rll_no_args_gives_empty_tuple():
    assert parse_rll("NOP();") == [InstructionCall("NOP", ())]


def test_parse_rll_keeps_nested_function_calls_inside_args():
    calls = parse_rll("CPT(dest,(a+b[idx])*ABS(c)/2.5)")
    assert calls == [InstructionCall("CPT", ("dest", "(a+b[idx])*ABS(c)/2.5"))]


@pytest.mark.parametrize("text", ["XIC(a", "[XIC(a)", "XIC(a))", "XIC(a]", "'x"])
def test_parse_rll_rejects_malformed_text(text):
    with pytest.raises(ValueError):
        parse_rll(text)


# --- extract_rll_operands --------------------------------------------------


def test_rll_basic_with_member_bit_and_subscript():
    assert extract_rll_operands("XIC(a)OTE(b.c[1].2);") == ["a", "b.c[1].2"]


def test_rll_branch_operands():
    assert extract_rll_operands("[XIC(a) ,XIO(b) ]OTE(c);") == ["a", "b", "c"]


def test_rll_move_members():
    assert extract_rll_operands("MOVE(onDelay,debounce.onDelay)") == [
        "onDelay",
        "debounce.onDelay",
    ]


def test_rll_cpt_expression_drops_functions_and_keeps_runtime_index():
    text = "CPT(dest,(a+b[idx])*ABS(c)/2.5)"
    assert extract_rll_operands(text) == ["dest", "a", "b[idx]", "idx", "c"]


def test_rll_cpt_expression_keywords_dropped():
    text = "CPT(x,a MOD b AND NOT (c XOR d))"
    assert extract_rll_operands(text) == ["x", "a", "b", "c", "d"]


def test_rll_jsr_routine_and_literal_skipped():
    assert extract_rll_operands("JSR(SequenceRoutine,0);") == []


def test_rll_jmp_and_lbl_label_skipped():
    assert extract_rll_operands("JMP(begin);LBL(begin);") == []


def test_rll_msg_tag():
    assert extract_rll_operands("MSG(message_tag);") == ["message_tag"]


def test_rll_module_io_tag_names_keep_colons():
    text = "GenericInput(TestInput,Local:1:I.Pt00.Data);"
    assert extract_rll_operands(text) == ["TestInput", "Local:1:I.Pt00.Data"]


def test_rll_program_prefix_kept():
    text = "XIC(\\EM_Gantry._FXN_Change_Active_Tray.Start)"
    assert extract_rll_operands(text) == ["\\EM_Gantry._FXN_Change_Active_Tray.Start"]


def test_rll_string_literal_contents_not_operands():
    text = "MSG('send, (ctl.step) now',msg_tag)"
    assert extract_rll_operands(text) == ["msg_tag"]


def test_rll_numeric_literals_dropped():
    text = "EQ(ctl.step,16#1F)"
    assert extract_rll_operands(text) == ["ctl.step"]
    assert extract_rll_operands("MOVE(-5,x)MOVE(1.5e3,y)MOVE(2#101,z)") == [
        "x",
        "y",
        "z",
    ]


def test_rll_placeholders_dropped():
    assert extract_rll_operands("TON(t,?,?)") == ["t"]


def test_rll_dcs_keeps_enum_keyword_as_candidate():
    # ACTIVE is an enum keyword, not a tag. It is kept here and filtered later.
    assert extract_rll_operands("DCS(dcs1,ACTIVE,250,Local:2:I.Pt00.Data)") == [
        "dcs1",
        "ACTIVE",
        "Local:2:I.Pt00.Data",
    ]


def test_rll_unique_and_order_preserving():
    assert extract_rll_operands("XIC(b)XIC(a)XIC(b)OTE(a)") == ["b", "a"]


def test_rll_runtime_index_with_expression_emits_inner_operands():
    assert extract_rll_operands("MOVE(arr[i+1],out)") == ["arr[i+1]", "i", "out"]


# --- extract_st_operands ---------------------------------------------------


def test_st_if_condition_and_call_argument():
    line = "IF a.b > 5 AND NOT c[i] THEN x := ABS(y) + T#5s; END_IF;"
    assert extract_st_operands(line) == ["a.b", "c[i]", "i", "x", "y"]


def test_st_simple_increment():
    assert extract_st_operands("j := j+1;") == ["j"]


def test_st_typed_and_based_literals_dropped():
    line = "t := DT#2020-01-01-00:00:00 + TOD#12:30:00 + REAL#1.5e3 + 16#FF;"
    assert extract_st_operands(line) == ["t"]


def test_st_keywords_mixed_case():
    line = "if Flag then Cnt := Cnt + 1; end_if;"
    assert extract_st_operands(line) == ["Flag", "Cnt"]


def test_st_string_literal_not_an_operand():
    assert extract_st_operands("msg := 'a := b, (c)';") == ["msg"]


def test_st_booleans_dropped():
    assert extract_st_operands("ok := TRUE OR fault;") == ["ok", "fault"]


def test_st_function_call_name_dropped_arguments_kept():
    assert extract_st_operands("y := TON_CALL(timer, start);") == [
        "y",
        "timer",
        "start",
    ]


def test_st_module_io_name_and_bit():
    assert extract_st_operands("x := Local:1:I.Data.2;") == ["x", "Local:1:I.Data.2"]


# --- strip_st_comments -----------------------------------------------------


def test_strip_st_line_comment_removed():
    assert strip_st_comments(["x := 1; // note"]) == ["x := 1;"]


def test_strip_st_block_comment_inline_and_multiline():
    lines = ["a := 1; (* start", "still comment *) b := 2;", "/* x */ c := 3;"]
    assert strip_st_comments(lines) == ["a := 1;", " b := 2;", " c := 3;"]


def test_strip_st_fully_commented_line_is_empty():
    assert strip_st_comments(["// only", "(* only *)"]) == ["", ""]


def test_strip_st_markers_inside_string_kept():
    assert strip_st_comments(["s := '(* not *) //';"]) == ["s := '(* not *) //';"]


def test_strip_st_escaped_quote_in_string():
    assert strip_st_comments(["s := 'it''s // ok'; // gone"]) == ["s := 'it''s // ok';"]


# --- fixture sweep ---------------------------------------------------------


def _rung_texts(project):
    for program in project.programs.values():
        for routine in program.routines.values():
            for rung in getattr(routine, "rungs", []):
                yield rung.text
    for aoi in project.aois.values():
        for routine in aoi.routines.values():
            for rung in getattr(routine, "rungs", []):
                yield rung.text


def test_fixture_every_rung_parses_and_operands_are_parseable(project):
    count = 0
    for text in _rung_texts(project):
        count += 1
        for operand in extract_rll_operands(text):
            parse_operand(operand)
    assert count > 0


def test_fixture_st_lines_parse(project):
    routine = project.programs["AnotherProgram"].routines["StructuredTextRoutine"]
    lines = strip_st_comments([line.text or "" for line in routine.st_lines])
    assert lines
    for line in lines:
        for operand in extract_st_operands(line):
            parse_operand(operand)
