"""End-to-end tests: talk to the MCP server through a real MCP client."""

import sys

import pytest
from mcp import Client, StdioServerParameters

from l5x_mcp import parse_args
from l5x_mcp.registry import ProjectRegistry
from l5x_mcp.server import TOOLS, _strip_registry_doc, create_server

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def server(fixtures_dir):
    return create_server(ProjectRegistry(fixtures_dir))


async def test_lists_every_tool_with_clean_schema(server):
    async with Client(server) as client:
        tools = (await client.list_tools()).tools

    assert {t.name for t in tools} == {fn.__name__ for fn in TOOLS}
    for tool in tools:
        assert "registry" not in tool.input_schema.get("properties", {})
        assert "registry:" not in (tool.description or "")
        assert tool.description, f"{tool.name} has no description"
        assert tool.annotations.read_only_hint is True


async def test_call_tool_returns_structured_content(server):
    async with Client(server) as client:
        result = await client.call_tool(
            "get_routine_logic",
            {"routine": "Logic", "aoi": "Debounce", "path": "example.L5X"},
        )

    assert not result.is_error
    data = result.structured_content
    assert data["file"] == "example.L5X"
    assert data["container"] == {"kind": "aoi", "name": "Debounce"}
    assert data["type"] == "RLL"
    assert data["rungs"]


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
    paths = {f["path"] for f in result.structured_content["files"]}
    assert "example.L5X" in paths


def test_parse_args_root_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("L5X_MCP_ROOT", str(tmp_path))
    assert parse_args([]).root == str(tmp_path)
    assert parse_args(["--root", "other"]).root == "other"


def test_strip_registry_doc():
    doc = (
        "Do a thing.\n\nArgs:\n    registry: The registry.\n"
        "        continued line.\n    name: A name.\n"
    )
    out = _strip_registry_doc(doc)
    assert "registry" not in out
    assert "continued" not in out
    assert "name: A name." in out
