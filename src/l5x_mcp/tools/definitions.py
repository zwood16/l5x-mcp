"""Write tools for UDTs, AOIs and programs, plus the read-only ``get_spec``.

UDTs, AOIs and programs are described by specs (see :mod:`l5x_mcp.specs`).
``get_spec`` returns the spec of an existing object in exactly the form the
add/replace tools accept, so the usual edit is: get_spec, change the spec,
replace_*.
"""

from __future__ import annotations

from typing import Any, Literal

from l5x_mcp.editing import Edit, edit_errors
from l5x_mcp.registry import (
    L5XError,
    ProjectRegistry,
    lookup,
    lookup_aoi,
    lookup_routine,
)
from l5x_mcp.specs import (
    AOISpecDict,
    DataTypeSpecDict,
    ProgramSpecDict,
    from_py_spec,
    to_py_spec,
)
from l5x_mcp.tools.edit_tags import (
    _find_tag,
    check_spec_aliases,
    references,
    with_warnings,
)
from l5x_mcp.tools.programs import json_size, validate_max_chars

SpecKind = Literal["data_type", "aoi", "program", "tag", "routine"]

#: Default size limit for get_spec; specs can't be truncated and still replaced.
SPEC_MAX_CHARS_DEFAULT = 30000


# ----------------------------------------------------------------------
# get_spec (read-only)
# ----------------------------------------------------------------------


def _strip_values(data: dict[str, Any]) -> None:
    for tag in data.get("tags", []):
        tag.pop("value", None)


def get_spec(
    registry: ProjectRegistry,
    kind: SpecKind,
    name: str,
    program: str | None = None,
    include_values: bool = True,
    max_chars: int = SPEC_MAX_CHARS_DEFAULT,
    path: str | None = None,
) -> dict[str, Any]:
    """Get the editable spec of an existing UDT, AOI, program, tag or routine.

    The spec is in exactly the form accepted by add_data_type /
    replace_data_type, add_aoi / replace_aoi, add_program / replace_program,
    add_tags and add_routine (fields equal to their default are omitted). To
    change an object: get_spec, edit the spec, then call the replace tool.

    kind="tag": name is a tag name; program selects a program scope (default:
    controller first, then programs). kind="routine": program is required.
    include_values=false drops tag values from program specs; replace_program
    then keeps each existing tag's current data, which is usually what you
    want and keeps the spec small.

    Args:
        registry: ProjectRegistry to load from.
        kind: "data_type", "aoi", "program", "tag" or "routine".
        name: Object name.
        program: Program scope for tags; required for routines.
        include_values: Include tag values in program specs (default true).
        max_chars: Maximum size of the spec as JSON (default 30000). Larger
            specs are an error rather than being truncated, because a cut spec
            cannot be replaced back.
        path: L5X file path (None for auto-discovery).

    Returns:
        Dict with file, kind and spec.
    """
    validate_max_chars(max_chars)
    file_path, project = registry.get_with_path(path)
    with edit_errors(f"{kind} {name!r}"):
        if kind == "data_type":
            spec = lookup(project.data_types, name, "Data type").to_spec()
        elif kind == "aoi":
            spec = lookup_aoi(project, name, "exported as a spec").to_spec()
        elif kind == "program":
            spec = lookup(project.programs, name, "Program").to_spec()
        elif kind == "tag":
            _, tag = _find_tag(project, name, program)
            spec = tag.to_spec()
        elif kind == "routine":
            if not program:
                raise L5XError("program is required for kind='routine'")
            prog = lookup(project.programs, program, "Program")
            spec = lookup_routine(prog, name, "exported as a spec").to_spec()
        else:
            raise L5XError(f"unknown kind {kind!r}")
    data = from_py_spec(spec)
    if kind == "program" and not include_values:
        _strip_values(data)
    size = json_size(data)
    if size > max_chars:
        hint = (
            " Try include_values=false." if kind == "program" and include_values else ""
        )
        raise L5XError(
            f"The {kind} spec is {size} characters, over max_chars={max_chars}. "
            f"Raise max_chars (up to 100000).{hint}"
        )
    result: dict[str, Any] = {"file": registry.relpath(file_path), "kind": kind}
    if kind == "routine":
        result["program"] = prog.name
    result["spec"] = data
    return result


