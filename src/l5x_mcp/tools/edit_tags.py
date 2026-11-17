"""Write tools for controller and program tags."""

from __future__ import annotations

from typing import Any

from py_l5x import AliasTag, ModuleTagRef, Tag
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


def references(
    registry: ProjectRegistry, out_path: str, name: str, program: str | None = None
) -> dict[str, Any] | None:
    """Summarize logic that still refers to ``name`` in the written file.

    Args:
        registry: The registry (used to read the output file).
        out_path: Root-relative path of the written file.
        name: The tag, routine or type name to look for.
        program: Limit the search to one program.

    Returns:
        ``{"total": n, "locations": [...]}``, or ``None`` when there are none.
    """
    found = find_references(registry, name, kind="tag", program=program, path=out_path)
    if not found["total_matches"]:
        return None
    locations = []
    for match in found["matches"][:MAX_REFERENCE_LOCATIONS]:
        where = f"{match['container']}/{match['routine']}"
        if "rung" in match:
            where += f" rung {match['rung']}"
        elif "line" in match:
            where += f" line {match['line']}"
        locations.append(where)
    return {"total": found["total_matches"], "locations": locations}


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

    Args:
        registry: ProjectRegistry to load from.
        tags: Tag specs to add, in order.
        output_path: New .L5X file to write (inside the server root; must not
            be the source file).
        scope: "controller" (default) or a program name.
        path: Source .L5X file (None for auto-discovery). Never modified.
        overwrite: Replace output_path if it already exists.

    Returns:
        Dict with file (written), source, scope and added (tag names).
    """
    if not tags:
        raise L5XError("tags must contain at least one tag spec")
    edit = Edit.open(registry, path, output_path, overwrite)
    scope_name, collection = scope_collection(edit.project, scope)
    added = []
    for data in tags:
        spec = to_py_spec("tag", data)
        with edit_errors(f"tag {spec.name!r}"):
            if spec.alias_for:
                if spec.data_type:
                    raise L5XError("give either data_type or alias_for, not both")
                tag = collection.add_alias(
                    spec.name, spec.alias_for, description=spec.description
                )
            else:
                if not spec.data_type:
                    raise L5XError("data_type (or alias_for) is required")
                check_data_type(edit.project, spec.data_type)
                tag = collection.add(
                    spec.name,
                    spec.data_type,
                    dimensions=spec.dimensions,
                    description=spec.description or None,
                    radix=spec.radix,
                    external_access=spec.external_access,
                    constant=spec.constant,
                    value=spec.value,
                )
            _apply_operand_metadata(
                tag, spec.operand_comments or {}, spec.operand_metadata or {}
            )
            for key, text in (spec.metadata or {}).items():
                tag._element.set(key, text)
        added.append(spec.name)
    return edit.save({"scope": scope_name, "added": added})


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
    the result lists remaining logic references so you can fix them (a project
    with dangling references fails to verify in Studio).

    Args:
        registry: ProjectRegistry to load from.
        names: Tag names to remove.
        output_path: New .L5X file to write (must not be the source file).
        scope: None (controller first, then programs), "controller", or a
            program name.
        path: Source .L5X file (None for auto-discovery). Never modified.
        overwrite: Replace output_path if it already exists.

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
        program = None if item["scope"] == "controller" else item["scope"]
        found = references(registry, result["file"], item["name"], program)
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
    lists them (references) so they can be edited with the rung tools.

    Args:
        registry: ProjectRegistry to load from.
        name: Current tag name.
        new_name: New tag name (Logix naming rules; unique in its scope).
        output_path: New .L5X file to write (must not be the source file).
        scope: None (controller first, then programs), "controller", or a
            program name.
        path: Source .L5X file (None for auto-discovery). Never modified.
        overwrite: Replace output_path if it already exists.

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
        program = None if tag_scope == "controller" else tag_scope
        found = references(registry, result["file"], old, program)
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
        output_path: New .L5X file to write (must not be the source file).
        scope: None (controller first, then programs), "controller", or a
            program name; "\\Program.tag" operands select a program directly.
        path: Source .L5X file (None for auto-discovery). Never modified.
        overwrite: Replace output_path if it already exists.

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
        output_path: New .L5X file to write (must not be the source file).
        scope: None (controller first, then programs), "controller", or a
            program name.
        description: New description; "" removes it; omit to keep.
        operand_comments: {operand: comment or null}.
        operand_metadata: {operand: {key: text or null}}.
        path: Source .L5X file (None for auto-discovery). Never modified.
        overwrite: Replace output_path if it already exists.

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
