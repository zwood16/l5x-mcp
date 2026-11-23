"""Tools for exploring Add-On Instructions (AOIs) in L5X projects.

This module provides functions to list AOIs, get detailed information about their
parameters and local tags, inspect routines, and find instances of AOI calls in code.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from py_l5x import AOIParameter, BoolNode, FloatNode, IntegerNode, TagNode
from py_l5x.parsers.routine import Routine

from l5x_mcp.registry import ProjectRegistry, lookup, protected_aoi_name
from l5x_mcp.serialize import compact, first_line, tag_summary
from l5x_mcp.tools.programs import (
    MAX_CHARS_DEFAULT,
    OutputBudget,
    json_size,
    validate_max_chars,
)


def list_aois(registry: ProjectRegistry, path: str | None = None) -> dict[str, Any]:
    """List all Add-On Instructions in a project with basic metadata.

    Returns name, revision, description (first line), parameter_count,
    and routine names. Source-protected AOIs (definition and logic not in the
    file) are listed with protected=true, parameter_count and their metadata.

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
        Source-protected AOIs have name, protected (true), revision,
        parameter_count and description (when the file shows them).

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

    for protected in project.protected_aois.values():
        item = {
            "name": protected.name,
            "protected": True,
            "revision": protected.revision,
            "parameter_count": len(protected.parameters),
            "description": first_line(protected.description, 200),
        }
        aois_list.append(compact(item))

    return {
        "file": registry.relpath(resolved_path),
        "aois": aois_list,
    }


def _parameter_dimensions(param: AOIParameter) -> list[int]:
    """Return the array dimensions of an AOI parameter, or [] for a scalar.

    Read from the raw ``Dimensions`` attribute (e.g. ``"20"`` or ``"2,3"``)
    because InOut parameters are plain :class:`AOIParameter` objects with no
    value tree to take dimensions from.

    Args:
        param: The AOI parameter.

    Returns:
        The dimensions as a list of ints.
    """
    raw = param.attributes.get("Dimensions", "")
    return [int(part) for part in raw.split(",") if part.strip()]


def _parameter_dict(param: AOIParameter) -> dict[str, Any]:
    """Serialize one AOI parameter for :func:`get_aoi`.

    Typed Input/Output parameters (value-carrying py_l5x classes) add
    engineering unit, min/max, and BOOL state labels. Plain parameters (InOut,
    EnableIn/EnableOut) do not have those, so the fields are omitted for them.

    Args:
        param: The AOI parameter.

    Returns:
        A compacted dict of parameter fields.
    """
    result: dict[str, Any] = {
        "name": param.name,
        "data_type": param.data_type,
        "usage": param.usage,
        "required": param.required,
        "visible": param.visible,
        "description": param.description,
        "radix": param.radix,
        "external_access": param.external_access,
        "dimensions": _parameter_dimensions(param),
    }
    if isinstance(param, TagNode):
        result["engineering_unit"] = param.engineering_unit
    if isinstance(param, (IntegerNode, FloatNode)):
        result["min"] = param.min
        result["max"] = param.max
    if isinstance(param, BoolNode):
        result["state0"] = param.state0
        result["state1"] = param.state1
    if param.constant:
        result["constant"] = True
    if comments := param.operand_comments:
        result["operand_comments"] = comments
    return compact(result)


_LOGIC_OVERHEAD = 320


def _logic_within_budget(
    routines: Mapping[str, Routine], max_chars: int
) -> tuple[dict[str, str], list[str]]:
    """Return routine logic text in order while the logic dict fits max_chars.

    Args:
        routines: The AOI's routines, keyed by name.
        max_chars: Size budget for the serialized logic dict.

    Returns:
        Tuple of (logic dict, names of the routines left out). Once one
        routine does not fit, it and all later routines are left out.
    """
    logic: dict[str, str] = {}
    names = list(routines)
    if max_chars <= json_size({}):
        return logic, names
    budget = OutputBudget(base_size=json_size({}), max_chars=max_chars)
    for index, routine in enumerate(routines.values()):
        text = routine.as_text()
        # Size of the "name":"text" member without the enclosing braces
        entry_size = json_size({routine.name: text}) - 2
        if not budget.fits(entry_size):
            return logic, names[index:]
        budget.add(entry_size)
        logic[routine.name] = text
    return logic, []


