"""MCP server exposing py_l5x project data as read-only tools."""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from typing import Any, get_type_hints

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from l5x_mcp.registry import L5XError, ProjectRegistry
from l5x_mcp.tools import (
    aois,
    datatypes,
    modules,
    programs,
    project,
    search,
    tags,
    tasks,
)

SERVER_NAME = "l5x-mcp"

INSTRUCTIONS = """\
Read-only access to Rockwell Automation Studio 5000 Logix Designer projects exported as
.L5X (XML) files. Prefer these tools over reading the raw .L5X XML: the files are large
and the tools return compact, structured summaries.

Vocabulary: a controller runs Tasks (continuous/periodic/event) which schedule Programs.
Programs contain program-scoped Tags and Routines (RLL = ladder rungs, ST = structured
text). Controller-scoped tags are global. UDTs are user-defined data types; AOIs are
Add-On Instructions (reusable instructions with parameters, local tags and logic).
Modules are the I/O tree (local chassis + networked devices).

The .L5X file is regenerated whenever the engineer saves the project; tools always read
the latest version on disk. Every project tool accepts an optional `path` (absolute or
relative to the server root); it may be omitted when exactly one .L5X file exists.

Suggested workflow: list_l5x_files -> project_overview -> list_programs / list_routines
-> get_routine_logic, and get_tag / get_data_type / get_aoi to understand operands.
Use find_references to see where a tag or instruction is used across all logic.
"""

TOOLS: list[Callable[..., Any]] = [
    project.list_l5x_files,
    project.project_overview,
    tasks.list_tasks,
    tasks.get_task,
    programs.list_programs,
    programs.get_program,
    programs.list_routines,
    programs.get_routine_logic,
    tags.list_tags,
    tags.get_tag,
    datatypes.list_data_types,
    datatypes.get_data_type,
    aois.list_aois,
    aois.get_aoi,
    modules.list_modules,
    modules.get_module,
    search.find_references,
    search.instruction_usage,
]

_READ_ONLY = ToolAnnotations(
    readOnlyHint=True, idempotentHint=True, openWorldHint=False
)


def bind_registry(
    fn: Callable[..., Any], registry: ProjectRegistry
) -> Callable[..., Any]:
    """Wrap ``fn(registry, ...)`` as ``tool(...)`` with an introspectable signature."""
    hints = get_type_hints(fn)
    sig = inspect.signature(fn)
    params = list(sig.parameters.values())
    if not params or params[0].name != "registry":
        raise TypeError(f"{fn.__name__} must take `registry` as its first parameter")
    params = [p.replace(annotation=hints.get(p.name, p.annotation)) for p in params[1:]]

    @functools.wraps(fn)
    def tool(**kwargs: Any) -> Any:
        try:
            return fn(registry, **kwargs)
        except L5XError as exc:
            # ToolError messages reach the model; other exceptions are hidden.
            raise ToolError(str(exc)) from exc

    tool.__signature__ = sig.replace(  # type: ignore[attr-defined]
        parameters=params,
        return_annotation=hints.get("return", sig.return_annotation),
    )
    tool.__doc__ = _strip_registry_doc(inspect.getdoc(fn) or "")
    return tool


def _strip_registry_doc(doc: str) -> str:
    """Drop the internal ``registry`` argument from an LLM-facing docstring."""
    lines = doc.splitlines()
    out: list[str] = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("registry:"):
            indent = len(line) - len(line.lstrip())
            skipping = True
            continue
        if skipping:
            cur = len(line) - len(line.lstrip())
            if stripped and cur > indent:
                continue
            skipping = False
        out.append(line)
    return "\n".join(out)


def create_server(registry: ProjectRegistry | None = None) -> MCPServer:
    """Build the MCP server with every L5X tool registered."""
    registry = registry or ProjectRegistry()
    server = MCPServer(name=SERVER_NAME, instructions=INSTRUCTIONS)
    for fn in TOOLS:
        server.add_tool(bind_registry(fn, registry), annotations=_READ_ONLY)
    return server
