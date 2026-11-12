"""Serialization of py_l5x tags and value nodes to JSON-native structures.

This module converts py_l5x objects (controller and program tags, AOI local
tags and parameters, module I/O references, and value-tree nodes) into
JSON-compatible dicts for MCP structured output to LLMs. Depth and element
limits keep large structures bounded, and every truncation is flagged.

Dispatch is isinstance-based against the py_l5x 0.3.x class model. A missing
attribute or unexpected node class raises instead of silently dropping data.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from py_l5x import (
    AliasTag,
    AOILocalTag,
    AOIParameter,
    ArrayNode,
    AtomicNode,
    AxisTag,
    BoolNode,
    DateTimeNode,
    FloatNode,
    IntegerNode,
    MessageTag,
    ModuleTagRef,
    MotionGroupTag,
    StringNode,
    StructNode,
    Tag,
    TagNode,
    TimeNode,
    UnknownTag,
)

#: Objects accepted by :func:`tag_summary` and :func:`tag_detail`.
TagLike = Tag | AOILocalTag | AOIParameter | ModuleTagRef

#: Tag classes whose ``<Data>`` section is not a standard value tree.
_SPECIAL_DATA_TAGS = (MessageTag, AxisTag, MotionGroupTag, UnknownTag)


def jsonable(value: Any) -> Any:
    """Recursively convert a value to JSON-native types.

    Converts Mapping -> dict with str keys, list/tuple/Sequence (not str) ->
    list, bool/int/float/str/None passthrough, float NaN/inf -> str, anything
    else -> str(value).

    Args:
        value: The value to convert.

    Returns:
        A JSON-native value (str/int/float/bool/None/list/dict only).
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value

    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return value

    if isinstance(value, Mapping):
        return {str(k): jsonable(v) for k, v in value.items()}

    if isinstance(value, (list, tuple)) or (
        isinstance(value, Sequence) and not isinstance(value, str)
    ):
        return [jsonable(item) for item in value]

    return str(value)


def compact(d: dict) -> dict:
    """Drop keys whose value is None, "", [], or {} (but keep False and 0).

    Args:
        d: A dict to compact.

    Returns:
        A new dict with empty/None values removed.
    """
    return {
        k: v for k, v in d.items() if v is not None and v != "" and v != [] and v != {}
    }


def first_line(text: str | None, limit: int = 200) -> str:
    """Extract the first line of text, capped at limit characters.

    Args:
        text: The text to process.
        limit: Maximum character length.

    Returns:
        The first line, stripped and capped, or empty string if text is None.
    """
    if not text:
        return ""
    # Strip leading whitespace first, then split by newline
    text = text.lstrip()
    if not text:
        return ""
    first = text.split("\n")[0].strip()
    if len(first) > limit:
        return first[:limit]
    return first


def _logix_index(operand_path: str) -> str:
    """Return the trailing Logix subscript of an array element's operand path.

    py_l5x builds element paths as ``<array path>[i]`` or ``<array path>[i,j]``
    using the 0-based subscripts exported in the L5X file, so the subscript is
    everything from the last ``[``.

    Args:
        operand_path: The element's ``operand_path``.

    Returns:
        The subscript, e.g. ``"[1,2]"``.

    Raises:
        ValueError: If the path has no subscript.
    """
    start = operand_path.rfind("[")
    if start == -1:
        raise ValueError(f"array element has no subscript: {operand_path!r}")
    return operand_path[start:]


def _node_metadata(node: TagNode) -> dict[str, Any]:
    """Return the description and engineering unit of a node, when set."""
    meta: dict[str, Any] = {}
    if node.description:
        meta["description"] = node.description
    if node.engineering_unit:
        meta["engineering_unit"] = node.engineering_unit
    return meta


def _bit_descriptions(node: IntegerNode) -> dict[str, str]:
    """Map bit number (as a string) to its comment, for commented bits only.

    Bit comments resolve through the owning tag's operand overrides and any
    enclosing AOI parameter definition, so an AOI instance's bits inherit the
    parameter's comments.

    Args:
        node: The integer node whose bits to inspect.

    Returns:
        ``{"0": "...", ...}``; empty if no bit has a comment.
    """
    return {
        str(i): bit.description for i, bit in enumerate(node.bits) if bit.description
    }


