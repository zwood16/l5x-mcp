"""MCP server exposing py_l5x project data to LLM agents as tools.

Read tools are always registered. Write tools (which save edited copies of a
project or create import files) are registered unless the server runs with
``read_only=True``.
"""

from __future__ import annotations

import functools
import inspect
import json
from collections.abc import Callable
from typing import Any, get_type_hints

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from l5x_mcp.registry import DEFAULT_OUTPUT_DIR, L5XError, ProjectRegistry
from l5x_mcp.tools import (
    aois,
    components,
    datatypes,
    definitions,
    edit_logic,
    edit_tags,
    modules,
    programs,
    project,
    search,
    tags,
    tasks,
)

SERVER_NAME = "l5x-mcp"

_READ_ONLY_OPENING = """\
Read-only access to Rockwell Automation Studio 5000 Logix Designer projects exported as
.L5X (XML) files. Prefer these tools over reading the raw .L5X XML: the files are large
and the tools return compact, structured summaries.

"""

_EDIT_OPENING = """\
Access to Rockwell Automation Studio 5000 Logix Designer projects exported as .L5X
(XML) files. Prefer the read tools over reading the raw .L5X XML: the files are large
and the tools return compact, structured summaries.

"""

_SHARED_BODY = """\
Vocabulary: a controller runs Tasks (continuous/periodic/event) which schedule Programs.
Programs contain program-scoped Tags and Routines (RLL = ladder rungs, ST = structured
text). Controller-scoped tags are global. UDTs are user-defined data types; AOIs are
Add-On Instructions (reusable instructions with parameters, local tags and logic).
Modules are the I/O tree (local chassis + networked devices); module I/O tags such as
Local:1:I are listed with scope="module_io".

The .L5X file is regenerated whenever the engineer saves the project; tools always read
the latest version on disk. Every project tool accepts an optional `path` (absolute or
relative to the server root); it may be omitted when exactly one .L5X file exists.

Suggested workflow: list_l5x_files -> project_overview -> list_programs / list_routines
-> get_routine_logic. Start with detail="logic" to skim a routine, detail="outline" to
read rung comments, and follow next_start_rung when truncated. The operands map says
what each operand means; use get_tag, get_data_type and get_aoi for deeper detail.
Use find_references and instruction_usage for cross-references.
"""

_EDIT_SECTION = """
Editing (write tools are enabled):
- Each write tool loads the project at path, applies one change and writes a NEW .L5X
  to output_path. The source file is never modified. output_path is required. A bare
  file name such as "step1.L5X" is written to {output_dir}/ under the server root;
  a path with a directory is relative to the root (and must stay inside it). Files in
  {output_dir}/ are skipped by auto-discovery, so path can still be omitted for the
  source project. Results give the root-relative file: pass it as the next path to
  chain edits. overwrite=true only replaces a file a write tool wrote earlier in this
  server session (and that is unchanged since); other existing files are never
  replaced.
- Replacing a UDT, AOI or program: get_spec returns the object as a spec in the form
  the add/replace tools accept; change that spec, then call the replace_* tool.
- create_*_file and export_component write Studio Import Component files; no project
  is modified. Import them in Studio 5000.
- Logic is not verified by these tools. Open the output in Studio 5000 to verify it.
  Use instructions valid for the project's version (v36+ uses MOVE, EQ, ... instead
  of MOV, EQU, ...). Logix ST has no TRUE/FALSE literals; use 1 and 0.
"""

INSTRUCTIONS = _READ_ONLY_OPENING + _SHARED_BODY
"""Server prompt when the server is read-only."""


def edit_instructions(output_dir: str = DEFAULT_OUTPUT_DIR) -> str:
    """Return the server prompt for write mode.

    Args:
        output_dir: Root-relative output folder to mention in the prompt.

    Returns:
        The full instructions text.
    """
    return (
        _EDIT_OPENING + _SHARED_BODY + _EDIT_SECTION.replace("{output_dir}", output_dir)
    )


EDIT_INSTRUCTIONS = edit_instructions()
"""Server prompt when write tools are enabled (default output folder)."""

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
    definitions.get_spec,
]

