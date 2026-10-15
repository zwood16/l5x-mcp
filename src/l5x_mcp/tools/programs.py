"""Tools for exploring programs and their routines in L5X projects.

This module provides functions to list programs, get program details,
and view routine logic (RLL rungs, ST lines, etc.) from L5X exports.
"""

from __future__ import annotations

from typing import Any

from py_l5x.parsers.program import Program
from py_l5x.parsers.project import Project
from py_l5x.parsers.routine import Routine, RoutinesCollection

from l5x_mcp.registry import L5XError, ProjectRegistry, lookup
from l5x_mcp.serialize import compact, first_line

# Maximum rungs to return by default; can be overridden in tests
MAX_RUNGS_DEFAULT = 200


def _resolve_routine_container(
    project: Project, program: str | None, aoi: str | None
) -> tuple[str, str, RoutinesCollection]:
    """Resolve which container (program or AOI) to use for routines.

    Exactly one of program/aoi should be given. If neither: if the project
    is a component export of a single program or AOI, use it; else raise
    L5XError explaining to pass `program` or `aoi`. If both → L5XError.

    Args:
        project: The loaded Project object.
        program: Name of a program, or None.
        aoi: Name of an AOI, or None.

    Returns:
        Tuple of (container_kind: "program"|"aoi", container_name: str,
        RoutinesCollection for that container).

    Raises:
        L5XError: If both program and aoi are given, or if neither and
                  auto-detection fails.
        ItemNotFoundError: If named program/AOI is not found.
    """
    if program and aoi:
        raise L5XError("Cannot specify both 'program' and 'aoi'. Pass one or neither.")

    if program:
        prog = lookup(project.programs, program, "Program")
        return "program", prog.name, prog.routines

    if aoi:
        aoi_def = lookup(project.aois, aoi, "AOI")
        return "aoi", aoi_def.name, aoi_def.routines

    # Neither given; try auto-detection for component exports
    # Program export: exactly 1 program (AOIs may be present as dependencies)
    if len(project.programs) == 1:
        prog = list(project.programs.values())[0]
        return "program", prog.name, prog.routines

    # AOI export: no programs, exactly 1 AOI
    if len(project.aois) == 1 and len(project.programs) == 0:
        aoi_def = list(project.aois.values())[0]
        return "aoi", aoi_def.name, aoi_def.routines

    raise L5XError(
        "No container specified. Pass 'program' or 'aoi' argument. "
        "Alternatively, use a component export of a single program or AOI."
    )


def list_programs(registry: ProjectRegistry, path: str | None = None) -> dict[str, Any]:
    """List all programs in a project with basic metadata.

    Returns name, description (first line), main_routine, disabled flag (if true),
    is_safety flag (if true), routine count, tag count, and scheduled task (if any).

    Args:
        registry: ProjectRegistry to load from.
        path: Project file path (None for auto-discovery).

    Returns:
        Dict with keys: file, programs (array of program objects).
    """
    resolved_path, project = registry.get_with_path(path)

    programs_list = []
    for prog in project.programs.values():
        # Find which task schedules this program
        task_name = None
        for task in project.tasks.values():
            if prog.name in task.scheduled_program_names:
                task_name = task.name
                break

        prog_dict = {
            "name": prog.name,
            "description": first_line(prog.description),
            "main_routine": prog.main_routine_name or "",
            "routine_count": len(prog.routines),
            "tag_count": len(prog.tags),
        }
        if prog.disabled:
            prog_dict["disabled"] = True
        if prog.is_safety:
            prog_dict["is_safety"] = True
        if task_name:
            prog_dict["task"] = task_name

        programs_list.append(prog_dict)

    return {
        "file": registry.relpath(resolved_path),
        "programs": programs_list,
    }


