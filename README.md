# l5x-mcp

> A set of tools to interact with and generate L5X files

## What it is

This is a Model Context Protocol (MCP) server for Rockwell Automation Studio 5000 Logix Designer projects exported as `.L5X` (XML) files. It allows coding agents (Claude Code, VS Code Copilot Chat, etc.) to explore project structure, list programs and routines, examine logic code, look up tags and data types, and find cross-references without reading the large raw XML themselves.

It can also edit projects and create components (UDTs, AOIs, programs, routines, rungs, tags) as Studio 5000 import files. Write tools never modify their input: every edit is written to a new `.L5X` file. Run with `--read-only` flag to expose only the read tools (see [Write tools](#write-tools)).

> [!IMPORTANT]
> The underlying `py_l5x` parser currently supports **RLL (ladder rungs) and ST (structured text) routines only**. FBD (function block diagram) and SFC (sequential function chart) routines are recognized but their logic is not parsed; tools will return a note that these types are unsupported.

**Related Projects**

- [Studio 5000 Doc MCP](https://github.com/zwood16/studio5000-docs-mcp): an MCP server to allow AI to read through all Studio 5000 docs installed on your PC
- [py_l5x](https://github.com/zwood16/py_l5x): the underlying Python L5X parser used in this project
- [ACD Auto Export](https://github.com/zwood16/acd-auto-export): a companion script that automatically exports your active Studio 5000 project (`.acd` file) to the more usable `.l5x` file format using the Studio 5000 SDK every time you save.

## Requirements

- Python 3.12 or later
- [uv](https://github.com/astral-sh/uv) (Python package manager)

The `py_l5x` parser is automatically downloaded from its GitHub release as a wheel via the `[tool.uv.sources]` configuration in `pyproject.toml` (source: https://github.com/zwood16/py_l5x).

## Install

Neither this server nor `py_l5x` is on PyPI. Install from a release wheel (simplest),
or run from a source checkout (for development).

### From a release wheel

Wheels are attached to the [releases](https://github.com/zwood16/l5x-mcp/releases)
of this repository. [uv](https://docs.astral.sh/uv/getting-started/installation/) can install them straight from the release URL. Because
`py_l5x` isn't on PyPI either, pass its release wheel with `--with`. Without it, uv
fails with `py-l5x was not found in the package registry`. Use a `py_l5x` version
that meets this server's requirement (currently `py-l5x>=0.4.0`).

**Global install** (puts the `l5x-mcp` command on your PATH):

```bash
uv tool install --with https://github.com/zwood16/py_l5x/releases/download/v0.4.0/py_l5x-0.4.0-py3-none-any.whl https://github.com/zwood16/l5x-mcp/releases/download/v0.2.0/l5x_mcp-0.2.0-py3-none-any.whl
```

Then register the `l5x-mcp` command with Claude Code (see
[Claude Code configuration](#claude-code-configuration)). To upgrade, run the same
command with the new release URLs. To reinstall the same version, add `--reinstall`.

**No install:** Claude Code can also launch the server from the release wheels with
`uvx`, which downloads them on the first launch and reuses its cached environment
afterwards. See [Claude Code configuration](#claude-code-configuration).

### From source

Clone the repository and install dependencies:

```bash
git clone https://github.com/zwood16/l5x-mcp.git
cd l5x-mcp
uv sync
```

Run it with `uv run --project <repo> --no-sync l5x-mcp` (see
[Claude Code configuration](#claude-code-configuration)), or install the checkout
globally (puts `l5x-mcp` command on PATH):

```bash
uv tool install --editable /path/to/l5x-mcp
```

After this, you can run `l5x-mcp` from anywhere without the `uv run` prefix.

## Claude Code configuration

Register the server with `claude mcp add`. Use `-s user` to make it available in every
project: the server isn't tied to one PLC project, because it searches the directory
Claude Code is started in (see [How .L5X files are discovered](#how-l5x-files-are-discovered)).
Without `-s`, the server is added to the current project only (`local` scope).
Everything after `--` is the command Claude Code runs.

Pick the line that matches how you installed the server:

```bash
# Global install from a release wheel (uv tool install ..., see Install)
claude mcp add l5x -s user -- l5x-mcp

# No install: run straight from the release wheels with uvx
claude mcp add l5x -s user -- uvx --with https://github.com/zwood16/py_l5x/releases/download/v0.4.0/py_l5x-0.4.0-py3-none-any.whl --from https://github.com/zwood16/l5x-mcp/releases/download/v0.2.0/l5x_mcp-0.2.0-py3-none-any.whl l5x-mcp

# Source checkout (run `uv sync` in the checkout first)
claude mcp add l5x -s user -- uv run --project /path/to/l5x-mcp --no-sync l5x-mcp
```

Server options go after the command, and environment variables go in `-e` options
before `--`. For example:

```bash
claude mcp add l5x -s user -e L5X_MCP_STRUCTURED_OUTPUT=1 -- l5x-mcp --output-dir edits
```


## How .L5X files are discovered

The server searches for `.L5X` files starting from a root directory:

1. **Root directory precedence:** `--root` CLI argument > `L5X_MCP_ROOT` environment variable > current working directory
2. **Recursive discovery:** Searches subdirectories recursively, skipping hidden directories, `node_modules/`, `__pycache__/`, and `venv/`
3. **Auto-selection:** When exactly one `.L5X` file exists, it is automatically used as the default; all tools accept an optional `path` argument to explicitly specify a file (absolute or relative to root). Files in the write tools' output folder (`l5x-mcp-output/` by default, see [Write tools](#write-tools)) are skipped here, so edits don't break auto-selection of the source project. `list_l5x_files` still lists them, marked `"output": true`.
4. **Auto-reload:** The server detects file changes (mtime and size) and re-parses the project automatically

The root is selected at server startup. It is the server process's working
directory, which with Claude Code is the directory you start `claude` in. Restart
the MCP server after changing its configuration.

When launching from a source checkout, use `uv run --project <server-repo>`,
**not** `uv --directory <server-repo> run`. `--project` selects the Python project
and its environment without changing the working directory inherited from Claude
Code. `--directory` changes that directory to the server repository.
Run `uv sync` in the server repository before using the `--no-sync` examples.

## Output format

By default, every tool returns one compact JSON text block (no indentation or extra
spaces).

Add `--structured-output` to the server arguments, or set
`L5X_MCP_STRUCTURED_OUTPUT=1` (also `true`, `yes`, or `on`), to also return MCP
`structuredContent` and an output schema for each tool. The text block stays
compact. Clients that do not use structured content can ignore it. Restart the
server after changing this setting.

With Claude Code, either as a flag or through the environment:

```bash
claude mcp add l5x -s user -- l5x-mcp --structured-output
claude mcp add l5x -s user -e L5X_MCP_STRUCTURED_OUTPUT=1 -- l5x-mcp
```

## Tools Reference

| Tool Name             | Purpose                                                                                                                                                                  | Key Arguments                                                                                                                                                              |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **list_l5x_files**    | Discover .L5X files with size, mtime, target type and name                                                                                                               | `subdir=None`                                                                                                                                                              |
| **project_overview**  | Summarize controller, tasks, programs, AOIs, UDTs, modules and counts (including `module_io_tags`)                                                                       | `path=None`                                                                                                                                                                |
| **list_tasks**        | List tasks with type, rate, priority, watchdog and scheduled programs                                                                                                    | `path=None`                                                                                                                                                                |
| **get_task**          | Get task detail: type, rate, watchdog, event info, scheduled programs                                                                                                    | `name`, `path=None`                                                                                                                                                        |
| **list_programs**     | List programs: main routine, disabled/safety flags, routine and tag counts, scheduled task                                                                               | `path=None`                                                                                                                                                                |
| **get_program**       | Get program detail: routines, flags, tag_count; the tag list only with `include_tags=True` (otherwise a hint to use `list_tags`)                                         | `name`, `include_tags=False`, `path=None`                                                                                                                                  |
| **list_routines**     | List routines in a program or AOI with type and rung/line counts                                                                                                         | `program=None`, `aoi=None`, `path=None`                                                                                                                                    |
| **get_routine_logic** | Get RLL rungs or ST lines. `detail`: `full`, `outline` (comments only) or `logic` (code only). Returns an `operands` map. Paged by `max_chars` budget (max 200 per call) | `routine`, `program=None`, `aoi=None`, `start_rung=None`, `end_rung=None`, `detail='full'`, `max_chars=8000`, `include_operands=True`, `include_values=False`, `path=None` |
| **list_tags**         | List tags in `scope`: `controller`, `module_io` (module I/O tags such as `Local:1:I`), or a program name; filter and paginate                                            | `scope='controller'`, `name_contains=None`, `data_type=None`, `tag_type=None`, `limit=100`, `offset=0`, `path=None`                                                        |
| **get_tag**           | Get a tag, or the value at an operand path: members, `[i]`/`[i,j]`, bits, module I/O names, `\Program.Tag`. Follows aliases                                              | `name`, `scope=None`, `max_depth=3`, `max_elements=32`, `path=None`                                                                                                        |
| **list_data_types**   | List user-defined data types (UDTs) with member counts and string flags                                                                                                  | `path=None`                                                                                                                                                                |
| **get_data_type**     | Get UDT members with metadata, which UDTs/AOIs use it, and how many tags have this type                                                                                  | `name`, `path=None`                                                                                                                                                        |
| **list_aois**         | List Add-On Instructions with revision, parameter count and routine names                                                                                                | `path=None`                                                                                                                                                                |
| **get_aoi**           | Get AOI parameters (with `operand_comments`), local tags, routines, instances; optionally logic text within a `max_chars` budget                                         | `name`, `include_logic=False`, `max_chars=8000`, `path=None`                                                                                                               |
| **list_modules**      | List I/O modules with `tag_prefix`, address, and a hierarchy `tree` (remote racks nested under their adapter)                                                            | `path=None`                                                                                                                                                                |
| **get_module**        | Get module detail: identity, ports, communications, `io_tags` (global names such as `ShopRobot:I`), children                                                             | `name`, `include_data=False`, `max_depth=2`, `max_elements=32`, `path=None`                                                                                                |
| **find_references**   | Find uses of a tag, instruction, or text in program and AOI logic. Comments are ignored for `tag`/`instruction` on ST                                                    | `query`, `kind='tag'` (`tag`/`instruction`/`text`), `program=None`, `include_aois=True`, `limit=200`, `path=None`                                                          |
| **instruction_usage** | Count instruction mnemonics used across all programs (or limit to one)                                                                                                   | `program=None`, `path=None`                                                                                                                                                |

## Write tools

Write tools are enabled by default. Start the server with `--read-only` (or set
`L5X_MCP_READ_ONLY=1`, also `true`, `yes` or `on`) to register only the read tools.

Rules shared by every write tool:

- The source project (`path`) is **never modified**. The result is written to
  `output_path`, which is required, must end in `.L5X`, must be inside the server root,
  and must not be the source file.
- A bare file name such as `step1.L5X` is written to the output folder,
  `l5x-mcp-output/` under the root. Change it with `--output-dir` or
  `L5X_MCP_OUTPUT_DIR` (relative to the root, or an absolute path inside it). A path
  with a directory part, such as `edits/step1.L5X`, is relative to the root.
- An existing file is never replaced unless you pass `overwrite=true`, and even then
  only if a write tool wrote it earlier in the same server session and it hasn't changed
  since. Other `.L5X` files in the root, and outputs from before a server restart, are
  never replaced.
- To chain edits, pass the previous call's output (the `file` in its result) as the
  next call's `path`.
- Edits are all-or-nothing: if any part fails, no file is written.
- Renames and removals of tags, routines and programs don't rewrite logic or alias tags.
  The result lists the remaining `references` (logic locations, including
  `\Program.Tag` uses in other programs, and alias tags that still point at the old
  name) so they can be fixed. Programs whose own tag shadows a controller tag of the same
  name, and AOI logic, are left out. `rename_aoi` does rewrite call sites, and
  `rename_data_type` updates every tag, member and parameter of that type.
- Alias targets must exist (in the scope, the controller tags, module I/O, or another
  tag added in the same call). Members of tags without a value tree (MESSAGE, AXIS\_\*,
  …) can't be checked; those aliases are accepted with a `warnings` entry in the result.
- Component files built without `context_path` carry a v37 header. Studio ignores it:
  py_l5x verified imports into v33, v35, v37 and v38.
- Logic is only checked for balanced brackets and a trailing `;`. Undefined tags and
  wrong instructions show up when Studio verifies the project. Use instructions that
  exist in your version (v36+ uses `MOVE`, `EQ`, … instead of `MOV`, `EQU`, …).

UDTs, AOIs, programs and tags are described by JSON **specs**, whose fields are listed in
each tool's input schema. `get_spec` returns an existing object's spec in exactly the
form the add/replace tools accept, so the usual way to change an object is
`get_spec` → edit → `replace_*`.

| Tool                                                                                                                                               | Purpose                                                                                                                |
| -------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| **get_spec** (read-only)                                                                                                                           | Spec of an existing UDT, AOI, program, tag or routine                                                                  |
| **add_tags** / **remove_tags** / **rename_tag**                                                                                                    | Add base or alias tags (with values and operand comments; an alias target must exist), remove or rename tags           |
| **set_tag_values**                                                                                                                                 | Set values by operand path: scalars, structure members, array elements, strings, TIME                                  |
| **update_tag**                                                                                                                                     | Tag description, operand comments and operand metadata (units, min/max, states)                                        |
| **add_routine** / **remove_routine** / **rename_routine**                                                                                          | Program routines (RLL or ST)                                                                                           |
| **add_rungs** / **replace_rung** / **remove_rungs**                                                                                                | Ladder rungs (insert, change text or comment, delete)                                                                  |
| **set_st_lines**                                                                                                                                   | Replace an ST routine's source                                                                                         |
| **add_data_type** / **replace_data_type** / **rename_data_type** / **remove_data_type**                                                            | UDTs. Replace migrates every instance by member name, the way Studio does                                              |
| **add_aoi** / **replace_aoi** / **rename_aoi** / **remove_aoi**                                                                                    | AOIs. Replace migrates instances and protects call sites from signature changes                                        |
| **add_program** / **replace_program** / **rename_program** / **remove_program**                                                                    | Programs with tags and routines                                                                                        |
| **schedule_program**                                                                                                                               | Schedule, move or unschedule a program                                                                                 |
| **set_description**                                                                                                                                | Description of a program, routine, UDT or AOI                                                                          |
| **export_component**                                                                                                                               | Write existing objects (UDT, AOI, program, routine, rungs, tags) as an Import Component file with their dependencies   |
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

To build a wheel for a release, run `uv build`. The `.whl` and `.tar.gz` go to
`dist/`.

### Project layout

```
l5x-mcp/
├── src/l5x_mcp/
│   ├── __init__.py           # CLI entry point and arg parsing (--root, --output-dir, --structured-output, --read-only)
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
