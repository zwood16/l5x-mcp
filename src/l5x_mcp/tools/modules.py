"""Tools for exploring modules in L5X projects.

This module provides functions to list and inspect modules in a project,
including their ports, communications, and I/O data structures.
"""

from __future__ import annotations

from typing import Any

from l5x_mcp.registry import ProjectRegistry, lookup
from l5x_mcp.serialize import compact, first_line, tag_node_to_dict


def list_modules(registry: ProjectRegistry, path: str | None = None) -> dict[str, Any]:
    """List all modules in a project with basic metadata and I/O tree.

    Returns each module's name, catalog_number, description (first line),
    parent_module, parent_port, address, and inhibited/major_fault flags
    (only when True).

    Also includes a "tree" key: indented text rendering of the module I/O
    hierarchy, showing parent→children relationships with catalog numbers
    and addresses. For example:
        Local [5069-L310ERMS3] @ slot 0
          Test_Input_Module [5069-IB16/A] @ slot 1
          ShopRobot [ETHERNET-MODULE] @ 192.168.0.3

    Address is determined from the module's upstream-marked port:
    - Ethernet type → IP address (e.g., 192.168.0.3)
    - Backplane type (5069, 1756, ICP, PointIO) → slot number (e.g., 1)

    Args:
        registry: ProjectRegistry to load from.
        path: Project file path (None for auto-discovery).

    Returns:
        Dict with keys:
        - file: Relative path to project file.
        - modules: List of dicts with name, catalog_number, description,
                   parent_module, parent_port, address, inhibited and
                   major_fault (only if True).
        - tree: Indented text rendering of I/O hierarchy showing all modules.

    Raises:
        ProjectNotFoundError: If project file cannot be found.
    """
    resolved_path, project = registry.get_with_path(path)

    modules_list = []
    modules_by_name = project.modules

    for _name, mod in modules_by_name.items():
        # Safely extract basic info (use default arg to capture loop var)
        name = _get_safe(lambda m=mod: m.name, "")
        catalog = _get_safe(lambda m=mod: m.catalog_number, "")
        description = _get_safe(lambda m=mod: first_line(m.description), "")
        parent_module = _get_safe(lambda m=mod: m.parent_module, "")
        parent_port = _get_safe(lambda m=mod: m.parent_mod_port_id, "")
        inhibited = _get_safe(lambda m=mod: m.inhibited, False)
        major_fault = _get_safe(lambda m=mod: m.major_fault, False)

        # Compute address from upstream port
        address = _compute_module_address(mod, modules_by_name)

        modules_list.append(
            compact(
                {
                    "name": name,
                    "catalog_number": catalog,
                    "description": description,
                    "parent_module": parent_module,
                    "parent_port": parent_port,
                    "address": address,
                    "inhibited": inhibited if inhibited else None,
                    "major_fault": major_fault if major_fault else None,
                }
            )
        )

    # Build tree view
    tree_lines = _build_module_tree(modules_by_name)
    tree_text = "\n".join(tree_lines)

    return {
        "file": registry.relpath(resolved_path),
        "modules": modules_list,
        "tree": tree_text,
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
    parent_port), status (inhibited, major_fault, safety_enabled, ekey_state),
    address, ports (id, type, address, upstream, bus_size), communications
    (comm_method, config_tag info, connections), and child module names.

    For ports and communications, each connection includes:
    - name, type, rpi, priority, input_connection_type, input_size, output_size,
      unicast, connection_path
    - input_tag and output_tag with data_type and (if include_data) full value_tree

    If include_data is False, tag sections only show data_type and member names
    (cheap summary useful to LLM). If True, include full value_tree via
    tag_node_to_dict with depth/element limits.

    Every property access is wrapped; one odd module never breaks the tool.

    Args:
        registry: ProjectRegistry to load from.
        name: Module name (case-insensitive).
        include_data: If True, include full value_tree for config/input/output tags.
                     If False, just show data_type and member names (default).
        max_depth: Max recursion depth for value trees (default 2).
        max_elements: Max array elements to include (default 32).
        path: Project file path (None for auto-discovery).

    Returns:
        Dict with keys:
        - file: Relative path to project file.
        - name, description, catalog_number, vendor, product_type, product_code,
          revision (major.minor format).
        - parent_module, parent_port: Hierarchy info.
        - address: Module's address (IP for Ethernet, slot for backplane).
        - inhibited, major_fault, safety_enabled, ekey_state: Status flags.
        - ports: List of dicts with id, type, address, upstream, bus_size.
        - communications: Dict with comm_method, config_tag (optional),
                         connections list.
        - children: List of child module names.

    Raises:
        ItemNotFoundError: If module not found.
    """
    resolved_path, project = registry.get_with_path(path)

    # Look up module (case-insensitive)
    modules_dict = project.modules
    mod = lookup(modules_dict, name, "Module")

    # Basic identity
    mod_name = _get_safe(lambda m=mod: m.name, "")
    description = _get_safe(lambda m=mod: m.description, "")
    catalog = _get_safe(lambda m=mod: m.catalog_number, "")
    vendor = _get_safe(lambda m=mod: m.vendor, "")
    product_type = _get_safe(lambda m=mod: m.product_type, "")
    product_code = _get_safe(lambda m=mod: m.product_code, "")
    major = _get_safe(lambda m=mod: m.major, "")
    minor = _get_safe(lambda m=mod: m.minor, "")
    revision = f"{major}.{minor}" if major and minor else ""

    # Hierarchy
    parent_module = _get_safe(lambda m=mod: m.parent_module, "")
    parent_port = _get_safe(lambda m=mod: m.parent_mod_port_id, "")

    # Address
    address = _compute_module_address(mod, modules_dict)

    # Status
    inhibited = _get_safe(lambda m=mod: m.inhibited, False)
    major_fault = _get_safe(lambda m=mod: m.major_fault, False)
    safety_enabled = _get_safe(lambda m=mod: m.safety_enabled, None)
    ekey_state = _get_safe(lambda m=mod: m.ekey_state, "")

    # Ports
    ports_list = _build_ports_list(mod)

    # Communications
    communications_dict = _build_communications_dict(
        mod, include_data, max_depth, max_elements
    )

    # Children: modules whose parent_module == this module's name
    children = []
    for other_name, other_mod in modules_dict.items():
        try:
            if (
                _get_safe(lambda m=other_mod: m.parent_module, "") == mod_name
                and _get_safe(lambda m=other_mod: m.name, "") != mod_name
            ):
                children.append(other_name)
        except Exception:
            pass
    children.sort()

    return compact(
        {
            "file": registry.relpath(resolved_path),
            "name": mod_name,
            "description": description,
            "catalog_number": catalog,
            "vendor": vendor,
            "product_type": product_type,
            "product_code": product_code,
            "revision": revision,
            "parent_module": parent_module,
            "parent_port": parent_port,
            "address": address,
            "inhibited": inhibited if inhibited else None,
            "major_fault": major_fault if major_fault else None,
            "safety_enabled": safety_enabled,
            "ekey_state": ekey_state,
            "ports": ports_list,
            "communications": communications_dict,
            "children": children,
        }
    )


# ============================================================================
# Helpers
# ============================================================================


def _get_safe(fn, default: Any = None) -> Any:
    """Call a function safely, returning default on any exception.

    Args:
        fn: Callable to invoke.
        default: Value to return if fn raises.

    Returns:
        Result of fn() or default.
    """
    try:
        return fn()
    except Exception:
        return default


def _compute_module_address(mod: Any, modules_dict: dict) -> str:
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
        modules_dict: Dict of all modules (unused, kept for consistency).

    Returns:
        Address string (e.g., "192.168.0.3", "slot 1", "slot 0"), or "".
    """
    try:
        # Check if this is the root controller (parent_module == own name)
        is_root = _get_safe(lambda m=mod: m.parent_module, "") == _get_safe(
            lambda m=mod: m.name, ""
        )

        if is_root:
            # For root, find non-upstream backplane port address
            for port_id in mod.ports:
                try:
                    port = mod.ports[port_id]
                    if not _get_safe(
                        lambda p=port: p.upstream, False
                    ) and _is_backplane_type(_get_safe(lambda p=port: p.type, "")):
                        addr = _get_safe(lambda p=port: p.address, "")
                        if addr and addr != "0":
                            return f"slot {addr}"
                except Exception:
                    pass
            # Fallback to slot 0
            return "slot 0"

        # For non-root modules, find upstream port
        for port_id in mod.ports:
            try:
                port = mod.ports[port_id]
                if _get_safe(lambda p=port: p.upstream, False):
                    port_type = _get_safe(lambda p=port: p.type, "")
                    address = _get_safe(lambda p=port: p.address, "")

                    if not address:
                        return ""

                    # Ethernet → bare IP
                    if port_type == "Ethernet":
                        return address

                    # Backplane → "slot <address>"
                    if _is_backplane_type(port_type):
                        return f"slot {address}"

                    # Other types → bare address
                    return address
            except Exception:
                pass

    except Exception:
        pass

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