def get_program(
    registry: ProjectRegistry, name: str, path: str | None = None
) -> dict[str, Any]:
    """Get detailed information about a program.

    Includes name, full description, main routine name, disabled/test_edits/
    use_as_folder/class flags, is_safety flag, scheduled task (if any),
    list of routines (with type, description, rung/line counts), and tags
    (lightweight summary: name, data_type, tag_type, usage).

    Args:
        registry: ProjectRegistry to load from.
        name: Program name (case-insensitive lookup).
        path: Project file path (None for auto-discovery).

    Returns:
        Dict with program details including routines and tags arrays.

    Raises:
        ItemNotFoundError: If program not found.
    """
    resolved_path, project = registry.get_with_path(path)

    prog: Program = lookup(project.programs, name, "Program")

    # Find scheduled task
    task_name = None
    for task in project.tasks.values():
        if prog.name in task.scheduled_program_names:
            task_name = task.name
            break

    # Build routines list
    routines_list = []
    for routine in prog.routines.values():
        routine_dict = {
            "name": routine.name,
            "type": routine.type_,
            "description": first_line(routine.description),
        }
        if routine.type_ == "RLL":
            routine_dict["rung_count"] = len(routine.rungs)
        elif routine.type_ == "ST":
            routine_dict["line_count"] = len(routine.st_lines)
        routines_list.append(routine_dict)

    # Build tags list (lightweight)
    tags_list = []
    for tag in prog.tags.values():
        tag_dict = {
            "name": tag.name,
            "data_type": tag.data_type or "",
            "tag_type": tag.tag_type or "",
            "usage": tag.usage or "",
        }
        tags_list.append(tag_dict)

    result = {
        "file": registry.relpath(resolved_path),
        "name": prog.name,
        "description": prog.description or "",
        "main_routine": prog.main_routine_name or "",
        "disabled": prog.disabled,
        "test_edits": prog.test_edits,
        "use_as_folder": prog.use_as_folder,
        "class": prog.class_ or "",
        "is_safety": prog.is_safety,
        "routines": routines_list,
        "tags": tags_list,
    }
    if task_name:
        result["task"] = task_name

    return compact(result)


def list_routines(
    registry: ProjectRegistry,
    program: str | None = None,
    aoi: str | None = None,
    path: str | None = None,
) -> dict[str, Any]:
    """List all routines in a program or AOI.

    Args:
        registry: ProjectRegistry to load from.
        program: Program name (case-insensitive), or None.
        aoi: AOI name (case-insensitive), or None.
        path: Project file path (None for auto-discovery).

    Returns:
        Dict with keys: file, container (kind and name), routines (array).

    Raises:
        L5XError: If both/neither program and aoi given, or auto-detection fails.
        ItemNotFoundError: If named program/AOI not found.
    """
    resolved_path, project = registry.get_with_path(path)

    container_kind, container_name, routines_collection = _resolve_routine_container(
        project, program, aoi
    )

    routines_list = []
    for routine in routines_collection.values():
        routine_dict = {
            "name": routine.name,
            "type": routine.type_,
            "description": first_line(routine.description),
        }
        if routine.type_ == "RLL":
            routine_dict["rung_count"] = len(routine.rungs)
        elif routine.type_ == "ST":
            routine_dict["line_count"] = len(routine.st_lines)
        routines_list.append(routine_dict)

    return {
        "file": registry.relpath(resolved_path),
        "container": {
            "kind": container_kind,
            "name": container_name,
        },
        "routines": routines_list,
    }


def _apply_range_and_cap(
    items: list[tuple[int, dict]],
    start_num: int | None,
    end_num: int | None,
) -> tuple[list[dict], bool, int | None, str | None]:
    """Apply range filtering and cap to at most MAX_RUNGS_DEFAULT items.

    Args:
        items: List of (number, item_dict) tuples sorted by number.
        start_num: Start number (0-based inclusive), or None for 0.
        end_num: End number (0-based inclusive), or None for last.

    Returns:
        Tuple of (filtered_items, truncated, next_start_rung, note).
        filtered_items: List of item dicts in range, capped at MAX_RUNGS_DEFAULT.
        truncated: True if more items exist in range.
        next_start_rung: Number of first omitted item (if truncated).
        note: Helpful message if truncated.

    Raises:
        L5XError: If range is invalid.
    """
    if not items:
        return [], False, None, None

    if start_num is None:
        start_num = 0
    if end_num is None:
        end_num = items[-1][0]  # Last item's number

    # Validate range
    if start_num < 0 or end_num < 0:
        raise L5XError("start_rung and end_rung must be non-negative.")
    if start_num > end_num:
        raise L5XError("start_rung must be <= end_rung.")

    # Filter to range
    filtered = [(num, item) for num, item in items if start_num <= num <= end_num]

    if not filtered:
        return [], False, None, None

    # Apply cap
    truncated = False
    next_start = None
    note = None

    if len(filtered) > MAX_RUNGS_DEFAULT:
        truncated = True
        next_start = filtered[MAX_RUNGS_DEFAULT][0]  # Number of first omitted item
        filtered = filtered[:MAX_RUNGS_DEFAULT]
        note = (
            f"Returned {MAX_RUNGS_DEFAULT} items (cap). "
            f"Pass start_rung={next_start} to continue."
        )

    # Return items with per-item compaction (preserves text/number always)
    result_items = []
    for _, item in filtered:
        # Compact but preserve text/number fields
        compacted = {}
        for k, v in item.items():
            # Always keep text/number fields, or keep if value is not empty
            if k in ("text", "number") or (
                v is not None and v != "" and v != [] and v != {}
            ):
                compacted[k] = v
        result_items.append(compacted)

    return result_items, truncated, next_start, note