def _protected_aoi_result(file: str, aoi: Any) -> dict[str, Any]:
    """Build the get_aoi result of a source-protected AOI."""
    return compact(
        {
            "file": file,
            "name": aoi.name,
            "protected": True,
            "description": aoi.description,
            "revision": aoi.revision,
            "vendor": aoi.vendor,
            "class": aoi.class_,
            "signature_id": aoi.signature_id,
            "edited_date": aoi.edited_date,
            "software_revision": aoi.software_revision,
            "parameters": [_parameter_dict(p) for p in aoi.parameters.values()],
            "dependencies": aoi.dependency_names,
            "note": (
                "source-protected: its local tags and logic are encoded and not "
                "readable; parameters and tags of its type read normally."
            ),
        }
    )


def get_aoi(
    registry: ProjectRegistry,
    name: str,
    include_logic: bool = False,
    max_chars: int = MAX_CHARS_DEFAULT,
    path: str | None = None,
) -> dict[str, Any]:
    """Get detailed information about an Add-On Instruction.

    Returns AOI metadata, parameters, local tags, routines, call signature,
    and optionally the logic text of each routine.

    A source-protected AOI (listed by list_aois with protected=true) has no
    definition or logic in the file: the result is only name, protected,
    revision/vendor/class, signature_id, edited_date, software_revision,
    description, parameters (same fields as a normal AOI's) and dependencies
    when the file shows them, plus a note. Its local tags and logic are encoded;
    include_logic returns no logic for it.

    Args:
        registry: ProjectRegistry to load from.
        name: The AOI name to look up.
        include_logic: If True, include the "logic" dict with routine text.
        max_chars: Size budget (compact JSON chars, 1000-100000, default 8000)
            for the whole response. Routines are added to "logic" in order while
            they fit; the rest are listed in logic_omitted. Only used with
            include_logic.
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
          - description, radix, external_access (omitted if empty)
          - engineering_unit, min, max, state0, state1: only for typed
            Input/Output parameters that declare them (omitted if empty).
            InOut and EnableIn/EnableOut parameters never carry these.
          - dimensions: list of ints for an array parameter (omitted if scalar)
          - constant: True only if constant
          - operand_comments: map of operand to comment, e.g. per-bit labels
            {".0": "..."} or per-state labels {".FAULT.2": "..."} for an InOut
            parameter's member (omitted if none)
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
          - line: Line number (for ST routines)
        - instance_count: Total count of AOI instances found (may exceed 50).
        - logic: (only if include_logic=True) A dict mapping routine names to their
          as_text() logic output, so the response fits max_chars. Routines that do
          not fit are not included; their names are in logic_omitted, and a note
          says to fetch them with get_routine_logic(routine=..., aoi=...).

    Raises:
        L5XError: If the project cannot be loaded, or max_chars is invalid.
        ItemNotFoundError: If the AOI is not found.
    """
    validate_max_chars(max_chars)
    resolved_path, project = registry.get_with_path(path)

    if name not in project.aois and (protected := protected_aoi_name(project, name)):
        return _protected_aoi_result(
            registry.relpath(resolved_path), project.protected_aois[protected]
        )

    aoi = lookup(project.aois, name, "Add-On Instruction")

    result = {
        "file": registry.relpath(resolved_path),
        "name": aoi.name,
        "revision": aoi.revision,
    }

    # Add description (full text, not truncated)
    if aoi.description:
        result["description"] = aoi.description

    # Add revision_extension if available (undeclared XML attribute)
    revision_ext = aoi.extra_attributes.get("RevisionExtension")
    if revision_ext:
        result["revision_extension"] = revision_ext

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

    for param in aoi.parameters.values():
        parameters_list.append(_parameter_dict(param))

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
            elif routine.type_ == "ST" and routine.st_lines:
                for st_line in routine.st_lines:
                    line_idx = st_line.number
                    if aoi_pattern.search(st_line.text):
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
            elif routine.type_ == "ST" and routine.st_lines:
                for st_line in routine.st_lines:
                    line_idx = st_line.number
                    if aoi_pattern.search(st_line.text):
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

    # Add logic if requested, within the max_chars budget
    if include_logic:
        # The budget covers the whole response: reserve the non-logic part plus
        # room for the "logic" key, logic_omitted and the note.
        reserve = json_size(result) + _LOGIC_OVERHEAD + json_size(list(aoi.routines))
        logic, omitted = _logic_within_budget(aoi.routines, max_chars - reserve)
        result["logic"] = logic
        if omitted:
            result["logic_omitted"] = omitted
            result["note"] = (
                f"Logic for {len(omitted)} routine(s) exceeds max_chars={max_chars}. "
                f'Fetch each with get_routine_logic(routine=<name>, aoi="{aoi.name}").'
            )

    return result