def _build_ports_list(mod: Any) -> list[dict[str, Any]]:
    """Build list of port dicts from a module.

    Args:
        mod: The module object.

    Returns:
        List of dicts with id, type, address, upstream, bus_size.
    """
    ports_list = []
    try:
        for port_id in mod.ports:
            try:
                port = mod.ports[port_id]
                port_dict = compact(
                    {
                        "id": _get_safe(lambda p=port: p.id, port_id),
                        "type": _get_safe(lambda p=port: p.type, ""),
                        "address": _get_safe(lambda p=port: p.address, ""),
                        "upstream": _get_safe(lambda p=port: p.upstream, False),
                        "bus_size": _get_safe(lambda p=port: p.bus_size, None),
                    }
                )
                ports_list.append(port_dict)
            except Exception:
                pass
    except Exception:
        pass
    return ports_list


def _build_communications_dict(
    mod: Any, include_data: bool, max_depth: int, max_elements: int
) -> dict[str, Any] | None:
    """Build communications dict from a module.

    Args:
        mod: The module object.
        include_data: Whether to include full value trees for tags.
        max_depth: Max recursion depth for value trees.
        max_elements: Max array elements.

    Returns:
        Communications dict or None if module has no communications section.
    """
    comms = _get_safe(lambda m=mod: m.communications, None)
    if not comms:
        return None

    comm_method = _get_safe(lambda c=comms: c.comm_method, "")

    # Config tag
    config_tag_dict = None
    config_tag = _get_safe(lambda c=comms: c.config_tag, None)
    if config_tag:
        config_tag_dict = _build_tag_dict(
            config_tag, include_data, max_depth, max_elements
        )

    # Connections
    connections_list = []
    try:
        for conn_name in comms.connections:
            try:
                conn = comms.connections[conn_name]
                conn_dict = _build_connection_dict(
                    conn, include_data, max_depth, max_elements
                )
                connections_list.append(conn_dict)
            except Exception:
                pass
    except Exception:
        pass

    return compact(
        {
            "comm_method": comm_method,
            "config_tag": config_tag_dict,
            "connections": connections_list,
        }
    )


