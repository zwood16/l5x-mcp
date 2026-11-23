"""Tools for exploring L5X project files and overall structure.

This module provides functions to list L5X files, get project overviews,
and summarize project metadata, controllers, tasks, programs, and components.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any

from l5x_mcp.registry import L5XError, ProjectRegistry
from l5x_mcp.serialize import compact, first_line


def _get_root_attributes(path: Path) -> dict[str, str]:
    """Extract TargetType and TargetName from L5X root element.

    Uses iterparse to avoid loading entire file, stopping at first start event.

    Args:
        path: Path to .L5X file.

    Returns:
        Dict with 'TargetType' and 'TargetName' keys.

    Raises:
        L5XError: If parsing fails or attributes not found.
    """
    try:
        for _event, elem in ET.iterparse(str(path), events=["start"]):
            if elem.tag.endswith("RSLogix5000Content"):
                return {
                    "target_type": elem.attrib.get("TargetType", "Unknown"),
                    "target_name": elem.attrib.get("TargetName", "Unknown"),
                }
        raise L5XError(f"No RSLogix5000Content element found in {path}")
    except Exception as e:
        if isinstance(e, L5XError):
            raise
        raise L5XError(f"Failed to parse {path}: {e}") from e


def list_l5x_files(
    registry: ProjectRegistry, subdir: str | None = None
) -> dict[str, Any]:
    """List all .L5X files under the registry root with fast metadata.

    Returns file paths, sizes, modification times, and target type/name
    (parsed without full load). Errors are included per-file rather than
    raising, to ensure the LLM sees all available files.

    Args:
        registry: ProjectRegistry to discover from.
        subdir: Optional subdirectory to search within root.

    Returns:
        Dict with keys:
        - root: Absolute root directory path.
        - files: List of dicts with keys: path, size_bytes, modified (ISO-8601),
                 target_type, target_name. Per-file errors go in "error" key.
                 "output": true marks files in the write tools' output folder
                 (skipped by auto-discovery of the source project).
    """
    files_list: list[dict[str, Any]] = []
    discovered = registry.discover(subdir)

    for file_path in discovered:
        entry: dict[str, Any] = {"path": registry.relpath(file_path)}
        if registry.is_output(file_path):
            entry["output"] = True

        try:
            stat = file_path.stat()
            entry["size_bytes"] = stat.st_size

            # ISO-8601 local time for modification
            mtime = datetime.fromtimestamp(stat.st_mtime)
            entry["modified"] = mtime.isoformat()

            # Parse root attributes
            root_attrs = _get_root_attributes(file_path)
            entry["target_type"] = root_attrs["target_type"]
            entry["target_name"] = root_attrs["target_name"]

        except Exception as e:
            entry["error"] = str(e)

        files_list.append(entry)

    return {
        "root": str(registry.root),
        "files": files_list,
    }


def project_overview(
    registry: ProjectRegistry, path: str | None = None
) -> dict[str, Any]:
    """Get a comprehensive overview of a project structure and metadata.

    Works on full projects and component exports (AOI, Program, Module, Routine,
    Rung, DataType, Tag). Returns controller metadata (None for context), counts,
    tasks, programs, unscheduled programs, AOIs, data types, and modules.

    Args:
        registry: ProjectRegistry to load from.
        path: Project file path (None for auto-discovery).

    Returns:
        Dict with keys:
        - file: Relative path to project file.
        - target_type: "Controller", "AddOnInstructionDefinition", etc.
        - target_name: Name of target (omitted when empty, e.g. some Rung exports).
        - is_component_export: True if this is a context export.
        - controller: Dict with name, processor_type, firmware (e.g., "37.11"),
                      project_creation_date, last_modified_date, project_sn,
                      is_safety_controller, safety_level (if safety). None for
                      context exports.
        - counts: Dict with data_types, aois, modules, controller_tags,
                  module_io_tags (module I/O tag references, e.g. "Local:1:I";
                  these are not Logix tags and are not in controller_tags),
                  programs, tasks, routines.
        - tasks: List of dicts with name, type, rate, priority, watchdog,
                 inhibited (only if True), description (first_line),
                 programs (list of scheduled program names).
        - unscheduled_programs: List of program names not in any task.
        - programs: List of dicts with name, main_routine, disabled (only if True),
                    routine_count, tag_count.
        - aois: List of strings "Name vX.Y" with revision if available;
          source-protected AOIs end with " (protected)" and are counted in counts.
        - data_types: List of data type names.
        - modules: List of dicts with name, catalog_number.
    """
    resolved_path, project = registry.get_with_path(path)

    # Build controller info (None for context exports)
    controller_info = None
    if project.controller and not project.controller.is_context:
        c = project.controller
        firmware = None
        if c.major_rev is not None and c.minor_rev is not None:
            firmware = f"{c.major_rev}.{c.minor_rev}"

        controller_info = compact(
            {
                "name": c.name,
                "processor_type": c.processor_type,
                "firmware": firmware,
                "project_creation_date": c.project_creation_date,
                "last_modified_date": c.last_modified_date,
                "project_sn": c.project_sn,
                "is_safety_controller": c.is_safety_controller,
                "safety_level": c.safety_info.safety_level if c.safety_info else None,
            }
        )

    # Count routines across all programs
    routine_count = sum(
        len(prog.routines) + len(prog.protected_routines)
        for prog in project.programs.values()
    )

    # Count controller-scoped tags (module I/O tags are not counted here)
    controller_tags_count = len(project.controller_tags)

    # Count module I/O tags (their global names contain ':', e.g. "Local:1:I")
    module_io_tags_count = sum(1 for name in project.tags if ":" in name)

    # Build tasks list
    tasks_list = []
    scheduled_program_set = set()
    for _task_name, task in project.tasks.items():
        scheduled_program_set.update(task.scheduled_program_names)
        tasks_list.append(
            compact(
                {
                    "name": task.name,
                    "type": task.type_,
                    "rate": task.rate,
                    "priority": task.priority,
                    "watchdog": task.watchdog,
                    "inhibited": task.inhibit_task if task.inhibit_task else None,
                    "description": first_line(task.description),
                    "programs": list(task.scheduled_program_names),
                }
            )
        )

    # Build programs list
    programs_list = []
    for _prog_name, prog in project.programs.items():
        programs_list.append(
            compact(
                {
                    "name": prog.name,
                    "main_routine": prog.main_routine_name,
                    "disabled": prog.disabled if prog.disabled else None,
                    "routine_count": len(prog.routines) + len(prog.protected_routines),
                    "tag_count": len(prog.tags),
                }
            )
        )

    # Build unscheduled programs list
    unscheduled = [
        name for name in project.programs if name not in scheduled_program_set
    ]

    # Build AOIs list with revision info
    aois_list = []
    for aoi_name, aoi in project.aois.items():
        aoi_str = aoi_name
        if aoi.revision:
            aoi_str = f"{aoi_name} v{aoi.revision}"
        aois_list.append(aoi_str)
    for aoi_name, protected in project.protected_aois.items():
        aoi_str = (
            f"{aoi_name} v{protected.revision}" if protected.revision else aoi_name
        )
        aois_list.append(f"{aoi_str} (protected)")

    # Build data types list
    data_types_list = list(project.data_types.keys())

    # Build modules list
    modules_list = []
    for _mod_name, mod in project.modules.items():
        modules_list.append(
            {
                "name": mod.name,
                "catalog_number": mod.catalog_number,
            }
        )

    return compact(
        {
            "file": registry.relpath(resolved_path),
            "target_type": project.target_type,
            "target_name": project.target_name,
            "is_component_export": project.controller.is_context
            if project.controller
            else False,
            "controller": controller_info,
            "counts": {
                "data_types": len(project.data_types),
                "aois": len(project.aois) + len(project.protected_aois),
                "modules": len(project.modules),
                "controller_tags": controller_tags_count,
                "module_io_tags": module_io_tags_count,
                "programs": len(project.programs),
                "tasks": len(project.tasks),
                "routines": routine_count,
            },
            "tasks": tasks_list,
            "unscheduled_programs": unscheduled,
            "programs": programs_list,
            "aois": aois_list,
            "data_types": data_types_list,
            "modules": modules_list,
        }
    )
