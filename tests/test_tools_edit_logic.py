"""Tests for the routine, rung and structured text write tools."""

import pytest
from py_l5x import load

from l5x_mcp.registry import DEFAULT_OUTPUT_DIR, ItemNotFoundError, L5XError
from l5x_mcp.tools.edit_logic import (
    add_routine,
    add_rungs,
    remove_routine,
    remove_rungs,
    rename_routine,
    replace_rung,
    set_st_lines,
)

OUT_DIR = DEFAULT_OUTPUT_DIR
OUT = OUT_DIR + "/"
EXAMPLE = "example.L5X"


def _read(editable, rel):
    return load(str(editable.root / rel))


class TestRoutineTypeGuard:
    def test_routine_of_unknown_type_is_refused(self, editable):
        add_routine(editable, "MainProgram", "Blank", output_path="b.L5X", path=EXAMPLE)
        blank = editable.root / OUT_DIR / "b.L5X"
        text = blank.read_text()
        assert '<Routine Name="Blank" Type="RLL"/>' in text
        (editable.root / "blank.L5X").write_text(
            text.replace(
                '<Routine Name="Blank" Type="RLL"/>', '<Routine Name="Blank"/>'
            )
        )
        with pytest.raises(L5XError, match="unknown type, not RLL"):
            add_rungs(
                editable,
                "MainProgram",
                "Blank",
                rungs=[{"text": "NOP();"}],
                output_path="c.L5X",
                path="blank.L5X",
            )

    def test_st_routine_is_refused_by_rung_tools(self, editable):
        add_routine(
            editable, "MainProgram", "Txt", type="ST", output_path="s.L5X", path=EXAMPLE
        )
        with pytest.raises(L5XError, match="is ST, not RLL"):
            add_rungs(
                editable,
                "MainProgram",
                "Txt",
                rungs=[{"text": "NOP();"}],
                output_path="t.L5X",
                path=OUT + "s.L5X",
            )


class TestAddRoutine:
    def test_adds_rll_routine_with_rung_comment_and_description(self, editable):
        result = add_routine(
            editable,
            program="PeriodicProgram",
            name="NewRll",
            rungs=[{"text": "XIC(test_bool)OTE(test_int);", "comment": "Check"}],
            description="Scratch",
            output_path="out.L5X",
            path=EXAMPLE,
        )

        assert result["rungs"] == 1
        routine = (
            _read(editable, OUT + "out.L5X")
            .programs["PeriodicProgram"]
            .routines["NewRll"]
        )
        assert routine.type_ == "RLL"
        assert routine.description == "Scratch"
        assert [r.text for r in routine.rungs] == ["XIC(test_bool)OTE(test_int);"]
        assert routine.rungs[0].comment == "Check"

    def test_adds_st_routine_with_lines(self, editable):
        result = add_routine(
            editable,
            program="AnotherProgram",
            name="NewSt",
            type="ST",
            lines=["a := 1;", "b := a + 1;"],
            output_path="out.L5X",
            path=EXAMPLE,
        )

        assert result["lines"] == 2
        routine = (
            _read(editable, OUT + "out.L5X")
            .programs["AnotherProgram"]
            .routines["NewSt"]
        )
        assert routine.type_ == "ST"
        assert routine.st_code == "a := 1;\nb := a + 1;"

    def test_lines_on_rll_and_rungs_on_st_are_refused(self, editable):
        with pytest.raises(L5XError, match="lines are for ST routines"):
            add_routine(
                editable,
                program="PeriodicProgram",
                name="Bad",
                lines=["x := 1;"],
                output_path="out.L5X",
                path=EXAMPLE,
            )
        with pytest.raises(L5XError, match="rungs are for RLL routines"):
            add_routine(
                editable,
                program="AnotherProgram",
                name="Bad",
                type="ST",
                rungs=[{"text": "XIC(a)OTE(b);"}],
                output_path="out.L5X",
                path=EXAMPLE,
            )
        assert not (editable.root / OUT_DIR / "out.L5X").exists()

    def test_duplicate_routine_name_is_refused(self, editable):
        with pytest.raises(L5XError, match="MainRoutine"):
            add_routine(
                editable,
                program="MainProgram",
                name="MainRoutine",
                output_path="out.L5X",
                path=EXAMPLE,
            )

    def test_unknown_program_lists_programs(self, editable):
        with pytest.raises(ItemNotFoundError, match="MainProgram"):
            add_routine(
                editable,
                program="Nope",
                name="X",
                output_path="out.L5X",
                path=EXAMPLE,
            )


