"""JSON schemas (TypedDicts) for the specs that write tools accept.

These mirror py_l5x's spec dataclasses (``DataTypeSpec``, ``AOISpec``,
``ProgramSpec``, ``TagSpec`` and their parts) so that MCP clients see every
field, with a description, in the tool's input schema. Unknown keys are
rejected (``extra="forbid"``) so a misspelled field fails loudly instead of
being dropped.

Two keys differ from py_l5x, because the py_l5x names are Python-specific:
routine ``type`` (py_l5x ``type_``) and program ``program_class`` (py_l5x
``class_``). :func:`to_py_spec` and :func:`from_py_spec` convert between the
two, so specs returned by ``get_spec`` can be edited and passed straight back.
"""

from __future__ import annotations

import dataclasses
from typing import Annotated, Any, Literal, NotRequired, TypedDict

from py_l5x import AOISpec, DataTypeSpec, ProgramSpec, RoutineSpec, RungSpec, TagSpec
from pydantic import ConfigDict, Field, with_config

from l5x_mcp.registry import L5XError

_FORBID = ConfigDict(extra="forbid")

Access = Literal["Read/Write", "Read Only", "None"]
Limit = str | int | float


@with_config(_FORBID)
class MemberSpecDict(TypedDict):
    """One UDT member. BOOL members are packed into hidden SINT hosts for you."""

    name: str
    data_type: Annotated[
        str, Field(description="BOOL, SINT, INT, DINT, LINT, REAL, a UDT, AOI, ...")
    ]
    dimension: NotRequired[
        Annotated[int, Field(description="Array size; 0 (default) for a scalar.")]
    ]
    description: NotRequired[str]
    radix: NotRequired[
        Annotated[str | None, Field(description="e.g. Decimal, Hex, Float, ASCII.")]
    ]
    external_access: NotRequired[Access]
    engineering_unit: NotRequired[str]
    min: NotRequired[Limit | None]
    max: NotRequired[Limit | None]
    state0: NotRequired[Annotated[str, Field(description="BOOL zero-state text.")]]
    state1: NotRequired[Annotated[str, Field(description="BOOL one-state text.")]]
    external_logging: NotRequired[bool | None]


@with_config(_FORBID)
class DataTypeSpecDict(TypedDict):
    """A user-defined data type (UDT)."""

    name: str
    members: list[MemberSpecDict]
    description: NotRequired[str]
    family: NotRequired[
        Annotated[
            Literal["NoFamily", "StringFamily"],
            Field(
                description="StringFamily for a custom string type: members "
                "LEN (DINT) and DATA (SINT[n], radix ASCII)."
            ),
        ]
    ]


@with_config(_FORBID)
class RungSpecDict(TypedDict):
    """One ladder rung in neutral text, e.g. "XIC(Start)OTE(Run);"."""

    text: Annotated[str, Field(description="Neutral rung text ending in ';'.")]
    comment: NotRequired[str]


@with_config(_FORBID)
class RoutineSpecDict(TypedDict):
    """A routine: RLL (rungs) or ST (lines)."""

    name: Annotated[
        str,
        Field(
            description="Routine name. AOI routines must be Logic, Prescan, "
            "Postscan or EnableInFalse."
        ),
    ]
    type: NotRequired[Literal["RLL", "ST"]]
    rungs: NotRequired[list[RungSpecDict]]
    lines: NotRequired[
        Annotated[list[str], Field(description="ST source, one item per line.")]
    ]
    description: NotRequired[str]


