"""Tools for exploring programs and their routines in L5X projects.

This module provides functions to list programs, get program details,
and view routine logic (RLL rungs, ST lines, etc.) from L5X exports.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any, NamedTuple

from py_l5x.parsers.program import Program
from py_l5x.parsers.project import Project
from py_l5x.parsers.routine import Routine, RoutinesCollection

from l5x_mcp.operand_resolver import OperandResolver
from l5x_mcp.registry import L5XError, ProjectRegistry, lookup
from l5x_mcp.serialize import compact, first_line, tag_summary
from l5x_mcp.tools.search import _strip_st_comments_per_line

# Maximum rungs to return by default; can be overridden in tests
MAX_RUNGS_DEFAULT = 200

# Size budget (compact JSON characters) for routine logic and AOI logic
MAX_CHARS_DEFAULT = 8000
MAX_CHARS_MIN = 1000
MAX_CHARS_MAX = 100000

# Routine detail modes for get_routine_logic
DETAIL_MODES = ("full", "outline", "logic")

# String fields cut, in order, when a single item alone exceeds the budget
_SHRINKABLE_KEYS = ("comment", "text")

# Response keys for operand bookkeeping (see _OperandLedger)
_UNPARSED_KEY = "operands_unparsed"
_OMITTED_KEY = "operands_omitted"

# Shown when a non-constant value was included in the operands
VALUES_NOTE = "values are the offline snapshot saved in the export, not live data"


def _routine_type(routine: Routine) -> str:
    """Return the routine's language (RLL, ST, ...), inferring it when omitted.

    The routine in a rung-level component export (Rung2 from SequenceRoutine)
    has no ``Type`` attribute, but its ``RLLContent``/``STContent`` still
    identifies the language.

    Args:
        routine: The routine to inspect.

    Returns:
        "RLL", "ST", another declared type, or "" if it cannot be determined.
    """
    if routine.type_:
        return routine.type_
    if routine.rungs:
        return "RLL"
    if routine.st_lines:
        return "ST"
    return ""


def _resolve_routine_container(
    project: Project, program: str | None, aoi: str | None
) -> tuple[str, str, RoutinesCollection]:
    """Resolve which container (program or AOI) to use for routines.

    Exactly one of program/aoi should be given. If neither: if the project
    is a component export of a single program or AOI, use it; else raise
    L5XError explaining to pass `program` or `aoi`. If both → L5XError.

    Args:
        project: The loaded Project object.
        program: Name of a program, or None.
        aoi: Name of an AOI, or None.

    Returns:
        Tuple of (container_kind: "program"|"aoi", container_name: str,
        RoutinesCollection for that container).

    Raises:
        L5XError: If both program and aoi are given, or if neither and
                  auto-detection fails.
        ItemNotFoundError: If named program/AOI is not found.
    """
    if program and aoi:
        raise L5XError("Cannot specify both 'program' and 'aoi'. Pass one or neither.")

    if program:
        prog = lookup(project.programs, program, "Program")
        return "program", prog.name, prog.routines

    if aoi:
        aoi_def = lookup(project.aois, aoi, "AOI")
        return "aoi", aoi_def.name, aoi_def.routines

    # Neither given; try auto-detection for component exports
    # Program export: exactly 1 program (AOIs may be present as dependencies)
    if len(project.programs) == 1:
        prog = list(project.programs.values())[0]
        return "program", prog.name, prog.routines

    # AOI export: no programs, exactly 1 AOI
    if len(project.aois) == 1 and len(project.programs) == 0:
        aoi_def = list(project.aois.values())[0]
        return "aoi", aoi_def.name, aoi_def.routines

    raise L5XError(
        "No container specified. Pass 'program' or 'aoi' argument. "
        "Alternatively, use a component export of a single program or AOI."
    )


def list_programs(registry: ProjectRegistry, path: str | None = None) -> dict[str, Any]:
    """List all programs in a project with basic metadata.

    Returns name, description (first line), main_routine, disabled flag (if true),
    is_safety flag (if true), routine count, tag count, and scheduled task (if any).

    Args:
        registry: ProjectRegistry to load from.
        path: Project file path (None for auto-discovery).

    Returns:
        Dict with keys: file, programs (array of program objects).
    """
    resolved_path, project = registry.get_with_path(path)

    programs_list = []
    for prog in project.programs.values():
        # Find which task schedules this program
        task_name = None
        for task in project.tasks.values():
            if prog.name in task.scheduled_program_names:
                task_name = task.name
                break

        prog_dict = {
            "name": prog.name,
            "description": first_line(prog.description),
            "main_routine": prog.main_routine_name or "",
            "routine_count": len(prog.routines),
            "tag_count": len(prog.tags),
        }
        if prog.disabled:
            prog_dict["disabled"] = True
        if prog.is_safety:
            prog_dict["is_safety"] = True
        if task_name:
            prog_dict["task"] = task_name

        programs_list.append(prog_dict)

    return {
        "file": registry.relpath(resolved_path),
        "programs": programs_list,
    }


def get_program(
    registry: ProjectRegistry,
    name: str,
    include_tags: bool = False,
    path: str | None = None,
) -> dict[str, Any]:
    """Get detailed information about a program.

    Includes name, full description, main routine name, disabled/test_edits/
    use_as_folder/class flags, is_safety flag, scheduled task (if any),
    list of routines (with type, description, rung/line counts), and tag_count.

    The per-tag list is omitted by default (it can be large); pass
    include_tags=True to add it, or use list_tags(scope=<program name>).
    When included, each tag is a summary via tag_summary(): name, data_type,
    description, tag_type, usage, external_access, and dimensions/constant/
    alias_for where present.

    Args:
        registry: ProjectRegistry to load from.
        name: Program name (case-insensitive lookup).
        include_tags: If True, include the "tags" list of tag summaries.
        path: Project file path (None for auto-discovery).

    Returns:
        Dict with program details including routines and tags arrays.

    Raises:
        ItemNotFoundError: If program not found.
    """
    resolved_path, project = registry.get_with_path(path)

    prog: Program = lookup(project.programs, name, "Program")

    # Find scheduled task
    task_name = None
    for task in project.tasks.values():
        if prog.name in task.scheduled_program_names:
            task_name = task.name
            break

    # Build routines list
    routines_list = []
    for routine in prog.routines.values():
        routine_kind = _routine_type(routine)
        routine_dict = {
            "name": routine.name,
            "type": routine_kind,
            "description": first_line(routine.description),
        }
        if routine_kind == "RLL":
            routine_dict["rung_count"] = len(routine.rungs)
        elif routine_kind == "ST":
            routine_dict["line_count"] = len(routine.st_lines)
        routines_list.append(routine_dict)

    result = {
        "file": registry.relpath(resolved_path),
        "name": prog.name,
        "description": prog.description or "",
        "main_routine": prog.main_routine_name or "",
        "disabled": prog.disabled,
        "test_edits": prog.test_edits,
        "use_as_folder": prog.use_as_folder,
        "class": prog.class_ or "",
        "is_safety": prog.is_safety,
        "routines": routines_list,
        "tag_count": len(prog.tags),
    }
    if task_name:
        result["task"] = task_name

    if include_tags:
        result["tags"] = [tag_summary(tag) for tag in prog.tags.values()]
    else:
        result["note"] = (
            f'Tag list omitted. Use list_tags(scope="{prog.name}") for the tags, '
            "or pass include_tags=True."
        )

    return compact(result)


def list_routines(
    registry: ProjectRegistry,
    program: str | None = None,
    aoi: str | None = None,
    path: str | None = None,
) -> dict[str, Any]:
    """List all routines in a program or AOI.

    Args:
        registry: ProjectRegistry to load from.
        program: Program name (case-insensitive), or None.
        aoi: AOI name (case-insensitive), or None.
        path: Project file path (None for auto-discovery).

    Returns:
        Dict with keys: file, container (kind and name), routines (array).

    Raises:
        L5XError: If both/neither program and aoi given, or auto-detection fails.
        ItemNotFoundError: If named program/AOI not found.
    """
    resolved_path, project = registry.get_with_path(path)

    container_kind, container_name, routines_collection = _resolve_routine_container(
        project, program, aoi
    )

    routines_list = []
    for routine in routines_collection.values():
        routine_kind = _routine_type(routine)
        routine_dict = {
            "name": routine.name,
            "type": routine_kind,
            "description": first_line(routine.description),
        }
        if routine_kind == "RLL":
            routine_dict["rung_count"] = len(routine.rungs)
        elif routine_kind == "ST":
            routine_dict["line_count"] = len(routine.st_lines)
        routines_list.append(routine_dict)

    return {
        "file": registry.relpath(resolved_path),
        "container": {
            "kind": container_kind,
            "name": container_name,
        },
        "routines": routines_list,
    }


def json_size(value: Any) -> int:
    """Return the length of ``value`` serialized as compact JSON.

    This is the size measured against ``max_chars``.

    Args:
        value: A JSON-serializable value.

    Returns:
        Number of characters in the compact JSON text (no spaces).
    """
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False))


class OutputBudget:
    """Running compact-JSON size of a response, checked against ``max_chars``.

    Sizes are summed as items are appended, so the response is never
    re-serialized per item.
    """

    def __init__(self, base_size: int, max_chars: int, reserve: int = 0) -> None:
        """Start a budget.

        Args:
            base_size: Size of the response before items are appended, with
                the (empty) items array already counted.
            max_chars: Maximum allowed size.
            reserve: Characters held back for keys added after the items.
        """
        self.size = base_size
        self.max_chars = max_chars
        self.reserve = reserve
        self.count = 0

    def _separator(self) -> int:
        return 1 if self.count else 0

    def fits(self, item_size: int) -> bool:
        """Return True if an item of ``item_size`` characters can be appended."""
        total = self.size + self._separator() + item_size + self.reserve
        return total <= self.max_chars

    def add(self, item_size: int) -> None:
        """Account for an appended item of ``item_size`` characters."""
        self.size += self._separator() + item_size
        self.count += 1


def validate_max_chars(max_chars: int) -> None:
    """Raise L5XError unless max_chars is an int in [MAX_CHARS_MIN, MAX_CHARS_MAX].

    Args:
        max_chars: The requested budget.

    Raises:
        L5XError: If max_chars is out of range or not an integer.
    """
    if (
        isinstance(max_chars, bool)
        or not isinstance(max_chars, int)
        or not MAX_CHARS_MIN <= max_chars <= MAX_CHARS_MAX
    ):
        raise L5XError(
            f"max_chars must be an integer from {MAX_CHARS_MIN} to "
            f"{MAX_CHARS_MAX}, got {max_chars!r}."
        )


def _validate_detail(detail: str) -> None:
    """Raise L5XError unless detail is one of DETAIL_MODES."""
    if detail not in DETAIL_MODES:
        raise L5XError(
            f"Invalid detail {detail!r}. Use one of: 'full' (number, comment, "
            "text), 'outline' (number and comment only), 'logic' (number and "
            "text only)."
        )


def _resolve_range(
    start_rung: int | None, end_rung: int | None
) -> tuple[int, int | None]:
    """Validate the requested range and return (start, end) numbers.

    Args:
        start_rung: Start number (0-based inclusive), or None for 0.
        end_rung: End number (0-based inclusive), or None for no upper bound.

    Returns:
        Tuple of (start, end), where end is None if unbounded.

    Raises:
        L5XError: If the range is negative or start > end.
    """
    start = 0 if start_rung is None else start_rung
    if start < 0 or (end_rung is not None and end_rung < 0):
        raise L5XError("start_rung and end_rung must be non-negative.")
    if end_rung is not None and start > end_rung:
        raise L5XError("start_rung must be <= end_rung.")
    return start, end_rung


def _in_range(number: int, start: int, end: int | None) -> bool:
    return number >= start and (end is None or number <= end)


def _tidy(item: dict[str, Any]) -> dict[str, Any]:
    """Drop empty optional fields; ``number`` and ``text`` are always kept."""
    return {
        k: v
        for k, v in item.items()
        if k in ("number", "text")
        or (v is not None and v != "" and v != [] and v != {})
    }


def _with_cut_field(item: dict[str, Any], key: str, value: str) -> dict[str, Any]:
    """Return ``item`` with ``key`` replaced by a cut ``value``, flagged as cut."""
    return _tidy({**item, key: value, f"{key}_truncated": True})


def _shrink_to_fit(
    item: dict[str, Any], budget: OutputBudget, extra: int = 0
) -> dict[str, Any]:
    """Cut the string fields of one oversized item until it fits the budget.

    The comment is cut first, then the text. Each cut keeps the longest prefix
    that fits (found by binary search) and sets ``<field>_truncated: true``.

    Args:
        item: The item that does not fit on its own.
        budget: The budget it must fit in.
        extra: Characters the item's operand bookkeeping adds on top.

    Returns:
        The item (the same object if nothing needed cutting). It may still
        exceed the budget if no cut suffices.
    """
    for key in _SHRINKABLE_KEYS:
        value = item.get(key)
        if not value or budget.fits(json_size(item) + extra):
            continue
        # The full value is known not to fit; find the longest prefix that does.
        lo, hi = 0, len(value) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            cut = _with_cut_field(item, key, value[:mid])
            if budget.fits(json_size(cut) + extra):
                lo = mid
            else:
                hi = mid - 1
        item = _with_cut_field(item, key, value[:lo])
    return item


class _Candidate(NamedTuple):
    """One rung or line offered for output, with the operands it references."""

    number: int
    item: dict[str, Any]
    operands: dict[str, dict[str, Any]] | None = None  # None: not resolved
    unparsed: bool = False  # the text could not be parsed for operands


class _OperandPlan(NamedTuple):
    """What keeping one candidate would add to the operand bookkeeping."""

    number: int
    delta: int  # characters added to the response by the operand keys
    entries: dict[str, dict[str, Any]]  # operand entries not yet in the map
    unparsed: bool
    omitted: bool  # its operands were left out to make room


def _append_cost(values: list[int], key: str, number: int) -> int:
    """Return the characters that appending ``number`` to ``key``'s list adds."""
    if values:
        return len(str(number)) + 1  # comma, then the number
    # The first number also adds the key member and its separating comma
    return json_size({key: []}) - 2 + 1 + len(str(number))


