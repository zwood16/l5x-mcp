"""Tools for exploring Add-On Instructions (AOIs) in L5X projects.

This module provides functions to list AOIs, get detailed information about their
parameters and local tags, inspect routines, and find instances of AOI calls in code.
"""

from __future__ import annotations

import re
from typing import Any

from l5x_mcp.registry import ProjectRegistry, lookup
from l5x_mcp.serialize import compact, first_line, tag_summary


def list_aois(registry: ProjectRegistry, path: str | None = None) -> dict[str, Any]:
    """List all Add-On Instructions in a project with basic metadata.

    Returns name, revision, description (first line), parameter_count,
    and routine names.

    Args:
        registry: ProjectRegistry to load from.
        path: Optional path to a specific L5X file. Defaults to auto-detecting.

    Returns:
        A dict with "file" key and "aois" list, each with:
        - name: The AOI name.
        - revision: The revision string (e.g. "1.2").
        - description: First line of description, max 200 chars (omitted if empty).
        - parameter_count: Number of parameters.
        - routines: List of routine names.

    Raises:
        L5XError: If the project cannot be loaded.
    """
    resolved_path, project = registry.get_with_path(path)

    aois_list = []
    for aoi in project.aois.values():
        item = {
            "name": aoi.name,
            "revision": aoi.revision,
            "parameter_count": len(aoi.parameters),
            "routines": list(aoi.routines.keys()),
        }

        # Add description (first line only)
        desc = first_line(aoi.description, 200) if aoi.description else ""
        if desc:
            item["description"] = desc

        aois_list.append(compact(item))

    return {
        "file": registry.relpath(resolved_path),
        "aois": aois_list,
    }