def _scalar_fields(node: AtomicNode) -> dict[str, Any]:
    """Return the value and type-specific fields of a scalar node."""
    if isinstance(node, BoolNode):
        return {
            "value": jsonable(node.value),
            "state0": node.state0,
            "state1": node.state1,
        }
    if isinstance(node, IntegerNode):
        return {
            "value": jsonable(node.value),
            "radix": node.radix,
            "min": jsonable(node.min),
            "max": jsonable(node.max),
            "bit_descriptions": _bit_descriptions(node),
        }
    if isinstance(node, FloatNode):
        return {
            "value": jsonable(node.value),
            "radix": node.radix,
            "min": jsonable(node.min),
            "max": jsonable(node.max),
        }
    if isinstance(node, (TimeNode, DateTimeNode)):
        return {"value": jsonable(node.value), "unit": node.unit}
    return {"value": jsonable(node.value), "radix": node.radix}


def _string_fields(node: StringNode) -> dict[str, Any]:
    """Return the collapsed form of a STRING: text, length and capacity.

    The LEN and DATA members are not emitted; they are implementation detail of
    the string's value.
    """
    return {
        "value": jsonable(node.value),
        "len": node.len,
        "max_length": node.max_length,
    }


def _structure_fields(
    node: StructNode, max_depth: int, max_elements: int, depth: int
) -> dict[str, Any]:
    """Return the members of a structure, or its member names when truncated."""
    if depth >= max_depth:
        return {"truncated": True, "member_names": list(node.members)}
    return {
        "members": {
            name: node_to_dict(member, max_depth, max_elements, depth + 1)
            for name, member in node.members.items()
        }
    }


def _array_fields(
    node: ArrayNode, max_depth: int, max_elements: int, depth: int
) -> dict[str, Any]:
    """Return dimensions, element count and (bounded) elements of an array.

    Each element carries an ``index`` key with its Logix subscript, e.g.
    ``"[1,2]"``. Elements are cut at *max_elements*, which sets
    ``elements_truncated``. At *max_depth* the elements are omitted and
    ``truncated`` is set instead.
    """
    elements = node.elements
    count = len(elements)
    fields: dict[str, Any] = {
        "dimensions": list(node.dimensions),
        "element_count": count,
    }
    if depth >= max_depth:
        fields["truncated"] = True
        return fields

    shown = min(count, max_elements)
    fields["elements"] = [
        {
            "index": _logix_index(element.operand_path),
            **node_to_dict(element, max_depth, max_elements, depth + 1),
        }
        for element in elements[:shown]
    ]
    if count > max_elements:
        fields["elements_truncated"] = True
    return fields