class _OperandLedger:
    """The operands map and side lists for the rungs/lines kept so far.

    Operand bookkeeping is charged to the same size budget as the items:
    ``plan`` returns what a candidate would add, and ``commit`` records it
    once the candidate is kept. Each operand is counted once, the first time
    it appears.
    """

    def __init__(self) -> None:
        self.entries: dict[str, dict[str, Any]] = {}
        self.unparsed: list[int] = []
        self.omitted: list[int] = []

    def plan(self, cand: _Candidate, keep: bool) -> _OperandPlan:
        """Plan adding ``cand``. With ``keep=False`` its operands are left out."""
        new: dict[str, dict[str, Any]] = {}
        delta = 0
        count = len(self.entries)
        if keep and cand.operands:
            for text, entry in cand.operands.items():
                if text not in self.entries:
                    # One member of the operands object; a comma after the first
                    delta += json_size({text: entry}) - 2 + (1 if count else 0)
                    count += 1
                    new[text] = entry
        omitted = not keep and bool(cand.operands)
        if cand.unparsed:
            delta += _append_cost(self.unparsed, _UNPARSED_KEY, cand.number)
        if omitted:
            delta += _append_cost(self.omitted, _OMITTED_KEY, cand.number)
        return _OperandPlan(cand.number, delta, new, cand.unparsed, omitted)

    def commit(self, plan: _OperandPlan) -> None:
        """Record a planned candidate as kept."""
        self.entries.update(plan.entries)
        if plan.unparsed:
            self.unparsed.append(plan.number)
        if plan.omitted:
            self.omitted.append(plan.number)