class TestRenameRoutine:
    def test_main_routine_setting_follows_the_rename(self, editable):
        result = rename_routine(
            editable,
            program="MainProgram",
            name="MainRoutine",
            new_name="MainR2",
            output_path="out.L5X",
            path=EXAMPLE,
        )

        assert result["renamed"] == {"from": "MainRoutine", "to": "MainR2"}
        program = _read(editable, OUT + "out.L5X").programs["MainProgram"]
        assert program.main_routine_name == "MainR2"
        assert "MainR2" in program.routines
        assert "references" not in result

    def test_reports_jsr_callers(self, editable):
        result = rename_routine(
            editable,
            program="MainProgram",
            name="SequenceRoutine",
            new_name="Sequence2",
            output_path="out.L5X",
            path=EXAMPLE,
        )

        assert result["references"]["locations"] == ["MainProgram/MainRoutine rung 0"]
        # JSR text is not rewritten; the caller still names the old routine.
        caller = (
            _read(editable, OUT + "out.L5X")
            .programs["MainProgram"]
            .routines["MainRoutine"]
        )
        assert caller.rungs[0].text == "JSR(SequenceRoutine,0);"

    def test_rename_to_existing_name_is_refused(self, editable):
        with pytest.raises(L5XError, match="MainRoutine"):
            rename_routine(
                editable,
                program="MainProgram",
                name="SequenceRoutine",
                new_name="MainRoutine",
                output_path="out.L5X",
                path=EXAMPLE,
            )


class TestRemoveRoutine:
    def test_main_routine_cannot_be_removed(self, editable):
        with pytest.raises(L5XError, match="main or fault routine"):
            remove_routine(
                editable,
                program="MainProgram",
                name="MainRoutine",
                output_path="out.L5X",
                path=EXAMPLE,
            )
        assert not (editable.root / OUT_DIR / "out.L5X").exists()

    def test_removes_and_reports_jsr_callers(self, editable):
        result = remove_routine(
            editable,
            program="MainProgram",
            name="SequenceRoutine",
            output_path="out.L5X",
            path=EXAMPLE,
        )

        assert result["removed"] == "SequenceRoutine"
        assert result["references"]["locations"] == ["MainProgram/MainRoutine rung 0"]
        program = _read(editable, OUT + "out.L5X").programs["MainProgram"]
        assert "SequenceRoutine" not in program.routines