def _build_connection_dict(
    conn: Any, include_data: bool, max_depth: int, max_elements: int
) -> dict[str, Any]:
    """Build a connection dict.

    Args:
        conn: The connection object.
        include_data: Whether to include full value trees for tags.
        max_depth: Max recursion depth for value trees.
        max_elements: Max array elements.

    Returns:
        Connection dict.
    """
    name = _get_safe(lambda c=conn: c.name, "")
    conn_type = _get_safe(lambda c=conn: c.type, "")
    rpi = _get_safe(lambda c=conn: c.rpi, None)
    priority = _get_safe(lambda c=conn: c.priority, "")
    input_cxn_type = _get_safe(lambda c=conn: c.input_connection_type, "")
    input_size = _get_safe(lambda c=conn: c.input_size, None)
    output_size = _get_safe(lambda c=conn: c.output_size, None)
    unicast = _get_safe(lambda c=conn: c.unicast, None)
    connection_path = _get_safe(lambda c=conn: c.connection_path, "")

    # Input tag
    input_tag_dict = None
    input_tag = _get_safe(lambda c=conn: c.input_tag, None)
    if input_tag:
        input_tag_dict = _build_tag_dict(
            input_tag, include_data, max_depth, max_elements
        )

    # Output tag
    output_tag_dict = None
    output_tag = _get_safe(lambda c=conn: c.output_tag, None)
    if output_tag:
        output_tag_dict = _build_tag_dict(
            output_tag, include_data, max_depth, max_elements
        )

    return compact(
        {
            "name": name,
            "type": conn_type,
            "rpi": rpi,
            "priority": priority,
            "input_connection_type": input_cxn_type,
            "input_size": input_size,
            "output_size": output_size,
            "unicast": unicast,
            "connection_path": connection_path,
            "input_tag": input_tag_dict,
            "output_tag": output_tag_dict,
        }
    )