@with_config(_FORBID)
class ParameterSpecDict(TypedDict):
    """One AOI parameter (EnableIn/EnableOut are added automatically)."""

    name: str
    data_type: Annotated[
        str,
        Field(
            description="Input/Output parameters must be atomic scalars "
            "(BOOL, DINT, REAL, ...); only InOut may be a structure or array."
        ),
    ]
    usage: NotRequired[Literal["Input", "Output", "InOut"]]
    required: NotRequired[
        Annotated[
            bool | None,
            Field(
                description="Appears as an argument in calls. Default: true "
                "for InOut, else false."
            ),
        ]
    ]
    visible: NotRequired[
        Annotated[
            bool | None,
            Field(description="Default: true for InOut and required parameters."),
        ]
    ]
    dimension: NotRequired[
        Annotated[int, Field(description="Array size (InOut only); 0 scalar.")]
    ]
    description: NotRequired[str]
    default: NotRequired[
        Annotated[Any, Field(description="Default value; not allowed for InOut.")]
    ]
    radix: NotRequired[str | None]
    external_access: NotRequired[Access | None]
    engineering_unit: NotRequired[str]
    min: NotRequired[Limit | None]
    max: NotRequired[Limit | None]
    state0: NotRequired[str]
    state1: NotRequired[str]
    operand_comments: NotRequired[
        Annotated[
            dict[str, str], Field(description='{operand: comment}, e.g. {".3": "x"}')
        ]
    ]


@with_config(_FORBID)
class LocalTagSpecDict(TypedDict):
    """One AOI local tag."""

    name: str
    data_type: str
    dimension: NotRequired[int]
    description: NotRequired[str]
    default: NotRequired[
        Annotated[
            Any,
            Field(description='Default value, e.g. 5 or {"PRE": 1000} for a TIMER.'),
        ]
    ]
    radix: NotRequired[str | None]
    external_access: NotRequired[Access]


@with_config(_FORBID)
class AOISpecDict(TypedDict):
    """An Add-On Instruction definition."""

    name: str
    parameters: list[ParameterSpecDict]
    local_tags: NotRequired[list[LocalTagSpecDict]]
    routines: NotRequired[
        Annotated[
            list[RoutineSpecDict],
            Field(description="Must include a 'Logic' routine."),
        ]
    ]
    revision: NotRequired[Annotated[str, Field(description='e.g. "1.0"')]]
    revision_note: NotRequired[str]
    description: NotRequired[str]
    vendor: NotRequired[str]
    execute_prescan: NotRequired[bool | None]
    execute_postscan: NotRequired[bool | None]
    execute_enable_in_false: NotRequired[bool | None]
    additional_help_text: NotRequired[str]
    metadata: NotRequired[
        Annotated[
            dict[str, str] | None,
            Field(description="Extra XML attributes (from get_spec); usually omit."),
        ]
    ]


@with_config(_FORBID)
class TagSpecDict(TypedDict):
    """A controller or program tag. Give data_type, or alias_for for an alias."""

    name: str
    data_type: NotRequired[str | None]
    dimensions: NotRequired[
        Annotated[
            int | list[int] | None,
            Field(description="Array size, or up to three sizes, e.g. [2, 3]."),
        ]
    ]
    description: NotRequired[str]
    value: NotRequired[
        Annotated[
            Any,
            Field(
                description="Initial value: scalar, string, {member: value} for a "
                'structure (e.g. {"PRE": 5000}), list for an array. Omit for '
                "type defaults."
            ),
        ]
    ]
    radix: NotRequired[str | None]
    external_access: NotRequired[Access | None]
    constant: NotRequired[bool | None]
    alias_for: NotRequired[
        Annotated[str | None, Field(description="Target operand of an alias tag.")]
    ]
    operand_comments: NotRequired[
        Annotated[
            dict[str, str] | None,
            Field(description='{operand: comment}, e.g. {".DN": "Done"}.'),
        ]
    ]
    operand_metadata: NotRequired[
        Annotated[
            dict[str, dict[str, str]] | None,
            Field(
                description="{operand: {key: text}}; keys max, min, "
                "engineering_unit, state0, state1, external_logging."
            ),
        ]
    ]
    metadata: NotRequired[
        Annotated[
            dict[str, str] | None,
            Field(description="Extra XML attributes (from get_spec); usually omit."),
        ]
    ]


