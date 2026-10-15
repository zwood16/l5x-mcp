"""Tools for exploring data types (UDTs) and their members in L5X projects.

This module provides functions to list user-defined data types and get detailed
information about their members, including cross-references to where they are used.
"""

from __future__ import annotations

from typing import Any

from l5x_mcp.registry import ProjectRegistry, lookup
from l5x_mcp.serialize import compact, first_line


def list_data_types(
    registry: ProjectRegistry, path: str | None = None
) -> dict[str, Any]:
    """List all data types in a project with basic metadata.

    Returns name, family, description (first line), member_count (visible members),
    and is_string flag (only if True for StringFamily types).

    Args:
        registry: ProjectRegistry to load from.
        path: Optional path to a specific L5X file. Defaults to auto-detecting.

    Returns:
        A dict with "file" key and "data_types" list, each with:
        - name: The data type name.
        - family: The data type family (e.g. "NoFamily", "StringFamily").
        - description: First line of description, max 200 chars (omitted if empty).
        - member_count: Number of visible members.
        - is_string: True only for StringFamily types (omitted if False).

    Raises:
        L5XError: If the project cannot be loaded.
    """
    resolved_path, project = registry.get_with_path(path)

    data_types_list = []
    for dt in project.data_types.values():
        member_count = len(dt.visible_members) if hasattr(dt, "visible_members") else 0

        item = {
            "name": dt.name,
            "family": dt.family,
            "member_count": member_count,
        }

        # Add description (first line only)
        desc = first_line(dt.description, 200) if dt.description else ""
        if desc:
            item["description"] = desc

        # Add is_string flag only if True
        if dt.is_string:
            item["is_string"] = True

        data_types_list.append(compact(item))

    return {
        "file": registry.relpath(resolved_path),
        "data_types": data_types_list,
    }


def get_data_type(
    registry: ProjectRegistry, name: str, path: str | None = None
) -> dict[str, Any]:
    """Get detailed information about a data type (UDT).

    Returns name, family, class, description, is_string, max_length (for StringFamily),
    members with their properties (including visibility, dimensions, min/max, EU, etc.),
    and cross-references to where this type is used (used_by, tag_count).

    Args:
        registry: ProjectRegistry to load from.
        name: The data type name to look up.
        path: Optional path to a specific L5X file. Defaults to auto-detecting.

    Returns:
        A dict with:
        - file: The resolved file path.
        - name: The data type name.
        - family: The family (e.g. "NoFamily", "StringFamily").
        - class: The class (e.g. "User", "System").
        - description: Full description (omitted if empty).
        - is_string: True only for StringFamily types.
        - max_length: For StringFamily types only; the max character length.
        - members: List of member dicts (from visible_members), each with:
          - name, data_type, radix, description, engineering_unit, min, max,
            external_access
          - dimension: Only if > 0 (array member).
          - state0/state1: BOOL member descriptions (omitted if empty).
          - Note: BIT members appear as data_type "BOOL"; packed host details
            (bit_number, target) are hidden as they are internal.
        - used_by: List of UDT and AOI names that reference this type.
        - tag_count: Number of controller and program tags of this type.

    Raises:
        L5XError: If the project cannot be loaded.
        ItemNotFoundError: If the data type is not found.
    """
    resolved_path, project = registry.get_with_path(path)

    dt = lookup(project.data_types, name, "Data type")

    result = {
        "file": registry.relpath(resolved_path),
        "name": dt.name,
        "family": dt.family,
        "class": dt.class_,
    }

    # Add description (full text, not truncated)
    if dt.description:
        result["description"] = dt.description

    # Add is_string flag only if True
    if dt.is_string:
        result["is_string"] = True
        result["max_length"] = dt.max_length

    # Build members list from visible_members
    members_list = []
    if hasattr(dt, "visible_members"):
        for member_name in dt.visible_members:
            member = dt.visible_members[member_name]

            member_dict = {
                "name": member.name,
                "data_type": member.data_type,
                "radix": member.radix,
            }

            # Add dimension only if it's an array (dimension > 0)
            if member.dimension and member.dimension > 0:
                member_dict["dimension"] = member.dimension

            # Add description
            if member.description:
                member_dict["description"] = member.description

            # Add engineering_unit
            if member.engineering_unit:
                member_dict["engineering_unit"] = member.engineering_unit

            # Add min/max
            if member.min is not None:
                member_dict["min"] = member.min
            if member.max is not None:
                member_dict["max"] = member.max

            # Add external_access
            if member.external_access:
                member_dict["external_access"] = member.external_access

            # Add state0/state1 for boolean members
            if member.state0:
                member_dict["state0"] = member.state0
            if member.state1:
                member_dict["state1"] = member.state1

            # For BIT members, map data_type to BOOL (hide packed host details)
            if member.is_bit_member:
                member_dict["data_type"] = "BOOL"  # Show as BOOL even though it's BIT

            members_list.append(compact(member_dict))

    result["members"] = members_list

    # Find used_by: UDTs and AOIs that reference this type
    used_by_set = set()

    # Check UDTs
    for other_dt in project.data_types.values():
        if other_dt.name == dt.name:
            continue
        if hasattr(other_dt, "visible_members"):
            for member in other_dt.visible_members.values():
                if member.data_type == dt.name:
                    used_by_set.add(other_dt.name)
                    break

    # Check AOIs (both parameters and local_tags)
    for aoi in project.aois.values():
        # Check parameters
        for param in aoi.parameters.values():
            if param.data_type == dt.name:
                used_by_set.add(aoi.name)
                break
        # Check local_tags
        if aoi.name not in used_by_set:
            for ltag in aoi.local_tags.values():
                if ltag.data_type == dt.name:
                    used_by_set.add(aoi.name)
                    break

    result["used_by"] = sorted(used_by_set)

    # Count tags: scan controller and program tags
    tag_count = 0
    for tag in project.tags.values():
        if tag.data_type == dt.name:
            tag_count += 1

    for prog in project.programs.values():
        for tag in prog.tags.values():
            if tag.data_type == dt.name:
                tag_count += 1

    result["tag_count"] = tag_count

    return result
