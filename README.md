# l5x-mcp

A personal project to add AI tools to my Studio 5000 workflow.

## What it is

This is a Model Context Protocol (MCP) server that exposes a read-only interface to Rockwell Automation Studio 5000 Logix Designer projects exported as `.L5X` (XML) files. It allows LLM coding agents (VS Code Copilot Chat, GitHub Copilot CLI) to explore project structure, list programs and routines, examine logic code, look up tags and data types, and find cross-references—without reading the large raw XML themselves.

**Important limitations:** This is work in progress. The underlying `py_l5x` parser currently supports **RLL (ladder rungs) and ST (structured text) routines only**. FBD (function block diagram) and SFC (sequential function chart) routines are recognized but their logic is not parsed; tools will return a note that these types are unsupported.

## Requirements

- Python 3.11 or later
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

## Tools Reference

| Tool Name             | Purpose                                                                                     | Key Arguments                                                                                                       |
| --------------------- | ------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| **list_l5x_files**    | Discover all .L5X files with metadata (size, mtime, target type)                            | `subdir=None`                                                                                                       |
| **project_overview**  | Summarize project structure, controllers, tasks, programs, components                       | `path=None`                                                                                                         |
| **list_tasks**        | List all tasks with type, rate, priority, scheduled programs                                | `path=None`                                                                                                         |
| **get_task**          | Get detailed task info: description, type, rate, watchdog, event config, scheduled programs | `name`, `path=None`                                                                                                 |
| **list_programs**     | List programs: main routine, disabled/safety flags, tag/routine counts, scheduled task      | `path=None`                                                                                                         |
| **get_program**       | Get program details: description, routines, tags, disabled/test/safety flags                | `name`, `path=None`                                                                                                 |
| **list_routines**     | List routines in a program or AOI with type and rung/line counts                            | `program=None`, `aoi=None`, `path=None`                                                                             |
| **get_routine_logic** | Get RLL rungs or ST lines; supports range queries with pagination (max 200 per call)        | `routine`, `program=None`, `aoi=None`, `start_rung=None`, `end_rung=None`, `path=None`                              |
| **list_tags**         | List controller or program tags with filtering by name, data type, tag type; paginated      | `scope='controller'`, `name_contains=None`, `data_type=None`, `tag_type=None`, `limit=100`, `offset=0`, `path=None` |
| **get_tag**           | Get tag with full metadata; supports operand paths into nested structures/arrays/bits       | `name`, `scope=None`, `max_depth=3`, `max_elements=32`, `path=None`                                                 |
| **list_data_types**   | List user-defined data types (UDTs) with member counts and string flags                     | `path=None`                                                                                                         |
| **get_data_type**     | Get UDT members with metadata, which UDTs/AOIs use it, and how many tags have this type     | `name`, `path=None`                                                                                                 |
| **list_aois**         | List Add-On Instructions with revision, parameter count, routine names                      | `path=None`                                                                                                         |
| **get_aoi**           | Get AOI: parameters, local tags, routines, metadata; optionally include logic text          | `name`, `include_logic=False`, `path=None`                                                                          |
| **list_modules**      | List I/O modules: addresses, hierarchy tree, slot/IP assignments                            | `path=None`                                                                                                         |
| **get_module**        | Get module I/O structures: data, configuration, parent/child relationships                  | `name`, `include_data=False`, `max_depth=2`, `max_elements=32`, `path=None`                                         |
| **find_references**   | Find all uses of a tag, instruction, or text in program and AOI logic                       | `query`, `kind='tag'`, `program=None`, `include_aois=True`, `limit=200`, `path=None`                                |
| **instruction_usage** | Count instruction mnemonics used across all programs (or limit to one)                      | `program=None`, `path=None`                                                                                         |

## Suggested LLM workflow

1. **Explore the project:** `list_l5x_files` → `project_overview`
2. **Find relevant code:** `list_programs` / `list_routines`
3. **Read logic:** `get_routine_logic` (paginate with `start_rung`/`end_rung` if needed; max 200 rungs per call)
4. **Understand operands:** `get_tag`, `get_data_type`, `get_aoi` for any operands referenced in logic
5. **Find cross-references:** `find_references` to see where a tag or instruction is used elsewhere
6. **Analyze instructions:** `instruction_usage` to see which instructions are most common

### Tips

- **Operand paths:** `get_tag` supports paths into nested structures: `Tag.Member[3].1` accesses array element 3's bit 1 of a DINT member. See tool docstring for full syntax.
- **Pagination:** `get_routine_logic` returns at most 200 rungs/lines per call. If truncated, use `next_start_rung` to continue.
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

Test fixtures in `tests/fixtures/` are sample exports copied from the py_l5x repository.

### Project layout

```
l5x-mcp/
├── src/l5x_mcp/
│   ├── __init__.py           # CLI entry point and arg parsing
│   ├── __main__.py           # Module runner
│   ├── server.py             # MCPServer creation and tool registration
│   ├── registry.py           # Project discovery and caching
│   ├── serialize.py          # JSON serialization helpers
│   └── tools/                # Tool implementations
│       ├── project.py        # list_l5x_files, project_overview
│       ├── tasks.py          # list_tasks, get_task
│       ├── programs.py       # list_programs, get_program, list_routines, get_routine_logic
│       ├── tags.py           # list_tags, get_tag
│       ├── datatypes.py      # list_data_types, get_data_type
│       ├── aois.py           # list_aois, get_aoi
│       ├── modules.py        # list_modules, get_module
│       └── search.py         # find_references, instruction_usage
├── tests/
│   ├── fixtures/             # Test .L5X files
│   ├── conftest.py
│   └── test_*.py
├── pyproject.toml            # Project metadata, dependencies, scripts, ruff config
└── README.md                 # This file
```
