"""MCP server that lets LLMs explore Studio 5000 .L5X project exports."""

from __future__ import annotations

import argparse
import os
import re
from collections.abc import Sequence

ROOT_ENV_VAR = "L5X_MCP_ROOT"
STRUCTURED_OUTPUT_ENV_VAR = "L5X_MCP_STRUCTURED_OUTPUT"
READ_ONLY_ENV_VAR = "L5X_MCP_READ_ONLY"
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUTHY


def _root_argument(value: str) -> str:
    if re.search(r"\$\{[^}]+\}", value):
        raise argparse.ArgumentTypeError(
            f"Root contains an unresolved configuration variable: {value!r}. "
            "Variables such as ${workspaceFolder} must be expanded by the MCP client, "
            "not by this server. Omit --root and use "
            "'uv run --project <server-repo> --no-sync l5x-mcp' to preserve the "
            "client's launch directory, or provide a literal directory via --root "
            f"or {ROOT_ENV_VAR}."
        )
    return value


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="l5x-mcp",
        description="MCP server for exploring Studio 5000 .L5X project exports.",
    )
    parser.add_argument(
        "--root",
        type=_root_argument,
        default=os.environ.get(ROOT_ENV_VAR) or None,
        help=(
            "Directory to search for .L5X files and resolve relative paths against. "
            f"Defaults to {ROOT_ENV_VAR} or the current working directory. "
            "Configuration variables must be expanded by the MCP client."
        ),
    )
    parser.add_argument(
        "--transport",
        choices=["stdio"],
        default="stdio",
        help="MCP transport (default: stdio).",
    )
    parser.add_argument(
        "--structured-output",
        action="store_true",
        default=_env_flag(STRUCTURED_OUTPUT_ENV_VAR),
        help=(
            "Advertise output schemas and return results as structured_content in "
            "addition to the compact JSON text block. "
            f"Defaults to truthy {STRUCTURED_OUTPUT_ENV_VAR} (1/true/yes/on)."
        ),
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        default=_env_flag(READ_ONLY_ENV_VAR),
        help=(
            "Expose only the read tools; write tools (edits and component files) "
            "are not registered. Write tools are enabled by default. "
            f"Defaults to truthy {READ_ONLY_ENV_VAR} (1/true/yes/on)."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)

    from l5x_mcp.registry import ProjectRegistry
    from l5x_mcp.server import create_server

    create_server(
        ProjectRegistry(args.root),
        structured_output=args.structured_output,
        read_only=args.read_only,
    ).run(transport=args.transport)
