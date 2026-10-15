"""Tools for exploring tags in L5X projects.

This module provides functions to list and examine tags at controller or
program scope, with support for operand paths into nested structures, arrays,
and bit fields.
"""

from __future__ import annotations

import re
from typing import Any

from py_l5x.parsers.tag import Tag, TagNode

from l5x_mcp.registry import ItemNotFoundError, L5XError, ProjectRegistry, lookup
from l5x_mcp.serialize import compact, tag_detail, tag_node_to_dict, tag_summary


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
    """List tags in a project at controller or program scope with filtering.

    Filters tags by name substring (case-insensitive), data_type (exact),
    and tag_type (exact: Base/Alias/Produced/Consumed). Supports pagination
    with limit and offset. Returns summary for each tag (name, data_type,
    tag_type, description first line, etc.).

    Args:
        registry: ProjectRegistry to load from.
        scope: "controller" for controller-scoped tags, or a program name.
        name_contains: Filter by name substring (case-insensitive, optional).
        data_type: Filter by exact data_type match (optional).
        tag_type: Filter by exact tag_type (Base/Alias/Produced/Consumed, optional).
        limit: Max tags to return (1..1000, default 100).
        offset: Skip first N tags after filtering (default 0).
        path: L5X file path (None for auto-discovery).

    Returns:
        Dict with: file (path), scope, total (count after filtering), offset,
        limit, next_offset (only if more remain), tags (list of tag_summary).

    Raises:
        L5XError: For invalid limit/offset or scope issues.
        ItemNotFoundError: If program scope not found.
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

    if scope.lower() == "controller":
        tags_collection = project.tags
        resolved_scope = "controller"
        use_default_note = False

        # Check if no controller tags and should auto-switch for component exports
        if not tags_collection and len(project.programs) == 1 and is_component_export:
            program = list(project.programs.values())[0]
            tags_collection = program.tags
            resolved_scope = program.name
            use_default_note = True
    else:
        program = lookup(project.programs, scope, "Program")
        tags_collection = program.tags
        resolved_scope = program.name
        use_default_note = False

    # Filter tags
    filtered_tags: list[tuple[str, Tag]] = []
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

    # Add helpful note if controller scope has no results but programs exist
    if (
        resolved_scope == "controller"
        and total == 0
        and project.programs
        and not use_default_note
    ):
        prog_list = []
        for prog_name in sorted(project.programs.keys())[:20]:
            prog_tag_count = len(project.programs[prog_name].tags)
            prog_list.append(f"{prog_name} ({prog_tag_count} tags)")
        programs_str = ", ".join(prog_list)
        if len(project.programs) > 20:
            programs_str += f", ... ({len(project.programs) - 20} more)"
        result["note"] = (
            f"No controller-scoped tags matched. Program-scoped tags exist in: "
            f"{programs_str} — pass scope=<program name>."
        )

    # Add note if auto-switched scope for component export
    if use_default_note:
        result["note"] = (
            f"Defaulted to {resolved_scope} scope (component export with no "
            "controller tags). Pass scope=controller to view controller scope."
        )

    # Add tags
    result["tags"] = [tag_summary(tag_obj) for _, tag_obj in tags_slice]

    return compact(result)


def _parse_operand_path(path_str: str) -> list[str | int]:
    """Parse an operand path into segments.

    Examples:
        "a_udt_instance.a_nested_UDT.bool1" →
            ["a_udt_instance", "a_nested_UDT", "bool1"]
        "ALLOWABLE_ALARMS[3]" → ["ALLOWABLE_ALARMS", 3]
        "ALLOWABLE_ALARMS[3].LEN" → ["ALLOWABLE_ALARMS", 3, "LEN"]
        "a_dint.2" → ["a_dint", 2] (bit access)
        "ALLOWABLE_ALARMS[1,2]" → ["ALLOWABLE_ALARMS", (1, 2)] (multi-dim)

    Can also parse remainder paths (for internal use):
        "[3]" → [3]
        ".member" → ["member"]
        "[3].LEN" → [3, "LEN"]

    Args:
        path_str: Path string to parse.

    Returns:
        List of segments: strings (member names) or ints/tuples
        (indices/bit numbers).

    Raises:
        L5XError: If path format is invalid.
    """
    if not path_str:
        raise L5XError("Operand path cannot be empty")

    segments: list[str | int | tuple[int, ...]] = []
    remaining = path_str

    while remaining:
        # Skip leading dot or bracket (will be handled below)
        if remaining[0] == ".":
            remaining = remaining[1:]
            if not remaining:
                raise L5XError("Operand path cannot end with '.'")
            continue
        elif remaining[0] == "[":
            # Parse array index: [i] or [i,j,k,...]
            close = remaining.find("]")
            if close == -1:
                raise L5XError(f"Unclosed bracket in operand path: {path_str}")

            index_str = remaining[1:close]
            try:
                indices = [int(x.strip()) for x in index_str.split(",")]
                if len(indices) == 1:
                    segments.append(indices[0])
                else:
                    # Multi-dimensional: store as tuple for row-major flattening
                    segments.append(tuple(indices))
            except ValueError:
                raise L5XError(
                    f"Invalid array index in operand path: [{index_str}]"
                ) from None

            remaining = remaining[close + 1 :]
            continue

        # Try to match an integer (bit access)
        int_match = re.match(r"^(\d+)", remaining)
        if int_match:
            bit_num = int(int_match.group(1))
            segments.append(bit_num)
            remaining = remaining[len(int_match.group(1)) :]
            continue

        # Try to match a member name
        match = re.match(r"^([a-zA-Z_]\w*)", remaining)
        if not match:
            if remaining:
                raise L5XError(
                    f"Invalid operand path: expected member name, got '{remaining}'"
                )
            break

        member_name = match.group(1)
        segments.append(member_name)
        remaining = remaining[len(member_name) :]

    return segments


def _flatten_multi_dim_index(
    multi_index: tuple[int, ...], dimensions: list[int]
) -> int:
    """Convert multi-dimensional index to flat row-major index.

    Args:
        multi_index: Tuple of indices like (i, j, k).
        dimensions: List of dimension sizes like [2, 3, 4].

    Returns:
        Flat index.

    Raises:
        L5XError: If index out of bounds or dimension mismatch.
    """
    if len(multi_index) != len(dimensions):
        raise L5XError(
            f"Index has {len(multi_index)} dimensions but tag has {len(dimensions)}"
        )

    flat = 0
    stride = 1
    for i in range(len(dimensions) - 1, -1, -1):
        idx = multi_index[i]
        if not (0 <= idx < dimensions[i]):
            raise L5XError(
                f"Index out of bounds: dimension {i} is {dimensions[i]}, got {idx}"
            )
        flat += idx * stride
        stride *= dimensions[i]

    return flat


def _walk_operand_path(
    base_tag: Tag, path_segments: list[str | int | tuple[int, ...]]
) -> tuple[TagNode, str]:
    """Walk an operand path through nested structures and arrays.

    Args:
        base_tag: The base Tag to start from.
        path_segments: List of segments from _parse_operand_path.

    Returns:
        Tuple of (final_node, full_path_walked) where full_path_walked shows
        how the path was resolved (e.g. "a_udt_instance.a_nested_UDT.bool1").

    Raises:
        L5XError: For member not found, index out of bounds, etc.
    """
    current_node = base_tag.data
    path_parts: list[str] = [base_tag.name]

    if current_node is None:
        msg = f"Tag '{base_tag.name}' has no data (may be Alias or uninitialized)"
        raise L5XError(msg)

    for segment in path_segments:
        if isinstance(segment, str):
            # Member access
            if current_node.kind != "structure":
                raise L5XError(
                    f"Cannot access member '{segment}' on {current_node.kind} "
                    f"(data_type: {current_node.data_type})"
                )

            # Case-insensitive member lookup
            member_name = None
            for key in current_node.members:
                if key.lower() == segment.lower():
                    member_name = key
                    break

            if member_name is None:
                available = ", ".join(sorted(current_node.members.keys()))
                raise L5XError(
                    f"Member '{segment}' not found in {current_node.data_type}. "
                    f"Available: {available}"
                )

            current_node = current_node.members[member_name]
            path_parts.append(f".{member_name}")

        elif isinstance(segment, tuple):
            # Multi-dimensional array index
            if current_node.kind != "array":
                msg = (
                    f"Cannot index {current_node.kind} "
                    f"(data_type: {current_node.data_type})"
                )
                raise L5XError(msg)

            # Try to get dimensions
            dimensions: list[int] | None = None
            if hasattr(current_node, "_element") and current_node._element is not None:
                dimensions = current_node._element.get("Dimensions")

            if not dimensions:
                raise L5XError(
                    "Multi-dimensional indexing not supported for this array "
                    "(dimensions not available)"
                )

            # Convert to flat index
            try:
                flat_idx = _flatten_multi_dim_index(segment, dimensions)
            except L5XError:
                raise

            # Access the element
            if flat_idx >= len(current_node.elements):
                raise L5XError(
                    f"Array index {segment} out of bounds "
                    f"(element count: {len(current_node.elements)})"
                )

            current_node = current_node.elements[flat_idx]
            path_parts.append(f"[{','.join(str(i) for i in segment)}]")

        else:  # int
            # Array index or bit access
            if current_node.kind == "array":
                if segment >= len(current_node.elements):
                    raise L5XError(
                        f"Array index {segment} out of bounds "
                        f"(element count: {len(current_node.elements)})"
                    )
                current_node = current_node.elements[segment]
                path_parts.append(f"[{segment}]")

            elif current_node.kind == "scalar":
                # Bit access
                if not hasattr(current_node, "bit"):
                    raise L5XError(
                        f"Cannot access bit on {current_node.data_type} scalar "
                        f"(only integral types support bit access)"
                    )
                current_node = current_node.bit(segment)
                path_parts.append(f".{segment}")

            else:
                msg = (
                    f"Cannot index {current_node.kind} "
                    f"(data_type: {current_node.data_type})"
                )
                raise L5XError(msg)

    # Build the path string properly (no leading dot)
    full_path = "".join(path_parts)
    return current_node, full_path


def get_tag(
    registry: ProjectRegistry,
    name: str,
    scope: str | None = None,
    max_depth: int = 3,
    max_elements: int = 32,
    path: str | None = None,
) -> dict[str, Any]:
    """Get a tag with full metadata and optional operand path.

    If `name` is an operand path (e.g. "a_udt_instance.a_nested_UDT.bool1"),
    parses it to find the base tag and walks through nested members/arrays/bits.
    When a sub-path is given, returns tag_summary for the base tag plus operand
    and node (tag_node_to_dict of the final node). Without a sub-path, returns
    full tag_detail with value_tree.

    If `scope` is None: searches controller tags first, then programs. If found
    in multiple programs but not controller, raises L5XError listing programs.
    If found at controller scope, returns controller tag and includes
    "also_in_programs" if any program has a same-named tag.

    Args:
        registry: ProjectRegistry to load from.
        name: Tag name, possibly with operand path (e.g. "a_udt.member[2].bit").
        scope: "controller", a program name, or None for auto-search.
        max_depth: Max recursion depth for value_tree (default 3).
        max_elements: Max array elements to include (default 32).
        path: L5X file path (None for auto-discovery).

    Returns:
        Dict with: file, scope, tag (tag_summary), and either:
        - operand, node (for operand paths); or
        - full tag_detail fields (for base tags)

    Raises:
        L5XError: For invalid operand paths, member not found, etc.
        ItemNotFoundError: If tag not found.
    """
    resolved_path, project = registry.get_with_path(path)

    # Parse the name to see if it includes an operand path
    base_name_match = re.match(r"^([a-zA-Z_]\w*)", name)
    if not base_name_match:
        raise L5XError(f"Invalid tag name: {name}")

    base_tag_name = base_name_match.group(1)
    remainder = name[len(base_tag_name) :]

    # Resolve scope
    if scope is not None and scope.lower() == "controller":
        resolved_scope = "controller"
        tags_to_search = {"controller": project.tags}
    elif scope is not None:
        program = lookup(project.programs, scope, "Program")
        resolved_scope = program.name
        tags_to_search = {resolved_scope: program.tags}
    else:
        # scope is None: search all (controller first)
        resolved_scope = None  # Will resolve dynamically
        tags_to_search = {"controller": project.tags}
        for prog_name in sorted(project.programs.keys()):
            tags_to_search[prog_name] = project.programs[prog_name].tags

    # Find the base tag
    base_tag: Tag | None = None
    found_in_scopes: list[str] = []

    for scope_name, tags_dict in tags_to_search.items():
        # Try exact match first
        if base_tag_name in tags_dict:
            base_tag = tags_dict[base_tag_name]
            found_in_scopes.append(scope_name)
        else:
            # Try case-insensitive
            for key in tags_dict:
                if key.lower() == base_tag_name.lower():
                    base_tag = tags_dict[key]
                    found_in_scopes.append(scope_name)
                    base_tag_name = key  # Use correct case
                    break

    if base_tag is None:
        # Build helpful error message with suggestions
        # Collect all tag names from all scopes
        all_tags: dict[str, list[str]] = {}
        all_tags["controller"] = sorted(project.tags.keys())
        for prog_name in sorted(project.programs.keys()):
            all_tags[prog_name] = sorted(project.programs[prog_name].tags.keys())

        # Find case-insensitive substring matches for suggestions
        suggestions: list[str] = []
        lower_name = base_tag_name.lower()
        for scope_name, tag_names in all_tags.items():
            for tag_name in tag_names:
                if lower_name in tag_name.lower() and len(suggestions) < 10:
                    suggestions.append(f"{scope_name}/{tag_name}")

        # Build error message based on search scope
        if scope is None:
            num_progs = len(project.programs)
            msg = (
                f"Tag '{base_tag_name}' not found at controller scope or "
                f"in any program (searched {num_progs} programs)."
            )
        else:
            msg = f"Tag '{base_tag_name}' not found."

        # Add available tags or suggestions
        if suggestions:
            msg += f"\nDid you mean: {', '.join(suggestions[:10])}"
        elif all_tags["controller"]:
            available = ", ".join(all_tags["controller"][:20])
            if len(all_tags["controller"]) > 20:
                available += f", ... ({len(all_tags['controller']) - 20} more)"
            msg += f"\nAvailable controller tags: {available}"

        raise ItemNotFoundError(msg)

    # If scope was None, resolve it now
    if resolved_scope is None:
        if "controller" in found_in_scopes:
            resolved_scope = "controller"
        elif len(found_in_scopes) == 1:
            resolved_scope = found_in_scopes[0]
        else:
            # Found in multiple programs (and not controller)
            raise L5XError(
                f"Tag '{base_tag_name}' found in multiple programs: "
                f"{', '.join(sorted(found_in_scopes))}. "
                f"Specify the desired scope."
            )

    # If we have an operand path, walk it
    if remainder:
        path_segments = _parse_operand_path(remainder)
        try:
            final_node, full_path = _walk_operand_path(base_tag, path_segments)
        except L5XError:
            raise

        result: dict[str, Any] = {
            "file": registry.relpath(resolved_path),
            "scope": resolved_scope,
            "tag": tag_summary(base_tag),
            "operand": full_path,
            "node": tag_node_to_dict(final_node, max_depth, max_elements),
        }
    else:
        # Return full tag detail
        detail = tag_detail(base_tag, max_depth, max_elements)
        result = {
            "file": registry.relpath(resolved_path),
            "scope": resolved_scope,
            **detail,
        }

        # Check if this base tag exists in other scopes (for context)
        also_in: list[str] = []
        if resolved_scope == "controller":
            for prog_name, prog in project.programs.items():
                for prog_tag_name in prog.tags:
                    if prog_tag_name.lower() == base_tag_name.lower():
                        also_in.append(prog_name)
                        break
        if also_in:
            result["also_in_programs"] = sorted(also_in)

    return compact(result)
