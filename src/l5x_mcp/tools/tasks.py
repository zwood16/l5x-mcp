"""Tools for exploring tasks in L5X projects.

This module provides functions to list and get detailed information about
tasks, including their type, scheduling, watchdog settings, and programs.
"""

from __future__ import annotations

from typing import Any

from l5x_mcp.registry import ProjectRegistry, lookup
from l5x_mcp.serialize import compact, first_line


def list_tasks(registry: ProjectRegistry, path: str | None = None) -> dict[str, Any]:
    """List all tasks in a project with basic metadata.

    Returns task name, type, rate, priority, watchdog, inhibited flag
    (if true), description (first line), and scheduled programs.

    Args:
        registry: ProjectRegistry to load from.
        path: Project file path (None for auto-discovery).

    Returns:
        Dict with keys:
        - file: Relative path to project file.
        - tasks: List of dicts with name, type, rate, priority, watchdog,
                 inhibited (only if True), description (first_line),
                 programs (list of scheduled program names).
    """
    resolved_path, project = registry.get_with_path(path)

    tasks_list = []
    for _task_name, task in project.tasks.items():
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

    return {
        "file": registry.relpath(resolved_path),
        "tasks": tasks_list,
    }


def get_task(
    registry: ProjectRegistry, name: str, path: str | None = None
) -> dict[str, Any]:
    """Get detailed information about a specific task.

    Returns name, description, type, rate, priority, watchdog, disable_update_outputs,
    inhibit_task, class, is_safety, and event_info (if present for EVENT tasks).
    Scheduled programs include their main_routine, disabled flag, and routine count.

    Args:
        registry: ProjectRegistry to load from.
        name: Task name (case-insensitive).
        path: Project file path (None for auto-discovery).

    Returns:
        Dict with keys:
        - file: Relative path to project file.
        - name: Task name.
        - description: Full description.
        - type: Task type (CONTINUOUS, PERIODIC, EVENT, etc.).
        - rate: Rate in ms for periodic tasks, or None.
        - priority: Priority number.
        - watchdog: Watchdog timeout in ms.
        - disable_update_outputs: Boolean.
        - inhibit_task: Boolean.
        - class: Task class (Standard, Safety).
        - is_safety: Boolean.
        - event_info: Dict with event_trigger, enable_timeout, and any extra
                      attributes (only present if task is EVENT type).
        - scheduled_programs: List of dicts with name, main_routine, disabled
                              (only if True), routine_count.

    Raises:
        ItemNotFoundError: If task not found.
    """
    resolved_path, project = registry.get_with_path(path)

    # Look up task (case-insensitive)
    task = lookup(project.tasks, name, "Task")

    # Build scheduled programs list
    scheduled_programs = []
    for prog_name in task.scheduled_program_names:
        prog = project.programs.get(prog_name)
        if prog:
            scheduled_programs.append(
                compact(
                    {
                        "name": prog.name,
                        "main_routine": prog.main_routine_name,
                        "disabled": prog.disabled if prog.disabled else None,
                        "routine_count": len(prog.routines),
                    }
                )
            )

    # Build event_info if present
    event_info_dict = None
    if task.event_info:
        ei = task.event_info
        event_info_dict = compact(
            {
                "event_trigger": ei.event_trigger,
                "enable_timeout": ei.enable_timeout,
                **ei.extra_attributes,
            }
        )

    return compact(
        {
            "file": registry.relpath(resolved_path),
            "name": task.name,
            "description": task.description,
            "type": task.type_,
            "rate": task.rate,
            "priority": task.priority,
            "watchdog": task.watchdog,
            "disable_update_outputs": task.disable_update_outputs,
            "inhibit_task": task.inhibit_task,
            "class": task.class_,
            "is_safety": task.is_safety,
            "event_info": event_info_dict,
            "scheduled_programs": scheduled_programs,
        }
    )