WRITE_TOOLS: list[Callable[..., Any]] = [
    edit_tags.add_tags,
    edit_tags.remove_tags,
    edit_tags.rename_tag,
    edit_tags.set_tag_values,
    edit_tags.update_tag,
    edit_logic.add_routine,
    edit_logic.remove_routine,
    edit_logic.rename_routine,
    edit_logic.add_rungs,
    edit_logic.replace_rung,
    edit_logic.remove_rungs,
    edit_logic.set_st_lines,
    definitions.add_data_type,
    definitions.replace_data_type,
    definitions.rename_data_type,
    definitions.remove_data_type,
    definitions.add_aoi,
    definitions.replace_aoi,
    definitions.rename_aoi,
    definitions.remove_aoi,
    definitions.add_program,
    definitions.replace_program,
    definitions.rename_program,
    definitions.remove_program,
    definitions.schedule_program,
    definitions.set_description,
    components.export_component,
    components.create_data_type_file,
    components.create_aoi_file,
    components.create_program_file,
    components.create_tags_file,
    components.create_routine_file,
    components.create_rungs_file,
]

_READ_ONLY = ToolAnnotations(
    readOnlyHint=True, idempotentHint=True, openWorldHint=False
)

_WRITE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
)


def _compact_json(result: Any) -> str:
    """Serialize a tool result as single-line JSON (no indentation or spaces)."""
    return json.dumps(result, separators=(",", ":"), ensure_ascii=False)


def bind_registry(
    fn: Callable[..., Any],
    registry: ProjectRegistry,
    *,
    structured_output: bool = False,
) -> Callable[..., Any]:
    """Wrap ``fn(registry, ...)`` as ``tool(...)`` with an introspectable signature.

    The wrapper returns one compact JSON text block. With ``structured_output`` it
    also sets ``structured_content`` to the result dict, which matches the output
    schema derived from the dict return annotation.
    """
    hints = get_type_hints(fn)
    sig = inspect.signature(fn)
    params = list(sig.parameters.values())
    if not params or params[0].name != "registry":
        raise TypeError(f"{fn.__name__} must take `registry` as its first parameter")
    params = [p.replace(annotation=hints.get(p.name, p.annotation)) for p in params[1:]]

    @functools.wraps(fn)
    def tool(**kwargs: Any) -> Any:
        try:
            result = fn(registry, **kwargs)
        except L5XError as exc:
            # ToolError messages reach the model; other exceptions are hidden.
            raise ToolError(str(exc)) from exc
        text = _compact_json(result)
        if structured_output:
            return CallToolResult(
                content=[TextContent(type="text", text=text)],
                structured_content=result,
            )
        return text

    return_annotation = hints.get("return", sig.return_annotation)
    tool.__signature__ = sig.replace(  # type: ignore[attr-defined]
        parameters=params,
        return_annotation=return_annotation if structured_output else str,
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


def create_server(
    registry: ProjectRegistry | None = None,
    structured_output: bool = False,
    read_only: bool = False,
) -> MCPServer:
    """Build the MCP server with the L5X tools registered.

    By default each tool returns one compact JSON text block. With
    ``structured_output=True`` tools also advertise an output schema and return
    the same data as ``structured_content``.

    Write tools (``WRITE_TOOLS``) are registered unless ``read_only=True``, in
    which case only the read tools (``TOOLS``) are exposed.
    """
    registry = registry or ProjectRegistry()
    if read_only:
        server = MCPServer(name=SERVER_NAME, instructions=INSTRUCTIONS)
        groups = [(TOOLS, _READ_ONLY)]
    else:
        server = MCPServer(
            name=SERVER_NAME,
            instructions=edit_instructions(registry.relpath(registry.output_dir)),
        )
        groups = [(TOOLS, _READ_ONLY), (WRITE_TOOLS, _WRITE)]
    for tool_list, tool_annotations in groups:
        for fn in tool_list:
            server.add_tool(
                bind_registry(fn, registry, structured_output=structured_output),
                annotations=tool_annotations,
                structured_output=structured_output,
            )
    return server