def _build_tag_dict(
    tag: Any, include_data: bool, max_depth: int, max_elements: int
) -> dict[str, Any]:
    """Build a tag summary dict, with optional full value tree.

    Args:
        tag: The ConfigTag, InputTag, or OutputTag object.
        include_data: Whether to include full value tree.
        max_depth: Max recursion depth.
        max_elements: Max array elements.

    Returns:
        Tag dict with data_type, and optionally value_tree and member_names.
    """
    tag_dict: dict[str, Any] = {}

    # Data type
    data_node = _get_safe(lambda t=tag: t.data, None)
    if data_node:
        tag_dict["data_type"] = _get_safe(lambda n=data_node: n.data_type, "")

        # Member names (top-level structure members, always cheap)
        if _get_safe(lambda n=data_node: n.kind, None) == "structure":
            try:
                member_names = sorted(data_node.members.keys())
                if member_names:
                    tag_dict["member_names"] = member_names
            except Exception:
                pass

        # Full value tree if requested
        if include_data:
            try:  # noqa: SIM105
                tag_dict["value_tree"] = tag_node_to_dict(
                    data_node, max_depth, max_elements
                )
            except Exception:
                pass

    return tag_dict


def _build_module_tree(modules_dict: dict) -> list[str]:
    """Build indented text tree of module I/O hierarchy.

    Each module appears exactly once. Root (parent_module == own name) at top level,
    then children grouped by parent port and ordered by address/slot.

    Args:
        modules_dict: Dict of all modules.

    Returns:
        List of text lines representing the tree.
    """
    lines = []

    # Find root controller(s) - module(s) whose parent_module == their own name
    roots = []
    for name, mod in modules_dict.items():
        try:
            if _get_safe(lambda m=mod: m.parent_module, "") == _get_safe(
                lambda m=mod: m.name, ""
            ):
                roots.append(name)
        except Exception:
            pass

    # Track visited to avoid cycles and duplicates
    visited = set()

    # Render all roots
    for root_name in sorted(roots):
        _add_tree_lines(root_name, modules_dict, lines, visited, indent=0)

    # Handle orphans (modules not reachable from any root)
    for name in sorted(modules_dict.keys()):
        if name not in visited:
            try:
                mod = modules_dict[name]
                catalog = _get_safe(lambda m=mod: m.catalog_number, "")
                address = _compute_module_address(mod, modules_dict)
                addr_str = f" @ {address}" if address else ""
                lines.append(f"{name} [{catalog}]{addr_str}")
                visited.add(name)
            except Exception:
                pass

    return lines


def _add_tree_lines(
    module_name: str,
    modules_dict: dict,
    lines: list[str],
    visited: set[str],
    indent: int = 0,
) -> None:
    """Add tree lines for a module and its children (no duplicates or cycles).

    Args:
        module_name: Name of the module to render.
        modules_dict: Dict of all modules.
        lines: List to append lines to.
        visited: Set of visited module names (prevents cycles/duplicates).
        indent: Current indentation level.
    """
    if module_name in visited:
        return

    visited.add(module_name)

    mod = modules_dict.get(module_name)
    if not mod:
        return

    # Render this module
    catalog = _get_safe(lambda m=mod: m.catalog_number, "")
    address = _compute_module_address(mod, modules_dict)
    addr_str = f" @ {address}" if address else ""
    line = " " * (indent * 2) + f"{module_name} [{catalog}]{addr_str}"
    lines.append(line)

    # Group children by parent_port
    children_by_port: dict[str, list[tuple[str, Any]]] = {}
    try:
        for other_name, other_mod in modules_dict.items():
            if other_name not in visited:
                try:
                    if (
                        _get_safe(lambda m=other_mod: m.parent_module, "")
                        == module_name
                        and _get_safe(lambda m=other_mod: m.name, "") != module_name
                    ):
                        parent_port = _get_safe(
                            lambda m=other_mod: m.parent_mod_port_id, ""
                        )
                        if parent_port not in children_by_port:
                            children_by_port[parent_port] = []
                        children_by_port[parent_port].append((other_name, other_mod))
                except Exception:
                    pass
    except Exception:
        pass

    # Render children, grouped by parent_port
    for parent_port in sorted(children_by_port.keys()):
        children = children_by_port[parent_port]
        # Sort by address for determinism
        children.sort(key=lambda x: _compute_module_address(x[1], modules_dict))

        for child_name, _child_mod in children:
            _add_tree_lines(child_name, modules_dict, lines, visited, indent + 1)
