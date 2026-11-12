"""Operand-path parsing and resolution for L5X tags.

This module is pure library code (no MCP or JSON concerns). It maps Logix
operand text onto py_l5x objects in three steps:

1. :func:`parse_operand` splits text such as ``\\MainProgram.tag.m[1,2].3`` or
   ``Local:1:I.Pt00.Data`` into a program prefix, a base tag name and segments.
2. :func:`walk` follows segments through structures, arrays, strings and
   integer bits, validating each step and returning the canonical path.
3. :func:`resolve_tag` (controller, module I/O and program scopes) and
   :func:`resolve_in_aoi` (operands inside an Add-On Instruction) find the base
   object and combine the two steps into a :class:`Resolved` result.

Segments are represented as:

- ``str``: a member name (``".Pt00"``).
- ``tuple[int | str, ...]``: an array subscript (``"[1,2]"``). Integers are
  literal subscripts; strings are non-literal runtime indexes (``"[idx]"``).
- ``int``: a bit number (``".3"``) on an integer value.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, NamedTuple

from py_l5x import (
    AliasTag,
    ArrayNode,
    IntegerNode,
    ModuleTagRef,
    StringNode,
    StructNode,
    TagNode,
)

from l5x_mcp.registry import ItemNotFoundError, L5XError, lookup
from l5x_mcp.serialize import TagLike

if TYPE_CHECKING:
    from py_l5x.parsers.aoi import AOIDefinition
    from py_l5x.parsers.project import Project

__all__ = [
    "MAX_ALIAS_DEPTH",
    "ParsedOperand",
    "Resolved",
    "Segment",
    "format_segments",
    "is_module_io_scope",
    "module_tags",
    "parse_operand",
    "resolve_in_aoi",
    "resolve_tag",
    "walk",
]

#: Maximum number of alias hops followed before reporting ``alias_error``.
MAX_ALIAS_DEPTH = 5

#: One element of a parsed operand path (see the module docstring).
Segment = str | tuple[int | str, ...] | int

_IDENT = re.compile(r"[A-Za-z_]\w*")
#: Tag names; module I/O global names add ``:`` separated parts (``Local:1:I``).
_BASE = re.compile(r"[A-Za-z_]\w*(?::\w+)*")
_INT = re.compile(r"-?\d+")
_BIT = re.compile(r"\d+")


@dataclass
class ParsedOperand:
    """The syntactic parts of an operand path.

    Attributes:
        program: Program named by a leading ``\\Prog.`` prefix, else ``None``.
        base: Base tag name, e.g. ``"a_udt"`` or ``"Local:1:I"``.
        segments: Member, subscript and bit segments after the base.
    """

    program: str | None
    base: str
    segments: list[Segment] = field(default_factory=list)


@dataclass
class Resolved:
    """The result of resolving an operand to a py_l5x object.

    Attributes:
        tag: The base object: a controller/program ``Tag``, a
            :class:`ModuleTagRef`, or an AOI parameter or local tag.
        scope: ``"controller"``, ``"module_io"``, a program name, or the AOI name for
            operands resolved with :func:`resolve_in_aoi`.
        node: The resolved value node, or ``None`` when the base has no value
            tree (alias, message, plain AOI parameter, ...). With no segments
            this is the base's own value tree.
        path: Canonical operand string (base name with correct case, plus the
            walked segments). Excludes the ``\\Prog.`` prefix.
        segments: All parsed segments of the operand.
        segments_remaining: Segments that could not be walked because the base
            has no value tree. Empty when the walk completed.
        also_in_programs: For controller-scope matches, programs that also
            define a tag with the same name.
        description_override: Description found through AOI definition metadata
            when the base has no value tree.
        data_type_override: Data type found through AOI definition metadata
            when the base has no value tree.
        notes: Human-readable notes, e.g. about runtime indexes.
        alias_chain: For operands reached through alias tags, the ``AliasFor``
            text of each alias hop, in order. Empty otherwise.
        alias_error: Set when an alias could not be followed (missing target,
            loop, or more than :data:`MAX_ALIAS_DEPTH` hops). The operand is
            then unresolved and ``target`` is ``None``.
        target: For an alias operand, the :class:`Resolved` of its target,
            including the remaining segments. ``None`` for non-alias operands.
    """

    tag: TagLike
    scope: str
    node: TagNode | None
    path: str
    segments: list[Segment] = field(default_factory=list)
    segments_remaining: list[Segment] = field(default_factory=list)
    also_in_programs: list[str] = field(default_factory=list)
    description_override: str | None = None
    data_type_override: str | None = None
    notes: list[str] = field(default_factory=list)
    alias_chain: list[str] = field(default_factory=list)
    alias_error: str | None = None
    target: Resolved | None = None

    def terminal(self) -> Resolved:
        """Return the final resolved operand after following any alias targets.

        Returns:
            ``self`` for non-alias operands, otherwise the innermost target.
        """
        current = self
        while current.target is not None:
            current = current.target
        return current


class _TypeMember(NamedTuple):
    """A member of a UDT or AOI definition, as needed for type walking."""

    name: str
    data_type: str
    description: str | None


def format_segments(segments: Iterable[Segment]) -> str:
    """Render segments back to operand text, e.g. ``".FAULT.0"``.

    Args:
        segments: Segments as produced by :func:`parse_operand`.

    Returns:
        The concatenated operand suffix. Members and bits become ``.name`` or
        ``.n``; subscripts become ``[i,j]``.
    """
    parts: list[str] = []
    for segment in segments:
        if isinstance(segment, tuple):
            parts.append("[" + ",".join(str(i) for i in segment) + "]")
        else:
            parts.append(f".{segment}")
    return "".join(parts)


def parse_operand(text: str) -> ParsedOperand:
    """Parse operand text into program prefix, base name and segments.

    The base name runs up to the first ``.`` or ``[``. Module I/O base names
    keep their ``:`` separated parts, so ``Local:1:I.Pt00.Data`` has base
    ``Local:1:I``.

    Examples:
        ``\\MainProgram.tag.m[1,2].3`` gives program ``MainProgram``, base
        ``tag``, segments ``["m", (1, 2), 3]``. ``arr[idx]`` gives segment
        ``("idx",)``, a runtime index.

    Args:
        text: The operand text.

    Returns:
        The parsed operand.

    Raises:
        L5XError: If the text is empty or malformed.
    """
    if not isinstance(text, str) or not text.strip():
        raise L5XError("Operand path cannot be empty")

    raw = text.strip()
    program: str | None = None
    if raw.startswith("\\"):
        dot = raw.find(".")
        if dot == -1:
            raise L5XError(
                f"Program prefix in {text!r} must be followed by '.' and a tag "
                "name, e.g. \\MainProgram.MyTag"
            )
        program = raw[1:dot]
        if not _IDENT.fullmatch(program):
            raise L5XError(f"Invalid program name {program!r} in operand {text!r}")
        raw = raw[dot + 1 :]

    cut = len(raw)
    for i, ch in enumerate(raw):
        if ch in ".[":
            cut = i
            break

    base = raw[:cut]
    if not _BASE.fullmatch(base):
        raise L5XError(f"Invalid tag name {base!r} in operand {text!r}")

    segments = _parse_segments(raw, cut, text)
    return ParsedOperand(program=program, base=base, segments=segments)


def _parse_segments(raw: str, pos: int, text: str) -> list[Segment]:
    """Parse the segment section of an operand starting at *pos*."""
    segments: list[Segment] = []
    while pos < len(raw):
        ch = raw[pos]
        if ch == ".":
            match = _IDENT.match(raw, pos + 1)
            if match:
                segments.append(match.group())
                pos = match.end()
                continue
            match = _BIT.match(raw, pos + 1)
            if match:
                segments.append(int(match.group()))
                pos = match.end()
                continue
            raise L5XError(
                f"Expected a member name or bit number after '.' in operand {text!r}"
            )
        if ch == "[":
            items, pos = _read_subscript(raw, pos, text)
            indexes: list[int | str] = []
            for item in items:
                part = item.strip()
                if not part:
                    raise L5XError(f"Empty array index in operand {text!r}")
                # Literals are subscripts; anything else is a runtime expression
                # (e.g. "idx", "idx+1", "\\Prog.x") kept verbatim.
                indexes.append(int(part) if _INT.fullmatch(part) else part)
            segments.append(tuple(indexes))
            continue
        raise L5XError(f"Unexpected {ch!r} in operand {text!r}")
    return segments


def _read_subscript(raw: str, pos: int, text: str) -> tuple[list[str], int]:
    """Read a bracketed subscript whose ``[`` is at *pos*.

    Commas separate items only at the top level, so nested brackets and
    parentheses inside an expression (``arr[f(1,2)]``, ``arr[a[1]]``) are kept.

    Returns:
        ``(items, index_after_closing_bracket)``.

    Raises:
        L5XError: If the brackets or parentheses are unbalanced.
    """
    items: list[str] = []
    depth = 0
    start = pos + 1
    for i in range(start, len(raw)):
        ch = raw[i]
        if ch in "([":
            depth += 1
        elif ch in ")]":
            if depth == 0:
                if ch != "]":
                    raise L5XError(f"Unbalanced {ch!r} in operand {text!r}")
                items.append(raw[start:i])
                return items, i + 1
            depth -= 1
        elif ch == "," and depth == 0:
            items.append(raw[start:i])
            start = i + 1
    raise L5XError(f"Unclosed '[' in operand {text!r}")


def _kind(node: TagNode) -> str:
    """Return a short description of a node's kind for error messages."""
    if isinstance(node, StringNode):
        return "string"
    if isinstance(node, StructNode):
        return "structure"
    if isinstance(node, ArrayNode):
        return "array"
    if isinstance(node, IntegerNode):
        return "integer"
    return "scalar"


def _find_name(names: Iterable[str], name: str) -> str | None:
    """Return the name matching *name* exactly, else case-insensitively."""
    candidates = list(names)
    if name in candidates:
        return name
    lowered = name.lower()
    for candidate in candidates:
        if candidate.lower() == lowered:
            return candidate
    return None


def _find_in(mapping: Mapping[str, Any], name: str) -> tuple[str, Any] | None:
    """Return ``(key, value)`` for *name* in *mapping*, case-insensitively."""
    key = _find_name(mapping.keys(), name)
    return None if key is None else (key, mapping[key])


def walk(
    node: TagNode,
    segments: Iterable[Segment],
    *,
    label: str,
    notes: list[str] | None = None,
) -> tuple[TagNode, str]:
    """Follow segments from a value node and return the node reached.

    Member names match case-insensitively and the canonical (declared) case is
    used in the returned path. Subscripts index arrays by Logix subscript,
    checking the dimension count and bounds. Non-literal runtime indexes use
    element 0 and add a note to *notes*. Bit numbers select a bit of an
    integer. STRING values expose ``LEN`` and ``DATA``.

    Args:
        node: The value node to start from (usually a tag's root value).
        segments: Segments from :func:`parse_operand`.
        label: Canonical name of the base, used as the path prefix and in
            error messages.
        notes: Optional list that receives notes about the walk.

    Returns:
        ``(resolved_node, canonical_path)``.

    Raises:
        L5XError: For a missing member, bad subscript, out-of-range index or
            bit, or a segment that the current node cannot take.
    """
    current: TagNode = node
    path = label
    for segment in segments:
        if isinstance(segment, str):
            current, path = _member(current, segment, path)
        elif isinstance(segment, tuple):
            current, path = _index(current, segment, path, notes)
        else:
            current, path = _bit(current, segment, path)
    return current, path


def _member(node: TagNode, name: str, path: str) -> tuple[TagNode, str]:
    """Select a structure or STRING member, matching the name case-insensitively."""
    if not isinstance(node, (StructNode, StringNode)):
        raise L5XError(
            f"Cannot access member '{name}' on {_kind(node)} '{path}' "
            f"(data_type: {node.data_type})"
        )
    members = node.members
    key = _find_name(members.keys(), name)
    if key is None:
        available = ", ".join(members.keys()) or "(none)"
        raise L5XError(
            f"Member '{name}' not found in '{path}' ({node.data_type}). "
            f"Available: {available}"
        )
    return members[key], f"{path}.{key}"


def _index(
    node: TagNode,
    indexes: tuple[int | str, ...],
    path: str,
    notes: list[str] | None,
) -> tuple[TagNode, str]:
    """Select an array element by Logix subscript."""
    subscript = "[" + ",".join(str(i) for i in indexes) + "]"
    if not isinstance(node, ArrayNode):
        raise L5XError(
            f"Cannot index {_kind(node)} '{path}' with {subscript} "
            f"(data_type: {node.data_type})"
        )
    dims = node.dimensions
    if not dims:
        raise L5XError(
            f"Array '{path}' has no dimensions in the export; cannot index {subscript}"
        )
    if len(indexes) != len(dims):
        raise L5XError(
            f"'{path}' has {len(dims)} dimension(s) {list(dims)} but "
            f"{len(indexes)} index value(s) were given: {subscript}"
        )

    literal: list[int] = []
    runtime = False
    for axis, (value, size) in enumerate(zip(indexes, dims, strict=True)):
        if isinstance(value, int):
            if not 0 <= value < size:
                raise L5XError(
                    f"Index {value} out of bounds for dimension {axis} of '{path}' "
                    f"(size {size}; dimensions {list(dims)})"
                )
            literal.append(value)
        else:
            runtime = True
            literal.append(0)

    try:
        element = node[tuple(literal)]
    except IndexError:
        raise L5XError(f"Element {subscript} not found in '{path}'") from None

    new_path = f"{path}{subscript}"
    if runtime and notes is not None:
        shown = ",".join(str(i) for i in literal)
        notes.append(
            f"'{new_path}' uses a runtime index; showing element [{shown}] "
            "as a representative value."
        )
    return element, new_path


def _bit(node: TagNode, bit: int, path: str) -> tuple[TagNode, str]:
    """Select bit *bit* of an integer value."""
    if not isinstance(node, IntegerNode):
        raise L5XError(
            f"Cannot access bit .{bit} on '{path}' (data_type: {node.data_type}); "
            "only integer types have bits"
        )
    width = node.bit_width
    if not 0 <= bit < width:
        raise L5XError(
            f"Bit {bit} out of range for '{path}' ({node.data_type}); "
            f"valid bits are 0..{width - 1}"
        )
    return node.bit(bit), f"{path}.{bit}"


def module_tags(project: Project) -> dict[str, ModuleTagRef]:
    """Return the module I/O tags of a project, keyed by global name.

    Module I/O tags are the entries of ``project.tags`` whose names contain
    ``:`` (for example ``Local:2:I`` or ``ShopRobot:I``).

    Args:
        project: The loaded project.

    Returns:
        ``{global_name: ModuleTagRef}`` in project order.
    """
    tags = project.tags
    return {name: tags[name] for name in tags if ":" in name}


def _value_root(tag: TagLike) -> TagNode | None:
    """Return the value tree of a tag-like object, or ``None`` if it has none."""
    if isinstance(tag, ModuleTagRef):
        return tag.data
    if isinstance(tag, TagNode):
        return tag
    return None


def _not_found(project: Project, base: str, scope: str | None) -> ItemNotFoundError:
    """Build the helpful not-found error used by :func:`resolve_tag`."""
    io = module_tags(project)
    controller_names = sorted(project.controller_tags.keys())
    program_names = {
        prog_name: sorted(prog.tags.keys())
        for prog_name, prog in sorted(project.programs.items())
    }

    if ":" in base or (scope is not None and scope.lower() == "module_io"):
        msg = f"Module I/O tag '{base}' not found."
        available = sorted(io.keys())
        if available:
            shown = ", ".join(available[:20])
            if len(available) > 20:
                shown += f", ... ({len(available) - 20} more)"
            msg += f"\nAvailable module I/O tags: {shown}"
        return ItemNotFoundError(msg)

    all_tags: dict[str, list[str]] = {
        "controller": controller_names,
        "module_io": sorted(io),
    }
    all_tags.update(program_names)

    lowered = base.lower()
    suggestions: list[str] = []
    for scope_name, names in all_tags.items():
        for name in names:
            if lowered in name.lower() and len(suggestions) < 10:
                suggestions.append(f"{scope_name}/{name}")

    if scope is None:
        msg = (
            f"Tag '{base}' not found at controller scope or in any program "
            f"(searched {len(program_names)} programs)."
        )
    else:
        msg = f"Tag '{base}' not found."

    if suggestions:
        msg += f"\nDid you mean: {', '.join(suggestions)}"
    elif controller_names:
        available_str = ", ".join(controller_names[:20])
        if len(controller_names) > 20:
            available_str += f", ... ({len(controller_names) - 20} more)"
        msg += f"\nAvailable controller tags: {available_str}"
    return ItemNotFoundError(msg)


def _finish(
    project: Project,
    parsed: ParsedOperand,
    scope_name: str,
    key: str,
    tag: TagLike,
    hops: tuple[tuple[str, str], ...] = (),
) -> Resolved:
    """Walk a located base tag and build its :class:`Resolved` result.

    Alias tags are followed: their target is located from the alias's own
    scope and the remaining segments are walked on the target.

    Args:
        project: The loaded project.
        parsed: The operand being resolved (its base is *key*'s tag).
        scope_name: Scope the base was found in.
        key: Canonical name of the base tag.
        tag: The base object.
        hops: ``(scope, name)`` pairs of aliases already followed, used to
            detect loops.
    """
    also_in: list[str] = []
    if scope_name == "controller":
        also_in = sorted(
            prog_name
            for prog_name, prog in project.programs.items()
            if _find_name(prog.tags.keys(), key) is not None
        )

    segments = list(parsed.segments)
    if isinstance(tag, AliasTag):
        return _follow_alias(project, parsed, scope_name, key, tag, also_in, hops=hops)

    root = _value_root(tag)
    if root is None:
        return Resolved(
            tag=tag,
            scope=scope_name,
            node=None,
            path=key + format_segments(segments),
            segments=segments,
            segments_remaining=list(segments),
            also_in_programs=also_in,
        )

    notes: list[str] = []
    node, path = walk(root, segments, label=key, notes=notes)
    return Resolved(
        tag=tag,
        scope=scope_name,
        node=node,
        path=path,
        segments=segments,
        also_in_programs=also_in,
        notes=notes,
    )


def _follow_alias(
    project: Project,
    parsed: ParsedOperand,
    scope_name: str,
    key: str,
    tag: AliasTag,
    also_in: list[str],
    *,
    hops: tuple[tuple[str, str], ...],
) -> Resolved:
    """Resolve an alias tag by following its ``AliasFor`` target.

    The alias's own remaining segments are appended to the target's segments.
    A missing target, a loop, or more than :data:`MAX_ALIAS_DEPTH` hops sets
    ``alias_error`` instead of raising, so the alias itself stays inspectable.
    Errors from walking the remaining segments on the target are raised.
    """
    segments = list(parsed.segments)
    text = tag.alias_for or ""
    own_path = key + format_segments(segments)

    def unresolved(message: str) -> Resolved:
        return Resolved(
            tag=tag,
            scope=scope_name,
            node=None,
            path=own_path,
            segments=segments,
            segments_remaining=list(segments),
            also_in_programs=also_in,
            alias_chain=[text] if text else [],
            alias_error=message,
        )

    if not text:
        return unresolved(f"alias '{key}' has no AliasFor target")
    ident = (scope_name, key)
    if ident in hops:
        loop = " -> ".join(name for _, name in (*hops, ident))
        return unresolved(f"alias loop: {loop}")
    if len(hops) >= MAX_ALIAS_DEPTH:
        return unresolved(
            f"alias chain through '{key}' is deeper than {MAX_ALIAS_DEPTH} hops"
        )

    try:
        target_parsed = parse_operand(text)
        target_scope, target_key, target_tag = _locate_alias_target(
            project, target_parsed, scope_name
        )
    except L5XError as exc:
        return unresolved(f"alias target '{text}' could not be resolved: {exc}")

    combined = ParsedOperand(
        program=None,
        base=target_parsed.base,
        segments=[*target_parsed.segments, *segments],
    )
    target = _finish(
        project,
        combined,
        target_scope,
        target_key,
        target_tag,
        hops=(*hops, ident),
    )
    return Resolved(
        tag=tag,
        scope=scope_name,
        node=None,
        path=own_path,
        segments=segments,
        segments_remaining=list(segments),
        also_in_programs=also_in,
        alias_chain=[text, *target.alias_chain],
        alias_error=target.terminal().alias_error,
        target=target,
    )


def _locate_alias_target(
    project: Project,
    parsed: ParsedOperand,
    origin_scope: str,
) -> tuple[str, str, Any]:
    """Locate the base of an alias's ``AliasFor`` target.

    Rules, in order: an explicit ``\\Prog.`` prefix selects that program. A
    module I/O name (contains ``:``) selects module I/O. Otherwise the origin
    program (when the alias is program-scoped) is searched, then controller
    tags.

    Returns:
        ``(scope_name, key, tag)``.

    Raises:
        ItemNotFoundError: If the target base is not found.
    """
    base = parsed.base
    if parsed.program is not None:
        program = lookup(project.programs, parsed.program, "Program")
        hit = _find_in(program.tags, base)
        if hit is None:
            raise _not_found(project, base, parsed.program)
        return (program.name, *hit)

    if ":" in base:
        hit = _find_in(module_tags(project), base)
        if hit is None:
            raise _not_found(project, base, None)
        return ("module_io", *hit)

    if origin_scope != "controller":
        origin = _find_in(project.programs, origin_scope)
        if origin is not None:
            hit = _find_in(origin[1].tags, base)
            if hit is not None:
                return (origin[1].name, *hit)

    hit = _find_in(project.controller_tags, base)
    if hit is not None:
        return ("controller", *hit)
    raise _not_found(project, base, None)


def is_module_io_scope(project: Project, scope: str) -> bool:
    """Return whether *scope* selects module I/O tags.

    ``"module_io"`` is the module I/O scope, unless a program with that name
    (case insensitive) exists; then the program wins and module I/O tags are
    only reachable by name without a scope.

    Args:
        project: The loaded project.
        scope: The scope string given by the caller.

    Returns:
        ``True`` for the module I/O scope.
    """
    return (
        scope.lower() == "module_io"
        and _find_name(project.programs.keys(), scope) is None
    )


def resolve_tag(
    project: Project,
    name: str,
    *,
    scope: str | None = None,
) -> Resolved:
    """Resolve an operand against the project's controller, module I/O and program tags.

    Search order:

    - A base containing ``:`` is a module I/O tag, whatever the scope.
    - An explicit ``\\Prog.`` prefix (or ``scope``) selects that program.
    - ``scope="controller"`` searches controller tags only.
    - ``scope="module_io"`` searches module I/O tags only, unless a program
      named ``module_io`` exists, in which case the program is used.
    - Any other ``scope`` is a program name (looked up case-insensitively).
    - ``scope=None``: controller tags first (``also_in_programs`` lists
      same-named program tags). If not found there, the programs are searched; a
      name found in more than one program is an error.

    Aliases are followed (see :class:`Resolved`): the alias's target is
    located from the alias's own scope (program, then controller; module I/O
    names directly), and the alias's remaining segments are walked on it.

    Args:
        project: The loaded project.
        name: Operand text, e.g. ``"a_udt.member[2].3"`` or
            ``"\\MainProgram.tag"``.
        scope: ``None``, ``"controller"``, ``"module_io"`` or a program name.

    Returns:
        The resolved operand.

    Raises:
        L5XError: For malformed operands, conflicting scopes, or a name found
            in several programs.
        ItemNotFoundError: If the base tag or program does not exist, or a
            segment cannot be walked (its subclass :class:`L5XError` carries
            the reason).
    """
    parsed = parse_operand(name)
    if parsed.program is not None:
        if scope is not None and scope.lower() != parsed.program.lower():
            raise L5XError(
                f"Operand {name!r} names program {parsed.program!r} but "
                f"scope={scope!r} was given. Pass one or the other."
            )
        scope = parsed.program

    base = parsed.base

    # Module I/O names are reachable from any routine, so a base containing ':'
    # never searches program or controller tags, whatever the scope.
    if ":" in base:
        hit = _find_in(module_tags(project), base)
        if hit is None:
            raise _not_found(project, base, scope)
        return _finish(project, parsed, "module_io", *hit)

    if scope is not None and scope.lower() == "controller":
        hit = _find_in(project.controller_tags, base)
        if hit is None:
            raise _not_found(project, base, scope)
        return _finish(project, parsed, "controller", *hit)

    if scope is not None and is_module_io_scope(project, scope):
        hit = _find_in(module_tags(project), base)
        if hit is None:
            raise _not_found(project, base, scope)
        return _finish(project, parsed, "module_io", *hit)

    if scope is not None:
        program = lookup(project.programs, scope, "Program")
        hit = _find_in(program.tags, base)
        if hit is None:
            raise _not_found(project, base, scope)
        return _finish(project, parsed, program.name, *hit)

    hit = _find_in(project.controller_tags, base)
    if hit is not None:
        return _finish(project, parsed, "controller", *hit)

    matches: list[tuple[str, str, Any]] = []
    for prog_name, prog in project.programs.items():
        prog_hit = _find_in(prog.tags, base)
        if prog_hit is not None:
            matches.append((prog_name, *prog_hit))
    if not matches:
        raise _not_found(project, base, None)
    if len(matches) > 1:
        names = ", ".join(sorted(m[0] for m in matches))
        raise L5XError(
            f"Tag '{base}' found in multiple programs: {names}. "
            "Specify the desired scope."
        )
    prog_name, key, tag = matches[0]
    return _finish(project, parsed, prog_name, key, tag)


def _get_type(project: Project, type_name: str) -> dict[str, _TypeMember] | None:
    """Return the members of a UDT or AOI type by name, or ``None`` if unknown."""
    udt_hit = _find_in(project.data_types, type_name)
    if udt_hit is not None:
        udt = udt_hit[1]
        return {
            m.name: _TypeMember(m.name, m.data_type, m.description or None)
            for m in udt.visible_members.values()
        }

    aoi_hit = _find_in(project.aois, type_name)
    if aoi_hit is not None:
        aoi: AOIDefinition = aoi_hit[1]
        members: dict[str, _TypeMember] = {}
        for obj in [*aoi.parameters.values(), *aoi.local_tags.values()]:
            members.setdefault(
                obj.name,
                _TypeMember(obj.name, obj.data_type, obj.description or None),
            )
        return members
    return None


def _type_walk(
    project: Project,
    type_name: str,
    segments: list[Segment],
    comments: Mapping[str, str],
) -> tuple[str | None, str | None, str, list[Segment]]:
    """Find the description, data type and path through type definitions.

    Used for AOI parameters that have no value tree (for example an InOut
    ``SeqCtrl``). Walks the UDT or AOI definitions of *type_name* segment by
    segment. Member names take the definition's declared case. Integer bits
    and ``BIT`` members are ``BOOL``.

    Args:
        project: The loaded project (for type lookup).
        type_name: Data type of the value-less base.
        segments: Segments after the base.
        comments: Operand comments of the base (for example ``{".FAULT.0": ...}``).

    Returns:
        ``(description, data_type, path_suffix, canonical_segments)``.

        - ``description`` is the operand comment for the full path if present,
          else the description of the final member.
        - ``data_type`` is ``None`` when the type is unknown.
        - ``path_suffix`` is the operand comment's key when one matches the
          path (so ``seq.FAULT.0`` keeps the casing Logix wrote), otherwise the
          definition-cased suffix.

    Raises:
        L5XError: If a member does not exist in a known type.
    """
    current: str | None = type_name
    last_description: str | None = None
    canonical: list[Segment] = []
    for segment in segments:
        if isinstance(segment, str):
            members = _get_type(project, current) if current else None
            if members is None:
                current = None
                last_description = None
                canonical.append(segment)
                continue
            key = _find_name(members.keys(), segment)
            if key is None:
                raise L5XError(
                    f"Member '{segment}' not found in type '{current}'. "
                    f"Available: {', '.join(members.keys()) or '(none)'}"
                )
            member = members[key]
            current = "BOOL" if member.data_type == "BIT" else member.data_type
            last_description = member.description
            canonical.append(key)
        elif isinstance(segment, tuple):
            # Element of an array member has the same type as the array.
            canonical.append(segment)
        else:
            current = "BOOL"
            last_description = None
            canonical.append(segment)

    suffix = format_segments(canonical)
    # Logix writes operand comment keys in its own operand casing (".FAULT.0"),
    # so a commented operand reports that casing; others use the definition's.
    comment_key = next((k for k in comments if k.upper() == suffix.upper()), None)
    if comment_key is not None:
        return comments[comment_key], current, comment_key, canonical
    return last_description, current, suffix, canonical


def resolve_in_aoi(
    project: Project,
    aoi: AOIDefinition,
    name: str,
) -> Resolved:
    """Resolve an operand used inside an Add-On Instruction's logic.

    The base is looked up among the AOI's parameters, then its local tags
    (case-insensitively). A base with a value tree is walked like a controller
    tag. A value-less base, such as an InOut ``SeqCtrl`` parameter, returns a
    description and data type from the AOI's operand comments and the type
    definition instead.

    Args:
        project: The loaded project (needed to look up UDT and AOI types).
        aoi: The AOI definition the operand appears in.
        name: Operand text inside the AOI, e.g. ``"seq.FAULT.0"``. A
            ``\\Prog.`` prefix is not allowed.

    Returns:
        The resolved operand. ``scope`` is the AOI name.

    Raises:
        L5XError: For malformed operands, unknown members, or a program prefix.
        ItemNotFoundError: If the base is neither a parameter nor a local tag.
    """
    parsed = parse_operand(name)
    if parsed.program is not None:
        raise L5XError(f"Operands inside AOI '{aoi.name}' cannot use a program prefix")

    base = parsed.base
    params = aoi.parameters
    locals_ = aoi.local_tags
    hit = _find_in(params, base) or _find_in(locals_, base)
    if hit is None:
        raise ItemNotFoundError(
            f"Tag '{base}' not found in AOI '{aoi.name}'. "
            f"Parameters: {', '.join(params.keys()) or '(none)'}; "
            f"local tags: {', '.join(locals_.keys()) or '(none)'}"
        )
    key, obj = hit

    if _value_root(obj) is not None or not parsed.segments:
        return _finish(project, parsed, aoi.name, key, obj)

    segments = list(parsed.segments)
    description, data_type, suffix, canonical = _type_walk(
        project,
        getattr(obj, "data_type", "") or "",
        segments,
        getattr(obj, "operand_comments", {}) or {},
    )
    return Resolved(
        tag=obj,
        scope=aoi.name,
        node=None,
        path=key + suffix,
        segments=canonical,
        segments_remaining=list(canonical),
        description_override=description,
        data_type_override=data_type,
    )
