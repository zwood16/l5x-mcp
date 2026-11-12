"""Tools for exploring modules in L5X projects.

This module provides functions to list and inspect modules in a project,
including their ports, communications, and I/O tags. Module I/O is addressed by
the Studio 5000 global names of those tags (for example ``Local:1:I`` or
``ShopRobot:I``), the same names ``get_tag`` accepts.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from py_l5x import ArrayNode, Module, ModuleTagRef, StructNode

from l5x_mcp.registry import ProjectRegistry, lookup
from l5x_mcp.serialize import compact, first_line, node_to_dict


def list_modules(registry: ProjectRegistry, path: str | None = None) -> dict[str, Any]:
    """List all modules in a project with basic metadata and an I/O tree.

    Each module entry has name, catalog_number, description (first line),
    parent_module, parent_port, tag_prefix, address, and inhibited/major_fault
    flags (only when True).

    tag_prefix is the prefix of the module's I/O tag names, which are
    "<tag_prefix>:<kind>" (for example "Local:1:I", "ShopRobot:O"):
    - a module in slot N of the controller chassis: "Local:N"
    - a module in slot N behind a remote adapter: "<adapter name>:N"
    - a network (Ethernet) module: its own name, e.g. "ValveBank"

    Module data is addressed through these io tag names, as in Logix operand
    paths: a member path is appended to the name. get_tag accepts these names,
    e.g. get_tag(name="Local:1:I.Pt00.Data") or get_tag(name="ShopRobot:I.Data[0]").
    list_tags(scope="module_io") lists all module I/O tags; get_module lists one
    module's io_tags.

    Also includes a "tree" key: indented text rendering of the module hierarchy,
    with each module listed exactly once and children nested under their parent:
        Local [5069-L310ERMS3] @ slot 0
          Test_Input_Module [5069-IB16/A] @ slot 1
          ShopRobot [ETHERNET-MODULE] @ 192.168.0.3

    Address is determined from the module's upstream-marked port:
    - Ethernet type → IP address (e.g., 192.168.0.3)
    - Backplane type (5069, 1756, ICP, PointIO) → "slot <N>" (e.g., slot 1)
    - The controller module → "slot 0"

    Args:
        registry: ProjectRegistry to load from.
        path: Project file path (None for auto-discovery).

    Returns:
        Dict with keys:
        - file: Relative path to project file.
        - modules: List of dicts with name, catalog_number, description,
                   parent_module, parent_port, tag_prefix, address, inhibited
                   and major_fault (only if True).
        - tree: Indented text rendering of I/O hierarchy showing all modules.

    Raises:
        ProjectNotFoundError: If project file cannot be found.
    """
    resolved_path, project = registry.get_with_path(path)
    modules_by_name = project.modules

    modules_list = []
    for mod in modules_by_name.values():
        modules_list.append(
            compact(
                {
                    "name": mod.name,
                    "catalog_number": mod.catalog_number,
                    "description": first_line(mod.description),
                    "parent_module": mod.parent_module,
                    "parent_port": mod.parent_mod_port_id,
                    "tag_prefix": mod.tag_prefix,
                    "address": _compute_module_address(mod),
                    "inhibited": mod.inhibited or None,
                    "major_fault": mod.major_fault or None,
                }
            )
        )

    tree_lines = _build_module_tree(modules_by_name)

    return {
        "file": registry.relpath(resolved_path),
        "modules": modules_list,
        "tree": "\n".join(tree_lines),
    }


def get_module(
    registry: ProjectRegistry,
    name: str,
    include_data: bool = False,
    max_depth: int = 2,
    max_elements: int = 32,
    path: str | None = None,
) -> dict[str, Any]:
    """Get detailed information about a specific module.

    Returns module identity (name, description, catalog_number, vendor,
    product_type, product_code, revision), hierarchy (parent_module,
    parent_port, tag_prefix), status (inhibited, major_fault, safety_enabled,
    ekey_state), address, ports, communications, io_tags, and child module names.

    io_tags lists the module's I/O tags under their Studio 5000 global names,
    e.g. "ShopRobot:C", "ShopRobot:I", "ShopRobot:O", "Local:1:I". Each entry has:
    - name, kind ("C" config, "I" input, "O" output, or another suffix), data_type
    - connection: name of the owning connection (absent for the config tag)
    - members: top-level member names of a structure, or element_count for an array
    - value_tree: full value, only when include_data is True

    Module data is addressed through these io tag names: a member path is
    appended to the name, as in Logix operand paths. get_tag accepts these
    names, e.g. get_tag(name="Local:1:I.Pt00.Data") or
    get_tag(name="ShopRobot:I.Data[0]"). list_tags(scope="module_io") lists all module
    I/O tags.

    communications has comm_method, config_tag (io tag name of the config tag),
    and connections. Each connection has name, type, rpi, priority,
    input_connection_type, input_size, output_size, unicast, connection_path,
    and io_tags: the names of its io_tags entries (input and output). Tag data
    is not repeated under the connection.

    Args:
        registry: ProjectRegistry to load from.
        name: Module name (case-insensitive).
        include_data: If True, add value_tree to each io_tags entry. If False
                     (default), entries show only name, kind, data_type,
                     connection and member summaries.
        max_depth: Max recursion depth for value trees (default 2).
        max_elements: Max array elements to include (default 32).
        path: Project file path (None for auto-discovery).

    Returns:
        Dict with keys:
        - file: Relative path to project file.
        - name, description, catalog_number, vendor, product_type, product_code,
          revision (major.minor format).
        - parent_module, parent_port, tag_prefix: Hierarchy and I/O tag prefix.
        - address: Module's address (IP for Ethernet, slot for backplane).
        - inhibited, major_fault, safety_enabled, ekey_state: Status flags.
        - ports: List of dicts with id, type, address, upstream, bus_size.
        - communications: Dict with comm_method, config_tag (optional),
                         connections list.
        - io_tags: List of I/O tag dicts (see above).
        - children: List of child module names.

    Raises:
        ItemNotFoundError: If module not found.
    """
    resolved_path, project = registry.get_with_path(path)

    modules_dict = project.modules
    mod = lookup(modules_dict, name, "Module")

    major = mod.major
    minor = mod.minor
    revision = f"{major}.{minor}" if major and minor else ""

    # Children: modules whose parent_module is this module's name
    children = sorted(
        other_name
        for other_name, other in modules_dict.items()
        if other.parent_module == mod.name and other.name != mod.name
    )

    return compact(
        {
            "file": registry.relpath(resolved_path),
            "name": mod.name,
            "description": mod.description,
            "catalog_number": mod.catalog_number,
            "vendor": mod.vendor,
            "product_type": mod.product_type,
            "product_code": mod.product_code,
            "revision": revision,
            "parent_module": mod.parent_module,
            "parent_port": mod.parent_mod_port_id,
            "tag_prefix": mod.tag_prefix,
            "address": _compute_module_address(mod),
            "inhibited": mod.inhibited or None,
            "major_fault": mod.major_fault or None,
            "safety_enabled": mod.safety_enabled,
            "ekey_state": mod.ekey_state,
            "ports": _build_ports_list(mod),
            "communications": _build_communications(mod),
            "io_tags": [
                _build_io_tag(ref, include_data, max_depth, max_elements)
                for ref in mod.tags.values()
            ],
            "children": children,
        }
    )


# ============================================================================
# Helpers
# ============================================================================


def _compute_module_address(mod: Module) -> str:
    """Compute a module's display address from its upstream port.

    For a module, the address is the address of its port marked upstream=True:
    - If port.type is "Ethernet" → return the IP address string.
    - If port.type is backplane (5069, 1756, ICP, PointIO, etc.) → return
      "slot <address>".
    - For the root controller (parent_module == own name), return "slot 0"
      from the first non-upstream backplane port address found.
    - If no upstream port or address is empty, return "".

    Args:
        mod: The module object.

    Returns:
        Address string (e.g., "192.168.0.3", "slot 1", "slot 0"), or "".
    """
    ports = list(mod.ports.values())

    if mod.parent_module == mod.name:
        # Root controller: first non-upstream backplane port with a real slot
        for port in ports:
            if (
                not port.upstream
                and _is_backplane_type(port.type)
                and port.address not in ("", "0")
            ):
                return f"slot {port.address}"
        return "slot 0"

    for port in ports:
        if not port.upstream:
            continue
        if not port.address:
            return ""
        if port.type == "Ethernet":
            return port.address
        if _is_backplane_type(port.type):
            return f"slot {port.address}"
        return port.address

    return ""


def _is_backplane_type(port_type: str) -> bool:
    """Check if a port type is a backplane type.

    Args:
        port_type: The port type string (e.g., "5069", "Ethernet", "1756").

    Returns:
        True if backplane, False otherwise.
    """
    backplane_types = {"5069", "1756", "ICP", "PointIO"}
    return port_type in backplane_types


def _build_ports_list(mod: Module) -> list[dict[str, Any]]:
    """Build list of port dicts from a module.

    Args:
        mod: The module object.

    Returns:
        List of dicts with id, type, address, upstream, bus_size.
    """
    return [
        compact(
            {
                "id": port_id,
                "type": port.type,
                "address": port.address,
                "upstream": port.upstream,
                "bus_size": port.bus_size,
            }
        )
        for port_id, port in mod.ports.items()
    ]


def _build_communications(mod: Module) -> dict[str, Any] | None:
    """Build the communications dict from a module.

    Each connection lists the names of its io tags, grouped from
    ``ModuleTagRef.connection``. The config tag is the io tag with no
    connection. Tag data is not repeated here (see :func:`_build_io_tag`).

    Args:
        mod: The module object.

    Returns:
        Communications dict, or None if the module has no communications section.
    """
    comms = mod.communications
    if comms is None:
        return None

    config_name = None
    io_names_by_connection: dict[str, list[str]] = {}
    for ref in mod.tags.values():
        if ref.connection is None:
            config_name = config_name or ref.name
        else:
            io_names_by_connection.setdefault(ref.connection.name, []).append(ref.name)

    connections = [
        compact(
            {
                "name": conn.name,
                "type": conn.type,
                "rpi": conn.rpi,
                "priority": conn.priority,
                "input_connection_type": conn.input_connection_type,
                "input_size": conn.input_size,
                "output_size": conn.output_size,
                "unicast": conn.unicast,
                "connection_path": conn.connection_path,
                "io_tags": io_names_by_connection.get(conn.name, []),
            }
        )
        for conn in comms.connections.values()
    ]

    return compact(
        {
            "comm_method": comms.comm_method,
            "config_tag": config_name,
            "connections": connections,
        }
    )


def _build_io_tag(
    ref: ModuleTagRef, include_data: bool, max_depth: int, max_elements: int
) -> dict[str, Any]:
    """Build a summary dict for one module I/O tag.

    Args:
        ref: The module tag, keyed by its global name (e.g. "ShopRobot:I").
        include_data: Whether to include the full value tree.
        max_depth: Max recursion depth for the value tree.
        max_elements: Max array elements for the value tree.

    Returns:
        Dict with name, kind, data_type, connection (if any), members (for a
        structure) or element_count (for an array), and value_tree (if
        include_data).
    """
    entry: dict[str, Any] = {
        "name": ref.name,
        "kind": ref.kind,
        "data_type": ref.data_type,
    }
    if ref.connection is not None:
        entry["connection"] = ref.connection.name

    data = ref.data
    if isinstance(data, StructNode):
        entry["members"] = sorted(data.members)
    elif isinstance(data, ArrayNode):
        entry["element_count"] = len(data.elements)
    if include_data and data is not None:
        entry["value_tree"] = node_to_dict(data, max_depth, max_elements)

    return compact(entry)


def _build_module_tree(modules: Mapping[str, Module]) -> list[str]:
    """Build indented text tree of module I/O hierarchy.

    Each module appears exactly once. Root (parent_module == own name) at top level,
    then children grouped by parent port and ordered by address/slot.

    Args:
        modules: Mapping of module name to module.

    Returns:
        List of text lines representing the tree.
    """
    lines: list[str] = []

    roots = [name for name, mod in modules.items() if mod.parent_module == mod.name]

    # Track visited to avoid cycles and duplicates
    visited: set[str] = set()

    for root_name in sorted(roots):
        _add_tree_lines(root_name, modules, lines, visited, indent=0)

    # Modules not reachable from any root render at top level, with their children
    for name in sorted(modules):
        if name not in visited:
            _add_tree_lines(name, modules, lines, visited, indent=0)

    return lines


def _tree_line(module_name: str, mod: Module, indent: int) -> str:
    """Render one tree line: indented name, catalog number and address."""
    address = _compute_module_address(mod)
    catalog_str = f" [{mod.catalog_number}]" if mod.catalog_number else ""
    addr_str = f" @ {address}" if address else ""
    return " " * (indent * 2) + f"{module_name}{catalog_str}{addr_str}"


def _add_tree_lines(
    module_name: str,
    modules: Mapping[str, Module],
    lines: list[str],
    visited: set[str],
    indent: int = 0,
) -> None:
    """Add tree lines for a module and its children (no duplicates or cycles).

    Args:
        module_name: Name of the module to render.
        modules: Mapping of module name to module.
        lines: List to append lines to.
        visited: Set of visited module names (prevents cycles/duplicates).
        indent: Current indentation level.
    """
    if module_name in visited:
        return

    visited.add(module_name)
    mod = modules[module_name]
    lines.append(_tree_line(module_name, mod, indent))

    # Group unvisited children by parent_port
    children_by_port: dict[str, list[tuple[str, Module]]] = {}
    for other_name, other in modules.items():
        if other_name not in visited and other.parent_module == module_name:
            children_by_port.setdefault(other.parent_mod_port_id, []).append(
                (other_name, other)
            )

    # Render children, grouped by parent_port, sorted by address for determinism
    for parent_port in sorted(children_by_port):
        children = sorted(
            children_by_port[parent_port],
            key=lambda item: _compute_module_address(item[1]),
        )
        for child_name, _child_mod in children:
            _add_tree_lines(child_name, modules, lines, visited, indent + 1)
