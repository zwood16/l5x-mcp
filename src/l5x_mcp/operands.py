"""Extract tag operand candidates from ladder (RLL) rung text and ST lines.

This module is pure text processing (no py_l5x objects, no MCP concerns). The
strings it returns are *candidates*: they are not resolved here. Pass each one
through :func:`l5x_mcp.operand_paths.parse_operand` and resolution to find the
tag. Candidates may include things that are not tags, such as enum keywords
(``DCS(dcs1,ACTIVE,...)`` gives ``ACTIVE``), routine names or labels, so
resolution must filter those out.

Candidates keep the forms that ``parse_operand`` accepts: an optional
``\\Prog.`` prefix, ``Ident(:\\w+)*`` base names (``Local:1:I``), ``.member``,
``.bit`` and ``[subscript]`` segments. A subscript with a runtime expression
keeps the whole token (``b[idx]``) and also yields the operands inside it
(``idx``).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

__all__ = [
    "InstructionCall",
    "extract_rll_operands",
    "extract_st_operands",
    "instruction_arg_kinds",
    "parse_rll",
    "strip_st_comments",
]


@dataclass(frozen=True)
class InstructionCall:
    """One instruction call in rung text, such as ``XIC(a)``.

    Attributes:
        name: The mnemonic as written, e.g. ``"XIC"``.
        args: Raw top-level argument strings, stripped. Nested calls and
            subscripts stay inside their argument. ``NOP()`` has no arguments.
    """

    name: str
    args: tuple[str, ...]


#: Kinds of non-operand arguments, by instruction name and argument position.
#: Positions not listed are ``"operand"`` and are scanned for tags.
instruction_arg_kinds: Mapping[str, tuple[str, ...]] = {
    "JSR": ("routine",),
    "JMP": ("label",),
    "LBL": ("label",),
}

_CALL_START = re.compile(r"([A-Za-z_]\w*)\s*\(")
_HEAD = re.compile(r"\\?[A-Za-z_]\w*(?::\w+)*")
_SEGMENT = re.compile(r"\.[A-Za-z_]\w*|\.\d+")
# Typed literals (T#5s, DT#..., REAL#1.5, 16#FF) and plain numbers (1, 2.5, 1.5e3).
_LITERAL = re.compile(
    r"(?:[A-Za-z_]\w*|\d\w*)#[\w.:-]*|\d\w*(?:\.\d+)?(?:[eE][+-]?\d+)?"
)
_EXPRESSION_INSTRUCTIONS = frozenset({"CPT", "CMP"})
_EXPRESSION_KEYWORDS = frozenset({"AND", "OR", "XOR", "NOT", "MOD"})
_ST_KEYWORDS = frozenset(
    {
        "IF",
        "THEN",
        "ELSIF",
        "ELSE",
        "END_IF",
        "CASE",
        "OF",
        "END_CASE",
        "FOR",
        "TO",
        "BY",
        "DO",
        "END_FOR",
        "WHILE",
        "END_WHILE",
        "REPEAT",
        "UNTIL",
        "END_REPEAT",
        "EXIT",
        "RETURN",
        "AND",
        "OR",
        "XOR",
        "NOT",
        "MOD",
        "TRUE",
        "FALSE",
    }
)


def parse_rll(text: str) -> list[InstructionCall]:
    """Split neutral rung text into instruction calls, in textual order.

    Branch brackets ``[ ... , ... ]`` are structure, not subscripts, and are
    skipped. Commas and semicolons between instructions are skipped. Argument
    splitting honours nested parentheses and brackets (subscripts) and
    single-quoted string literals (``$`` escapes the next character, and
    ``''`` is an escaped quote).

    Args:
        text: Neutral rung text, e.g. ``"[XIC(a) ,XIO(b) ]OTE(c);"``.

    Returns:
        Instruction calls in the order they appear. Calls nested inside an
        argument are not returned separately.

    Raises:
        ValueError: If the text has unbalanced brackets or parentheses,
            an unterminated string, or unexpected characters between
            instructions.
    """
    calls: list[InstructionCall] = []
    branch_depth = 0
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace() or ch in ",;":
            i += 1
        elif ch == "[":
            branch_depth += 1
            i += 1
        elif ch == "]":
            branch_depth -= 1
            if branch_depth < 0:
                raise ValueError(f"Unbalanced ']' at {i} in rung text {text!r}")
            i += 1
        else:
            match = _CALL_START.match(text, i)
            if match is None:
                raise ValueError(f"Unexpected {ch!r} at {i} in rung text {text!r}")
            args, end = _read_args(text, match.end() - 1)
            calls.append(InstructionCall(match.group(1), args))
            i = end
    if branch_depth:
        raise ValueError(f"Unbalanced '[' in rung text {text!r}")
    return calls


def extract_rll_operands(text: str) -> list[str]:
    """Return unique operand candidates referenced by a rung's neutral text.

    Each instruction argument is scanned for identifier paths. Numeric and
    typed literals, string literals, ``?`` placeholders, function names
    (tokens followed by ``(``) and, inside ``CPT``/``CMP``, the keywords
    ``AND OR XOR NOT MOD`` are dropped. Arguments listed in
    :data:`instruction_arg_kinds` as non-operands (``JSR``, ``JMP`` and
    ``LBL`` argument 0) are skipped.

    Args:
        text: Neutral rung text (``py_l5x`` ``Rung.text``).

    Returns:
        Unique candidate strings in first-seen order.

    Raises:
        ValueError: If the rung text is malformed (see :func:`parse_rll`).

    Examples:
        ``XIC(a)OTE(b.c[1].2);`` gives ``["a", "b.c[1].2"]``.
        ``CPT(dest,(a+b[idx])*ABS(c)/2.5)`` gives
        ``["dest", "a", "b[idx]", "idx", "c"]``.
    """
    found: list[str] = []
    for call in parse_rll(text):
        name = call.name.upper()
        kinds = instruction_arg_kinds.get(name, ())
        keywords = (
            _EXPRESSION_KEYWORDS if name in _EXPRESSION_INSTRUCTIONS else frozenset()
        )
        for index, arg in enumerate(call.args):
            if index < len(kinds) and kinds[index] != "operand":
                continue
            found.extend(_scan_operands(arg, keywords))
    return list(dict.fromkeys(found))


def extract_st_operands(line: str) -> list[str]:
    """Return unique operand candidates referenced by one ST line.

    The line must already have comments removed (see
    :func:`strip_st_comments`), because a ``//`` or ``(*`` comment would be
    scanned as code. String literals, numeric and typed literals, ST keywords
    (case-insensitive) and identifiers followed by ``(`` are dropped. Operands
    inside call arguments are still returned. Operators such as ``:=``, ``>``
    and ``+`` are skipped.

    Args:
        line: One line of ST code without comments.

    Returns:
        Unique candidate strings in first-seen order.

    Raises:
        ValueError: If a string literal or subscript is unterminated.

    Examples:
        ``IF a.b > 5 AND NOT c[i] THEN x := ABS(y) + T#5s; END_IF;`` gives
        ``["a.b", "c[i]", "i", "x", "y"]``.
    """
    return list(dict.fromkeys(_scan_operands(line, _ST_KEYWORDS)))


def strip_st_comments(lines: list[str]) -> list[str]:
    """Remove ST comments from each line, keeping the line count and order.

    Handles ``//`` line comments, ``(* ... *)`` and ``/* ... */`` block
    comments (which may span lines). String literals are respected: comment
    markers inside ``'...'`` are kept, ``''`` and ``$'`` are escaped quotes.
    Block comments carry across lines; string literals do not.

    Args:
        lines: Raw ST line texts, in routine order.

    Returns:
        One entry per input line containing only its code. Fully commented
        lines become ``""``. Leading indentation is kept and trailing
        whitespace is removed.
    """
    result: list[str] = []
    block_close: str | None = None  # "*)" or "*/" while inside a block comment
    for raw in lines:
        code: list[str] = []
        i = 0
        n = len(raw)
        while i < n:
            if block_close is not None:
                end = raw.find(block_close, i)
                if end == -1:
                    break
                i = end + len(block_close)
                block_close = None
                continue
            if raw[i] == "'":
                end = _skip_string(raw, i)
                code.append(raw[i:end])
                i = end
            elif raw.startswith("//", i):
                break
            elif raw.startswith("(*", i):
                block_close = "*)"
                i += 2
            elif raw.startswith("/*", i):
                block_close = "*/"
                i += 2
            else:
                code.append(raw[i])
                i += 1
        result.append("".join(code).rstrip())
    return result


def _skip_string(text: str, start: int) -> int:
    """Return the index just past the string literal that opens at *start*."""
    n = len(text)
    i = start + 1
    while i < n:
        ch = text[i]
        if ch == "$":
            i += 2
            continue
        if ch == "'":
            if i + 1 < n and text[i + 1] == "'":
                i += 2
                continue
            return i + 1
        i += 1
    raise ValueError(f"Unterminated string literal at {start} in {text!r}")


def _read_args(text: str, open_pos: int) -> tuple[tuple[str, ...], int]:
    """Read the arguments of the call whose ``(`` is at *open_pos*.

    Returns:
        ``(args, index_after_closing_parenthesis)``.
    """
    n = len(text)
    stack = [")"]  # expected closers; the call closes when the stack empties
    args: list[str] = []
    start = open_pos + 1
    i = open_pos + 1
    while i < n:
        ch = text[i]
        if ch == "'":
            i = _skip_string(text, i)
            continue
        if ch in "([":
            stack.append(")" if ch == "(" else "]")
        elif ch in ")]":
            if ch != stack.pop():
                raise ValueError(f"Mismatched {ch!r} at {i} in rung text {text!r}")
            if not stack:
                args.append(text[start:i].strip())
                if args == [""]:
                    args = []
                return tuple(args), i + 1
        elif ch == "," and len(stack) == 1:
            args.append(text[start:i].strip())
            start = i + 1
        i += 1
    raise ValueError(f"Unclosed '(' at {open_pos} in rung text {text!r}")


def _find_close_bracket(expr: str, open_pos: int) -> int:
    """Return the index of the ``]`` matching the ``[`` at *open_pos*."""
    depth = 0
    i = open_pos
    while i < len(expr):
        ch = expr[i]
        if ch == "'":
            i = _skip_string(expr, i)
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError(f"Unclosed '[' at {open_pos} in {expr!r}")


def _scan_operands(expr: str, keywords: frozenset[str]) -> list[str]:
    """Collect operand tokens from an expression, in order (may contain repeats).

    Subscript expressions are scanned recursively after the full token that
    contains them. Keywords are matched case-insensitively and must be given
    in upper case.
    """
    found: list[str] = []
    n = len(expr)
    i = 0
    while i < n:
        if expr[i] == "'":
            i = _skip_string(expr, i)
            continue
        literal = _LITERAL.match(expr, i)
        if literal is not None:
            i = literal.end()
            continue
        head = _HEAD.match(expr, i)
        if head is None:
            i += 1
            continue

        token = head.group()
        pos = head.end()
        index_exprs: list[str] = []
        segmented = False
        while pos < n:
            if expr[pos] == "[":
                close = _find_close_bracket(expr, pos)
                token += expr[pos : close + 1]
                index_exprs.append(expr[pos + 1 : close])
                pos = close + 1
            else:
                segment = _SEGMENT.match(expr, pos)
                if segment is None:
                    break
                token += segment.group()
                pos = segment.end()
            segmented = True

        after = pos
        while after < n and expr[after].isspace():
            after += 1
        is_call = after < n and expr[after] == "("
        is_keyword = not segmented and token.upper() in keywords
        if not is_call and not is_keyword:
            found.append(token)
        for inner in index_exprs:
            found.extend(_scan_operands(inner, keywords))
        i = pos
    return found
