"""Component tools: standalone import files (Studio's "Import Component").

``export_component`` writes objects of an existing project as an import file,
with everything they depend on as context, like Studio's Export Component.
The ``create_*_file`` tools build a new UDT, AOI, program, routine, rungs or
tags from specs and write them as an import file directly, without editing a
project. A ``context_path`` project, when given, is read (never modified) to
resolve the UDTs and AOIs the new component uses; they are copied into the
file so it imports on its own. Without one only atomic and built-in types
(TIMER, COUNTER, STRING, ...) can be used.

Without a context project the file gets a v37 header (``_BLANK_PROJECT``).
Studio ignores that header: generated components import into blank v33, v35,
v37 and v38 projects with no warnings (py_l5x experiment exp26, docs/
import-format.md, "Older Logix versions"). Logic must still use instructions
valid for the target version.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from py_l5x import ProgramSpec, loads
from py_l5x.parsers.project import Project

from l5x_mcp.editing import edit_errors, load_fresh, resolve_output, write_project
from l5x_mcp.registry import L5XError, ProjectRegistry, lookup
from l5x_mcp.specs import (
    AOISpecDict,
    DataTypeSpecDict,
    ProgramSpecDict,
    RoutineSpecDict,
    RungSpecDict,
    TagSpecDict,
    to_py_spec,
)
from l5x_mcp.tools.edit_tags import (
    check_spec_aliases,
    scope_collection,
    with_warnings,
)

#: An empty v37 project used when a component is created without context. The
#: v37 header is ignored by Studio (imports into v33+ verified, py_l5x exp26).
_BLANK_PROJECT = """\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<RSLogix5000Content SchemaRevision="1.0" SoftwareRevision="37.00" \
TargetName="Exported" TargetType="Controller" ContainsContext="false">
<Controller Use="Target" Name="Exported">
<DataTypes/>
<AddOnInstructionDefinitions/>
<Tags/>
<Programs/>
<Tasks/>
</Controller>
</RSLogix5000Content>
"""

_IMPORT_HINT = (
    "Import it in Studio 5000 with Import Component (or the matching "
    "right-click Import on the Controller Organizer folder)."
)


def _context(registry: ProjectRegistry, context_path: str | None) -> Project:
    """Load the context project, or a blank one.

    Args:
        registry: The registry.
        context_path: Optional project to resolve types against.

    Returns:
        A fresh project that may be modified freely.
    """
    if context_path:
        return load_fresh(registry, context_path)[1]
    return loads(_BLANK_PROJECT)


def _output(
    registry: ProjectRegistry,
    output_path: str,
    source: str | None,
    overwrite: bool,
) -> Path:
    """Validate ``output_path`` before any work is done.

    Args:
        registry: The registry.
        output_path: The tool's ``output_path``.
        source: The project read (``path`` or ``context_path``), if any; the
            output may not be this file.
        overwrite: The tool's ``overwrite``.

    Returns:
        The resolved destination path.
    """
    return resolve_output(
        registry,
        output_path,
        source=registry.resolve(source) if source else None,
        overwrite=overwrite,
    )


def _write(
    registry: ProjectRegistry,
    component: Project,
    out: Path,
    source: str | None,
    summary: dict[str, Any],
) -> dict[str, Any]:
    write_project(registry, component, out)
    result: dict[str, Any] = {"file": registry.relpath(out)}
    if source:
        result["source"] = registry.relpath(registry.resolve(source))
    result["target_type"] = component.target_type
    result.update(summary)
    result["context"] = _context_summary(component)
    result["note"] = _IMPORT_HINT
    return result


def _context_summary(component: Project) -> dict[str, list[str]]:
    """List the context objects carried by a component file.

    Args:
        component: The component export.

    Returns:
        Non-empty lists of context data_types, aois, tags and modules.
    """
    out: dict[str, list[str]] = {}
    groups = {
        "data_types": component.data_types.values(),
        "aois": component.aois.values(),
        "tags": component.controller_tags.values(),
    }
    for key, items in groups.items():
        names = [i.name for i in items if getattr(i, "use", None) != "Target"]
        if names:
            out[key] = names
    modules = list(component.modules)
    if modules:
        out["modules"] = modules
    return out


def _check_aliases(
    project: Project, specs: list[Any], context_path: str | None
) -> list[str]:
    """Check alias targets of new tags against the same list and the context.

    Returns:
        Warnings for targets whose members could not be verified.
    """
    try:
        return check_spec_aliases(project, specs)
    except L5XError as exc:
        if context_path:
            raise
        raise L5XError(
            f"{str(exc).rstrip('.')}. Pass context_path (a project that has "
            "the target) or add the target to the same tags list"
        ) from exc


def _check_free(collection: Any, name: str, kind: str) -> None:
    if any(key.lower() == name.lower() for key in collection):
        raise L5XError(
            f"{kind} {name!r} already exists in the context project; "
            "use export_component for existing objects or choose another name"
        )


# ----------------------------------------------------------------------
# Export existing objects
# ----------------------------------------------------------------------


def export_component(
    registry: ProjectRegistry,
    kind: Literal["data_type", "aoi", "program", "routine", "rungs", "tags"],
    output_path: str,
    names: list[str] | None = None,
    program: str | None = None,
    routine: str | None = None,
    rungs: list[int] | None = None,
    path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Write existing objects as a standalone import file (Export Component).

    The file carries every UDT and AOI the targets depend on (transitively,
    including AOIs called in their logic), the controller/program tags their
    logic uses, and references to the I/O modules of those tags, so it imports
    into another project on its own. Modules must already exist in the target
    project.

    kind and selectors:
    - "data_type" / "aoi" / "program": names = object names.
    - "routine": program + names = routine names in that program.
    - "rungs": program + routine + rungs = rung numbers (0-based).
    - "tags": names = tag names; program selects program tags (default:
      controller tags).

    Args:
        registry: ProjectRegistry to load from.
        kind: What to export.
        output_path: New .L5X file (a bare name is written to the output
            folder; a path is root-relative). Must not be the source.
        names: Object names (all kinds except "rungs").
        program: Program for routine, rungs and program tags.
        routine: Routine for rungs.
        rungs: Rung numbers for kind="rungs".
        path: Source .L5X file (None for auto-discovery). Never modified.
        overwrite: Replace output_path if this server wrote it earlier in this session.

    Returns:
        Dict with file, source, target_type, targets and context (the
        dependencies included).
    """
    out = resolve_output(
        registry, output_path, source=registry.resolve(path), overwrite=overwrite
    )
    source, project = load_fresh(registry, path)
    targets: list[Any]
    if kind == "rungs":
        if not (program and routine and rungs):
            raise L5XError("kind='rungs' needs program, routine and rungs")
        prog = lookup(project.programs, program, "Program")
        rtn = lookup(prog.routines, routine, "Routine")
        all_rungs = rtn.rungs
        bad = [n for n in rungs if not 0 <= n < len(all_rungs)]
        if bad:
            raise L5XError(f"rungs {bad} out of range: {rtn.name} has {len(all_rungs)}")
        targets = [all_rungs[n] for n in sorted(set(rungs))]
        labels = [f"{prog.name}/{rtn.name} rung {n}" for n in sorted(set(rungs))]
    else:
        if not names:
            raise L5XError(f"names is required for kind={kind!r}")
        if kind == "data_type":
            targets = [lookup(project.data_types, n, "Data type") for n in names]
        elif kind == "aoi":
            targets = [lookup(project.aois, n, "AOI") for n in names]
        elif kind == "program":
            targets = [lookup(project.programs, n, "Program") for n in names]
        elif kind == "routine":
            if not program:
                raise L5XError("program is required for kind='routine'")
            prog = lookup(project.programs, program, "Program")
            targets = [lookup(prog.routines, n, "Routine") for n in names]
        elif kind == "tags":
            _, collection = scope_collection(project, program or "controller")
            targets = [lookup(collection, n, "Tag") for n in names]
        else:
            raise L5XError(f"unknown kind {kind!r}")
        labels = [t.name for t in targets]
    with edit_errors(f"export {kind}"):
        component = project.export(targets)
    return _write(
        registry,
        component,
        out,
        str(source),
        {"targets": labels},
    )