def get_routine_logic(
    registry: ProjectRegistry,
    routine: str,
    program: str | None = None,
    aoi: str | None = None,
    start_rung: int | None = None,
    end_rung: int | None = None,
    path: str | None = None,
) -> dict[str, Any]:
    """Get the logic/code of a routine (RLL rungs, ST lines, etc.).

    Returns at most MAX_RUNGS_DEFAULT (200) items per call.

    For RLL: Returns rungs (number, text, optional comment) for the given range.
    For ST: Returns lines (number, text) and joined code text for the range.
    For other types (FBD/SFC): Returns type and a note that parsing isn't supported.

    Args:
        registry: ProjectRegistry to load from.
        routine: Routine name (case-insensitive lookup).
        program: Program name (case-insensitive), or None.
        aoi: AOI name (case-insensitive), or None.
        start_rung: Start rung/line number (0-based inclusive), or None for 0.
        end_rung: End rung/line number (0-based inclusive), or None for last.
        path: Project file path (None for auto-discovery).

    Returns:
        Dict with file, container, routine name/type/description, and:
        - RLL: total_rungs, rungs (array), optional truncated/next_start_rung/note.
        - ST: total_lines, lines (array), code (joined text), optional truncated/note.
        - Other: note about unsupported type.

    Raises:
        L5XError: If both/neither program and aoi given, invalid range, etc.
        ItemNotFoundError: If routine/program/AOI not found.
    """
    resolved_path, project = registry.get_with_path(path)

    container_kind, container_name, routines_collection = _resolve_routine_container(
        project, program, aoi
    )

    rtn: Routine = lookup(routines_collection, routine, "Routine")

    result = {
        "file": registry.relpath(resolved_path),
        "container": {
            "kind": container_kind,
            "name": container_name,
        },
        "routine": rtn.name,
        "type": rtn.type_,
        "description": rtn.description or "",
    }

    if rtn.type_ == "RLL":
        total_rungs = len(rtn.rungs)
        result["total_rungs"] = total_rungs

        # Build (number, item_dict) list for range/cap logic
        rungs_with_nums = [
            (
                rung.number,
                {
                    "number": rung.number,
                    "comment": rung.comment or "",
                    "text": rung.text,
                },
            )
            for rung in rtn.rungs
        ]

        # Apply range and cap
        rungs_list, truncated, next_start, note = _apply_range_and_cap(
            rungs_with_nums, start_rung, end_rung
        )

        result["rungs"] = rungs_list
        if truncated:
            result["truncated"] = True
            result["next_start_rung"] = next_start
        if note:
            result["note"] = note

    elif rtn.type_ == "ST":
        lines = rtn.st_lines
        total_lines = len(lines)
        result["total_lines"] = total_lines

        # Build (number, item_dict) list for range/cap logic
        lines_with_nums = [
            (line.number, {"number": line.number, "text": line.text}) for line in lines
        ]

        # Apply range and cap
        lines_list, truncated, next_start, note = _apply_range_and_cap(
            lines_with_nums, start_rung, end_rung
        )

        result["lines"] = lines_list
        result["code"] = "\n".join(line["text"] for line in lines_list)
        if truncated:
            result["truncated"] = True
            result["next_start_rung"] = next_start
        if note:
            result["note"] = note

    else:
        # FBD, SFC, or other unsupported type
        result["note"] = f"py_l5x does not parse {rtn.type_} routines yet."

    return compact(result)