def get_aoi(
    registry: ProjectRegistry,
    name: str,
    include_logic: bool = False,
    path: str | None = None,
) -> dict[str, Any]:
    """Get detailed information about an Add-On Instruction.

    Returns AOI metadata, parameters, local tags, routines, call signature,
    and optionally the logic text of each routine.

    Args:
        registry: ProjectRegistry to load from.
        name: The AOI name to look up.
        include_logic: If True, include the "logic" dict with routine text.
        path: Optional path to a specific L5X file. Defaults to auto-detecting.

    Returns:
        A dict with:
        - file: The resolved file path.
        - name: The AOI name.
        - description: Full description (omitted if empty).
        - revision: The revision string.
        - revision_extension: Revision extension/note if available (omitted if empty).
        - created_date: Creation timestamp.
        - created_by: Author at creation.
        - edited_date: Last edit timestamp.
        - edited_by: Last editor.
        - software_revision: Studio/Logix software revision.
        - execute_prescan: True if executes on prescan.
        - execute_postscan: True if executes on postscan.
        - execute_enable_in_false: True if executes when enable-in is false.
        - parameters: List of parameter dicts, each with:
          - name, data_type, usage (Input/Output/InOut), required, visible
          - description (omitted if empty)
          - default_value (omitted if not available)
          - dimensions (omitted if not an array)
          - external_access (omitted if empty)
          - constant (True only if constant)
        - local_tags: List of local tag summaries using tag_summary().
        - routines: List of routine dicts, each with:
          - name, type (RLL/ST), rung_count (for RLL) or line_count (for ST)
        - call_signature: A string like
          "Debounce(DebounceTag, onDelay, offDelay, state)" showing the RLL
          instruction operand order (backing tag first, then REQUIRED visible
          parameters in definition order).
        - instances: List of instances (up to 50) where this AOI is called, each with:
          - container_type: "program" or "aoi"
          - container: Program or AOI name
          - routine: Routine name
          - rung: Rung index (for RLL routines)
          - line: Line index (for ST routines)
        - instance_count: Total count of AOI instances found (may exceed 50).
        - logic: (only if include_logic=True) A dict mapping routine names to their
          as_text() logic output.

    Raises:
        L5XError: If the project cannot be loaded.
        ItemNotFoundError: If the AOI is not found.
    """
    resolved_path, project = registry.get_with_path(path)

    aoi = lookup(project.aois, name, "Add-On Instruction")

    result = {
        "file": registry.relpath(resolved_path),
        "name": aoi.name,
        "revision": aoi.revision,
    }

    # Add description (full text, not truncated)
    if aoi.description:
        result["description"] = aoi.description

    # Add revision_extension if available (extra_attributes)
    try:
        if hasattr(aoi, "_element") and aoi._element is not None:
            revision_ext = aoi._element.get("RevisionExtension")
            if revision_ext:
                result["revision_extension"] = revision_ext
    except Exception:
        pass

    # Add timestamps and authors
    result["created_date"] = aoi.created_date
    result["created_by"] = aoi.created_by
    result["edited_date"] = aoi.edited_date
    result["edited_by"] = aoi.edited_by
    result["software_revision"] = aoi.software_revision

    # Add execution flags
    result["execute_prescan"] = aoi.execute_prescan
    result["execute_postscan"] = aoi.execute_postscan
    result["execute_enable_in_false"] = aoi.execute_enable_in_false

    # Build parameters list
    parameters_list = []
    required_param_names = []  # For call_signature

    for param_name in aoi.parameters:
        param = aoi.parameters[param_name]

        param_dict = {
            "name": param.name,
            "data_type": param.data_type,
            "usage": param.usage,
            "required": param.required,
            "visible": param.visible,
        }

        # Add description
        if param.description:
            param_dict["description"] = param.description

        # Add min/max
        if param.min is not None:
            param_dict["min"] = param.min
        if param.max is not None:
            param_dict["max"] = param.max

        # Add external_access
        if param.external_access:
            param_dict["external_access"] = param.external_access

        # Add radix if present
        if param.radix:
            param_dict["radix"] = param.radix

        # Try to get dimensions from element
        try:
            if hasattr(param, "_element") and param._element is not None:
                dims = param._element.get("Dimensions")
                if dims:
                    param_dict["dimensions"] = dims
        except Exception:
            pass

        parameters_list.append(compact(param_dict))

        # Track required visible parameters for call_signature
        if param.required and param.visible:
            required_param_names.append(param.name)

    result["parameters"] = parameters_list

    # Build local_tags list using tag_summary
    local_tags_list = []
    for ltag in aoi.local_tags.values():
        local_tags_list.append(tag_summary(ltag))

    result["local_tags"] = local_tags_list

    # Build routines list
    routines_list = []
    for routine_name in aoi.routines:
        routine = aoi.routines[routine_name]

        routine_dict = {
            "name": routine.name,
            "type": routine.type_,
        }

        # Add rung_count for RLL or line_count for ST
        if routine.type_ == "RLL" and hasattr(routine, "rungs"):
            routine_dict["rung_count"] = len(routine.rungs)
        elif routine.type_ == "ST" and hasattr(routine, "st_code"):
            # Count lines in ST code
            st_text = routine.st_code
            if st_text:
                routine_dict["line_count"] = len(st_text.splitlines())

        routines_list.append(routine_dict)

    result["routines"] = routines_list

    # Build call_signature: "AOIName(InstanceTag, RequiredParam1, RequiredParam2, ...)"
    # The backing tag (instance) is first, then required visible parameters in order
    call_sig_params = ["<instance>"] + required_param_names
    result["call_signature"] = f"{aoi.name}({', '.join(call_sig_params)})"

    # Find instances (calls to this AOI in program and nested AOI routines)
    instances_list = []
    instance_count = 0
    # Case-insensitive regex to match AOI calls (handles variable casing in Studio 5000)
    aoi_pattern = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(aoi.name) + r"\s*\(")

    # Scan program routines
    for prog in project.programs.values():
        for routine in prog.routines.values():
            # RLL rungs
            if routine.type_ == "RLL" and hasattr(routine, "rungs"):
                for rung_idx, rung in enumerate(routine.rungs):
                    rung_text = rung.text if hasattr(rung, "text") else str(rung)
                    if aoi_pattern.search(rung_text):
                        instance_count += 1
                        if len(instances_list) < 50:
                            instances_list.append(
                                {
                                    "container_type": "program",
                                    "container": prog.name,
                                    "routine": routine.name,
                                    "rung": rung_idx,
                                }
                            )
            # ST lines
            elif (
                routine.type_ == "ST"
                and hasattr(routine, "st_code")
                and routine.st_code
            ):
                for line_idx, line in enumerate(routine.st_code.splitlines()):
                    if aoi_pattern.search(line):
                        instance_count += 1
                        if len(instances_list) < 50:
                            instances_list.append(
                                {
                                    "container_type": "program",
                                    "container": prog.name,
                                    "routine": routine.name,
                                    "line": line_idx,
                                }
                            )

    # Scan nested AOI routines (but skip this AOI's own routines)
    for other_aoi in project.aois.values():
        if other_aoi.name == aoi.name:
            continue
        for routine in other_aoi.routines.values():
            # RLL rungs
            if routine.type_ == "RLL" and hasattr(routine, "rungs"):
                for rung_idx, rung in enumerate(routine.rungs):
                    rung_text = rung.text if hasattr(rung, "text") else str(rung)
                    if aoi_pattern.search(rung_text):
                        instance_count += 1
                        if len(instances_list) < 50:
                            instances_list.append(
                                {
                                    "container_type": "aoi",
                                    "container": other_aoi.name,
                                    "routine": routine.name,
                                    "rung": rung_idx,
                                }
                            )
            # ST lines
            elif (
                routine.type_ == "ST"
                and hasattr(routine, "st_code")
                and routine.st_code
            ):
                for line_idx, line in enumerate(routine.st_code.splitlines()):
                    if aoi_pattern.search(line):
                        instance_count += 1
                        if len(instances_list) < 50:
                            instances_list.append(
                                {
                                    "container_type": "aoi",
                                    "container": other_aoi.name,
                                    "routine": routine.name,
                                    "line": line_idx,
                                }
                            )

    result["instances"] = instances_list
    result["instance_count"] = instance_count

    # Add logic if requested
    if include_logic:
        logic_dict = {}
        for routine_name in aoi.routines:
            routine = aoi.routines[routine_name]
            if hasattr(routine, "as_text"):
                try:
                    logic_dict[routine_name] = routine.as_text()
                except Exception:
                    logic_dict[routine_name] = None
        result["logic"] = logic_dict

    return result