@dataclass
class _Selection:
    """Result of selecting items within the budget."""

    items: list[dict[str, Any]] = field(default_factory=list)
    next_start: int | None = None  # number of the first omitted item
    stop_reason: str | None = None  # "cap" or "budget" when items were omitted
    content_truncated: bool = False  # the first item had fields cut
    ledger: _OperandLedger = field(default_factory=_OperandLedger)


def _select_items(
    candidates: Iterable[_Candidate],
    budget: OutputBudget,
    cap: int,
) -> _Selection:
    """Take items in order while they fit the budget and the item cap.

    Candidates are consumed lazily, so items after the stop point are not
    built beyond the first omitted one. The first item is always returned: if
    it does not fit with its operands, they are left out first (recorded in
    ``operands_omitted``), then its text is cut if still needed.

    Args:
        candidates: Candidates in routine order.
        budget: Running size budget; kept items and their operands are added.
        cap: Maximum number of items to return.

    Returns:
        The selected items, the operand ledger, and, if some were omitted, the
        first omitted number and the reason.
    """
    selection = _Selection()
    ledger = selection.ledger
    for cand in candidates:
        if len(selection.items) >= cap:
            selection.next_start, selection.stop_reason = cand.number, "cap"
            break
        plan = ledger.plan(cand, keep=True)
        item = cand.item
        if not budget.fits(json_size(item) + plan.delta):
            if selection.items:
                selection.next_start, selection.stop_reason = cand.number, "budget"
                break
            plan = ledger.plan(cand, keep=False)
            item = _shrink_to_fit(item, budget, plan.delta)
            selection.content_truncated = item is not cand.item
        budget.add(json_size(item) + plan.delta)
        ledger.commit(plan)
        selection.items.append(item)
    return selection


