"""Turn the operands of a routine's logic into descriptions, types and values.

:class:`OperandResolver` is bound to one container (a program or an AOI
definition) and resolves the operand text found in its rungs or ST lines. Each
resolved operand becomes a compact dict, keyed by the operand text exactly as
written, so an LLM can match it to the logic it is reading.

Scoping follows Logix:

- Program routines see the program's own tags first, then controller tags,
  then module I/O. Names of tags that live in *other* programs are not visible
  without a ``\\Prog.`` prefix, so such names (and enum words, labels and
  routine names) resolve to ``None``.
- AOI routines see their parameters and local tags only.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from py_l5x import ArrayNode, AtomicNode, StringNode, StructNode, TagNode

from l5x_mcp.operand_paths import Resolved, parse_operand, resolve_in_aoi, resolve_tag
from l5x_mcp.operands import extract_rll_operands, extract_st_operands
from l5x_mcp.registry import ItemNotFoundError, L5XError, lookup
from l5x_mcp.serialize import compact, first_line, jsonable

__all__ = ["OperandResolver"]


class OperandResolver:
    """Resolve operands of one routine container to description entries.

    Entries are cached per operand string. Call :meth:`operands_for_rung` or
    :meth:`operands_for_st_lines` to get the operands map for a piece of logic.

    Attributes:
        values_shown: ``True`` once a non-constant value has been emitted. The
            caller can then add a note that values are current controller
            values, not design values.
    """

    def __init__(
        self,
        project: Any,
        container_kind: Literal["program", "aoi"],
        container_name: str,
        *,
        include_values: bool = False,
    ) -> None:
        """Bind the resolver to a program or AOI definition.

        Args:
            project: The loaded py_l5x project.
            container_kind: ``"program"`` for a program's routines, ``"aoi"``
                for an Add-On Instruction's logic.
            container_name: Name of the program or AOI (case-insensitive).
            include_values: Emit current values of non-constant scalar
                operands. Constant values are always emitted.

        Raises:
            ValueError: If *container_kind* is not ``"program"`` or ``"aoi"``.
            ItemNotFoundError: If the program or AOI does not exist.
        """
        self._project = project
        self._include_values = include_values
        self._cache: dict[str, dict[str, Any] | None] = {}
        self.values_shown = False

        if container_kind == "program":
            program = lookup(project.programs, container_name, "Program")
            self._program_name: str | None = program.name
            self._aoi: Any = None
        elif container_kind == "aoi":
            self._aoi = lookup(project.aois, container_name, "AOI")
            self._program_name = None
        else:
            raise ValueError(
                f"container_kind must be 'program' or 'aoi', not {container_kind!r}"
            )
        self._kind = container_kind

    def resolve(self, operand: str) -> dict[str, Any] | None:
        """Return the description entry for one operand, or ``None``.

        ``None`` means the text is not a tag visible from this container (enum
        keywords, labels, routine names, unknown or out-of-scope names, and
        operands that do not resolve). Results are cached per operand string.

        Args:
            operand: Operand text as written in the logic, e.g. ``"seq.fault.0"``.

        Returns:
            A compact dict with any of the keys ``desc``, ``type``, ``tag_desc``,
            ``alias_for``, ``const``, ``value``, ``scope`` and ``indexed``.
        """
        if operand not in self._cache:
            self._cache[operand] = self._describe(operand)
        return self._cache[operand]

    def operands_for_rung(self, text: str) -> dict[str, dict[str, Any]]:
        """Return the operands map of one rung's neutral text.

        Args:
            text: Rung text from py_l5x (``Rung.text``).

        Returns:
            ``{operand text: entry}`` in first-seen order, omitting operands
            that are not tags.

        Raises:
            ValueError: If the rung text is malformed (see
                :func:`l5x_mcp.operands.parse_rll`).
        """
        return self._map(extract_rll_operands(text))

    def operands_for_st_lines(self, lines: list[str]) -> dict[str, dict[str, Any]]:
        """Return the operands map of ST lines.

        Args:
            lines: ST line texts with comments already removed (see
                :func:`l5x_mcp.operands.strip_st_comments`).

        Returns:
            ``{operand text: entry}`` in first-seen order, omitting operands
            that are not tags.

        Raises:
            ValueError: If a line has an unterminated string or subscript.
        """
        candidates: list[str] = []
        for line in lines:
            candidates.extend(extract_st_operands(line))
        return self._map(candidates)

    def _map(self, candidates: Sequence[str]) -> dict[str, dict[str, Any]]:
        """Resolve candidates in order, keeping only the tags."""
        result: dict[str, dict[str, Any]] = {}
        for operand in dict.fromkeys(candidates):
            entry = self.resolve(operand)
            if entry is not None:
                result[operand] = entry
        return result

    def _describe(self, operand: str) -> dict[str, Any] | None:
        """Resolve one operand and build its entry (``None`` if not a tag)."""
        try:
            resolved = self._locate(operand)
        except L5XError:
            return None
        return self._entry(resolved)

    def _locate(self, operand: str) -> Resolved:
        """Find the operand's base in the container's scope order.

        Raises:
            L5XError: If the operand is not visible from the container.
        """
        if self._kind == "aoi":
            return resolve_in_aoi(self._project, self._aoi, operand)

        parsed = parse_operand(operand)
        if parsed.program is not None or ":" in parsed.base:
            # Explicit \Prog. prefix or module I/O name: no program-local search.
            return resolve_tag(self._project, operand)
        try:
            return resolve_tag(self._project, operand, scope=self._program_name)
        except ItemNotFoundError:
            return resolve_tag(self._project, operand, scope="controller")

    def _entry(self, resolved: Resolved) -> dict[str, Any]:
        """Build the compact entry for a resolved operand."""
        target = resolved.terminal()
        node = target.node
        segments = target.segments
        is_path = bool(segments)
        base_desc = first_line(getattr(target.tag, "description", None))

        own_desc = first_line(
            node.description if node is not None else target.description_override
        )
        if not own_desc and not is_path:
            own_desc = base_desc

        if node is not None:
            data_type: str | None = node.data_type
        elif target.data_type_override:
            data_type = target.data_type_override
        elif not is_path:
            data_type = getattr(target.tag, "data_type", None) or None
        else:
            data_type = None

        entry: dict[str, Any] = {
            "desc": own_desc,
            "type": data_type,
        }
        if is_path and not own_desc:
            entry["tag_desc"] = base_desc
        if resolved.alias_chain:
            entry["alias_for"] = (
                target.path if target is not resolved else resolved.alias_chain[-1]
            )
        if self._kind == "program" and target.scope != self._program_name:
            entry["scope"] = target.scope
        if _has_runtime_index(segments):
            entry["indexed"] = True
        entry = compact(entry)

        scalar = _scalar_value(node)
        if getattr(target.tag, "constant", False):
            entry["const"] = True
            if scalar is not None:
                entry["value"] = scalar
        elif self._include_values and scalar is not None:
            entry["value"] = scalar
            self.values_shown = True
        return entry


def _has_runtime_index(segments: Sequence[Any]) -> bool:
    """Return whether any subscript uses a non-literal (runtime) index."""
    return any(
        isinstance(segment, tuple) and any(isinstance(i, str) for i in segment)
        for segment in segments
    )


def _scalar_value(node: TagNode | None) -> Any | None:
    """Return the JSON-native value of a scalar or string node, else ``None``."""
    if node is None or isinstance(node, (StructNode, ArrayNode)):
        return None
    if not isinstance(node, (AtomicNode, StringNode)):
        return None
    value = node.value
    if value is None:
        return None
    return jsonable(value)