def node_to_dict(
    node: TagNode, max_depth: int = 3, max_elements: int = 32, _depth: int = 0
) -> dict[str, Any]:
    """Serialize a value-tree node to a dict.

    Recursively converts scalars, strings, structures, and arrays. Depth and
    element limits add explicit ``truncated`` / ``elements_truncated`` flags.

    Args:
        node: The TagNode to serialize. A tag is itself a TagNode, so tags can
            be passed directly.
        max_depth: Maximum recursion depth (default 3).
        max_elements: Maximum array elements to include (default 32).
        _depth: Current recursion depth (internal use).

    Returns:
        A dict with ``data_type``, ``kind`` and optional ``description`` and
        ``engineering_unit``, plus:

        - scalars (``kind="scalar"``): ``value`` (always present), then
          ``state0``/``state1`` for BOOL, ``radix``/``min``/``max``/
          ``bit_descriptions`` for integers, ``radix``/``min``/``max`` for
          floats, ``unit`` for TIME/DT, ``radix`` otherwise.
        - strings (``kind="string"``): ``value`` (always present), ``len``,
          ``max_length``.
        - structures (``kind="structure"``): ``members`` mapping, or
          ``truncated`` plus ``member_names`` past *max_depth*.
        - arrays (``kind="array"``): ``dimensions``, ``element_count``,
          ``elements`` (each with an ``index`` such as ``"[1,2]"``), and
          ``elements_truncated`` when cut at *max_elements*. Past *max_depth*:
          ``truncated`` and no elements.

    Raises:
        TypeError: If the node is not a py_l5x value node class.
    """
    result: dict[str, Any] = {"data_type": node.data_type}
    result.update(_node_metadata(node))

    if isinstance(node, StringNode):
        result["kind"] = "string"
        result.update(_string_fields(node))
    elif isinstance(node, StructNode):
        result["kind"] = "structure"
        result.update(_structure_fields(node, max_depth, max_elements, _depth))
    elif isinstance(node, ArrayNode):
        result["kind"] = "array"
        result.update(_array_fields(node, max_depth, max_elements, _depth))
    elif isinstance(node, AtomicNode):
        result["kind"] = "scalar"
        result.update(_scalar_fields(node))
    else:
        raise TypeError(f"unsupported value node: {type(node).__name__}")

    out = compact(result)
    # Scalars and strings keep their value even when empty ('' or None).
    if "value" in result:
        out.setdefault("value", result["value"])
    return out


#: Backward-compatible name used by existing tools.
tag_node_to_dict = node_to_dict


def _specialty_to_dict(obj: Any, *, include_attributes: bool = False) -> dict[str, Any]:
    """Serialize a py_l5x BaseElement wrapper to a dict.

    Covers the typed specialty wrappers (MessageParameters, AxisParameters,
    MotionGroupParameters) and the produced/consumed facets (ProduceInfo,
    ConsumeInfo). Output contains the declared typed fields (``fields()``,
    which are descriptors and not properties), every public property on the
    class hierarchy, and ``extra_attributes``.

    Args:
        obj: A py_l5x BaseElement wrapper instance.
        include_attributes: Also emit the full raw ``attributes`` map. Off by
            default: AxisParameters has about 200 attributes, which would
            roughly double the output.

    Returns:
        A compacted dict of JSON-native values.
    """
    names = list(type(obj).fields())
    for klass in type(obj).__mro__:
        for name, attr in vars(klass).items():
            if (
                isinstance(attr, property)
                and not name.startswith("_")
                and name not in names
            ):
                names.append(name)

    result: dict[str, Any] = {}
    for name in names:
        if name == "attributes" and not include_attributes:
            continue
        try:
            value = getattr(obj, name)
        except Exception:
            # Narrow tolerance: a single property getter may fail. Skip only it.
            continue
        result[name] = jsonable(value)
    return compact(result)


def _specialty_parameters(tag: TagLike) -> dict[str, Any]:
    """Return the typed specialty wrapper(s) a tag exposes, keyed by output name.

    Only wrappers that are present (not None) are returned.
    """
    wrappers: dict[str, Any] = {}
    if isinstance(tag, MessageTag):
        wrappers["message_parameters"] = tag.message_parameters
    if isinstance(tag, AxisTag):
        wrappers["axis_parameters"] = tag.axis_parameters
    if isinstance(tag, MotionGroupTag):
        wrappers["motion_group_parameters"] = tag.motion_group_parameters
    return {key: obj for key, obj in wrappers.items() if obj is not None}