def _budget_note(next_start: int, max_chars: int) -> str:
    return (
        f"Stopped at max_chars={max_chars}. Continue with start_rung={next_start}; "
        'use detail="outline" to skim the rest, or a narrower range / larger '
        "max_chars."
    )


def _continuation_reserve(total: int, max_chars: int) -> int:
    """Upper bound on the characters taken by the truncation keys.

    Numbers are bounded by ``total`` (rung and line numbers are below it), so
    the digits used here are never fewer than the real ones.
    """
    trailer = {
        "truncated": True,
        "returned_rungs": total,
        "next_start_rung": total,
        "note": _budget_note(total, max_chars),
    }
    return json_size(trailer) + 1  # +1 for the comma that separates the key


def _minimal_item_size(total: int) -> int:
    """Upper bound on a first item after cutting, with its comma.

    Any item of a routine with ``total`` rungs/lines, once its fields are cut,
    is no larger than this, so one item is always able to fit.
    """
    item = {
        "number": total,
        "text": "",
        "comment_truncated": True,
        "text_truncated": True,
    }
    return json_size(item) + 1


def _fit_description(
    envelope: dict[str, Any], key: str | None, total: int, max_chars: int
) -> dict[str, Any]:
    """Cut the routine description, if needed, so one item still fits.

    The description is part of the envelope, so it is cut (longest prefix that
    fits, found by binary search) when the envelope plus the continuation keys
    plus one minimal item would exceed max_chars.

    Args:
        envelope: Response keys (including description).
        key: Items key counted in the size (None if there are no items).
        total: Number of rungs/lines in the routine.
        max_chars: Size budget.

    Returns:
        {} if the description is unchanged; otherwise the replacement
        "description" (possibly "") and "description_truncated": True.
    """
    description = envelope.get("description") or ""
    if not description:
        return {}
    reserve = _continuation_reserve(total, max_chars) + _minimal_item_size(total)
    if "operands" in envelope:
        # The first item may add both operand side lists (see _OperandLedger)
        reserve += _append_cost([], _UNPARSED_KEY, total)
        reserve += _append_cost([], _OMITTED_KEY, total)
    items_placeholder = {key: []} if key else {}

    def fits(text: str) -> bool:
        probe = {
            **envelope,
            **items_placeholder,
            "description": text,
            "description_truncated": True,
        }
        return json_size(probe) + reserve <= max_chars

    if fits(description):
        return {}
    # The full description is known not to fit; find the longest prefix that does.
    lo, hi = 0, len(description) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if fits(description[:mid]):
            lo = mid
        else:
            hi = mid - 1
    return {"description": description[:lo], "description_truncated": True}


