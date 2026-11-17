"""Write tools for controller and program tags."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from py_l5x import AliasTag, ModuleTagRef, Tag, build_tag
from py_l5x.parsers.project import Project
from py_l5x.parsers.tag import TagsCollection

from l5x_mcp.editing import Edit, check_data_type, edit_errors
from l5x_mcp.operand_paths import parse_operand, resolve_tag
from l5x_mcp.registry import L5XError, ProjectRegistry, lookup
from l5x_mcp.specs import TagSpecDict, to_py_spec
from l5x_mcp.tools.search import find_references

#: Maximum logic locations listed in a ``references`` warning.
MAX_REFERENCE_LOCATIONS = 10


def scope_collection(project: Project, scope: str) -> tuple[str, TagsCollection]:
    """Return the tag collection for ``"controller"`` or a program name.

    Args:
        project: The project being edited.
        scope: ``"controller"`` or a program name (case-insensitive).

    Returns:
        The canonical scope name and its tag collection.

    Raises:
        ItemNotFoundError: If the program does not exist.
    """
    if scope == "controller":
        return "controller", project.controller_tags
    program = lookup(project.programs, scope, "Program")
    return program.name, program.tags


def _logic_locations(
    registry: ProjectRegistry,
    out_path: str,
    query: str,
    program: str | None = None,
    skip_programs: frozenset[str] = frozenset(),
) -> list[str]:
    """List the program logic locations that mention ``query``.

    AOI logic is never searched: it only sees its own parameters and locals.

    Args:
        registry: The registry (used to read the output file).
        out_path: Root-relative path of the written file.
        query: Tag, routine or program text to look for.
        program: Limit the search to one program.
        skip_programs: Lower-case program names whose matches are dropped.

    Returns:
        Locations such as ``Program/Routine rung 3``.
    """
    found = find_references(
        registry,
        query,
        kind="tag",
        program=program,
        include_aois=False,
        limit=2000,
        path=out_path,
    )
    locations = []
    for match in found["matches"]:
        if match["container"].lower() in skip_programs:
            continue
        where = f"{match['container']}/{match['routine']}"
        if "rung" in match:
            where += f" rung {match['rung']}"
        elif "line" in match:
            where += f" line {match['line']}"
        locations.append(where)
    return locations


def _alias_hits(project: Project, hit: Callable[[str, Any], bool]) -> list[str]:
    """List alias tags whose target satisfies ``hit``.

    Args:
        project: The project to scan.
        hit: Called with the alias's scope (``"controller"`` or program name)
            and its parsed target operand.

    Returns:
        ``"<scope>/<alias name>"`` entries.
    """
    scopes = [("controller", project.controller_tags)]
    scopes += [(p.name, p.tags) for p in project.programs.values()]
    found = []
    for scope, collection in scopes:
        for tag in collection.values():
            if not isinstance(tag, AliasTag) or not tag.alias_for:
                continue
            try:
                parsed = parse_operand(tag.alias_for)
            except L5XError:
                continue
            if hit(scope, parsed):
                found.append(f"{scope}/{tag.name}")
    return found


def _references_result(
    locations: list[str], aliases: list[str]
) -> dict[str, Any] | None:
    """Build the compact ``references`` dict, or ``None`` when empty."""
    locations = list(dict.fromkeys(locations))
    if not locations and not aliases:
        return None
    out: dict[str, Any] = {"total": len(locations)}
    if locations:
        out["locations"] = locations[:MAX_REFERENCE_LOCATIONS]
    if aliases:
        out["aliases"] = aliases[:MAX_REFERENCE_LOCATIONS]
        if len(aliases) > MAX_REFERENCE_LOCATIONS:
            out["aliases_total"] = len(aliases)
    return out


def references(
    registry: ProjectRegistry,
    out_path: str,
    name: str,
    program: str | None = None,
    alias_program: str | None = None,
) -> dict[str, Any] | None:
    """Summarize logic that still refers to a routine or program name.

    AOI logic is not searched. For tags use :func:`tag_references`.

    Args:
        registry: The registry (used to read the output file).
        out_path: Root-relative path of the written file.
        name: The routine name, or ``\\Program`` text, to look for.
        program: Limit the search to one program.
        alias_program: Also list alias tags whose target has the prefix
            ``\\alias_program`` (for a renamed program).

    Returns:
        ``{"total": n, "locations": [...], "aliases": [...]}`` (empty parts
        omitted), or ``None`` when there is nothing.
    """
    locations = _logic_locations(registry, out_path, name, program)
    aliases = []
    if alias_program:
        project = registry.get_with_path(out_path)[1]
        low = alias_program.lower()
        aliases = _alias_hits(
            project, lambda _s, p: p.program is not None and p.program.lower() == low
        )
    return _references_result(locations, aliases)


def tag_references(
    registry: ProjectRegistry, out_path: str, name: str, scope: str
) -> dict[str, Any] | None:
    """Summarize logic and alias tags that still refer to a removed/renamed tag.

    A controller tag is looked for in every program except those that define
    their own tag of that name (there the name means the program tag). A
    program tag is looked for in its own program as ``name`` and in all
    programs as ``\\Program.name``. AOI logic is not searched.

    Args:
        registry: The registry (used to read the output file).
        out_path: Root-relative path of the written file.
        name: The tag's old name.
        scope: ``"controller"`` or the program name.

    Returns:
        ``{"total": n, "locations": [...], "aliases": [...]}`` (empty parts
        omitted), or ``None`` when there is nothing.
    """
    project = registry.get_with_path(out_path)[1]
    low = name.lower()
    if scope == "controller":
        shadowing = frozenset(
            prog.name.lower()
            for prog in project.programs.values()
            if any(k.lower() == low for k in prog.tags)
        )
        locations = _logic_locations(registry, out_path, name, skip_programs=shadowing)
        aliases = _alias_hits(
            project,
            lambda s, p: (
                p.program is None
                and p.base.lower() == low
                and (s == "controller" or s.lower() not in shadowing)
            ),
        )
    else:
        prog_low = scope.lower()
        locations = _logic_locations(registry, out_path, name, program=scope)
        locations += _logic_locations(registry, out_path, f"\\{scope}.{name}")
        aliases = _alias_hits(
            project,
            lambda s, p: (
                p.base.lower() == low
                and (
                    (p.program is None and s.lower() == prog_low)
                    or (p.program is not None and p.program.lower() == prog_low)
                )
            ),
        )
    return _references_result(locations, aliases)


def _find_tag(project: Project, name: str, scope: str | None) -> tuple[str, Any]:
    """Find a base tag by name (no operand path) for rename/remove/update.

    Args:
        project: The project.
        name: Tag name.
        scope: ``None`` (controller first, then programs), ``"controller"`` or a
            program name.

    Returns:
        The canonical scope (``"controller"`` or program name) and the tag.

    Raises:
        L5XError: If the name is an operand path or a module I/O tag.
    """
    if any(c in name for c in ".[:\\"):
        raise L5XError(
            f"{name!r} is not a plain tag name; pass the base tag name "
            "(module I/O tags cannot be renamed, removed or edited here)"
        )
    resolved = resolve_tag(project, name, scope=scope)
    if isinstance(resolved.tag, ModuleTagRef) or resolved.scope == "module_io":
        raise L5XError(f"{name!r} is a module I/O tag and cannot be edited here")
    return resolved.scope, resolved.tag


def add_tags(
    registry: ProjectRegistry,
    tags: list[TagSpecDict],
    output_path: str,
    scope: str = "controller",
    path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Add base or alias tags to a project and write the result to a new file.

    Each tag spec needs a name and either data_type (base tag) or alias_for
    (alias). value sets the initial value (scalar, string, {member: value} for
    structures, list for arrays); without it Studio uses the type's defaults.
    BOOL arrays are rounded up to a multiple of 32 elements. Names follow Logix
    rules and must be unique (case-insensitive) in the scope. All tags are
    added or none are.

    Alias tags take name, alias_for, description, radix and external_access
    (Studio ignores external_access on aliases); no data_type, value,
    dimensions, constant or operand comments. The alias target (including any
    member, bit or index) must exist: in the scope, in the controller tags
    (for a program alias), as a module I/O tag, or as another tag in the same
    call.

    Args:
        registry: ProjectRegistry to load from.
        tags: Tag specs to add, in order.
        output_path: New .L5X file (a bare name is written to the output
            folder; a path is root-relative). Must not be the source.
        scope: "controller" (default) or a program name.
        path: Source .L5X file (None for auto-discovery). Never modified.
        overwrite: Replace output_path if this server wrote it earlier in this session.

    Returns:
        Dict with file (written), source, scope and added (tag names), plus
        warnings (alias targets that could not be fully checked), when any.
    """
    if not tags:
        raise L5XError("tags must contain at least one tag spec")
    edit = Edit.open(registry, path, output_path, overwrite)
    scope_name, collection = scope_collection(edit.project, scope)
    specs = [to_py_spec("tag", data) for data in tags]
    for spec in specs:
        if not spec.alias_for:
            if not spec.data_type:
                raise L5XError(
                    f"tag {spec.name!r}: data_type (or alias_for) is required"
                )
            check_data_type(edit.project, spec.data_type)
    # Before adding, so error messages do not list the batch's own names.
    warnings = check_spec_aliases(edit.project, specs, scope_name)
    for spec in specs:
        with edit_errors(f"tag {spec.name!r}"):
            _add_tag_spec(collection, spec)
    return edit.save(
        with_warnings(
            {"scope": scope_name, "added": [spec.name for spec in specs]}, warnings
        )
    )


