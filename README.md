# l5x-mcp

A personal project to add AI tools to my Studio 5000 workflow.

## What it is

This is a Model Context Protocol (MCP) server for Rockwell Automation Studio 5000 Logix Designer projects exported as `.L5X` (XML) files. It allows LLM coding agents (VS Code Copilot Chat, GitHub Copilot CLI) to explore project structure, list programs and routines, examine logic code, look up tags and data types, and find cross-references—without reading the large raw XML themselves.

It can also **edit projects and create components** (UDTs, AOIs, programs, routines, rungs, tags) as Studio import files. Write tools never modify their input: every edit is written to a new `.L5X` file. Run with `--read-only` to expose only the read tools (see [Write tools](#write-tools)).

**Important limitations:** This is work in progress. The underlying `py_l5x` parser currently supports **RLL (ladder rungs) and ST (structured text) routines only**. FBD (function block diagram) and SFC (sequential function chart) routines are recognized but their logic is not parsed; tools will return a note that these types are unsupported.

## Requirements

- Python 3.12 or later
- [uv](https://github.com/astral-sh/uv) (Python package manager)

The `py_l5x` parser is automatically downloaded from its GitHub release as a wheel via the `[tool.uv.sources]` configuration in `pyproject.toml` (source: https://github.com/zwood16/py_l5x).

## Install

Clone the repository and install dependencies:

```bash
git clone <repo-url>
cd l5x-mcp
uv sync
```

**Optional: global install** (puts `l5x-mcp` command on PATH):

```bash
uv tool install --editable /path/to/l5x-mcp
```

After this, you can run `l5x-mcp` from anywhere without the `uv run` prefix.

## How .L5X files are discovered

The server searches for `.L5X` files starting from a root directory:

1. **Root directory precedence:** `--root` CLI argument > `L5X_MCP_ROOT` environment variable > current working directory
2. **Recursive discovery:** Searches subdirectories recursively, skipping hidden directories, `node_modules/`, `__pycache__/`, and `venv/`
3. **Auto-selection:** When exactly one `.L5X` file exists, it is automatically used as the default; all tools accept an optional `path` argument to explicitly specify a file (absolute or relative to root)
4. **Auto-reload:** The server detects file changes (mtime and size) and re-parses the project automatically

The root is selected at server startup. It is the server process's working
directory, not the directory of the currently open editor or an independently
changing chat session. Restart the MCP server after changing its configuration.

When launching from a source checkout, use `uv run --project <server-repo>`,
**not** `uv --directory <server-repo> run`. `--project` selects the Python project
and its environment without changing the working directory inherited from the
client. `--directory` changes that directory to the server repository.
Run `uv sync` in the server repository before using the `--no-sync` examples below.

## Configure VS Code Copilot Chat

Choose where to register the server:

- **Across projects:** Run **MCP: Open User Configuration** from the VS Code
  Command Palette and add the server to the user configuration.
- **For one project:** Add the server to `.vscode/mcp.json` in your PLC project
  (create the file if it doesn't exist).

Both VS Code configuration locations use the `"servers"` top-level key. Merge
the following entry into any existing servers rather than replacing them.
This example uses a Windows source checkout; replace the server repository path
with yours:

```json
{
    "servers": {
        "l5x-mcp": {
            "type": "stdio",
            "command": "uv",
            "args": [
                "run",
                "--project",
                "path/to/this/project",
                "--no-sync",
                "l5x-mcp"
            ]
        }
    }
}
```

VS Code's stdio server `cwd` defaults to the workspace folder when run in a
workspace, so no `--root` or variable substitution is needed here. With no folder
open, or if a client supplies a different working directory, use a literal
`--root` path or `L5X_MCP_ROOT` instead.

The path after `--project` is always the **server repository**, not the PLC
project. You do not need to clone or install the server inside each PLC project.
With user-level registration, open another PLC project in VS Code and start the
server there; discovery uses that workspace's launch directory. This setup has
been manually confirmed to work with VS Code chat in a separate project.

`${workspaceFolder}` is a **VS Code configuration variable**, not an environment
variable or Python feature. VS Code supports it in its own MCP configuration,
but a different client or configuration scope may reject it or pass it literally.
The server cannot infer an editor workspace from that literal text. If you see an
environment-variable substitution error, remove the placeholder rather than
moving the same placeholder into `env`. The server reports unexpanded `${...}`
values in `--root` or `L5X_MCP_ROOT` as startup errors.

**Alternative (with global install):**

```json
{
    "servers": {
        "l5x": {
            "type": "stdio",
            "command": "l5x-mcp",
            "args": []
        }
    }
}
```

### Verify the VS Code setup

1. Open the PLC project folder containing your `.L5X` exports.
2. Save the MCP configuration and restart the server from VS Code's MCP controls.
3. Ask Copilot Chat to call `list_l5x_files`.
4. Check that the returned `root` is your PLC project folder and that `files`
   contains your exports.

If the root points to the server repository, check for an old `--directory`
argument. If it points to a fixed, unrelated folder, check for an explicit
`--root` argument or an inherited `L5X_MCP_ROOT` environment variable.

## Configure GitHub Copilot CLI

Edit `~/.copilot/mcp-config.json` (user-level) or `.mcp.json` (repo-level).
Use the `"mcpServers"` top-level key, not VS Code's `"servers"`. For a source
checkout, use the same working-directory-preserving launch:

```json
{
    "mcpServers": {
        "l5x": {
            "type": "local",
            "command": "uv",
            "args": [
                "run",
                "--project",
                "path/to/this/project",
                "--no-sync",
                "l5x-mcp"
            ],
            "tools": ["*"]
        }
    }
}
```

Launch Copilot CLI from your PLC project directory. With no explicit root,
the server searches the working directory supplied by the client. This launch
does not require `${workspaceFolder}` support. If globally installed, use
`"command": "l5x-mcp"` with `"args": []` instead.

For a fixed root independent of the client's working directory, append
`"--root", "Z:\\path\\to\\plc-project"` to the arguments, or set a literal
environment variable (the following example assumes a global installation):

```json
{
    "mcpServers": {
        "l5x": {
            "type": "local",
            "command": "l5x-mcp",
            "env": { "L5X_MCP_ROOT": "path/to/plc-project" },
            "tools": ["*"]
        }
    }
}
```

**Debugging:** Run `list_l5x_files` and inspect its `root` and `files` fields.
If `root` is not your PLC project directory, configure a literal override.
An existing `L5X_MCP_ROOT` environment variable takes precedence over the launch
directory; remove it if you want automatic working-directory discovery.
Absolute tool `path` arguments still work independently of the discovery root.

See the [VS Code MCP configuration reference](https://code.visualstudio.com/docs/agents/reference/mcp-configuration)
for client configuration formats, variables, and working-directory defaults.

## Output format

By default, every tool returns one compact JSON text block (no indentation or extra
spaces).

Add `--structured-output` to the server arguments, or set
`L5X_MCP_STRUCTURED_OUTPUT=1` (also `true`, `yes`, or `on`), to also return MCP
`structuredContent` and an output schema for each tool. The text block stays
compact. Clients that do not use structured content can ignore it. Restart the
server after changing this setting.

VS Code (`.vscode/mcp.json` or user configuration), flag in `args`:

```json
{
    "servers": {
        "l5x-mcp": {
            "type": "stdio",
            "command": "uv",
            "args": [
                "run",
                "--project",
                "path/to/this/project",
                "--no-sync",
                "l5x-mcp",
                "--structured-output"
            ]
        }
    }
}
```

GitHub Copilot CLI (`~/.copilot/mcp-config.json` or `.mcp.json`), flag set through `env`:

```json
{
    "mcpServers": {
        "l5x": {
            "type": "local",
            "command": "uv",
            "args": [
                "run",
                "--project",
                "path/to/this/project",
                "--no-sync",
                "l5x-mcp"
            ],
            "env": { "L5X_MCP_STRUCTURED_OUTPUT": "1" },
            "tools": ["*"]
        }
    }
}
```

## Tools Reference

| Tool Name             | Purpose                                                                                                                                         | Key Arguments                                                                                                                                  |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| **list_l5x_files**    | Discover .L5X files with size, mtime, target type and name                                                                                       | `subdir=None`                                                                                                                                  |
| **project_overview**  | Summarize controller, tasks, programs, AOIs, UDTs, modules and counts (including `module_io_tags`)                                              | `path=None`                                                                                                                                    |
| **list_tasks**        | List tasks with type, rate, priority, watchdog and scheduled programs                                                                            | `path=None`                                                                                                                                    |
| **get_task**          | Get task detail: type, rate, watchdog, event info, scheduled programs                                                                            | `name`, `path=None`                                                                                                                            |
| **list_programs**     | List programs: main routine, disabled/safety flags, routine and tag counts, scheduled task                                                      | `path=None`                                                                                                                                    |
| **get_program**       | Get program detail: routines, flags, tag_count; the tag list only with `include_tags=True` (otherwise a hint to use `list_tags`)               | `name`, `include_tags=False`, `path=None`                                                                                                      |
| **list_routines**     | List routines in a program or AOI with type and rung/line counts                                                                                 | `program=None`, `aoi=None`, `path=None`                                                                                                        |
| **get_routine_logic** | Get RLL rungs or ST lines. `detail`: `full`, `outline` (comments only) or `logic` (code only). Returns an `operands` map. Paged by `max_chars` budget (max 200 per call) | `routine`, `program=None`, `aoi=None`, `start_rung=None`, `end_rung=None`, `detail='full'`, `max_chars=8000`, `include_operands=True`, `include_values=False`, `path=None` |
| **list_tags**         | List tags in `scope`: `controller`, `module_io` (module I/O tags such as `Local:1:I`), or a program name; filter and paginate                    | `scope='controller'`, `name_contains=None`, `data_type=None`, `tag_type=None`, `limit=100`, `offset=0`, `path=None`                           |
| **get_tag**           | Get a tag, or the value at an operand path: members, `[i]`/`[i,j]`, bits, module I/O names, `\Program.Tag`. Follows aliases                    | `name`, `scope=None`, `max_depth=3`, `max_elements=32`, `path=None`                                                                            |
| **list_data_types**   | List user-defined data types (UDTs) with member counts and string flags                                                                         | `path=None`                                                                                                                                    |
| **get_data_type**     | Get UDT members with metadata, which UDTs/AOIs use it, and how many tags have this type                                                         | `name`, `path=None`                                                                                                                            |
| **list_aois**         | List Add-On Instructions with revision, parameter count and routine names                                                                       | `path=None`                                                                                                                                    |
| **get_aoi**           | Get AOI parameters (with `operand_comments`), local tags, routines, instances; optionally logic text within a `max_chars` budget                | `name`, `include_logic=False`, `max_chars=8000`, `path=None`                                                                                   |
| **list_modules**      | List I/O modules with `tag_prefix`, address, and a hierarchy `tree` (remote racks nested under their adapter)                                   | `path=None`                                                                                                                                    |
| **get_module**        | Get module detail: identity, ports, communications, `io_tags` (global names such as `ShopRobot:I`), children                                    | `name`, `include_data=False`, `max_depth=2`, `max_elements=32`, `path=None`                                                                    |
| **find_references**   | Find uses of a tag, instruction, or text in program and AOI logic. Comments are ignored for `tag`/`instruction` on ST                           | `query`, `kind='tag'` (`tag`/`instruction`/`text`), `program=None`, `include_aois=True`, `limit=200`, `path=None`                              |
| **instruction_usage** | Count instruction mnemonics used across all programs (or limit to one)                                                                          | `program=None`, `path=None`                                                                                                                    |

## Write tools

Write tools are enabled by default. Start the server with `--read-only` (or set
`L5X_MCP_READ_ONLY=1`, also `true`, `yes` or `on`) to register only the read tools.

Rules shared by every write tool:

- The source project (`path`) is **never modified**. The result is written to
  `output_path`, which is required, must end in `.L5X`, must be inside the server root,
  and must not be the source file. An existing output is only replaced with
  `overwrite=true`.
- To chain edits, pass the previous call's output as the next call's `path`.
- Edits are all-or-nothing: if any part fails, no file is written.
- Renames and removals of tags, routines and programs don't rewrite logic. The result
  lists the remaining `references` so they can be fixed. `rename_aoi` does rewrite call
  sites, and `rename_data_type` updates every tag, member and parameter of that type.
- Logic is only checked for balanced brackets and a trailing `;`. Undefined tags and
  wrong instructions show up when Studio verifies the project. Use instructions that
  exist in your version (v36+ uses `MOVE`, `EQ`, … instead of `MOV`, `EQU`, …).

UDTs, AOIs, programs and tags are described by JSON **specs**, whose fields are listed in
each tool's input schema. `get_spec` returns an existing object's spec in exactly the
form the add/replace tools accept, so the usual way to change an object is
`get_spec` → edit → `replace_*`.

| Tool | Purpose |
| --- | --- |
| **get_spec** (read-only) | Spec of an existing UDT, AOI, program, tag or routine |
| **add_tags** / **remove_tags** / **rename_tag** | Add base or alias tags (with values and operand comments), remove or rename tags |
| **set_tag_values** | Set values by operand path: scalars, structure members, array elements, strings, TIME |
| **update_tag** | Tag description, operand comments and operand metadata (units, min/max, states) |
| **add_routine** / **remove_routine** / **rename_routine** | Program routines (RLL or ST) |
| **add_rungs** / **replace_rung** / **remove_rungs** | Ladder rungs (insert, change text or comment, delete) |
| **set_st_lines** | Replace an ST routine's source |
| **add_data_type** / **replace_data_type** / **rename_data_type** / **remove_data_type** | UDTs. Replace migrates every instance by member name, the way Studio does |
| **add_aoi** / **replace_aoi** / **rename_aoi** / **remove_aoi** | AOIs. Replace migrates instances and protects call sites from signature changes |
| **add_program** / **replace_program** / **rename_program** / **remove_program** | Programs with tags and routines |
| **schedule_program** | Schedule, move or unschedule a program |
| **set_description** | Description of a program, routine, UDT or AOI |
| **export_component** | Write existing objects (UDT, AOI, program, routine, rungs, tags) as an Import Component file with their dependencies |
| **create_data_type_file** / **create_aoi_file** / **create_program_file** / **create_tags_file** / **create_routine_file** / **create_rungs_file** | Build a new component from a spec as an Import Component file. `context_path` supplies the UDTs, AOIs and tags it uses |

Generated files are verified against real Studio 5000 **v37 and v38** through the
harness in [`tools/sdk/`](tools/sdk/README.md). The verified outputs are kept as golden
test fixtures, so the test suite itself doesn't need Windows or Rockwell software.

## Suggested LLM workflow

1. **Explore the project:** `list_l5x_files` → `project_overview`
2. **Find relevant code:** `list_programs` / `list_routines`
3. **Skim logic:** `get_routine_logic` with `detail="logic"` (cheapest) for a first pass
4. **Read documentation:** `get_routine_logic` with `detail="outline"` for rung comments, or the default `detail="full"` for both. Follow `next_start_rung` when `truncated` is true.
5. **Understand operands:** the `operands` map in `get_routine_logic` describes each operand. For more detail use `get_tag` (including operand paths), `get_data_type`, or `get_aoi`.
6. **Find cross-references:** `find_references` for where a tag or instruction is used; `instruction_usage` for mnemonic counts
7. **Module I/O:** `list_tags(scope="module_io")`, `get_module`, and `get_tag` with names such as `Local:1:I.Pt00.Data`

### Tips

- **Operand paths:** `get_tag` resolves `Tag.Member[3].1` (element 3, bit 1 of a DINT member), multi-dimensional `[i,j]`, `\MainProgram.tag` for an explicit program, and module I/O names like `Local:1:I.Pt00.Data`. Alias tags report `alias_for`, `alias_chain`, and `resolved_target`.
- **Output budget:** `get_routine_logic` bounds its whole response by `max_chars` (default 8000; 1000–100000). When output is cut it returns `truncated: true`, `returned_rungs`, and `next_start_rung`. Continue with `start_rung=next_start_rung`, use a narrower range, or raise `max_chars`. `include_operands=False` drops the operand map to save space. `get_aoi(include_logic=True)` also bounds its whole response by `max_chars`; routines that don't fit are listed in `logic_omitted`.
- **Routine pagination:** `get_routine_logic` returns at most 200 rungs or lines per call (`start_rung`/`end_rung` are 0-based and inclusive).
- **Current values:** `include_values=True` adds values of non-constant operands. These come from the offline snapshot saved in the export, not live data.
- **Structured Text results:** ST results use the `lines` key in every `detail` mode. `outline` returns only the lines with comments; `logic` returns the code with comments removed.
- **Tag pagination:** `list_tags` uses `limit`/`offset` for browsing large tag lists. Response includes `next_offset` when more tags remain.
- **Instruction aliases:** `find_references` treats legacy/IEC mnemonic pairs as equivalent (e.g., MOV ↔ MOVE, EQU ↔ EQ, GRT ↔ GT, etc.).

## Development

Install dev dependencies and run tests:

```bash
uv sync
uv run pytest
```

Code style and linting:

```bash
uv run ruff check src tests
uv run ruff format src tests
```

Test fixtures in `tests/fixtures/` are 9 sample exports copied from the py_l5x repository,
including component exports (AOI, program, routine, rung, module, data type).

### Project layout

```
l5x-mcp/
├── src/l5x_mcp/
│   ├── __init__.py           # CLI entry point and arg parsing (--root, --structured-output, --read-only)
│   ├── __main__.py           # Module runner
│   ├── server.py             # MCPServer creation, tool registration, INSTRUCTIONS
│   ├── registry.py           # Project discovery and caching
│   ├── serialize.py          # JSON serialization helpers
│   ├── operands.py           # Extract operand candidates from RLL rungs and ST lines
│   ├── operand_resolver.py   # Resolve routine operands to descriptions, types and values
│   ├── operand_paths.py      # Parse and resolve operand paths (get_tag and operands)
│   ├── editing.py            # Write plumbing: fresh load, output_path rules, atomic write
│   ├── specs.py              # JSON spec schemas (TypedDicts) <-> py_l5x specs
│   └── tools/                # Tool implementations
│       ├── project.py        # list_l5x_files, project_overview
│       ├── tasks.py          # list_tasks, get_task
│       ├── programs.py       # list_programs, get_program, list_routines, get_routine_logic
│       ├── tags.py           # list_tags, get_tag
│       ├── datatypes.py      # list_data_types, get_data_type
│       ├── aois.py           # list_aois, get_aoi
│       ├── modules.py        # list_modules, get_module
│       ├── search.py         # find_references, instruction_usage
│       ├── edit_tags.py      # add/remove/rename tags, set_tag_values, update_tag
│       ├── edit_logic.py     # routines, rungs, ST lines
│       ├── definitions.py    # get_spec; UDT/AOI/program add/replace/rename/remove; scheduling
│       └── components.py     # export_component, create_*_file
├── tests/
│   ├── fixtures/             # Test .L5X files
│   ├── conftest.py
│   └── test_*.py
├── pyproject.toml            # Project metadata, dependencies, scripts, ruff config
└── README.md                 # This file
```