def _budgeted_items(
    envelope: dict[str, Any],
    key: str,
    unit: str,
    make_candidates: Callable[[], Iterable[_Candidate]],
    total: int,
    max_chars: int,
    with_operands: bool = False,
) -> dict[str, Any]:
    """Select items for ``key`` so the whole response stays within max_chars.

    Args:
        envelope: Response keys other than the items (counted in the budget).
        key: Response key holding the items ("rungs" or "lines").
        unit: Singular noun for the items, used in notes ("rung" or "line").
        make_candidates: Factory returning a fresh candidate iterator.
        total: Number of rungs/lines in the routine.
        max_chars: Size budget.
        with_operands: Also return the "operands" map and its side lists.

    Returns:
        Dict with the items under ``key``, any description cut (see
        _fit_description), the operands keys when requested, plus, when output
        was cut, truncated, returned_rungs, next_start_rung (if items were
        omitted), and note.
    """
    if with_operands:
        envelope = {**envelope, "operands": {}}  # placeholder, so it is budgeted
    desc_keys = _fit_description(envelope, key, total, max_chars)
    envelope = {**envelope, **desc_keys}
    base = json_size({**envelope, key: []})
    selection = _select_items(
        make_candidates(), OutputBudget(base, max_chars), MAX_RUNGS_DEFAULT
    )
    ledger = selection.ledger
    if (
        selection.next_start is not None
        or selection.content_truncated
        or ledger.omitted
    ):
        # Re-run with room reserved for the truncation keys added below.
        reserve = _continuation_reserve(total, max_chars)
        selection = _select_items(
            make_candidates(),
            OutputBudget(base, max_chars, reserve),
            MAX_RUNGS_DEFAULT,
        )
        ledger = selection.ledger

    out: dict[str, Any] = {key: selection.items, **desc_keys}
    if with_operands:
        out["operands"] = ledger.entries
        if ledger.unparsed:
            out[_UNPARSED_KEY] = ledger.unparsed
        if ledger.omitted:
            out[_OMITTED_KEY] = ledger.omitted
    if (
        selection.next_start is None
        and not selection.content_truncated
        and not ledger.omitted
    ):
        return out

    out["truncated"] = True
    out["returned_rungs"] = len(selection.items)
    if selection.next_start is not None:
        out["next_start_rung"] = selection.next_start
        if selection.stop_reason == "cap":
            out["note"] = (
                f"Returned {len(selection.items)} items (cap). "
                f"Pass start_rung={selection.next_start} to continue."
            )
        else:
            out["note"] = _budget_note(selection.next_start, max_chars)
    elif selection.content_truncated:
        out["note"] = (
            f"The first {unit} was cut to fit max_chars={max_chars}; "
            "raise max_chars to see all of it."
        )
    else:
        out["note"] = (
            f"Operands of the first {unit} were left out to fit "
            f"max_chars={max_chars}; raise max_chars to see them."
        )
    return out