# ----------------------------------------------------------------------
# UDTs
# ----------------------------------------------------------------------


def add_data_type(
    registry: ProjectRegistry,
    spec: DataTypeSpecDict,
    output_path: str,
    path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Add a user-defined data type (UDT) and write the result to a new file.

    List BOOL members as plain BOOL; they are packed into hidden SINT hosts
    exactly as Studio does. Member types must exist (atomic, built-in such as
    TIMER/COUNTER/STRING, or a UDT/AOI in the project). For a custom string
    type use family "StringFamily" with members LEN (DINT) and DATA
    (SINT[n], radix ASCII).

    Args:
        registry: ProjectRegistry to load from.
        spec: The UDT spec.
        output_path: New .L5X file (a bare name is written to the output
            folder; a path is root-relative). Must not be the source.
        path: Source .L5X file (None for auto-discovery). Never modified.
        overwrite: Replace output_path if this server wrote it earlier in this session.

    Returns:
        Dict with file, source, data_type and members (count).
    """
    py_spec = to_py_spec("data_type", spec)
    edit = Edit.open(registry, path, output_path, overwrite)
    with edit_errors(f"data type {py_spec.name!r}"):
        edit.project.data_types.add(py_spec)
    return edit.save({"data_type": py_spec.name, "members": len(py_spec.members)})


def replace_data_type(
    registry: ProjectRegistry,
    spec: DataTypeSpecDict,
    output_path: str,
    path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Replace an existing UDT (selected by spec.name); write to a new file.

    Every instance (tags, nested members, arrays, AOI defaults) is migrated by
    member name, the way Studio does: kept members keep their values, new
    members get defaults, removed members are dropped and changed types are
    converted. Start from get_spec(kind="data_type").

    Args:
        registry: ProjectRegistry to load from.
        spec: The complete new UDT spec.
        output_path: New .L5X file (a bare name is written to the output
            folder; a path is root-relative). Must not be the source.
        path: Source .L5X file (None for auto-discovery). Never modified.
        overwrite: Replace output_path if this server wrote it earlier in this session.

    Returns:
        Dict with file, source, data_type and members (count).
    """
    py_spec = to_py_spec("data_type", spec)
    edit = Edit.open(registry, path, output_path, overwrite)
    py_spec.name = lookup(edit.project.data_types, py_spec.name, "Data type").name
    with edit_errors(f"data type {py_spec.name!r}"):
        edit.project.data_types.replace(py_spec)
    return edit.save({"data_type": py_spec.name, "members": len(py_spec.members)})


def rename_data_type(
    registry: ProjectRegistry,
    name: str,
    new_name: str,
    output_path: str,
    path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Rename a UDT and every reference to it outside logic; write to a new file.

    Tags, UDT members and AOI parameters/locals of this type are updated.

    Args:
        registry: ProjectRegistry to load from.
        name: Current UDT name.
        new_name: New UDT name.
        output_path: New .L5X file (a bare name is written to the output
            folder; a path is root-relative). Must not be the source.
        path: Source .L5X file (None for auto-discovery). Never modified.
        overwrite: Replace output_path if this server wrote it earlier in this session.

    Returns:
        Dict with file, source and renamed {from, to}.
    """
    edit = Edit.open(registry, path, output_path, overwrite)
    old = lookup(edit.project.data_types, name, "Data type").name
    with edit_errors(f"rename data type {old!r}"):
        edit.project.data_types.rename(old, new_name)
    return edit.save({"renamed": {"from": old, "to": new_name}})


def remove_data_type(
    registry: ProjectRegistry,
    name: str,
    output_path: str,
    force: bool = False,
    path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Delete a UDT and write the result to a new file.

    Refuses while the type is used (the error lists the users) unless force is
    true, which leaves those users pointing at a missing type.

    Args:
        registry: ProjectRegistry to load from.
        name: UDT name.
        output_path: New .L5X file (a bare name is written to the output
            folder; a path is root-relative). Must not be the source.
        force: Delete even if in use.
        path: Source .L5X file (None for auto-discovery). Never modified.
        overwrite: Replace output_path if this server wrote it earlier in this session.

    Returns:
        Dict with file, source and removed.
    """
    edit = Edit.open(registry, path, output_path, overwrite)
    old = lookup(edit.project.data_types, name, "Data type").name
    with edit_errors(f"remove data type {old!r}"):
        edit.project.data_types.remove(old, force=force)
    return edit.save({"removed": old})


# ----------------------------------------------------------------------
# AOIs
# ----------------------------------------------------------------------


def add_aoi(
    registry: ProjectRegistry,
    spec: AOISpecDict,
    output_path: str,
    path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Add an Add-On Instruction and write the result to a new file.

    EnableIn/EnableOut are added automatically. A "Logic" routine is required
    (RLL rungs or ST lines). Input/Output parameters must be atomic scalars;
    structures and arrays must be InOut. RLL calls take the instance tag
    followed by the Required parameters in order, e.g. "MyAoi(inst,In1,Out1);".

    Args:
        registry: ProjectRegistry to load from.
        spec: The AOI spec.
        output_path: New .L5X file (a bare name is written to the output
            folder; a path is root-relative). Must not be the source.
        path: Source .L5X file (None for auto-discovery). Never modified.
        overwrite: Replace output_path if this server wrote it earlier in this session.

    Returns:
        Dict with file, source, aoi and parameters (count, without
        EnableIn/EnableOut).
    """
    py_spec = to_py_spec("aoi", spec)
    edit = Edit.open(registry, path, output_path, overwrite)
    with edit_errors(f"AOI {py_spec.name!r}"):
        edit.project.aois.add(py_spec)
    return edit.save({"aoi": py_spec.name, "parameters": len(py_spec.parameters)})


def replace_aoi(
    registry: ProjectRegistry,
    spec: AOISpecDict,
    output_path: str,
    allow_signature_change: bool = False,
    path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Replace an existing AOI (selected by spec.name); write to a new file.

    Instances are migrated by parameter name. Changing the list of Required
    parameters is refused while the AOI is called anywhere, because call sites
    would no longer verify; pass allow_signature_change=true and then fix the
    calls (find_references kind="instruction"). Local-tag values of existing
    instances are reset to their defaults. Start from get_spec(kind="aoi").

    Args:
        registry: ProjectRegistry to load from.
        spec: The complete new AOI spec.
        output_path: New .L5X file (a bare name is written to the output
            folder; a path is root-relative). Must not be the source.
        allow_signature_change: Allow changing Required parameters while called.
        path: Source .L5X file (None for auto-discovery). Never modified.
        overwrite: Replace output_path if this server wrote it earlier in this session.

    Returns:
        Dict with file, source, aoi and parameters (count).
    """
    py_spec = to_py_spec("aoi", spec)
    edit = Edit.open(registry, path, output_path, overwrite)
    py_spec.name = lookup_aoi(edit.project, py_spec.name, "replaced").name
    with edit_errors(f"AOI {py_spec.name!r}"):
        edit.project.aois.replace(
            py_spec, allow_signature_change=allow_signature_change
        )
    return edit.save({"aoi": py_spec.name, "parameters": len(py_spec.parameters)})


def rename_aoi(
    registry: ProjectRegistry,
    name: str,
    new_name: str,
    output_path: str,
    path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Rename an AOI, its users and its call sites in logic; write to a new file.

    Args:
        registry: ProjectRegistry to load from.
        name: Current AOI name.
        new_name: New AOI name.
        output_path: New .L5X file (a bare name is written to the output
            folder; a path is root-relative). Must not be the source.
        path: Source .L5X file (None for auto-discovery). Never modified.
        overwrite: Replace output_path if this server wrote it earlier in this session.

    Returns:
        Dict with file, source, renamed {from, to} and call_sites (count
        rewritten).
    """
    edit = Edit.open(registry, path, output_path, overwrite)
    old = lookup_aoi(edit.project, name, "renamed").name
    with edit_errors(f"rename AOI {old!r}"):
        calls = len(edit.project.aois.call_sites(old))
        edit.project.aois.rename(old, new_name)
    return edit.save({"renamed": {"from": old, "to": new_name}, "call_sites": calls})


def remove_aoi(
    registry: ProjectRegistry,
    name: str,
    output_path: str,
    force: bool = False,
    path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Delete an AOI and write the result to a new file.

    Refuses while the AOI is used (tags, UDT members, other AOIs or call
    sites; the error lists them) unless force is true.

    Args:
        registry: ProjectRegistry to load from.
        name: AOI name.
        output_path: New .L5X file (a bare name is written to the output
            folder; a path is root-relative). Must not be the source.
        force: Delete even if in use, leaving users dangling.
        path: Source .L5X file (None for auto-discovery). Never modified.
        overwrite: Replace output_path if this server wrote it earlier in this session.

    Returns:
        Dict with file, source and removed.
    """
    edit = Edit.open(registry, path, output_path, overwrite)
    old = lookup_aoi(edit.project, name, "removed").name
    with edit_errors(f"remove AOI {old!r}"):
        edit.project.aois.remove(old, force=force)
    return edit.save({"removed": old})


# ----------------------------------------------------------------------
# Programs
# ----------------------------------------------------------------------


def add_program(
    registry: ProjectRegistry,
    spec: ProgramSpecDict,
    output_path: str,
    task: str | None = None,
    path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Add a program (tags + routines) and write the result to a new file.

    Set main_routine to the routine that runs each scan (it usually JSRs the
    others). Without task the program is unscheduled and does not run. Tag
    types must exist in the project; logic is not verified (Studio does that).
    Use instructions valid for the project's version (v36+ uses MOVE, EQ, ...
    instead of MOV, EQU, ...).

    Args:
        registry: ProjectRegistry to load from.
        spec: The program spec.
        output_path: New .L5X file (a bare name is written to the output
            folder; a path is root-relative). Must not be the source.
        task: Task to schedule the program in.
        path: Source .L5X file (None for auto-discovery). Never modified.
        overwrite: Replace output_path if this server wrote it earlier in this session.

    Returns:
        Dict with file, source, program, task, tags and routines (counts),
        plus warnings (alias targets that could not be fully checked), when any.
    """
    py_spec = to_py_spec("program", spec)
    edit = Edit.open(registry, path, output_path, overwrite)
    warnings = check_spec_aliases(edit.project, py_spec.tags)
    if task is not None:
        task = lookup(edit.project.tasks, task, "Task").name
    with edit_errors(f"program {py_spec.name!r}"):
        edit.project.programs.add(py_spec, task=task)
    return edit.save(
        with_warnings(
            {
                "program": py_spec.name,
                "task": task,
                "tags": len(py_spec.tags),
                "routines": len(py_spec.routines),
            },
            warnings,
        )
    )


def replace_program(
    registry: ProjectRegistry,
    spec: ProgramSpecDict,
    output_path: str,
    path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Replace a program (selected by spec.name) wholesale; write to a new file.

    Tags and routines not in the spec are removed. A tag whose spec has no
    value and whose type and dimensions are unchanged keeps its current data.
    Task scheduling and position are kept. Start from
    get_spec(kind="program", include_values=false).

    Args:
        registry: ProjectRegistry to load from.
        spec: The complete new program spec.
        output_path: New .L5X file (a bare name is written to the output
            folder; a path is root-relative). Must not be the source.
        path: Source .L5X file (None for auto-discovery). Never modified.
        overwrite: Replace output_path if this server wrote it earlier in this session.

    Returns:
        Dict with file, source, program, tags and routines (counts), plus
        warnings (alias targets that could not be fully checked), when any.
    """
    py_spec = to_py_spec("program", spec)
    edit = Edit.open(registry, path, output_path, overwrite)
    py_spec.name = lookup(edit.project.programs, py_spec.name, "Program").name
    warnings = check_spec_aliases(edit.project, py_spec.tags)
    with edit_errors(f"program {py_spec.name!r}"):
        edit.project.programs.replace(py_spec)
    return edit.save(
        with_warnings(
            {
                "program": py_spec.name,
                "tags": len(py_spec.tags),
                "routines": len(py_spec.routines),
            },
            warnings,
        )
    )


def rename_program(
    registry: ProjectRegistry,
    name: str,
    new_name: str,
    output_path: str,
    path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Rename a program (task schedules follow); write to a new file.

    "\\OldName.tag" references in other programs' logic are NOT updated; the
    result lists them (references), together with alias tags whose target
    still uses "\\OldName.".

    Args:
        registry: ProjectRegistry to load from.
        name: Current program name.
        new_name: New program name.
        output_path: New .L5X file (a bare name is written to the output
            folder; a path is root-relative). Must not be the source.
        path: Source .L5X file (None for auto-discovery). Never modified.
        overwrite: Replace output_path if this server wrote it earlier in this session.

    Returns:
        Dict with file, source, renamed {from, to} and references.
    """
    edit = Edit.open(registry, path, output_path, overwrite)
    old = lookup(edit.project.programs, name, "Program").name
    with edit_errors(f"rename program {old!r}"):
        edit.project.programs.rename(old, new_name)
    result = edit.save({"renamed": {"from": old, "to": new_name}})
    if old.lower() != new_name.lower():
        found = references(registry, result["file"], f"\\{old}", alias_program=old)
        if found:
            result["references"] = found
    return result


def remove_program(
    registry: ProjectRegistry,
    name: str,
    output_path: str,
    path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Delete a program (and its schedule entry); write to a new file.

    Args:
        registry: ProjectRegistry to load from.
        name: Program name.
        output_path: New .L5X file (a bare name is written to the output
            folder; a path is root-relative). Must not be the source.
        path: Source .L5X file (None for auto-discovery). Never modified.
        overwrite: Replace output_path if this server wrote it earlier in this session.

    Returns:
        Dict with file, source and removed.
    """
    edit = Edit.open(registry, path, output_path, overwrite)
    old = lookup(edit.project.programs, name, "Program").name
    with edit_errors(f"remove program {old!r}"):
        edit.project.programs.remove(old)
    return edit.save({"removed": old})


def schedule_program(
    registry: ProjectRegistry,
    name: str,
    output_path: str,
    task: str | None = None,
    path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Schedule a program in a task, move it, or unschedule it; write to a new file.

    A program runs in at most one task. With task, the program is moved there
    (from its current task, if any). With task omitted/null, it is
    unscheduled.

    Args:
        registry: ProjectRegistry to load from.
        name: Program name.
        output_path: New .L5X file (a bare name is written to the output
            folder; a path is root-relative). Must not be the source.
        task: Target task name, or null to unschedule.
        path: Source .L5X file (None for auto-discovery). Never modified.
        overwrite: Replace output_path if this server wrote it earlier in this session.

    Returns:
        Dict with file, source, program, previous_task and task.
    """
    edit = Edit.open(registry, path, output_path, overwrite)
    programs = edit.project.programs
    prog = lookup(programs, name, "Program").name
    if task is not None:
        task = lookup(edit.project.tasks, task, "Task").name
    with edit_errors(f"schedule program {prog!r}"):
        previous = programs.unschedule(prog)
        if task is not None:
            programs.schedule(prog, task)
    return edit.save({"program": prog, "previous_task": previous, "task": task})


# ----------------------------------------------------------------------
# Descriptions
# ----------------------------------------------------------------------


def set_description(
    registry: ProjectRegistry,
    kind: Literal["program", "routine", "data_type", "aoi"],
    name: str,
    description: str,
    output_path: str,
    program: str | None = None,
    path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Set the description of a program, routine, UDT or AOI; write to a new file.

    "" removes the description. For tags use update_tag; for rung comments
    use replace_rung.

    Args:
        registry: ProjectRegistry to load from.
        kind: "program", "routine", "data_type" or "aoi".
        name: Object name.
        description: New description ("" removes it).
        output_path: New .L5X file (a bare name is written to the output
            folder; a path is root-relative). Must not be the source.
        program: Program containing the routine (kind="routine" only).
        path: Source .L5X file (None for auto-discovery). Never modified.
        overwrite: Replace output_path if this server wrote it earlier in this session.

    Returns:
        Dict with file, source, kind and name.
    """
    edit = Edit.open(registry, path, output_path, overwrite)
    project = edit.project
    if kind == "program":
        obj = lookup(project.programs, name, "Program")
    elif kind == "routine":
        if not program:
            raise L5XError("program is required for kind='routine'")
        obj = lookup_routine(
            lookup(project.programs, program, "Program"), name, "edited"
        )
    elif kind == "data_type":
        obj = lookup(project.data_types, name, "Data type")
    elif kind == "aoi":
        obj = lookup_aoi(project, name, "edited")
    else:
        raise L5XError(f"unknown kind {kind!r}")
    with edit_errors(f"{kind} {obj.name!r}"):
        obj.description = description or None
    return edit.save({"kind": kind, "name": obj.name})
