"""End-to-end tests: talk to the MCP server through a real MCP client."""

import json
import os
import shutil
import sys
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters
from py_l5x import load

from l5x_mcp import main, parse_args
from l5x_mcp.registry import DEFAULT_OUTPUT_DIR, ProjectRegistry
from l5x_mcp.server import (
    EDIT_INSTRUCTIONS,
    INSTRUCTIONS,
    TOOLS,
    WRITE_TOOLS,
    _strip_registry_doc,
    create_server,
)

OUT_DIR = DEFAULT_OUTPUT_DIR

pytestmark = pytest.mark.anyio

LOGIC_CALL = (
    "get_routine_logic",
    {"routine": "Logic", "aoi": "Debounce", "path": "example.L5X"},
)
WRITE_NAMES = {fn.__name__ for fn in WRITE_TOOLS}
READ_NAMES = {fn.__name__ for fn in TOOLS}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def server(fixtures_dir):
    return create_server(ProjectRegistry(fixtures_dir))


@pytest.fixture
def read_only_server(fixtures_dir):
    return create_server(ProjectRegistry(fixtures_dir), read_only=True)


@pytest.fixture
def writable_server(editable):
    return create_server(editable)


@pytest.fixture
def structured_server(fixtures_dir):
    return create_server(ProjectRegistry(fixtures_dir), structured_output=True)


def _payload(result):
    """Parse the single JSON text block of a tool result."""
    return json.loads(result.content[0].text)


async def test_add_tags_schema_has_copy_from(server):
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}

    schema = json.dumps(tools["add_tags"].input_schema)
    assert '"copy_from"' in schema
    assert "L5K" in schema


async def test_lists_read_and_write_tools_by_default(server):
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}

    assert set(tools) == READ_NAMES | WRITE_NAMES
    assert "get_spec" in READ_NAMES
    for name, tool in tools.items():
        assert "registry" not in tool.input_schema.get("properties", {}), name
        assert "registry:" not in (tool.description or ""), name
        assert tool.description, f"{name} has no description"
        assert tool.output_schema is None, name
        expected_read_only = name in READ_NAMES
        assert tool.annotations.read_only_hint is expected_read_only, name
        if not expected_read_only:
            assert tool.annotations.destructive_hint is False, name
            assert tool.annotations.idempotent_hint is False, name
            assert tool.annotations.open_world_hint is False, name


async def test_read_only_mode_registers_only_read_tools(read_only_server):
    async with Client(read_only_server) as client:
        tools = (await client.list_tools()).tools
        instructions = client.instructions

    assert {t.name for t in tools} == READ_NAMES
    assert all(t.annotations.read_only_hint is True for t in tools)
    assert instructions == INSTRUCTIONS
    assert "Editing" not in instructions


async def test_read_only_mode_refuses_write_calls(read_only_server):
    async with Client(read_only_server) as client:
        result = await client.call_tool(
            "add_tags",
            {"tags": [{"name": "X", "data_type": "DINT"}], "output_path": "o.L5X"},
        )

    assert result.is_error


async def test_write_mode_instructions_describe_editing(server):
    async with Client(server) as client:
        instructions = client.instructions

    assert instructions == EDIT_INSTRUCTIONS
    assert "NEW .L5X" in instructions
    assert "get_spec" in instructions
    assert "Import Component" in instructions
    assert "MOVE" in instructions


async def test_default_returns_one_compact_json_block(server):
    async with Client(server) as client:
        result = await client.call_tool(*LOGIC_CALL)

    assert not result.is_error
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert result.structured_content is None
    text = result.content[0].text
    assert "\n" not in text
    data = json.loads(text)
    assert text == json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    assert data["file"] == "example.L5X"
    assert data["container"] == {"kind": "aoi", "name": "Debounce"}
    assert data["type"] == "RLL"
    assert data["rungs"]


