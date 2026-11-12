"""Tools for exploring tags in L5X projects.

This module lists and examines tags at controller, module I/O, or program
scope. Operand paths such as ``a_udt.member[2].3`` or ``Local:1:I.Pt00.Data``
are resolved by :mod:`l5x_mcp.operand_paths`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from l5x_mcp.operand_paths import (
    Resolved,
    format_segments,
    is_module_io_scope,
    module_tags,
    resolve_tag,
)
from l5x_mcp.registry import L5XError, ProjectRegistry, lookup
from l5x_mcp.serialize import compact, node_to_dict, tag_detail, tag_summary


def list_tags(
    registry: ProjectRegistry,
    scope: str = "controller",
    name_contains: str | None = None,
    data_type: str | None = None,
    tag_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
    path: str | None = None,
) -> dict[str, Any]:
    """List tags in a project with filtering and pagination.

    scope selects the tag set:
    - "controller" (default): controller-scoped tags.
    - "module_io": module I/O tags, whose global names contain a colon (e.g.
      "Local:2:I", "ShopRobot:I", "ValveBank:I"). Each summary has kind
      (C/I/O/...) and module. Use these names in operand paths, e.g.
      "Local:1:I.Pt00.Data". If a program is literally named "module_io", that
      program is listed instead.
    - any other value: the tags of that program (name is case-insensitive).

    Filters: name_contains (case-insensitive substring), data_type (exact),
    tag_type (exact: Base/Alias/Produced/Consumed; module I/O tags have none).
    Each returned tag is a summary (name, data_type, description first line,
    tag_type or kind/module, external_access).

    Args:
        registry: ProjectRegistry to load from.
        scope: "controller", "module_io", or a program name.
        name_contains: Filter by name substring (case-insensitive, optional).
        data_type: Filter by exact data_type match (optional).
        tag_type: Filter by exact tag_type (Base/Alias/Produced/Consumed, optional).
        limit: Max tags to return (1..1000, default 100).
        offset: Skip first N tags after filtering (default 0).
        path: L5X file path (None for auto-discovery).

    Returns:
        Dict with: file (path), scope, total (count after filtering), offset,
        limit, next_offset (only if more remain), note (when helpful), and
        tags (list of tag summaries).

    Raises:
        L5XError: For invalid limit/offset.
        ItemNotFoundError: If the program scope is not found.
    """
    resolved_path, project = registry.get_with_path(path)

    # Validate and normalize limit/offset
    if not (1 <= limit <= 1000):
        raise L5XError(f"limit must be 1..1000, got {limit}")
    if offset < 0:
        raise L5XError(f"offset must be >= 0, got {offset}")

    # Resolve scope to get tags collection
    is_component_export = bool(
        getattr(getattr(project, "controller", None), "is_context", False)
    )

    tags_collection: Mapping[str, Any]
    if scope.lower() == "controller":
        tags_collection = project.controller_tags
        resolved_scope = "controller"
        use_default_note = False

        # Check if no controller tags and should auto-switch for component exports
        if not tags_collection and len(project.programs) == 1 and is_component_export:
            program = list(project.programs.values())[0]
            tags_collection = program.tags
            resolved_scope = program.name
            use_default_note = True
    elif is_module_io_scope(project, scope):
        tags_collection = module_tags(project)
        resolved_scope = "module_io"
        use_default_note = False
    else:
        program = lookup(project.programs, scope, "Program")
        tags_collection = program.tags
        resolved_scope = program.name
        use_default_note = False

    # Filter tags
    filtered_tags: list[tuple[str, Any]] = []
    for tag_name, tag_obj in tags_collection.items():
        # Filter by name
        if name_contains and name_contains.lower() not in tag_name.lower():
            continue

        # Filter by data_type (exact match)
        if data_type and tag_obj.data_type != data_type:
            continue

        # Filter by tag_type (exact match)
        if tag_type and getattr(tag_obj, "tag_type", None) != tag_type:
            continue

        filtered_tags.append((tag_name, tag_obj))

    # Sort by name for consistent ordering
    filtered_tags.sort(key=lambda x: x[0])

    # Paginate
    total = len(filtered_tags)
    tags_slice = filtered_tags[offset : offset + limit]

    # Build result
    result: dict[str, Any] = {
        "file": registry.relpath(resolved_path),
        "scope": resolved_scope,
        "total": total,
        "offset": offset,
        "limit": limit,
    }

    # Include next_offset if there are more tags
    if offset + limit < total:
        result["next_offset"] = offset + limit

    # Helpful note when controller scope matched nothing
    if resolved_scope == "controller" and total == 0 and not use_default_note:
        notes: list[str] = []
        if project.programs:
            prog_list = []
            for prog_name in sorted(project.programs.keys())[:20]:
                prog_tag_count = len(project.programs[prog_name].tags)
                prog_list.append(f"{prog_name} ({prog_tag_count} tags)")
            programs_str = ", ".join(prog_list)
            if len(project.programs) > 20:
                programs_str += f", ... ({len(project.programs) - 20} more)"
            notes.append(
                f"Program-scoped tags exist in: {programs_str} — "
                "pass scope=<program name>."
            )
        io_count = len(module_tags(project))
        if io_count:
            notes.append(
                f"{io_count} module I/O tags exist — "
                'pass scope="module_io" to list them.'
            )
        if notes:
            result["note"] = "No controller-scoped tags matched. " + " ".join(notes)

    # Add note if auto-switched scope for component export
    if use_default_note:
        result["note"] = (
            f"Defaulted to {resolved_scope} scope (component export with no "
            "controller tags). Pass scope=controller to view controller scope."
        )

    # Add tags
    result["tags"] = [tag_summary(tag_obj) for _, tag_obj in tags_slice]

    return compact(result)


def _no_value_tree_error(res: Resolved) -> L5XError:
    """Explain why a sub-path cannot be resolved on a value-less operand."""
    tag = res.tag
    rest = format_segments(res.segments_remaining)
    if res.alias_error:
        return L5XError(
            f"'{tag.name}' is an alias and its target could not be followed: "
            f"{res.alias_error}"
        )
    return L5XError(
        f"'{tag.name}' ({type(tag).__name__}) has no value tree, so '{rest}' "
        "cannot be resolved."
    )


def get_tag(
    registry: ProjectRegistry,
    name: str,
    scope: str | None = None,
    max_depth: int = 3,
    max_elements: int = 32,
    path: str | None = None,
) -> dict[str, Any]:
    """Get a tag, or the value at an operand path inside it.

    name is a tag name or an operand path:
    - "message_tag": full tag detail with value_tree.
    - "a_udt.member[2].3": the value at that path (structure members, array
      elements by subscript, bits of integers, STRING LEN/DATA). Subscripts
      may be runtime expressions (e.g. "arr[idx+1]"); element 0 is shown and
      a note explains it.
    - "a_commented_dint.0": a single bit, with its comment as description.
    - "Local:2:I.Pt00.Data": module I/O tags, by their global name.
    - "\\MainProgram.tag": an explicit program prefix.

    Without a sub-path, the result has the tag detail fields (value_tree and
    related metadata). With a sub-path, the result has: tag (summary of the
    base), operand (canonical path with correct case), and node (the value at
    that path). Pass max_depth or max_elements to bound large values.

    Alias tags are followed. An alias result includes alias_for and
    alias_chain; with no sub-path it also includes resolved_target (the
    target's operand and node, when it has a value). With a sub-path, the
    operand and node refer to the target.

    scope: None searches controller tags first, then programs. "controller"
    searches controller tags only, "module_io" searches module I/O tags only (unless
    a program is literally named "module_io", which then takes precedence), and any
    other value is a program name. Results found in controller scope include
    also_in_programs when a program has a same-named tag.

    Args:
        registry: ProjectRegistry to load from.
        name: Tag name or operand path (e.g. "a_udt.member[2].bit").
        scope: None, "controller", "module_io", or a program name.
        max_depth: Max recursion depth for value_tree or node (default 3).
        max_elements: Max array elements to include (default 32).
        path: L5X file path (None for auto-discovery).

    Returns:
        Dict with file and scope, plus either the tag detail (no sub-path) or
        tag, operand and node (sub-path). Also also_in_programs and note when
        applicable.

    Raises:
        L5XError: For invalid operand paths, unknown members, out-of-range
            indexes or bits, or sub-paths of tags without a value tree.
        ItemNotFoundError: If the tag or program is not found.
    """
    resolved_path, project = registry.get_with_path(path)
    res = resolve_tag(project, name, scope=scope)
    final = res.terminal()

    result: dict[str, Any] = {
        "file": registry.relpath(resolved_path),
        "scope": res.scope,
    }
    if res.alias_chain or res.alias_error:
        result["alias_for"] = getattr(res.tag, "alias_for", None)
        result["alias_chain"] = res.alias_chain

    if not res.segments:
        result.update(tag_detail(res.tag, max_depth, max_elements))
        if res.target is not None:
            target_info: dict[str, Any] = {"scope": final.scope, "operand": final.path}
            if final.node is not None:
                target_info["node"] = node_to_dict(final.node, max_depth, max_elements)
            result["resolved_target"] = compact(target_info)
        if final.alias_error:
            result["alias_error"] = final.alias_error
    elif final.node is not None:
        result["tag"] = tag_summary(res.tag)
        result["operand"] = final.path
        result["node"] = node_to_dict(final.node, max_depth, max_elements)
    elif final.description_override is not None or final.data_type_override is not None:
        result["tag"] = tag_summary(res.tag)
        result["operand"] = final.path
        result["description"] = final.description_override
        result["data_type"] = final.data_type_override
    else:
        raise _no_value_tree_error(final)

    if res.also_in_programs:
        result["also_in_programs"] = res.also_in_programs
    if final.notes:
        result["note"] = " ".join(final.notes)

    return compact(result)
