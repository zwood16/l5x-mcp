"""Search tools for finding tags, instructions, and text in L5X programs and AOIs."""

from __future__ import annotations

import re
from typing import Any, Literal

from l5x_mcp.registry import ItemNotFoundError, L5XError, ProjectRegistry, lookup
from l5x_mcp.serialize import compact, first_line

# RLL mnemonic aliases (IEC vs legacy Logix names)
# Maps canonical name to alternate names for equivalence
MNEMONIC_ALIASES = {
    "MOV": {"MOVE"},
    "MOVE": {"MOV"},
    "EQU": {"EQ"},
    "EQ": {"EQU"},
    "NEQ": {"NE"},
    "NE": {"NEQ"},
    "GRT": {"GT"},
    "GT": {"GRT"},
    "GEQ": {"GE"},
    "GE": {"GEQ"},
    "LES": {"LT"},
    "LT": {"LES"},
    "LEQ": {"LE"},
    "LE": {"LEQ"},
}


def _get_mnemonic_equivalents(mnemonic: str) -> set[str]:
    """Get all equivalent mnemonics for a given instruction name (case-insensitive).

    Args:
        mnemonic: The instruction mnemonic to look up.

    Returns:
        Set containing the input mnemonic and all its aliases (uppercase).
    """
    upper = mnemonic.upper()
    result = {upper}
    # Add direct aliases
    if upper in MNEMONIC_ALIASES:
        result.update(MNEMONIC_ALIASES[upper])
    # Also check lowercase to ensure we capture all forms
    for canonical, aliases in MNEMONIC_ALIASES.items():
        if upper in aliases:
            result.add(canonical)
            result.update(aliases)
    return result


