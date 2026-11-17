"""Write tools for program routines, ladder rungs and structured text."""

from __future__ import annotations

from typing import Any, Literal

from py_l5x.parsers.project import Project
from py_l5x.parsers.routine import Routine

from l5x_mcp.editing import Edit, edit_errors
from l5x_mcp.registry import L5XError, ProjectRegistry, lookup
from l5x_mcp.specs import RungSpecDict
from l5x_mcp.tools.edit_tags import references
from l5x_mcp.tools.programs import _routine_type


def _routine(project: Project, program: str, routine: str) -> tuple[str, Routine]:
    """Look up a program routine (case-insensitive).

    Args:
        project: The project.
        program: Program name.
        routine: Routine name.

    Returns:
        The canonical program name and the routine.
    """
    prog = lookup(project.programs, program, "Program")
    return prog.name, lookup(prog.routines, routine, "Routine")


def _require_type(routine: Routine, kind: str) -> None:
    actual = _routine_type(routine)
    if actual and actual != kind:
        raise L5XError(
            f"routine {routine.name!r} is {actual or 'empty'}, not {kind}; "
            f"this tool only edits {kind} routines"
        )


def add_routine(
    registry: ProjectRegistry,
    program: str,
    name: str,
    output_path: str,
    type: Literal["RLL", "ST"] = "RLL",
    description: str = "",
    rungs: list[RungSpecDict] | None = None,
    lines: list[str] | None = None,
    path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Add a routine to a program and write the result to a new file.

    An RLL routine takes rungs ([{text, comment?}], e.g.
    {"text": "XIC(Start)OTE(Run);"}); an ST routine takes lines (one string per
    line). Call it from the main routine with a JSR rung, e.g.
    "JSR(NewRoutine,0);". Rung text and ST are only checked for balanced
    brackets and a trailing ';' (rungs); undefined tags or wrong instructions
    show up when Studio verifies the project. Use instructions valid for the
    project's version (v36+ uses MOVE, EQ, ... instead of MOV, EQU, ...).

    Args:
        registry: ProjectRegistry to load from.
        program: Program to add the routine to.
        name: New routine name.
        output_path: New .L5X file to write (must not be the source file).
        type: "RLL" (ladder, default) or "ST" (structured text).
        description: Routine description.
        rungs: RLL rungs in order.
        lines: ST lines in order.
        path: Source .L5X file (None for auto-discovery). Never modified.
        overwrite: Replace output_path if it already exists.

    Returns:
        Dict with file, source, program, routine, type and rungs/lines count.
    """
    if type == "RLL" and lines:
        raise L5XError("lines are for ST routines; use rungs for RLL")
    if type == "ST" and rungs:
        raise L5XError("rungs are for RLL routines; use lines for ST")
    edit = Edit.open(registry, path, output_path, overwrite)
    prog = lookup(edit.project.programs, program, "Program")
    with edit_errors(f"routine {name!r}"):
        routine = prog.routines.add(name, type, description=description or None)
        for rung in rungs or []:
            routine.add_rung(rung["text"], rung.get("comment") or None)
        if lines:
            routine.set_st_lines(list(lines))
    count = (
        {"rungs": len(rungs or [])} if type == "RLL" else {"lines": len(lines or [])}
    )
    return edit.save({"program": prog.name, "routine": name, "type": type, **count})


def remove_routine(
    registry: ProjectRegistry,
    program: str,
    name: str,
    output_path: str,
    path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Delete a program routine and write the result to a new file.

    The main and fault routines cannot be removed. JSR calls to the routine
    are NOT removed; the result lists them (references).

    Args:
        registry: ProjectRegistry to load from.
        program: Program name.
        name: Routine name.
        output_path: New .L5X file to write (must not be the source file).
        path: Source .L5X file (None for auto-discovery). Never modified.
        overwrite: Replace output_path if it already exists.

    Returns:
        Dict with file, source, program, removed and references (when any).
    """
    edit = Edit.open(registry, path, output_path, overwrite)
    prog_name, routine = _routine(edit.project, program, name)
    with edit_errors(f"remove routine {routine.name!r}"):
        edit.project.programs[prog_name].routines.remove(routine.name)
    result = edit.save({"program": prog_name, "removed": routine.name})
    found = references(registry, result["file"], routine.name, prog_name)
    if found:
        result["references"] = found
    return result


def rename_routine(
    registry: ProjectRegistry,
    program: str,
    name: str,
    new_name: str,
    output_path: str,
    path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Rename a program routine and write the result to a new file.

    The program's main/fault routine setting follows the rename. JSR calls
    are NOT updated; the result lists them (references).

    Args:
        registry: ProjectRegistry to load from.
        program: Program name.
        name: Current routine name.
        new_name: New routine name.
        output_path: New .L5X file to write (must not be the source file).
        path: Source .L5X file (None for auto-discovery). Never modified.
        overwrite: Replace output_path if it already exists.

    Returns:
        Dict with file, source, program, renamed {from, to} and references.
    """
    edit = Edit.open(registry, path, output_path, overwrite)
    prog_name, routine = _routine(edit.project, program, name)
    old = routine.name
    with edit_errors(f"rename routine {old!r}"):
        edit.project.programs[prog_name].routines.rename(old, new_name)
    result = edit.save({"program": prog_name, "renamed": {"from": old, "to": new_name}})
    if old.lower() != new_name.lower():
        found = references(registry, result["file"], old, prog_name)
        if found:
            result["references"] = found
    return result


def add_rungs(
    registry: ProjectRegistry,
    program: str,
    routine: str,
    rungs: list[RungSpecDict],
    output_path: str,
    index: int | None = None,
    path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Insert ladder rungs into an RLL routine and write the result to a new file.

    Rungs are inserted before rung number index (0-based), or appended when
    index is omitted; following rungs are renumbered. Rung text is neutral
    text such as "XIC(Start)[OTE(Run),TON(Delay,?,?)];". Only bracket balance
    and the trailing ';' are checked; Studio verifies the logic. Use
    instructions valid for the project's version (v36+ uses MOVE, EQ, ...
    instead of MOV, EQU, ...). A literal preset in rung text (TON(t,3000,0))
    overwrites the timer's preset value on import.

    Args:
        registry: ProjectRegistry to load from.
        program: Program name.
        routine: RLL routine name.
        rungs: Rungs to insert, in order ([{text, comment?}]).
        output_path: New .L5X file to write (must not be the source file).
        index: Insert position (0 = first); omit to append.
        path: Source .L5X file (None for auto-discovery). Never modified.
        overwrite: Replace output_path if it already exists.

    Returns:
        Dict with file, source, program, routine, inserted (rung numbers) and
        rung_count (new total).
    """
    if not rungs:
        raise L5XError("rungs must contain at least one rung")
    edit = Edit.open(registry, path, output_path, overwrite)
    prog_name, target = _routine(edit.project, program, routine)
    _require_type(target, "RLL")
    start = len(target.rungs) if index is None else index
    with edit_errors(f"routine {target.name!r}"):
        for offset, rung in enumerate(rungs):
            target.add_rung(rung["text"], rung.get("comment") or None, start + offset)
    return edit.save(
        {
            "program": prog_name,
            "routine": target.name,
            "inserted": list(range(start, start + len(rungs))),
            "rung_count": len(target.rungs),
        }
    )


def replace_rung(
    registry: ProjectRegistry,
    program: str,
    routine: str,
    number: int,
    output_path: str,
    text: str | None = None,
    comment: str | None = None,
    path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Change one ladder rung's text and/or comment; write the result to a new file.

    Pass text to replace the logic, comment to replace the comment ("" removes
    it), or both. What you omit is kept. Only bracket balance and the trailing
    ';' are checked; Studio verifies the logic.

    Args:
        registry: ProjectRegistry to load from.
        program: Program name.
        routine: RLL routine name.
        number: Rung number (0-based).
        output_path: New .L5X file to write (must not be the source file).
        text: New neutral rung text.
        comment: New rung comment ("" removes it).
        path: Source .L5X file (None for auto-discovery). Never modified.
        overwrite: Replace output_path if it already exists.

    Returns:
        Dict with file, source, program, routine, rung, text and comment.
    """
    if text is None and comment is None:
        raise L5XError("nothing to change: pass text and/or comment")
    edit = Edit.open(registry, path, output_path, overwrite)
    prog_name, target = _routine(edit.project, program, routine)
    _require_type(target, "RLL")
    rungs = target.rungs
    if not 0 <= number < len(rungs):
        raise L5XError(f"rung {number} out of range: {target.name} has {len(rungs)}")
    old = rungs[number]
    new_text = old.text if text is None else text
    new_comment = (old.comment or "") if comment is None else comment
    with edit_errors(f"rung {number}"):
        target.add_rung(new_text, new_comment or None, number)
        target.remove_rung(number + 1)
    return edit.save(
        {
            "program": prog_name,
            "routine": target.name,
            "rung": number,
            "text": new_text,
            "comment": new_comment,
        }
    )


def remove_rungs(
    registry: ProjectRegistry,
    program: str,
    routine: str,
    numbers: list[int],
    output_path: str,
    path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Delete ladder rungs and write the result to a new file.

    numbers are the current rung numbers (0-based); the remaining rungs are
    renumbered from 0 afterwards.

    Args:
        registry: ProjectRegistry to load from.
        program: Program name.
        routine: RLL routine name.
        numbers: Rung numbers to remove.
        output_path: New .L5X file to write (must not be the source file).
        path: Source .L5X file (None for auto-discovery). Never modified.
        overwrite: Replace output_path if it already exists.

    Returns:
        Dict with file, source, program, routine, removed and rung_count.
    """
    if not numbers:
        raise L5XError("numbers must contain at least one rung number")
    edit = Edit.open(registry, path, output_path, overwrite)
    prog_name, target = _routine(edit.project, program, routine)
    _require_type(target, "RLL")
    count = len(target.rungs)
    bad = [n for n in numbers if not 0 <= n < count]
    if bad:
        raise L5XError(f"rungs {bad} out of range: {target.name} has {count}")
    unique = sorted(set(numbers), reverse=True)
    with edit_errors(f"routine {target.name!r}"):
        for number in unique:
            target.remove_rung(number)
    return edit.save(
        {
            "program": prog_name,
            "routine": target.name,
            "removed": sorted(unique),
            "rung_count": len(target.rungs),
        }
    )


def set_st_lines(
    registry: ProjectRegistry,
    program: str,
    routine: str,
    lines: list[str],
    output_path: str,
    path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Replace all structured text in an ST routine; write the result to a new file.

    lines is the complete new source, one string per line (indentation kept).
    ST is not syntax-checked; Studio verifies it. Logix ST has no TRUE/FALSE
    literals (use 1/0). In v38 use >= / <= (not => / =<).

    Args:
        registry: ProjectRegistry to load from.
        program: Program name.
        routine: ST routine name.
        lines: The new ST source lines.
        output_path: New .L5X file to write (must not be the source file).
        path: Source .L5X file (None for auto-discovery). Never modified.
        overwrite: Replace output_path if it already exists.

    Returns:
        Dict with file, source, program, routine and line_count.
    """
    edit = Edit.open(registry, path, output_path, overwrite)
    prog_name, target = _routine(edit.project, program, routine)
    _require_type(target, "ST")
    with edit_errors(f"routine {target.name!r}"):
        target.set_st_lines(list(lines))
    return edit.save(
        {"program": prog_name, "routine": target.name, "line_count": len(lines)}
    )