def with_warnings(summary: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    """Add a ``warnings`` key to a tool summary when there are warnings.

    Args:
        summary: The tool-specific result fields.
        warnings: Warning strings (possibly empty).

    Returns:
        ``summary``, with ``warnings`` added when non-empty.
    """
    if warnings:
        summary["warnings"] = warnings
    return summary


def check_spec_aliases(
    project: Project, tags: list[Any], scope: str = "controller"
) -> list[str]:
    """Check the alias targets of tag specs that are not in the project yet.

    A target is accepted if its base is a base tag of the same spec list, a
    controller tag, or a module I/O tag of ``project``. Alias chains inside the
    list are followed; a cycle (including a self alias) is an error.

    Args:
        project: The project to resolve against (edited or context project).
        tags: py_l5x ``TagSpec`` objects.
        scope: Scope for resolution, normally ``"controller"``.

    Returns:
        Warnings for targets whose members could not be verified.

    Raises:
        L5XError: If an alias target cannot be found.
    """
    batch = {t.name.lower(): t for t in tags}
    warnings: list[str] = []
    for tag in tags:
        if tag.alias_for:
            warnings += check_alias_target(
                project, tag.alias_for, scope, tag.name, batch
            )
    return warnings


def _add_tag_spec(collection: TagsCollection, spec: Any) -> Any:
    """Add a tag from a ``TagSpec`` (validated metadata, aliases keep radix).

    Mirrors ``TagsCollection.add``; this should become a public py_l5x API
    (``TagsCollection.add_spec``) and then be replaced by it.

    Args:
        collection: The collection to add to.
        spec: The py_l5x ``TagSpec``.

    Returns:
        The new tag.
    """
    collection._check_new_name(spec.name)
    return collection._append(build_tag(spec, collection._registry))


def check_alias_target(
    project: Project,
    alias_for: str,
    scope: str,
    alias_name: str | None = None,
    batch: Mapping[str, Any] | None = None,
) -> list[str]:
    """Check that an alias target exists, including members, bits and indexes.

    Args:
        project: The project to resolve against.
        alias_for: The alias's target operand.
        scope: ``"controller"`` or a program name (program tags are searched
            first, then controller tags). Module I/O names always resolve.
        alias_name: The alias's name, for the error message.
        batch: ``{lower-case name: TagSpec}`` of the tags being added together
            with the alias (not yet in ``project``). A target whose base is a
            base tag of the batch is accepted without walking its path (it
            may have no data yet). A base that is another alias of the batch
            is followed through the batch specs.

    Returns:
        Warnings (empty when the whole path was verified). A target through a
        tag with no value tree (MESSAGE, AXIS_*, ...) is accepted with a
        warning, because its members cannot be checked here.

    Raises:
        L5XError: If the target cannot be found, or aliases form a cycle.
    """
    batch = batch or {}
    label = f"alias {alias_name!r}: " if alias_name else "alias: "
    chain = [alias_name] if alias_name else []
    target = alias_for
    while True:
        parsed = parse_operand(target)
        spec = batch.get(parsed.base.lower()) if parsed.program is None else None
        if spec is None:
            break
        if not spec.alias_for:
            return []
        if spec.name.lower() in (c.lower() for c in chain):
            cycle = " -> ".join([*chain, spec.name])
            raise L5XError(f"{label}alias cycle {cycle}")
        chain.append(spec.name)
        target = spec.alias_for
    use = scope
    if parsed.program is None and scope != "controller" and ":" not in parsed.base:
        program = lookup(project.programs, scope, "Program")
        if not any(k.lower() == parsed.base.lower() for k in program.tags):
            use = "controller"
    try:
        resolved = resolve_tag(project, target, scope=None if parsed.program else use)
    except L5XError as exc:
        raise L5XError(f"{label}target {target!r} not found: {exc}") from exc
    if resolved.alias_error:
        raise L5XError(f"{label}target {target!r} not found: {resolved.alias_error}")
    hop = resolved
    while hop is not None:
        if hop.segments_remaining:
            return [
                f"{label}members of {hop.tag.data_type} tag {hop.tag.name!r} are "
                f"not checked; Studio verifies {target!r} when the project is built"
            ]
        hop = hop.target
    return []


def _apply_operand_metadata(
    tag: Any,
    comments: dict[str, str | None],
    metadata: dict[str, dict[str, str | None]],
) -> None:
    """Set operand comments and metadata on a tag.

    Args:
        tag: The tag.
        comments: ``{operand: text}``; ``None``/``""`` removes.
        metadata: ``{operand: {key: text}}``; ``None``/``""`` removes.
    """
    if (comments or metadata) and isinstance(tag, AliasTag):
        raise L5XError("alias tags have no operand comments or metadata")
    for operand, text in comments.items():
        tag.set_operand_comment(operand, text)
    for operand, entries in metadata.items():
        for key, text in entries.items():
            tag.set_operand_metadata(operand, key, text)


def remove_tags(
    registry: ProjectRegistry,
    names: list[str],
    output_path: str,
    scope: str | None = None,
    path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Delete tags and write the result to a new file.

    Logic, alias tags and other references to removed tags are NOT updated;
    the result lists remaining logic references and alias tags that point at
    them so you can fix them (a project with dangling references fails to
    verify in Studio).

    Args:
        registry: ProjectRegistry to load from.
        names: Tag names to remove.
        output_path: New .L5X file (a bare name is written to the output
            folder; a path is root-relative). Must not be the source.
        scope: None (controller first, then programs), "controller", or a
            program name.
        path: Source .L5X file (None for auto-discovery). Never modified.
        overwrite: Replace output_path if this server wrote it earlier in this session.

    Returns:
        Dict with file, source, removed ([{name, scope}]) and references
        (logic still using each removed name, when any).
    """
    if not names:
        raise L5XError("names must contain at least one tag name")
    edit = Edit.open(registry, path, output_path, overwrite)
    removed = []
    for name in names:
        tag_scope, tag = _find_tag(edit.project, name, scope)
        _, collection = scope_collection(edit.project, tag_scope)
        with edit_errors(f"remove {name!r}"):
            collection.remove(tag.name)
        removed.append({"name": tag.name, "scope": tag_scope})
    result = edit.save({"removed": removed})
    refs = {}
    for item in removed:
        found = tag_references(registry, result["file"], item["name"], item["scope"])
        if found:
            refs[item["name"]] = found
    if refs:
        result["references"] = refs
    return result


def rename_tag(
    registry: ProjectRegistry,
    name: str,
    new_name: str,
    output_path: str,
    scope: str | None = None,
    path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Rename a tag and write the result to a new file.

    Logic and alias references to the old name are NOT updated; the result
    lists them (references: logic locations and alias tags) so they can be
    edited with the rung and tag tools.

    Args:
        registry: ProjectRegistry to load from.
        name: Current tag name.
        new_name: New tag name (Logix naming rules; unique in its scope).
        output_path: New .L5X file (a bare name is written to the output
            folder; a path is root-relative). Must not be the source.
        scope: None (controller first, then programs), "controller", or a
            program name.
        path: Source .L5X file (None for auto-discovery). Never modified.
        overwrite: Replace output_path if this server wrote it earlier in this session.

    Returns:
        Dict with file, source, scope, renamed {from, to} and references (logic
        still using the old name, when any).
    """
    edit = Edit.open(registry, path, output_path, overwrite)
    tag_scope, tag = _find_tag(edit.project, name, scope)
    _, collection = scope_collection(edit.project, tag_scope)
    old = tag.name
    with edit_errors(f"rename {old!r}"):
        collection.rename(old, new_name)
    result = edit.save({"scope": tag_scope, "renamed": {"from": old, "to": new_name}})
    if old.lower() != new_name.lower():  # Logix names are case-insensitive
        found = tag_references(registry, result["file"], old, tag_scope)
        if found:
            result["references"] = found
    return result


def set_tag_values(
    registry: ProjectRegistry,
    values: dict[str, Any],
    output_path: str,
    scope: str | None = None,
    path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Set tag values (initial/offline values) and write the result to a new file.

    values maps operand paths to new values, e.g. {"Motor.Speed": 900.0,
    "Recipe[2]": 5, "Delay.PRE": 5000, "Msg": "Hello",
    "Cfg": {"Mode": 2, "Gain": 1.5}, "Table": [1, 2, 3]}. Structures accept a
    partial {member: value} dict; arrays a list or {index: value}. Unmentioned
    members keep their values. TIME values accept literals such as "T#5s".
    Aliases are followed to their target. Bits of integers (Tag.3) are
    read-only; set the whole integer instead. All values are validated first;
    if any fails, nothing is written.

    Args:
        registry: ProjectRegistry to load from.
        values: {operand path: value}.
        output_path: New .L5X file (a bare name is written to the output
            folder; a path is root-relative). Must not be the source.
        scope: None (controller first, then programs), "controller", or a
            program name; "\\Program.tag" operands select a program directly.
        path: Source .L5X file (None for auto-discovery). Never modified.
        overwrite: Replace output_path if this server wrote it earlier in this session.

    Returns:
        Dict with file, source and set ({operand: new value as stored}).
    """
    if not values:
        raise L5XError("values must contain at least one operand")
    edit = Edit.open(registry, path, output_path, overwrite)
    written: dict[str, Any] = {}
    for operand, value in values.items():
        _materialize(edit.project, operand, scope)
        resolved = resolve_tag(edit.project, operand, scope=scope).terminal()
        if resolved.alias_error:
            raise L5XError(f"{operand}: {resolved.alias_error}")
        node = resolved.node
        if node is None or resolved.segments_remaining:
            raise L5XError(f"{operand}: this tag has no editable value")
        with edit_errors(operand):
            node.value = value
        key = resolved.path
        if resolved.scope not in ("controller", "module_io"):
            key = f"\\{resolved.scope}.{key}"
        written[key] = node.to_python()
    return edit.save({"set": written})


def _materialize(project: Project, operand: str, scope: str | None) -> None:
    """Give a data-less base tag its default data so sub-paths can be walked.

    Tags added without a value have no ``<Data>``, so ``Arr[2]`` or ``T.PRE``
    cannot be resolved until the default value tree exists.

    Args:
        project: The project being edited.
        operand: The operand path being set.
        scope: The scope passed to the tool.
    """
    parsed = parse_operand(operand)
    base = f"\\{parsed.program}.{parsed.base}" if parsed.program else parsed.base
    try:
        tag = resolve_tag(project, base, scope=scope).terminal().tag
    except L5XError:
        return  # resolve_tag on the full operand reports the error
    if isinstance(tag, Tag) and getattr(tag, "_value_element", True) is None:
        with edit_errors(base):
            tag.initialize_data()


def update_tag(
    registry: ProjectRegistry,
    name: str,
    output_path: str,
    scope: str | None = None,
    description: str | None = None,
    operand_comments: dict[str, str | None] | None = None,
    operand_metadata: dict[str, dict[str, str | None]] | None = None,
    path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Change a tag's description and per-operand documentation.

    Only the fields you pass are changed. description "" removes the
    description. operand_comments maps operands (starting with "." or "[")
    to comment text, e.g. {".DN": "Motor started", "[3]": "Spare"}; a null or
    "" value removes that comment. operand_metadata maps operands to
    {key: text} with keys max, min, engineering_unit, state0, state1 or
    external_logging, e.g. {".PRE": {"engineering_unit": "ms"}}.

    Args:
        registry: ProjectRegistry to load from.
        name: Tag name (not an operand path).
        output_path: New .L5X file (a bare name is written to the output
            folder; a path is root-relative). Must not be the source.
        scope: None (controller first, then programs), "controller", or a
            program name.
        description: New description; "" removes it; omit to keep.
        operand_comments: {operand: comment or null}.
        operand_metadata: {operand: {key: text or null}}.
        path: Source .L5X file (None for auto-discovery). Never modified.
        overwrite: Replace output_path if this server wrote it earlier in this session.

    Returns:
        Dict with file, source, scope, tag and changed (list of what changed).
    """
    if description is None and not operand_comments and not operand_metadata:
        raise L5XError(
            "nothing to change: pass description, operand_comments or operand_metadata"
        )
    edit = Edit.open(registry, path, output_path, overwrite)
    tag_scope, tag = _find_tag(edit.project, name, scope)
    changed = []
    with edit_errors(tag.name):
        if description is not None:
            tag.description = description or None
            changed.append("description")
        _apply_operand_metadata(tag, operand_comments or {}, operand_metadata or {})
    changed += [f"comment {op}" for op in operand_comments or {}]
    for op, entries in (operand_metadata or {}).items():
        changed += [f"{key} {op}" for key in entries]
    return edit.save({"scope": tag_scope, "tag": tag.name, "changed": changed})
