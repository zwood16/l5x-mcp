"""Serialization of py_l5x tag data to JSON-native structures.

This module converts py_l5x Tag and TagNode objects to JSON-compatible dicts
for MCP structured output to LLMs, with careful attention to depth limits,
element truncation, and proper handling of special data formats.
"""

from __future__ import annotations

import contextlib
import math
from collections.abc import Mapping, Sequence
from typing import Any

from py_l5x.parsers.tag import Tag, TagNode


def _get(obj: Any, name: str, default: Any = None) -> Any:
    """Get an attribute from an object with exception handling.

    Duck-types objects: uses getattr with a default value and swallows
    any exceptions that occur during attribute access.

    Args:
        obj: The object to get the attribute from.
        name: The attribute name.
        default: Value to return if the attribute is missing or access raises.

    Returns:
        The attribute value or *default*.
    """
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


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


def tag_node_to_dict(
    node: TagNode, max_depth: int = 3, max_elements: int = 32, _depth: int = 0
) -> dict:
    """Serialize a TagNode to a dict.

    Recursively converts TagNode scalars, structures, and arrays to dicts.
    Applies depth and element limits with truncation indicators.

    Args:
        node: The TagNode to serialize.
        max_depth: Maximum recursion depth (default 3).
        max_elements: Maximum array elements to include (default 32).
        _depth: Current recursion depth (internal use).

    Returns:
        A dict representation of the node with these keys:
        - data_type: The node's data type name.
        - kind: "scalar", "structure", or "array".
        - value: Present only for scalars.
        - Metadata: description, engineering_unit, min, max, state0, state1, radix
          (only if non-empty).
        - For structures: members dict, or truncated flag + member_names.
        - For arrays: element_count, elements list (possibly truncated),
          dimensions if available.
    """
    result: dict[str, Any] = {
        "data_type": node.data_type,
        "kind": node.kind,
    }

    # Add scalar value
    if node.kind == "scalar":
        result["value"] = jsonable(node.value)

    # Add metadata (description, min, max, etc.)
    metadata_fields = [
        "description",
        "engineering_unit",
        "min",
        "max",
        "state0",
        "state1",
        "radix",
    ]
    for field in metadata_fields:
        try:
            val = getattr(node, field, None)
            if val is not None and val != "":
                result[field] = jsonable(val)
        except Exception:
            pass

    # Handle structures
    if node.kind == "structure":
        if _depth >= max_depth:
            result["truncated"] = True
            result["member_names"] = list(node.members.keys())
        else:
            members_dict = {}
            try:
                for name in node.members:
                    try:
                        member = node.members[name]
                        members_dict[name] = tag_node_to_dict(
                            member, max_depth, max_elements, _depth + 1
                        )
                    except Exception:
                        members_dict[name] = {"error": "Failed to serialize"}
            except Exception:
                pass
            result["members"] = members_dict

    # Handle arrays
    elif node.kind == "array":
        try:
            element_count = len(node.elements)
            result["element_count"] = element_count

            # Try to include dimensions if available on the element
            try:
                if hasattr(node, "_element") and node._element is not None:
                    dimensions = node._element.get("Dimensions")
                    if dimensions:
                        result["dimensions"] = dimensions
            except Exception:
                pass

            if _depth >= max_depth:
                result["truncated"] = True
            else:
                # Include elements up to max_elements
                elements_list = []
                for i in range(min(element_count, max_elements)):
                    try:
                        elem = node.elements[i]
                        elem_dict = tag_node_to_dict(
                            elem, max_depth, max_elements, _depth + 1
                        )
                        elem_dict["index"] = i
                        elements_list.append(elem_dict)
                    except Exception:
                        elements_list.append(
                            {"index": i, "error": "Failed to serialize"}
                        )

                result["elements"] = elements_list

                if element_count > max_elements:
                    result["elements_truncated"] = True

        except Exception:
            result["element_count"] = 0
            result["elements"] = []

    out = compact(result)
    if node.kind == "scalar":
        # Keep scalar values even when empty (e.g. '' strings) so the key is stable.
        out["value"] = result.get("value")
    return out


def _specialty_to_dict(obj: Any) -> dict[str, Any]:
    """Convert a specialty tag wrapper (MessageParameters, MotionGroupParameters,
    AxisParameters) to a dict using its typed properties plus extra_attributes.

    Args:
        obj: A specialty parameters wrapper object.

    Returns:
        A dict with typed property values and extra_attributes.
    """
    result = {}

    # Collect typed properties
    obj_type = type(obj)
    for attr_name in dir(obj):
        if attr_name.startswith("_"):
            continue
        if attr_name in ("attributes", "extra_attributes"):
            continue
        try:
            attr = getattr(obj_type, attr_name, None)
            # Check if it's a property
            if isinstance(attr, property):
                val = getattr(obj, attr_name)
                if val is not None and val != "":
                    result[attr_name] = jsonable(val)
        except Exception:
            pass

    # Add extra_attributes
    try:
        extras = getattr(obj, "extra_attributes", {})
        if extras:
            result["extra_attributes"] = jsonable(extras)
    except Exception:
        pass

    return compact(result)