def _rll_operands(
    resolver: OperandResolver | None, text: str | None
) -> tuple[dict[str, dict[str, Any]] | None, bool]:
    """Return (operands, unparsed) for one rung; (None, False) if not wanted."""
    if resolver is None:
        return None, False
    try:
        return resolver.operands_for_rung(text or ""), False
    except ValueError:
        return None, True


def _st_operands(
    resolver: OperandResolver | None, code: str
) -> tuple[dict[str, dict[str, Any]] | None, bool]:
    """Return (operands, unparsed) for one comment-stripped ST line."""
    if resolver is None:
        return None, False
    try:
        return resolver.operands_for_st_lines([code]), False
    except ValueError:
        return None, True


def _rung_candidates(
    rtn: Routine,
    detail: str,
    start: int,
    end: int | None,
    resolver: OperandResolver | None,
) -> Iterator[_Candidate]:
    """Yield a candidate for each RLL rung in range, built lazily."""
    for rung in rtn.rungs:
        if not _in_range(rung.number, start, end):
            continue
        item: dict[str, Any] = {"number": rung.number}
        if detail in ("full", "outline"):
            item["comment"] = rung.comment or ""
        if detail in ("full", "logic"):
            item["text"] = rung.text
        operands, unparsed = _rll_operands(resolver, rung.text)
        yield _Candidate(rung.number, _tidy(item), operands, unparsed)