def tag_summary(tag: TagLike) -> dict[str, Any]:
    """Serialize a tag to a concise summary dict.

    Works for controller and program tags (:class:`Tag` subclasses), AOI local
    tags, AOI parameters (plain and typed), and module I/O references.

    Args:
        tag: The tag-like object to summarize.

    Returns:
        A compacted dict with ``name``, ``data_type``, ``description`` (first
        line only, max 200 chars), and ``external_access``. Also:

        - ``tag_type`` and ``usage`` for controller tags and AOI parameters.
        - ``alias_for`` for alias tags.
        - ``dimensions`` for array values.
        - ``constant: True`` only when the tag is a constant.
        - ``kind`` and ``module`` for module I/O references.
    """
    if isinstance(tag, ModuleTagRef):
        result: dict[str, Any] = {
            "name": tag.name,
            "data_type": tag.data_type,
            "kind": tag.kind,
            "module": tag.module_name,
            "external_access": tag.external_access,
        }
        if isinstance(tag.data, ArrayNode):
            result["dimensions"] = list(tag.data.dimensions)
        return compact(result)

    result = {
        "name": tag.name,
        "data_type": tag.data_type,
        "description": first_line(tag.description, 200),
        "external_access": tag.external_access,
    }
    if isinstance(tag, (Tag, AOIParameter)):
        result["tag_type"] = tag.tag_type
        result["usage"] = tag.usage
    if isinstance(tag, AliasTag):
        result["alias_for"] = tag.alias_for
    if isinstance(tag, ArrayNode):
        result["dimensions"] = list(tag.dimensions)
    if tag.constant:
        result["constant"] = True
    return compact(result)


def tag_detail(
    tag: TagLike, max_depth: int = 3, max_elements: int = 32
) -> dict[str, Any]:
    """Serialize a tag to a comprehensive detail dict.

    Args:
        tag: The tag-like object to serialize in detail.
        max_depth: Maximum recursion depth for the value tree (default 3).
        max_elements: Maximum array elements in the value tree (default 32).

    Returns:
        The :func:`tag_summary` fields, with ``description`` replaced by the
        full text, plus:

        - ``radix`` for atomic values and AOI parameters.
        - ``class``, ``is_safety`` (only when True), and ``opc_ua_access`` for
          controller tags and module references.
        - ``engineering_unit`` and ``min``/``max`` where the value type has them.
        - ``produced`` / ``consumed`` for produced and consumed tags, with
          typed fields plus raw ``attributes``.
        - ``operand_comments`` (for example per-bit comments) when non-empty.
        - ``message_parameters``, ``axis_parameters``, or
          ``motion_group_parameters`` for the matching tag types.
        - ``special_data_format`` and ``special_data_attributes`` for special
          data tags when no typed wrapper was emitted.
        - ``value_tree``: :func:`node_to_dict` of the value. Alias and special
          data tags have none.
    """
    result = tag_summary(tag)
    if not isinstance(tag, ModuleTagRef):
        result["description"] = tag.description

    if isinstance(tag, (AtomicNode, AOIParameter)):
        result["radix"] = tag.radix

    if isinstance(tag, (Tag, ModuleTagRef)):
        result["class"] = tag.class_
        if tag.is_safety:
            result["is_safety"] = True
        result["opc_ua_access"] = tag.opc_ua_access

    if isinstance(tag, TagNode):
        result["engineering_unit"] = tag.engineering_unit

    if isinstance(tag, (IntegerNode, FloatNode)):
        result["min"] = jsonable(tag.min)
        result["max"] = jsonable(tag.max)

    if isinstance(tag, Tag):
        if (produced := tag.produced) is not None:
            result["produced"] = _specialty_to_dict(produced, include_attributes=True)
        if (consumed := tag.consumed) is not None:
            result["consumed"] = _specialty_to_dict(consumed, include_attributes=True)

    if isinstance(tag, (Tag, AOILocalTag, AOIParameter)) and (
        comments := tag.operand_comments
    ):
        result["operand_comments"] = jsonable(comments)

    wrappers = _specialty_parameters(tag)
    for key, params in wrappers.items():
        result[key] = _specialty_to_dict(params)
    if not wrappers and isinstance(tag, _SPECIAL_DATA_TAGS):
        result["special_data_format"] = tag.special_data_format
        result["special_data_attributes"] = jsonable(tag.special_data_attributes)

    if isinstance(tag, ModuleTagRef):
        value_node = tag.data
    elif isinstance(tag, TagNode):
        value_node = tag
    else:
        value_node = None
    if value_node is not None:
        result["value_tree"] = node_to_dict(value_node, max_depth, max_elements)

    return compact(result)