def _is_word_boundary_before(text: str, pos: int) -> bool:
    """Check if position is at a word boundary (not preceded by alphanumeric._:)."""
    if pos == 0:
        return True
    allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_:.["
    return text[pos - 1] not in allowed


def _is_word_boundary_after(text: str, pos: int) -> bool:
    """Check if position is at a word boundary (not followed by alphanumeric_)."""
    if pos >= len(text):
        return True
    allowed_after = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_"
    return text[pos] not in allowed_after


def _escape_query(query: str) -> str:
    """Escape special regex characters in a query string."""
    return re.escape(query)


def _find_tag_matches(text: str, query: str) -> list[tuple[int, int]]:
    """Find all matches of a tag query in text with proper word boundaries.

    Args:
        text: The text to search in (case-insensitive).
        query: The tag name to match (case-insensitive).

    Returns:
        List of (start_pos, end_pos) tuples for all matches with proper boundaries.
    """
    matches = []
    text_lower = text.lower()
    query_lower = query.lower()

    # If query contains special chars like . [ :, escape and treat literally
    if any(c in query for c in ".[:"):
        # Escape special regex chars but preserve the literal string
        escaped = _escape_query(query_lower)
        # Build pattern with word boundaries
        pattern = r"(?<![A-Za-z0-9_.\[:])(" + escaped + r")(?![A-Za-z0-9_])"
        for match in re.finditer(pattern, text_lower, re.IGNORECASE):
            matches.append((match.start(1), match.end(1)))
    else:
        # Simple identifier - search for all occurrences
        start = 0
        while True:
            pos = text_lower.find(query_lower, start)
            if pos == -1:
                break
            # Check boundaries
            if _is_word_boundary_before(text, pos) and _is_word_boundary_after(
                text, pos + len(query)
            ):
                matches.append((pos, pos + len(query)))
            start = pos + 1

    return matches


def _find_instruction_matches(text: str, query: str) -> list[tuple[int, int]]:
    """Find all instruction calls matching QUERY\\s*\\( pattern.

    Args:
        text: The text to search in.
        query: The instruction mnemonic (case-insensitive).

    Returns:
        List of (start_pos, end_pos) tuples for all matches.
    """
    pattern = r"\b" + _escape_query(query) + r"\s*\("
    matches = []
    for match in re.finditer(pattern, text, re.IGNORECASE):
        # Return the position of the instruction name itself
        matches.append((match.start(), match.start() + len(query)))
    return matches


def _find_instruction_matches_with_aliases(
    text: str, query: str
) -> tuple[list[tuple[int, int]], list[str]]:
    """Find all instruction calls, including aliases, and return matched mnemonics.

    Args:
        text: The text to search in.
        query: The instruction mnemonic (case-insensitive).

    Returns:
        Tuple of (matches, matched_mnemonics) where matches is a list of
        (start_pos, end_pos) tuples and matched_mnemonics lists the actual
        instruction names found (e.g. if query is "MOV", matched_mnemonics
        might be ["MOV", "MOVE"]).
    """
    equivalents = _get_mnemonic_equivalents(query)
    matches = []
    matched_mnemonics = set()

    for equiv in equivalents:
        pattern = r"\b" + _escape_query(equiv) + r"\s*\("
        for match in re.finditer(pattern, text, re.IGNORECASE):
            # Return the position of the instruction name itself
            instr_name = match.group(0).split("(")[0].strip().upper()
            matches.append((match.start(), match.start() + len(equiv)))
            matched_mnemonics.add(instr_name)

    return matches, sorted(list(matched_mnemonics))


def _find_text_matches(text: str, query: str) -> list[tuple[int, int]]:
    """Find all substring matches (case-insensitive).

    Args:
        text: The text to search in.
        query: The substring to match.

    Returns:
        List of (start_pos, end_pos) tuples for all matches.
    """
    matches = []
    text_lower = text.lower()
    query_lower = query.lower()
    start = 0
    while True:
        pos = text_lower.find(query_lower, start)
        if pos == -1:
            break
        matches.append((pos, pos + len(query)))
        start = pos + 1
    return matches


def _classify_tag_usage(
    text: str, match_pos: int, aoi_names: set[str] | None = None
) -> str:
    """Classify tag usage as 'read' or 'write' based on enclosing instruction.

    Finds the innermost instruction that encloses the match and classifies:
    - write instructions: OTE, OTL, OTU, ONS, OSR, OSF, RES, TON, TOF, RTO, CTU, CTD
    - For MOV/MOVE, COP, CPS, CLR, ADD, SUB, MUL, DIV, CPT, BTD, FLL: write if in
      last arg, else read
    - For AOI calls (when name is in aoi_names): first arg is write, else read
    - Otherwise: read

    Args:
        text: The RLL text.
        match_pos: Position of the match in the text.
        aoi_names: Set of AOI names defined in the project (optional).

    Returns:
        "write" or "read"
    """
    if aoi_names is None:
        aoi_names = set()

    # Find all instruction calls in the text
    # Pattern: INSTR_NAME( (including mixed-case AOI names)
    instr_pattern = r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\("

    # Track nesting depth to find the innermost enclosing instruction
    enclosing_instr = None
    enclosing_paren_start = -1
    enclosing_paren_end = -1

    for instr_match in re.finditer(instr_pattern, text):
        instr_name = instr_match.group(1)
        paren_start = instr_match.end() - 1  # Position of '('

        # Scan forward from the opening paren to find matching close paren
        depth = 1
        scan_pos = paren_start + 1
        close_paren = -1

        while scan_pos < len(text) and depth > 0:
            if text[scan_pos] == "(":
                depth += 1
            elif text[scan_pos] == ")":
                depth -= 1
                if depth == 0:
                    close_paren = scan_pos
                    break
            scan_pos += 1

        # Check if match is inside this instruction's parentheses
        if paren_start < match_pos < close_paren and (
            enclosing_paren_start == -1 or close_paren < enclosing_paren_end
        ):
            # This is an enclosing instruction; if it's more deeply nested, use it
            enclosing_instr = instr_name
            enclosing_paren_start = paren_start
            enclosing_paren_end = close_paren

    if not enclosing_instr:
        return "read"

    # Check if it's an AOI call (first arg is write, rest are read)
    if enclosing_instr in aoi_names:
        # Count commas before match to determine argument position
        text_inside = text[enclosing_paren_start + 1 : enclosing_paren_end]
        relative_match_pos = match_pos - (enclosing_paren_start + 1)
        commas_before = text_inside[:relative_match_pos].count(",")
        # First argument (no commas before it) is write
        return "write" if commas_before == 0 else "read"

    # Write-only instructions
    write_only = {
        "OTE",
        "OTL",
        "OTU",
        "ONS",
        "OSR",
        "OSF",
        "RES",
        "TON",
        "TOF",
        "RTO",
        "CTU",
        "CTD",
    }
    if enclosing_instr in write_only:
        return "write"

    # Instructions where last argument is write, others read (include aliases)
    write_last = {
        "MOV",
        "MOVE",
        "COP",
        "CPS",
        "CLR",
        "ADD",
        "SUB",
        "MUL",
        "DIV",
        "CPT",
        "BTD",
        "FLL",
    }
    if enclosing_instr in write_last:
        # Find argument position: count commas to determine which argument we're in
        # Extract the text inside the instruction call
        text_inside = text[enclosing_paren_start + 1 : enclosing_paren_end]
        # Count commas before the match position (relative to instruction start)
        relative_match_pos = match_pos - (enclosing_paren_start + 1)
        commas_before = text_inside[:relative_match_pos].count(",")
        total_commas = text_inside.count(",")

        # If match is in the last argument, commas_before should equal total_commas
        if commas_before == total_commas:
            return "write"
        else:
            return "read"

    return "read"


def find_references(
    registry: ProjectRegistry,
    query: str,
    kind: Literal["tag", "instruction", "text"] = "tag",
    program: str | None = None,
    include_aois: bool = True,
    limit: int = 200,
    path: str | None = None,
) -> dict[str, Any]:
    """Find references to a tag, instruction, or text in program logic.

    Scans RLL rungs and ST code across programs (and optionally AOIs) to find
    matches based on the search kind.

    When kind="tag", matches whole identifiers with word boundaries:
    - 'foo' matches 'Var_foo' end, 'foo.member', 'foo[index]' but not 'x_foo' prefix
    - Dotted queries like 'Arr.mem' are treated as literals with escaping
    - Case-insensitive (Logix is case-insensitive)

    When kind="instruction", matches instruction calls (INSTR\\s*\\() case-insensitive.

    When kind="text", case-insensitive substring matching in logic text and comments.

    Args:
        registry: ProjectRegistry instance
        query: Search term (tag name, instruction mnemonic, or text substring)
        kind: Type of search - "tag" (default), "instruction", or "text"
        program: Optional program name to limit scope; if None, searches all programs
        include_aois: If True (default) and program is None, also search AOI routines
        limit: Maximum number of matches to return (1..2000, default 200)
        path: L5X file path (resolved via registry.get_with_path)

    Returns:
        Dict with keys:
        - file: Path to the L5X file
        - query: The search query
        - kind: The search kind
        - total_matches: Total number of matches found
        - truncated: Present and True if results exceed limit
        - matches: List of match dicts with container_type, container, routine,
                   routine_type, rung/line, text, comment (RLL only),
                   usage (tag kind only)
        - summary: Dict of "<container>/<routine>": count grouping

    Raises:
        L5XError: If query is empty, limit is out of range, or program name not found.
    """
    if not query or not query.strip():
        raise L5XError("Search query cannot be empty")
    if not (1 <= limit <= 2000):
        raise L5XError("Limit must be between 1 and 2000")

    project_path, project = registry.get_with_path(path)

    # Get set of AOI names for usage classification
    aoi_names = set(project.aois.keys())

    # Resolve program if specified
    target_programs = {}
    if program:
        try:
            prog_obj = lookup(project.programs, program, "Program")
            target_programs = {program: prog_obj}
        except ItemNotFoundError:
            raise
    else:
        target_programs = project.programs

    matches = []
    summary: dict[str, int] = {}
    matched_mnemonics: set[str] = set()

    # Determine which search function to use
    if kind == "tag":
        search_fn = _find_tag_matches
        use_usage = True
        use_aliases = False
    elif kind == "instruction":
        search_fn = _find_instruction_matches_with_aliases
        use_usage = False
        use_aliases = True
    elif kind == "text":
        search_fn = _find_text_matches
        use_usage = False
        use_aliases = False
    else:
        raise L5XError(f"Unknown search kind: {kind}")

    # Helper to process a single rung/line match
    def add_match(
        container_type: str,
        container: str,
        routine_name: str,
        routine_type: str,
        location_key: str,
        location_value: int,
        text: str,
        comment: str | None = None,
    ) -> None:
        """Add a match to the matches list and update summary."""
        match_dict = {
            "container_type": container_type,
            "container": container,
            "routine": routine_name,
            "routine_type": routine_type,
            location_key: location_value,
            "text": text,
        }
        if comment:
            match_dict["comment"] = first_line(comment)
        match_dict = compact(match_dict)
        matches.append(match_dict)
        container_key = f"{container}/{routine_name}"
        summary[container_key] = summary.get(container_key, 0) + 1

    # Search programs
    for prog_name, prog_obj in target_programs.items():
        for routine_name, routine in prog_obj.routines.items():
            # Search RLL rungs
            if routine.rungs:
                for rung in routine.rungs:
                    rung_text = rung.text if rung.text else ""
                    if use_aliases:
                        rung_matches, mnemonics = search_fn(rung_text, query)
                        matched_mnemonics.update(mnemonics)
                    else:
                        rung_matches = search_fn(rung_text, query)

                    # For text kind, also search comments
                    if kind == "text" and rung.comment:
                        comment_matches = search_fn(rung.comment, query)
                        rung_matches.extend(comment_matches)

                    for match_start, _match_end in rung_matches:
                        match_dict = {
                            "container_type": "program",
                            "container": prog_name,
                            "routine": routine_name,
                            "routine_type": "RLL",
                            "rung": rung.number,
                            "text": rung_text,
                        }
                        if rung.comment:
                            match_dict["comment"] = first_line(rung.comment)
                        if use_usage:
                            match_dict["usage"] = _classify_tag_usage(
                                rung_text, match_start, aoi_names
                            )
                        match_dict = compact(match_dict)
                        matches.append(match_dict)
                        container_key = f"{prog_name}/{routine_name}"
                        summary[container_key] = summary.get(container_key, 0) + 1

            # Search ST lines
            if routine.st_lines:
                for line in routine.st_lines:
                    if use_aliases:
                        line_matches, mnemonics = (
                            search_fn(line.text, query) if line.text else ([], [])
                        )
                        matched_mnemonics.update(mnemonics)
                    else:
                        line_matches = search_fn(line.text, query) if line.text else []
                    for _match_start, _match_end in line_matches:
                        match_dict = {
                            "container_type": "program",
                            "container": prog_name,
                            "routine": routine_name,
                            "routine_type": "ST",
                            "line": line.number,
                            "text": line.text,
                        }
                        match_dict = compact(match_dict)
                        matches.append(match_dict)
                        container_key = f"{prog_name}/{routine_name}"
                        summary[container_key] = summary.get(container_key, 0) + 1

    # Search AOIs if requested and no specific program was given
    if include_aois and not program:
        for aoi_name, aoi_obj in project.aois.items():
            for routine_name, routine in aoi_obj.routines.items():
                container_key = f"{aoi_name}/{routine_name}"

                # Search RLL rungs
                if routine.rungs:
                    for rung in routine.rungs:
                        rung_text = rung.text if rung.text else ""
                        if use_aliases:
                            rung_matches, mnemonics = search_fn(rung_text, query)
                            matched_mnemonics.update(mnemonics)
                        else:
                            rung_matches = search_fn(rung_text, query)

                        # For text kind, also search comments
                        if kind == "text" and rung.comment:
                            comment_matches = search_fn(rung.comment, query)
                            rung_matches.extend(comment_matches)

                        for match_start, _match_end in rung_matches:
                            match_dict = {
                                "container_type": "aoi",
                                "container": aoi_name,
                                "routine": routine_name,
                                "routine_type": "RLL",
                                "rung": rung.number,
                                "text": rung_text,
                            }
                            if rung.comment:
                                match_dict["comment"] = first_line(rung.comment)
                            if use_usage:
                                match_dict["usage"] = _classify_tag_usage(
                                    rung_text, match_start, aoi_names
                                )
                            match_dict = compact(match_dict)
                            matches.append(match_dict)
                            summary[container_key] = summary.get(container_key, 0) + 1

                # Search ST lines
                if routine.st_lines:
                    for line in routine.st_lines:
                        if use_aliases:
                            line_matches, mnemonics = (
                                search_fn(line.text, query) if line.text else ([], [])
                            )
                            matched_mnemonics.update(mnemonics)
                        else:
                            line_matches = (
                                search_fn(line.text, query) if line.text else []
                            )
                        for _match_start, _match_end in line_matches:
                            match_dict = {
                                "container_type": "aoi",
                                "container": aoi_name,
                                "routine": routine_name,
                                "routine_type": "ST",
                                "line": line.number,
                                "text": line.text,
                            }
                            match_dict = compact(match_dict)
                            matches.append(match_dict)
                            summary[container_key] = summary.get(container_key, 0) + 1

    # Compute total matches and truncation after scanning everything
    total_matches = len(matches)
    result = {
        "file": registry.relpath(project_path),
        "query": query,
        "kind": kind,
        "total_matches": total_matches,
    }
    # Only include truncated key if True (matches exceeded limit)
    if total_matches > limit:
        result["truncated"] = True
        matches = matches[:limit]

    if matched_mnemonics:
        result["matched_mnemonics"] = sorted(matched_mnemonics)

    result["matches"] = matches
    result["summary"] = summary

    return result


_INSTRUCTION_RE = re.compile(r"\b([A-Z_][A-Z0-9_]*)\s*\(", re.IGNORECASE)


def instruction_usage(
    registry: ProjectRegistry,
    program: str | None = None,
    path: str | None = None,
) -> dict[str, Any]:
    """Count usage of every instruction mnemonic in program logic.

    Scans RLL rungs across all programs (or a specific program) and AOIs,
    extracting instruction mnemonics and counting their frequency.
    Sorted by count (descending).

    Args:
        registry: ProjectRegistry instance
        program: Optional program name to limit scope; if None, searches all
        path: L5X file path (resolved via registry.get_with_path)

    Returns:
        Dict with keys:
        - file: Path to the L5X file
        - instructions: List of {"name", "count"} dicts sorted by count (desc)
    """
    project_path, project = registry.get_with_path(path)

    # Resolve program if specified
    target_programs = {}
    if program:
        try:
            prog_obj = lookup(project.programs, program, "Program")
            target_programs = {program: prog_obj}
        except ItemNotFoundError:
            raise
    else:
        target_programs = project.programs

    # Logix mnemonics are case-insensitive; count by upper-case key but report
    # AOIs under their defined names.
    aoi_by_upper = {name.upper(): name for name in project.aois}
    routine_groups = [prog.routines for prog in target_programs.values()]
    if program is None:
        routine_groups.extend(aoi.routines for aoi in project.aois.values())

    instruction_counts: dict[str, int] = {}
    for routines in routine_groups:
        for routine in routines.values():
            for rung in routine.rungs or []:
                for match in _INSTRUCTION_RE.finditer(rung.text or ""):
                    key = match.group(1).upper()
                    instruction_counts[key] = instruction_counts.get(key, 0) + 1

    instructions = []
    for key, count in sorted(instruction_counts.items(), key=lambda x: (-x[1], x[0])):
        if key in aoi_by_upper:
            instructions.append(
                {"name": aoi_by_upper[key], "count": count, "aoi": True}
            )
        else:
            instructions.append({"name": key, "count": count})

    return {"file": registry.relpath(project_path), "instructions": instructions}