async def test_structured_mode_advertises_schema_and_content(structured_server):
    async with Client(structured_server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        result = await client.call_tool(*LOGIC_CALL)

    assert tools["get_routine_logic"].output_schema is not None
    assert not result.is_error
    assert len(result.content) == 1
    text = result.content[0].text
    assert "\n" not in text
    assert result.structured_content == json.loads(text)
    assert result.structured_content["container"] == {"kind": "aoi", "name": "Debounce"}


async def test_structured_mode_keeps_annotations(structured_server):
    async with Client(structured_server) as client:
        tools = (await client.list_tools()).tools

    assert {t.name for t in tools} == READ_NAMES | WRITE_NAMES
    for tool in tools:
        assert tool.output_schema is not None, tool.name
        assert tool.annotations.read_only_hint is (tool.name in READ_NAMES), tool.name


async def test_write_tool_round_trip_through_mcp(writable_server, editable):
    source = editable.root / "example.L5X"
    before = source.read_bytes()

    async with Client(writable_server) as client:
        result = await client.call_tool(
            "add_tags",
            {
                "tags": [
                    {"name": "McpProbe", "data_type": "TIMER", "value": {"PRE": 250}},
                ],
                "output_path": "mcp_out.L5X",
                "path": "example.L5X",
            },
        )

    assert not result.is_error, result.content[0].text
    assert _payload(result)["added"] == ["McpProbe"]
    assert source.read_bytes() == before
    tag = load(str(editable.root / OUT_DIR / "mcp_out.L5X")).controller_tags["McpProbe"]
    assert tag.to_python()["PRE"] == 250


async def test_write_spec_with_unknown_field_is_rejected_before_running(
    writable_server, editable
):
    async with Client(writable_server) as client:
        result = await client.call_tool(
            "add_tags",
            {
                "tags": [{"name": "Typo", "data_type": "DINT", "descripton": "x"}],
                "output_path": "typo.L5X",
                "path": "example.L5X",
            },
        )

    assert result.is_error
    assert "descripton" in result.content[0].text
    assert not (editable.root / OUT_DIR / "typo.L5X").exists()


async def test_write_error_reaches_the_model(writable_server):
    async with Client(writable_server) as client:
        result = await client.call_tool(
            "add_tags",
            {
                "tags": [{"name": "Bad", "data_type": "NOTATYPE"}],
                "output_path": "bad.L5X",
                "path": "example.L5X",
            },
        )

    assert result.is_error
    assert "unknown data type 'NOTATYPE'" in result.content[0].text


@pytest.mark.parametrize("srv_fixture", ["server", "structured_server"])
async def test_errors_reach_model_in_both_modes(request, srv_fixture):
    srv = request.getfixturevalue(srv_fixture)
    async with Client(srv) as client:
        result = await client.call_tool(
            "get_program", {"name": "nope", "path": "example.L5X"}
        )

    assert result.is_error
    assert len(result.content) == 1
    assert "Program 'nope' not found" in result.content[0].text
    assert "MainProgram" in result.content[0].text


async def test_user_errors_reach_the_model(server):
    async with Client(server) as client:
        result = await client.call_tool(
            "get_program", {"name": "nope", "path": "example.L5X"}
        )

    assert result.is_error
    text = result.content[0].text
    assert "Program 'nope' not found" in text
    assert "MainProgram" in text


async def test_ambiguous_project_error_lists_files(server):
    async with Client(server) as client:
        result = await client.call_tool("project_overview", {})

    assert result.is_error
    assert "example.L5X" in result.content[0].text


async def test_stdio_entrypoint(fixtures_dir):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "l5x_mcp", "--root", str(fixtures_dir)],
    )
    async with Client(params) as client:
        result = await client.call_tool("list_l5x_files", {})

    assert not result.is_error
    paths = {f["path"] for f in _payload(result)["files"]}
    assert "example.L5X" in paths


@pytest.mark.parametrize("root_source", ["cwd", "env", "uv-project"])
async def test_stdio_discovers_client_directory(fixtures_dir, tmp_path, root_source):
    env = dict(os.environ)
    env.pop("L5X_MCP_ROOT", None)
    command = sys.executable
    args = ["-m", "l5x_mcp"]
    cwd = fixtures_dir
    if root_source == "env":
        env["L5X_MCP_ROOT"] = str(fixtures_dir)
        cwd = tmp_path
    elif root_source == "uv-project":
        command = shutil.which("uv")
        if command is None:
            pytest.skip("uv is not installed")
        args = [
            "run",
            "--project",
            str(Path(__file__).resolve().parents[1]),
            "--no-sync",
            "l5x-mcp",
        ]

    params = StdioServerParameters(command=command, args=args, cwd=str(cwd), env=env)
    async with Client(params) as client:
        result = await client.call_tool("list_l5x_files", {})

    assert not result.is_error
    assert Path(_payload(result)["root"]) == fixtures_dir.resolve()
    assert "example.L5X" in {f["path"] for f in _payload(result)["files"]}