# ----------------------------------------------------------------------
# Create new components from specs
# ----------------------------------------------------------------------


def create_data_type_file(
    registry: ProjectRegistry,
    spec: DataTypeSpecDict,
    output_path: str,
    context_path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Create an import file for a new UDT (no project is modified).

    List BOOL members as plain BOOL; they are packed into hidden SINT hosts
    exactly as Studio does. Member types must be atomic, built-in (TIMER,
    COUNTER, STRING, ...) or UDTs/AOIs in context_path, whose definitions are
    then included in the file.

    Without context_path the file has a v37 header, which Studio ignores
    (imports into v33+ verified); use instructions valid for the target version.

    Args:
        registry: ProjectRegistry to load from.
        spec: The UDT spec.
        output_path: New .L5X file (a bare name is written to the output
            folder; a path is root-relative). Must not be the source.
        context_path: Optional project whose UDTs/AOIs the spec may use.
        overwrite: Replace output_path if this server wrote it earlier in this session.

    Returns:
        Dict with file, target_type, targets and context.
    """
    out = _output(registry, output_path, context_path, overwrite)
    py_spec = to_py_spec("data_type", spec)
    project = _context(registry, context_path)
    _check_free(project.data_types, py_spec.name, "Data type")
    with edit_errors(f"data type {py_spec.name!r}"):
        component = project.export(py_spec)
    return _write(
        registry,
        component,
        out,
        context_path,
        {"targets": [py_spec.name]},
    )


def create_aoi_file(
    registry: ProjectRegistry,
    spec: AOISpecDict,
    output_path: str,
    context_path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Create an import file for a new Add-On Instruction (no project is modified).

    EnableIn/EnableOut are added automatically. A "Logic" routine is required.
    Input/Output parameters must be atomic scalars; structures and arrays must
    be InOut. UDTs/AOIs from context_path used by parameters, local tags or
    calls in the logic are included in the file. Use instructions valid for the
    target version (v36+ uses MOVE, EQ, ... instead of MOV, EQU, ...).

    Without context_path the file has a v37 header, which Studio ignores
    (imports into v33+ verified); use instructions valid for the target version.

    Args:
        registry: ProjectRegistry to load from.
        spec: The AOI spec.
        output_path: New .L5X file (a bare name is written to the output
            folder; a path is root-relative). Must not be the source.
        context_path: Optional project whose UDTs/AOIs the spec may use.
        overwrite: Replace output_path if this server wrote it earlier in this session.

    Returns:
        Dict with file, target_type, targets and context.
    """
    out = _output(registry, output_path, context_path, overwrite)
    py_spec = to_py_spec("aoi", spec)
    project = _context(registry, context_path)
    _check_free(project.aois, py_spec.name, "AOI")
    with edit_errors(f"AOI {py_spec.name!r}"):
        component = project.export(py_spec)
    return _write(
        registry,
        component,
        out,
        context_path,
        {"targets": [py_spec.name]},
    )


def create_program_file(
    registry: ProjectRegistry,
    spec: ProgramSpecDict,
    output_path: str,
    context_path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Create an import file for a new program with tags and routines.

    No project is modified. Set main_routine to the routine that runs each
    scan. UDTs/AOIs and controller tags from context_path that the program
    uses are included in the file (tag types must resolve; logic is verified
    by Studio). The imported program is unscheduled until added to a task.
    Use instructions valid for the target version (v36+ uses MOVE, EQ, ...).

    Without context_path the file has a v37 header, which Studio ignores
    (imports into v33+ verified); use instructions valid for the target version.

    Args:
        registry: ProjectRegistry to load from.
        spec: The program spec.
        output_path: New .L5X file (a bare name is written to the output
            folder; a path is root-relative). Must not be the source.
        context_path: Optional project whose UDTs/AOIs/tags the program uses.
        overwrite: Replace output_path if this server wrote it earlier in this session.

    Returns:
        Dict with file, target_type, targets and context, plus warnings (alias
        targets that could not be fully checked), when any.
    """
    out = _output(registry, output_path, context_path, overwrite)
    py_spec = to_py_spec("program", spec)
    project = _context(registry, context_path)
    _check_free(project.programs, py_spec.name, "Program")
    warnings = _check_aliases(project, py_spec.tags, context_path)
    with edit_errors(f"program {py_spec.name!r}"):
        component = project.export(py_spec)
    return _write(
        registry,
        component,
        out,
        context_path,
        with_warnings({"targets": [py_spec.name]}, warnings),
    )


def create_tags_file(
    registry: ProjectRegistry,
    tags: list[TagSpecDict],
    output_path: str,
    context_path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Create an import file for new controller tags (no project is modified).

    Each spec needs data_type (base tag) or alias_for (alias); value sets the
    initial value. UDTs/AOIs used by the tags are taken from context_path and
    included in the file.

    Without context_path the file has a v37 header, which Studio ignores
    (imports into v33+ verified); use instructions valid for the target version.

    Args:
        registry: ProjectRegistry to load from.
        tags: Tag specs.
        output_path: New .L5X file (a bare name is written to the output
            folder; a path is root-relative). Must not be the source.
        context_path: Optional project whose UDTs/AOIs the tags use.
        overwrite: Replace output_path if this server wrote it earlier in this session.

    Returns:
        Dict with file, target_type, targets and context, plus warnings (alias
        targets that could not be fully checked), when any.
    """
    out = _output(registry, output_path, context_path, overwrite)
    if not tags:
        raise L5XError("tags must contain at least one tag spec")
    specs = [to_py_spec("tag", t) for t in tags]
    project = _context(registry, context_path)
    for spec in specs:
        _check_free(project.controller_tags, spec.name, "Controller tag")
    warnings = _check_aliases(project, specs, context_path)
    with edit_errors("tags"):
        component = project.export(specs)
    return _write(
        registry,
        component,
        out,
        context_path,
        with_warnings({"targets": [s.name for s in specs]}, warnings),
    )


def _host_program(project: Project, program: str) -> Any:
    """Return the named program, creating an empty one if missing."""
    for name, prog in project.programs.items():
        if name.lower() == program.lower():
            return prog
    with edit_errors(f"program {program!r}"):
        return project.programs.add(ProgramSpec(program))


def create_routine_file(
    registry: ProjectRegistry,
    program: str,
    routine: RoutineSpecDict,
    output_path: str,
    context_path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Create an import file for a new routine in a program (no project is modified).

    Import it into the named program (which must exist in the target
    project). An RLL routine takes rungs ([{text, comment?}]); an ST routine
    takes lines. Tags of context_path used by the logic (program tags of
    program first, then controller tags) and their types are included.

    Without context_path the file has a v37 header, which Studio ignores
    (imports into v33+ verified); use instructions valid for the target version.

    Args:
        registry: ProjectRegistry to load from.
        program: Program the routine belongs to.
        routine: The routine spec (name, type, rungs or lines, description).
        output_path: New .L5X file (a bare name is written to the output
            folder; a path is root-relative). Must not be the source.
        context_path: Optional project with the tags/types the logic uses.
        overwrite: Replace output_path if this server wrote it earlier in this session.

    Returns:
        Dict with file, target_type, targets and context.
    """
    out = _output(registry, output_path, context_path, overwrite)
    spec = to_py_spec("routine", routine)
    if spec.type_ == "RLL" and spec.lines:
        raise L5XError("lines are for ST routines; use rungs for RLL")
    if spec.type_ == "ST" and spec.rungs:
        raise L5XError("rungs are for RLL routines; use lines for ST")
    project = _context(registry, context_path)
    prog = _host_program(project, program)
    _check_free(prog.routines, spec.name, "Routine")
    with edit_errors(f"routine {spec.name!r}"):
        new = prog.routines.add(spec.name, spec.type_, description=spec.description)
        for rung in spec.rungs:
            new.add_rung(rung.text, rung.comment or None)
        if spec.lines:
            new.set_st_lines(spec.lines)
        component = project.export(new)
    return _write(
        registry,
        component,
        out,
        context_path,
        {"targets": [f"{prog.name}/{spec.name}"]},
    )


def create_rungs_file(
    registry: ProjectRegistry,
    program: str,
    routine: str,
    rungs: list[RungSpecDict],
    output_path: str,
    context_path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Create an import file of new ladder rungs (no project is modified).

    The rungs are meant to be imported into an existing RLL routine (Studio:
    right-click a rung > Import Rungs). Tags of context_path used by the
    rungs (program tags of program first, then controller tags) and their
    types are included, so missing tags are created on import.

    Without context_path the file has a v37 header, which Studio ignores
    (imports into v33+ verified); use instructions valid for the target version.

    Args:
        registry: ProjectRegistry to load from.
        program: Program of the target routine.
        routine: Target RLL routine.
        rungs: Rungs in order ([{text, comment?}]).
        output_path: New .L5X file (a bare name is written to the output
            folder; a path is root-relative). Must not be the source.
        context_path: Optional project with the tags/types the rungs use.
        overwrite: Replace output_path if this server wrote it earlier in this session.

    Returns:
        Dict with file, target_type, targets (rung count) and context.
    """
    out = _output(registry, output_path, context_path, overwrite)
    if not rungs:
        raise L5XError("rungs must contain at least one rung")
    project = _context(registry, context_path)
    prog = _host_program(project, program)
    existing = {k.lower(): v for k, v in prog.routines.items()}
    with edit_errors(f"routine {routine!r}"):
        rtn = existing.get(routine.lower()) or prog.routines.add(routine, "RLL")
        start = len(rtn.rungs)
        for rung in rungs:
            spec = to_py_spec("routine", {"name": "x", "rungs": [rung]}).rungs[0]
            rtn.add_rung(spec.text, spec.comment or None)
        component = project.export(rtn.rungs[start:])
    return _write(
        registry,
        component,
        out,
        context_path,
        {"targets": [f"{prog.name}/{rtn.name}: {len(rungs)} rungs"]},
    )