class TestRungs:
    def test_add_rungs_inserts_at_index_and_renumbers(self, editable):
        result = add_rungs(
            editable,
            program="PeriodicProgram",
            routine="main",
            rungs=[{"text": "XIC(test_bool)OTE(test_dint);"}],
            index=0,
            output_path="out.L5X",
            path=EXAMPLE,
        )

        assert result["inserted"] == [0]
        assert result["rung_count"] == 3
        rungs = (
            _read(editable, OUT + "out.L5X")
            .programs["PeriodicProgram"]
            .routines["main"]
            .rungs
        )
        assert rungs[0].text == "XIC(test_bool)OTE(test_dint);"
        assert [r.number for r in rungs] == [0, 1, 2]

    def test_add_rungs_appends_by_default(self, editable):
        result = add_rungs(
            editable,
            program="PeriodicProgram",
            routine="main",
            rungs=[{"text": "XIC(test_bool)OTE(test_dint);"}],
            output_path="out.L5X",
            path=EXAMPLE,
        )

        assert result["inserted"] == [2]
        rungs = (
            _read(editable, OUT + "out.L5X")
            .programs["PeriodicProgram"]
            .routines["main"]
            .rungs
        )
        assert rungs[-1].text == "XIC(test_bool)OTE(test_dint);"

    def test_rungs_need_balanced_brackets_and_semicolon(self, editable):
        with pytest.raises(L5XError, match="unclosed '\\('"):
            add_rungs(
                editable,
                program="PeriodicProgram",
                routine="main",
                rungs=[{"text": "XIC(test_bool OTE(x);"}],
                output_path="out.L5X",
                path=EXAMPLE,
            )
        assert not (editable.root / OUT_DIR / "out.L5X").exists()

    def test_rungs_are_refused_for_st_routines(self, editable):
        with pytest.raises(L5XError, match="ST, not RLL"):
            add_rungs(
                editable,
                program="AnotherProgram",
                routine="StructuredTextRoutine",
                rungs=[{"text": "XIC(a)OTE(b);"}],
                output_path="out.L5X",
                path=EXAMPLE,
            )

    def test_index_out_of_range_is_refused(self, editable):
        with pytest.raises(L5XError, match="out of range"):
            add_rungs(
                editable,
                program="PeriodicProgram",
                routine="main",
                rungs=[{"text": "XIC(a)OTE(b);"}],
                index=9,
                output_path="out.L5X",
                path=EXAMPLE,
            )

    def test_replace_rung_keeps_comment_when_only_text_changes(self, editable):
        add_rungs(
            editable,
            program="PeriodicProgram",
            routine="main",
            rungs=[{"text": "XIC(test_bool)OTE(test_int);", "comment": "keep me"}],
            index=0,
            output_path="step1.L5X",
            path=EXAMPLE,
        )

        result = replace_rung(
            editable,
            program="PeriodicProgram",
            routine="main",
            number=0,
            text="XIC(test_bool)OTE(test_dint);",
            output_path="step2.L5X",
            path=OUT + "step1.L5X",
        )

        assert result["comment"] == "keep me"
        rung = (
            _read(editable, OUT + "step2.L5X")
            .programs["PeriodicProgram"]
            .routines["main"]
            .rungs[0]
        )
        assert rung.text == "XIC(test_bool)OTE(test_dint);"
        assert rung.comment == "keep me"

    def test_replace_rung_with_empty_comment_removes_it(self, editable):
        replace_rung(
            editable,
            program="PeriodicProgram",
            routine="main",
            number=1,
            comment="",
            output_path="out.L5X",
            path=EXAMPLE,
        )

        rung = (
            _read(editable, OUT + "out.L5X")
            .programs["PeriodicProgram"]
            .routines["main"]
            .rungs[1]
        )
        assert not rung.comment

    def test_replace_rung_requires_text_or_comment(self, editable):
        with pytest.raises(L5XError, match="nothing to change"):
            replace_rung(
                editable,
                program="PeriodicProgram",
                routine="main",
                number=0,
                output_path="out.L5X",
                path=EXAMPLE,
            )

    def test_replace_rung_out_of_range(self, editable):
        with pytest.raises(L5XError, match="rung 9 out of range"):
            replace_rung(
                editable,
                program="PeriodicProgram",
                routine="main",
                number=9,
                text="XIC(a)OTE(b);",
                output_path="out.L5X",
                path=EXAMPLE,
            )

    def test_remove_rungs_removes_several_and_renumbers(self, editable):
        result = remove_rungs(
            editable,
            program="PeriodicProgram",
            routine="main",
            numbers=[1, 0],
            output_path="out.L5X",
            path=EXAMPLE,
        )

        assert result["removed"] == [0, 1]
        assert result["rung_count"] == 0

    def test_remove_rungs_out_of_range_writes_nothing(self, editable):
        with pytest.raises(L5XError, match=r"rungs \[5\] out of range"):
            remove_rungs(
                editable,
                program="PeriodicProgram",
                routine="main",
                numbers=[0, 5],
                output_path="out.L5X",
                path=EXAMPLE,
            )
        assert not (editable.root / OUT_DIR / "out.L5X").exists()


class TestSetStLines:
    def test_replaces_all_lines(self, editable):
        result = set_st_lines(
            editable,
            program="AnotherProgram",
            routine="StructuredTextRoutine",
            lines=["IF a THEN", "  b := 2;", "END_IF;"],
            output_path="out.L5X",
            path=EXAMPLE,
        )

        assert result["line_count"] == 3
        routine = (
            _read(editable, OUT + "out.L5X")
            .programs["AnotherProgram"]
            .routines["StructuredTextRoutine"]
        )
        assert routine.st_code == "IF a THEN\n  b := 2;\nEND_IF;"

    def test_refuses_rll_routines(self, editable):
        with pytest.raises(L5XError, match="is RLL, not ST"):
            set_st_lines(
                editable,
                program="MainProgram",
                routine="MainRoutine",
                lines=["x := 1;"],
                output_path="out.L5X",
                path=EXAMPLE,
            )
