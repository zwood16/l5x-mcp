# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An MCP server (stdio) that exposes Rockwell Studio 5000 `.L5X` project exports to LLM agents as compact JSON tool results. Parsing is done by `py_l5x` (the author's own library, pinned to a GitHub release wheel via `[tool.uv.sources]` in `pyproject.toml`). Only RLL and ST routine logic is parsed; FBD/SFC are recognized but return an "unsupported" note. Write tools (enabled unless `--read-only` / `L5X_MCP_READ_ONLY`) edit projects and create Import Component files through py_l5x's write API.

## Commands

```bash
uv sync                                   # install (incl. dev group)
uv run pytest                             # all tests
uv run pytest tests/test_tools_tags.py::test_name   # single test
uv run ruff check src tests               # lint (E, F, I, UP, B, SIM; line length 88)
uv run ruff format src tests              # format
uv run l5x-mcp --root tests/fixtures      # run the server manually (add --read-only for read tools only)
```

## Architecture

- **Tool functions are plain functions** in `src/l5x_mcp/tools/*.py` with signature `fn(registry: ProjectRegistry, ..., path: str | None = None) -> dict`. They are unit-tested directly against `tests/fixtures/` using the session-scoped `registry` fixture in `tests/conftest.py`.
- **`server.py` wires them up.** A tool is exposed only if it is listed in `TOOLS`. `bind_registry` strips the `registry` parameter from the signature *and* from the docstring (`_strip_registry_doc`). The docstring becomes the LLM-facing tool description, so write it for the model. Results are serialized as single-line compact JSON. With `--structured-output` / `L5X_MCP_STRUCTURED_OUTPUT`, the result is also returned as `structured_content`. `INSTRUCTIONS` in `server.py` is the server-level prompt sent to clients.
- **Errors:** only `L5XError` subclasses (in `registry.py`) are turned into `ToolError`s that the model sees. Any other exception is hidden from the model. Raise `L5XError`/`ItemNotFoundError` for user-facing failures. Use `registry.lookup()` for name lookups: it tries an exact match, then a unique case-insensitive match, and on failure lists the available names.
- **`ProjectRegistry`** discovers `.L5X` files recursively under the root, auto-selects the file when exactly one exists, and caches parsed projects keyed by (mtime_ns, size), so saves from Studio 5000 are picked up automatically. Responses include `file` as a root-relative path via `registry.relpath`.
- **Operand pipeline** (used by `get_routine_logic` and `get_tag`):
  `operands.py` (pure text: extract candidate operands from RLL/ST) → `operand_paths.py` (parse `\Prog.tag.m[1,2].3` / `Local:1:I.Pt00.Data`, then walk the py_l5x value tree) → `operand_resolver.py` (Logix scoping: program tags → controller → module I/O; AOIs see only their params/locals; anything unresolvable maps to `None`).
- **`serialize.py`** converts py_l5x tags and value nodes to JSON, using isinstance dispatch against the py_l5x 0.3.x class model, with depth/element limits that flag truncation. It deliberately raises on unknown classes or missing attributes instead of silently dropping data. Expect to update it when bumping `py_l5x`.
- **Output size is a design constraint.** `serialize.compact()` drops empty/None fields, and `first_line()` trims descriptions. `get_routine_logic` and `get_aoi(include_logic=True)` bound the *whole* response to `max_chars` (via the size-budget helpers in `tools/programs.py`) and return `truncated` / `next_start_rung` for pagination. Keep new tools within the same budget conventions.

## Write tools

- `server.py` registers `WRITE_TOOLS` (annotated non-read-only) unless `read_only`; `EDIT_INSTRUCTIONS` adds the editing section to the server prompt.
- **Never modify the source.** Every write tool goes through `editing.Edit.open(registry, path, output_path, overwrite)` → change `edit.project` inside `edit_errors(...)` → `edit.save(summary)`. `Edit.open` loads a *fresh* project (the registry cache is shared with read tools, so never mutate it) and `resolve_output` enforces: `output_path` required, inside the root, `.L5X`, not the source, and exists only with `overwrite`. Writes are atomic. Component tools (`components.py`) treat `context_path` as the guarded source.
- `edit_errors` turns py_l5x's `ValueError`/`KeyError`/`TypeError`/`IndexError` into `L5XError` so the model sees them.
- Specs: `specs.py` TypedDicts (pydantic `extra="forbid"`) are the tool schemas. `to_py_spec` / `from_py_spec` convert to and from py_l5x specs (`type_`→`type`, `class_`→`program_class`; defaults omitted). `get_spec` output must round-trip through `replace_*` unchanged.
- Renames/removals that py_l5x doesn't propagate into logic report the remaining `references` (via `find_references` on the written file).

## SDK verification and golden fixtures

`tools/sdk/` (see its README) generates the cases in `tests/golden_cases.py` with the real tool functions, imports them into Studio 5000 v37 and v38 on the Windows VM through the Logix Designer SDK, builds, and compares Studio's re-exports. Only verified outputs are promoted to `tests/golden/`, with sha256s in `VERIFIED.json`. `tests/test_golden.py` regenerates every case and asserts the bytes are identical, so **any change to generated output requires re-running the harness**. pytest must never import the SDK or call the VM.

## Tests

`tests/test_server.py` runs end-to-end through a real MCP `Client`. It checks that the tool list matches `TOOLS` and that no schema leaks `registry`. `tests/fixtures/` holds sample exports copied from the py_l5x repo: `example.L5X` is the main full project, and the others are component exports (AOI, program, routine, rung, module, UDT). Because the fixtures dir holds several files, tests must pass `path=`. Write-tool tests use the `editable` fixture (a `ProjectRegistry` over a tmp copy of the fixtures).

## Launch-directory gotcha

The server root is `--root` > `L5X_MCP_ROOT` > cwd. Client configs should use `uv run --project <repo> --no-sync l5x-mcp`, not `uv --directory`, which changes cwd to the server repo. `--root` rejects unexpanded `${...}` variables by design.