def test_parse_args_root_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("L5X_MCP_ROOT", str(tmp_path))
    assert parse_args([]).root == str(tmp_path)
    assert parse_args(["--root", "other"]).root == "other"


def test_parse_args_default_root(monkeypatch):
    monkeypatch.delenv("L5X_MCP_ROOT", raising=False)
    assert parse_args([]).root is None


@pytest.mark.parametrize("placeholder", ["${workspaceFolder}", "${env:PROJECT_ROOT}"])
@pytest.mark.parametrize("source", ["argument", "environment"])
def test_parse_args_rejects_unresolved_root(monkeypatch, capsys, placeholder, source):
    monkeypatch.delenv("L5X_MCP_ROOT", raising=False)
    root = placeholder + "\\exports"
    if source == "environment":
        monkeypatch.setenv("L5X_MCP_ROOT", root)
    args = ["--root", root] if source == "argument" else []

    with pytest.raises(SystemExit) as exc_info:
        parse_args(args)

    assert exc_info.value.code == 2
    error = capsys.readouterr().err
    assert "unresolved" in error
    assert placeholder in error
    assert "--project" in error


def test_explicit_root_overrides_unresolved_env(monkeypatch, tmp_path):
    monkeypatch.setenv("L5X_MCP_ROOT", "${workspaceFolder}")
    assert parse_args(["--root", str(tmp_path)]).root == str(tmp_path)


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "On", " on "])
def test_structured_output_env_truthy(monkeypatch, value):
    monkeypatch.setenv("L5X_MCP_STRUCTURED_OUTPUT", value)
    assert parse_args([]).structured_output is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "maybe"])
def test_structured_output_env_falsy(monkeypatch, value):
    monkeypatch.setenv("L5X_MCP_STRUCTURED_OUTPUT", value)
    assert parse_args([]).structured_output is False


def test_structured_output_default_off(monkeypatch):
    monkeypatch.delenv("L5X_MCP_STRUCTURED_OUTPUT", raising=False)
    assert parse_args([]).structured_output is False


def test_structured_output_flag_overrides_env(monkeypatch):
    monkeypatch.delenv("L5X_MCP_STRUCTURED_OUTPUT", raising=False)
    assert parse_args(["--structured-output"]).structured_output is True
    monkeypatch.setenv("L5X_MCP_STRUCTURED_OUTPUT", "0")
    assert parse_args(["--structured-output"]).structured_output is True


def test_read_only_default_off(monkeypatch):
    monkeypatch.delenv("L5X_MCP_READ_ONLY", raising=False)
    assert parse_args([]).read_only is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "On", " on "])
def test_read_only_env_truthy(monkeypatch, value):
    monkeypatch.setenv("L5X_MCP_READ_ONLY", value)
    assert parse_args([]).read_only is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "maybe"])
def test_read_only_env_falsy(monkeypatch, value):
    monkeypatch.setenv("L5X_MCP_READ_ONLY", value)
    assert parse_args([]).read_only is False


def test_read_only_flag(monkeypatch):
    monkeypatch.delenv("L5X_MCP_READ_ONLY", raising=False)
    assert parse_args(["--read-only"]).read_only is True


def test_read_only_flag_is_independent_of_structured_output(monkeypatch):
    monkeypatch.delenv("L5X_MCP_READ_ONLY", raising=False)
    args = parse_args(["--read-only", "--structured-output"])
    assert args.read_only is True
    assert args.structured_output is True


def test_main_passes_read_only_to_the_server(monkeypatch, fixtures_dir):
    monkeypatch.delenv("L5X_MCP_READ_ONLY", raising=False)
    calls = {}

    class FakeServer:
        def run(self, transport):
            calls["transport"] = transport

    def fake_create_server(registry, **kwargs):
        calls["root"] = registry.root
        calls.update(kwargs)
        return FakeServer()

    monkeypatch.setattr("l5x_mcp.server.create_server", fake_create_server)
    main(["--root", str(fixtures_dir), "--read-only"])

    assert calls["read_only"] is True
    assert calls["root"] == fixtures_dir.resolve()
    assert calls["transport"] == "stdio"


def test_strip_registry_doc():
    doc = (
        "Do a thing.\n\nArgs:\n    registry: The registry.\n"
        "        continued line.\n    name: A name.\n"
    )
    out = _strip_registry_doc(doc)
    assert "registry" not in out
    assert "continued" not in out
    assert "name: A name." in out