def tag_summary(tag: Tag) -> dict[str, Any]:
    """Serialize a Tag to a concise summary dict.

    Duck-types tag objects (Tag, AOILocalTag, ConfigTag, InputTag, OutputTag, etc.)
    using getattr with defaults to handle missing attributes gracefully.

    Args:
        tag: The Tag-like object to summarize.

    Returns:
        A dict with: name (if present), data_type, tag_type (if present),
        description (first line, max 200), alias_for (if present), dimensions
        (if present), usage (if present), constant (if True), external_access
        (if present).
    """
    result: dict[str, Any] = {}

    # Name (all tag-like objects should have this)
    name = _get(tag, "name")
    if name:
        result["name"] = name

    # data_type (required on most, but may be empty on Alias tags)
    data_type = _get(tag, "data_type", "")
    if data_type:
        result["data_type"] = data_type

    # tag_type (only on Tag, not on AOILocalTag/ModuleDataTag)
    tag_type = _get(tag, "tag_type")
    if tag_type:
        result["tag_type"] = tag_type

    # Add description (first line only, capped)
    desc = _get(tag, "description", "")
    desc_first = first_line(desc, 200)
    if desc_first:
        result["description"] = desc_first

    # Alias-specific field (Tag only)
    alias_for = _get(tag, "alias_for")
    if alias_for:
        result["alias_for"] = alias_for

    # Try to get dimensions from XML element
    try:
        if hasattr(tag, "_element") and tag._element is not None:
            dims = tag._element.get("Dimensions")
            if dims:
                result["dimensions"] = dims
    except Exception:
        pass

    # Optional fields
    usage = _get(tag, "usage")
    if usage:
        result["usage"] = usage

    constant = _get(tag, "constant")
    if constant:
        result["constant"] = True

    external_access = _get(tag, "external_access")
    if external_access:
        result["external_access"] = external_access

    return compact(result)


def tag_detail(tag: Tag, max_depth: int = 3, max_elements: int = 32) -> dict[str, Any]:
    """Serialize a Tag to a comprehensive detail dict.

    Duck-types tag objects (Tag, AOILocalTag, ConfigTag, InputTag, OutputTag, etc.)
    using getattr with defaults to handle missing attributes gracefully.

    Args:
        tag: The Tag-like object to serialize in detail.
        max_depth: Maximum recursion depth for value tree (default 3).
        max_elements: Maximum array elements to serialize (default 32).

    Returns:
        A dict with summary fields plus:
        - Full description (not truncated)
        - radix, class, is_safety, opc_ua_access, engineering_unit, min, max
        - consume_info, produce_info (for Produced/Consumed tags)
        - special_data_format, special_data_attributes (when no known wrappers)
        - message_parameters, motion_group_parameters, axis_parameters (when present,
          serialized via _specialty_to_dict)
        - value_tree: tag_node_to_dict(tag.data, ...) if tag.data is not None
    """
    # Start with summary fields
    result = tag_summary(tag)

    # Override description with full version
    full_desc = _get(tag, "description", "")
    if full_desc:
        result["description"] = full_desc

    # Add detailed fields using duck-typing
    radix = _get(tag, "radix")
    if radix:
        result["radix"] = radix

    class_ = _get(tag, "class_")
    if class_:
        result["class"] = class_

    is_safety = _get(tag, "is_safety")
    if is_safety:
        result["is_safety"] = True

    opc_ua_access = _get(tag, "opc_ua_access")
    if opc_ua_access:
        result["opc_ua_access"] = opc_ua_access

    engineering_unit = _get(tag, "engineering_unit")
    if engineering_unit:
        result["engineering_unit"] = engineering_unit

    min_val = _get(tag, "min")
    if min_val is not None:
        result["min"] = jsonable(min_val)

    max_val = _get(tag, "max")
    if max_val is not None:
        result["max"] = jsonable(max_val)

    # Produced/Consumed info
    consume_info = _get(tag, "consume_info")
    if consume_info:
        result["consume_info"] = jsonable(consume_info)

    produce_info = _get(tag, "produce_info")
    if produce_info:
        result["produce_info"] = jsonable(produce_info)

    # Special data format
    special_data_format = _get(tag, "special_data_format")
    if special_data_format:
        result["special_data_format"] = special_data_format

    # Specialty tag wrappers (only emit if present)
    has_specialty_wrapper = False

    message_params = _get(tag, "message_parameters")
    if message_params is not None:
        result["message_parameters"] = _specialty_to_dict(message_params)
        has_specialty_wrapper = True

    motion_group_params = _get(tag, "motion_group_parameters")
    if motion_group_params is not None:
        result["motion_group_parameters"] = _specialty_to_dict(motion_group_params)
        has_specialty_wrapper = True

    axis_params = _get(tag, "axis_parameters")
    if axis_params is not None:
        result["axis_parameters"] = _specialty_to_dict(axis_params)
        has_specialty_wrapper = True

    # Only emit special_data_attributes if no known wrapper was emitted
    if not has_specialty_wrapper:
        special_data_attrs = _get(tag, "special_data_attributes")
        if special_data_attrs:
            result["special_data_attributes"] = jsonable(special_data_attrs)

    # Value tree
    tag_data = _get(tag, "data")
    if tag_data is not None:
        with contextlib.suppress(Exception):
            result["value_tree"] = tag_node_to_dict(tag_data, max_depth, max_elements)

    return compact(result)