@with_config(_FORBID)
class ProgramSpecDict(TypedDict):
    """A program with its tags and routines."""

    name: str
    tags: NotRequired[list[TagSpecDict]]
    routines: NotRequired[list[RoutineSpecDict]]
    main_routine: NotRequired[str | None]
    fault_routine: NotRequired[str | None]
    description: NotRequired[str]
    disabled: NotRequired[bool]
    program_class: NotRequired[
        Annotated[Literal["Standard", "Safety"] | None, Field(description="Class.")]
    ]
    metadata: NotRequired[
        Annotated[
            dict[str, str] | None,
            Field(description="Extra XML attributes (from get_spec); usually omit."),
        ]
    ]


def _routine(data: dict[str, Any]) -> RoutineSpec:
    fields = dict(data)
    if "type" in fields:
        fields["type_"] = fields.pop("type")
    fields["rungs"] = [RungSpec(**r) for r in fields.get("rungs") or []]
    fields["lines"] = list(fields.get("lines") or [])
    return RoutineSpec(**fields)


def _tag(data: dict[str, Any]) -> TagSpec:
    return TagSpec.from_dict(dict(data))


def to_py_spec(kind: str, data: dict[str, Any]) -> Any:
    """Build a py_l5x spec from a JSON spec dict.

    Args:
        kind: ``"data_type"``, ``"aoi"``, ``"program"``, ``"tag"`` or
            ``"routine"``.
        data: The spec dict, as described by the TypedDicts in this module.

    Returns:
        The py_l5x spec object.

    Raises:
        L5XError: If the dict has missing or unknown fields.
    """
    try:
        data = dict(data)
        if kind == "data_type":
            return DataTypeSpec.from_dict(data)
        if kind == "tag":
            return _tag(data)
        if kind == "routine":
            return _routine(data)
        if kind == "aoi":
            fields = dict(data)
            routines = fields.pop("routines", [])
            spec = AOISpec.from_dict({**fields, "routines": []})
            spec.routines = [_routine(r) for r in routines]
            return spec
        if kind == "program":
            fields = dict(data)
            if "program_class" in fields:
                fields["class_"] = fields.pop("program_class")
            return ProgramSpec(
                **{
                    **fields,
                    "tags": [_tag(t) for t in fields.get("tags") or []],
                    "routines": [_routine(r) for r in fields.get("routines") or []],
                }
            )
    except (TypeError, KeyError) as exc:
        raise L5XError(f"Invalid {kind} spec: {exc}") from exc
    raise ValueError(f"unknown spec kind {kind!r}")


_RENAMED = {"type_": "type", "class_": "program_class"}


def _default(f: dataclasses.Field) -> Any:
    if f.default is not dataclasses.MISSING:
        return f.default
    if f.default_factory is not dataclasses.MISSING:
        return f.default_factory()
    return dataclasses.MISSING


def from_py_spec(spec: Any) -> Any:
    """Convert a py_l5x spec to the JSON form accepted by the write tools.

    Fields equal to their default are left out (required fields are always
    kept), tuples become lists, and ``type_``/``class_`` are renamed to
    ``type``/``program_class``. The result passes back through
    :func:`to_py_spec` unchanged.

    Args:
        spec: A py_l5x spec, or a value nested inside one.

    Returns:
        JSON-friendly data.
    """
    if dataclasses.is_dataclass(spec) and not isinstance(spec, type):
        out = {}
        for f in dataclasses.fields(spec):
            value = getattr(spec, f.name)
            default = _default(f)
            if default is not dataclasses.MISSING and value == default:
                continue
            out[_RENAMED.get(f.name, f.name)] = from_py_spec(value)
        return out
    if isinstance(spec, list | tuple):
        return [from_py_spec(v) for v in spec]
    if isinstance(spec, dict):
        return {k: from_py_spec(v) for k, v in spec.items()}
    return spec