def _line_candidates(
    lines: list[Any],
    detail: str,
    start: int,
    end: int | None,
    resolver: OperandResolver | None,
) -> Iterator[_Candidate]:
    """Yield a candidate for each ST line in range, built lazily.

    Comments are stripped over the whole routine first because block comments
    can span lines. Line numbers keep their original values. Operands are read
    from the comment-stripped code, in every detail mode.
    """
    code_lines = _strip_st_comments_per_line([line.text for line in lines])
    for line, code in zip(lines, code_lines, strict=True):
        if not _in_range(line.number, start, end):
            continue
        if detail == "full":
            text = line.text
        elif detail == "logic":
            if not code:
                continue
            text = code
        else:  # outline: only lines that contain a comment
            if code == line.text.rstrip():
                continue
            text = line.text
        operands, unparsed = _st_operands(resolver, code)
        yield _Candidate(
            line.number, {"number": line.number, "text": text}, operands, unparsed
        )


def get_routine_logic(
    registry: ProjectRegistry,
    routine: str,
    program: str | None = None,
    aoi: str | None = None,
    start_rung: int | None = None,
    end_rung: int | None = None,
    detail: str = "full",
    max_chars: int = MAX_CHARS_DEFAULT,
    include_operands: bool = True,
    include_values: bool = False,
    path: str | None = None,
) -> dict[str, Any]:
    """Get the logic of a routine (RLL rungs or ST lines), within a size budget.

    detail (choose by what you need):
    - "logic": the cheapest way to skim what the code does. Number and text
      only (ST: code with comments removed; lines that become empty are
      dropped, and numbers keep their original values).
    - "outline": the rung documentation. Number and comment only; rungs without
      a comment appear as {"number": n} so gaps stay visible. ST: only lines
      containing a comment. Comment-heavy routines are mostly comments, so use
      outline with a start/end range. No operands are returned in this mode.
    - "full" (default): both. Number, comment and text (ST: each line as written).

    operands (include_operands, default True; not in outline mode): a map from
    each operand written in the returned rungs/lines to its description: desc,
    type, tag_desc (tag description when the member has none), alias_for,
    const, value (constants), scope (when not the container's own tag), and
    indexed. Each operand appears once, even if used in several rungs. The key
    is omitted when there are none. Rungs whose text cannot be parsed are listed
    in operands_unparsed. include_values adds current values of non-constant
    tags; these come from the offline snapshot in the export, not live data
    (values_note says so).

    max_chars (default 8000, range 1000-100000) bounds the compact JSON size of
    the whole response, including the description and operands. Items are added
    in order until the next one would exceed it. At most 200 items are returned
    per call. The first item is always returned: its operands are left out
    first (operands_omitted), then its text is cut (comment_truncated /
    text_truncated). A description too long to leave room for one item is cut
    and flagged with description_truncated.

    When output stops early, truncated is true, returned_rungs is the count
    returned, and next_start_rung is the first omitted number. Continue with
    start_rung=next_start_rung, or use a narrower range or a larger max_chars.
    For a first pass on a long routine, use detail="logic".

    Args:
        registry: ProjectRegistry to load from.
        routine: Routine name (case-insensitive lookup).
        program: Program name (case-insensitive), or None.
        aoi: AOI name (case-insensitive), or None.
        start_rung: Start rung/line number (0-based inclusive), or None for 0.
        end_rung: End rung/line number (0-based inclusive), or None for last.
        detail: "full", "outline", or "logic" (see above).
        max_chars: Response size budget, 1000-100000 (default 8000).
        include_operands: Add the operands map (not in outline mode).
        include_values: Add current values of non-constant operands. Requires
            include_operands.
        path: Project file path (None for auto-discovery).

    Returns:
        Dict with file, container, routine name/type/description, detail, and:
        - RLL: total_rungs, rungs (array).
        - ST: total_lines, lines (array).
        - operands, operands_unparsed, operands_omitted, values_note when
          applicable.
        - Other: note about unsupported type.
        When output was cut: truncated, returned_rungs, next_start_rung (if items
        were omitted), and note.

    Raises:
        L5XError: If detail or max_chars is invalid, include_values is given
            without include_operands, both/neither program and aoi are given,
            the range is invalid, etc.
        ItemNotFoundError: If routine/program/AOI not found.
    """
    _validate_detail(detail)
    validate_max_chars(max_chars)
    if include_values and not include_operands:
        raise L5XError("include_values=True requires include_operands=True.")

    resolved_path, project = registry.get_with_path(path)

    container_kind, container_name, routines_collection = _resolve_routine_container(
        project, program, aoi
    )

    rtn: Routine = lookup(routines_collection, routine, "Routine")
    routine_kind = _routine_type(rtn)
    start, end = _resolve_range(start_rung, end_rung)

    with_operands = (
        include_operands and detail != "outline" and routine_kind in ("RLL", "ST")
    )
    resolver = (
        OperandResolver(
            project,
            container_kind,
            container_name,
            include_values=include_values,
        )
        if with_operands
        else None
    )

    result: dict[str, Any] = {
        "file": registry.relpath(resolved_path),
        "container": {
            "kind": container_kind,
            "name": container_name,
        },
        "routine": rtn.name,
        "type": routine_kind,
        "description": rtn.description or "",
        "detail": detail,
    }
    if resolver is not None and include_values:
        result["values_note"] = VALUES_NOTE  # dropped below if no value is shown

    if routine_kind == "RLL":
        result["total_rungs"] = len(rtn.rungs)
        result.update(
            _budgeted_items(
                result,
                "rungs",
                "rung",
                lambda: _rung_candidates(rtn, detail, start, end, resolver),
                len(rtn.rungs),
                max_chars,
                with_operands=resolver is not None,
            )
        )

    elif routine_kind == "ST":
        lines = rtn.st_lines
        result["total_lines"] = len(lines)
        result.update(
            _budgeted_items(
                result,
                "lines",
                "line",
                lambda: _line_candidates(lines, detail, start, end, resolver),
                len(lines),
                max_chars,
                with_operands=resolver is not None,
            )
        )

    else:
        # FBD, SFC, or other unsupported type
        result["note"] = f"py_l5x does not parse {routine_kind} routines yet."
        result.update(_fit_description(result, None, 0, max_chars))

    if not any(
        "value" in entry and not entry.get("const")
        for entry in result.get("operands", {}).values()
    ):
        result.pop("values_note", None)

    return compact(result)
