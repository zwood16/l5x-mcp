"""Check harness results and promote verified goldens (Linux).

Usage:
    uv run python tools/sdk/check.py                 # report every case on v37 and v38
    uv run python tools/sdk/check.py --verbose       # also list every SAME key
    uv run python tools/sdk/check.py --log CASE      # print the ImportLog of a case
    uv run python tools/sdk/check.py --promote       # if all pass: write tests/golden/

A case passes on a version only if all of these hold:
  - every step of the case ran ok (import, build, exports, save_as);
  - every ImportLog entry is Info, and the Summary reports 0 warnings and 0 errors;
  - the Studio exports, read with py_l5x, contain every key the generated file has,
    with the same value (tags and their values, operand comments, rungs and their
    comments, ST lines, UDT members, AOI parameters and locals, programs, tasks).
    Keys Studio adds that we did not generate are ignored.
--promote also needs the v37 and v38 generated copies to be byte-identical.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harness import (
    EMPTY_EXPORT,
    EXPORTS,
    HERE,
    RESULTS,
    VERSIONS,
    load_cases,
    run_name,
)
from py_l5x import AliasTag, load

golden_cases = load_cases()
GOLDEN_DIR = golden_cases.GOLDEN_DIR
IMPORT_OPS = ("import", "import_rungs", "import_target")


# ----------------------------------------------------------------------
# Studio ImportLog
# ----------------------------------------------------------------------


@dataclass
class ImportReport:
    """What the ImportLog of one import step says."""

    entries: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)


def import_report(lines: list[str]) -> ImportReport:
    """Parse the ``INFO ImportLog`` messages of one step.

    Args:
        lines: The step's SDK messages (runner.py records them as ``INFO ...``).

    Returns:
        The entries (for display) and any problems (for the verdict).
    """
    rep = ImportReport()
    xml = "\n".join(
        line[len("INFO ImportLog ") :]
        for line in lines
        if line.startswith("INFO ImportLog ")
    )
    if not xml.strip():
        rep.problems.append("no ImportLog captured for this import")
        return rep
    # The declaration says UTF-16, but the SDK hands us text; parse the text itself.
    body = re.sub(r"^\s*<\?xml[^>]*\?>", "", xml)
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        rep.problems.append(f"unparseable ImportLog: {exc}")
        return rep
    for exc in root.iter("Exception"):
        severity = exc.get("Severity", "")
        mnemonic = exc.get("Mnemonic", "")
        text = " ".join(t.strip() for t in exc.itertext() if t.strip())
        target = (exc.findtext("Target") or "").strip()
        rep.entries.append(f"{severity}: {mnemonic}: {text[:200]} [{target[:80]}]")
        if severity.lower() not in ("info", "information"):
            rep.problems.append(f"ImportLog {severity}: {mnemonic}: {text[:200]}")
    summary = root.find(".//Summary")
    if summary is None:
        rep.problems.append("ImportLog has no Summary")
    else:
        warnings = int(summary.get("Warnings", "0") or 0)
        errors = int(summary.get("Errors", "0") or 0)
        if warnings or errors:
            rep.problems.append(
                f"ImportLog Summary Warnings={warnings} Errors={errors}"
            )
    rep.lines = xml.splitlines()
    return rep


# ----------------------------------------------------------------------
# Summaries: the semantic content of a project or component file
# ----------------------------------------------------------------------


def _norm(value: Any) -> Any:
    """Make a value JSON-comparable (dicts, lists, numbers, strings)."""
    return json.loads(json.dumps(value, default=str))


def _val(node: Any) -> Any:
    """A tag, parameter or local's value as py_l5x reads it."""
    to_python = getattr(node, "to_python", None)
    if to_python is None:
        return None
    try:
        return _norm(to_python())
    except Exception as exc:  # noqa: BLE001 - a failure is compared like a value
        return f"<{type(exc).__name__}: {exc}>"


def _text(value: Any) -> str:
    return value or ""


def _tags(out: dict[str, Any], scope: str, tags: Any) -> None:
    for tag in tags.values():
        key = f"tag:{scope}/{tag.name}"
        if isinstance(tag, AliasTag):
            out[key] = {
                "alias_for": tag.alias_for,
                "description": _text(tag.description),
            }
            continue
        entry: dict[str, Any] = {
            "type": tag.data_type,
            "description": _text(tag.description),
            "comments": dict(tag.operand_comments),
        }
        # A tag without <Data> gets Studio's type defaults on import, and py_l5x
        # has nothing to read, so only tags that carry data are compared by value.
        if tag.element.find("Data") is not None:
            entry["value"] = _val(tag)
        out[key] = entry


def owner(key: str) -> str:
    """Which export a summary key belongs to (dt, aoi, tag, prog or task).

    Partial exports can carry stubs of other objects (a task export holds program
    stubs with no attributes), so each export contributes only its own keys.
    """
    kind, _, rest = key.partition(":")
    if kind == "udt":
        return "dt"
    if kind in ("aoi", "task", "prog"):
        return kind
    scope = rest.split("/", 1)[0]
    if scope == "controller":
        return "tag"
    if scope.startswith("aoi:"):
        return "aoi"
    return "prog"


def _routines(out: dict[str, Any], prefix: str, routines: Any) -> None:
    for routine in routines.values():
        key = f"{prefix}/{routine.name}"
        st = [_text(line.text) for line in routine.st_lines]
        # A rung-only component routine has no Type attribute; its language is RLL.
        kind = _text(routine.type_) or ("ST" if st else "RLL")
        out[f"routine:{key}"] = {
            "type": kind,
            "description": _text(routine.description),
        }
        for number, rung in enumerate(routine.rungs):
            out[f"rung:{key}/{number}"] = [_text(rung.text), _text(rung.comment)]
        if st:
            out[f"st:{key}"] = st


def summarize(path: Path) -> dict[str, Any]:
    """The semantic content of an L5X file, keyed by object.

    Args:
        path: A project, component or partial export.

    Returns:
        A flat dict of key -> JSON-comparable value.
    """
    project = load(str(path))
    out: dict[str, Any] = {}
    for name, udt in project.data_types.items():
        out[f"udt:{name}"] = {
            "description": _text(udt.description),
            "members": [
                [m.name, m.data_type, m.dimension] for m in udt.visible_members.values()
            ],
        }
    for name, aoi in project.aois.items():
        out[f"aoi:{name}"] = {
            "description": _text(aoi.description),
            "revision": _text(aoi.revision),
            "parameters": [
                [
                    p.name,
                    p.data_type,
                    p.usage,
                    bool(p.required),
                    bool(p.visible),
                    _val(p),
                ]
                for p in aoi.parameters.values()
            ],
            "local_tags": [
                [t.name, t.data_type, _val(t)] for t in aoi.local_tags.values()
            ],
        }
        _routines(out, f"aoi:{name}", aoi.routines)
    _tags(out, "controller", project.controller_tags)
    for name, prog in project.programs.items():
        # A Use="Context" program in a component is a stub Studio ignores on import.
        if prog.use != "Context":
            out[f"prog:{name}"] = {
                "main": _text(prog.main_routine_name),
                "description": _text(prog.description),
                "disabled": bool(prog.disabled),
            }
        _tags(out, name, prog.tags)
        _routines(out, name, prog.routines)
    for name, task in project.tasks.items():
        out[f"task:{name}"] = {"programs": list(task.scheduled_program_names)}
    return out


def software_revision(path: Path) -> str:
    """The SoftwareRevision that Studio wrote into a file (the Logix version)."""
    return ET.parse(path).getroot().get("SoftwareRevision", "")


def covers(generated: Any, studio: Any) -> bool:
    """True when Studio's value includes everything we generated.

    Dicts compare on the keys we wrote (Studio may add defaults we did not set),
    lists must match in length and item by item, and scalars must be equal.
    """
    if isinstance(generated, dict):
        return isinstance(studio, dict) and all(
            k in studio and covers(v, studio[k]) for k, v in generated.items()
        )
    if isinstance(generated, list):
        return (
            isinstance(studio, list)
            and len(generated) == len(studio)
            and all(covers(a, b) for a, b in zip(generated, studio, strict=True))
        )
    return generated == studio


def compare(generated: dict[str, Any], studio: dict[str, Any]) -> tuple[int, list[str]]:
    """Compare each generated key with Studio's value for it.

    Returns:
        (number of SAME keys, one line per MISSING or DIFF key).
    """
    same = 0
    diffs: list[str] = []
    for key in sorted(generated):
        if key not in studio:
            diffs.append(f"MISSING {key}: generated={_short(generated[key])}")
        elif not covers(generated[key], studio[key]):
            diffs.append(
                f"DIFF    {key}: generated={_short(generated[key])} "
                f"studio={_short(studio[key])}"
            )
        else:
            same += 1
    return same, diffs


def _short(value: Any) -> str:
    text = json.dumps(value, default=str)
    return text if len(text) <= 240 else text[:237] + "..."


# ----------------------------------------------------------------------
# Verdicts
# ----------------------------------------------------------------------


@dataclass
class Verdict:
    """The result of one case on one version."""

    case: str
    version: int
    problems: list[str] = field(default_factory=list)
    same: int = 0
    diffs: list[str] = field(default_factory=list)
    logix: str = ""
    imports: list[str] = field(default_factory=list)
    build: str = ""

    @property
    def passed(self) -> bool:
        return not self.problems and not self.diffs


def build_log(results: dict[str, Any], case_id: str) -> list[str]:
    """Messages of the build step that follows an import.

    The SDK delivers an import's ImportLog after the import call returns, so the
    body often lands in the next step's messages (the build).
    """
    step = results.get(f"{case_id}:build")
    return step["log"] if step else []


def results_by_id(path: Path) -> dict[str, Any]:
    """A run's results.json, keyed by step id (empty if not pulled)."""
    if not path.exists():
        return {}
    return {r["id"]: r for r in json.loads(path.read_text("utf-8"))}


def check_case(case: Any, version: int) -> Verdict:
    """Check one case on one version against its run's results."""
    v = Verdict(case.id, version)
    run = run_name(version, case.vm)
    run_dir = RESULTS / run
    results_file = run_dir / "results.json"
    if not results_file.exists():
        v.problems.append(f"no results in {run_dir} (run not pulled)")
        return v
    results = {r["id"]: r for r in json.loads(results_file.read_text("utf-8"))}

    def step(name: str) -> dict[str, Any] | None:
        r = results.get(f"{case.id}:{name}")
        if r is None:
            v.problems.append(f"step {name} did not run")
        elif not r["ok"]:
            v.problems.append(f"step {name} failed: {r['err']}")
        return r

    if not case.chain:
        imp = step("import")
        if imp is not None:
            rep = import_report(imp["log"] + build_log(results, case.id))
            v.imports = rep.entries
            v.problems += [f"import: {p}" for p in rep.problems]
    build = step("build")
    if build is not None:
        v.build = "ok" if build["ok"] else "failed"
    if case.build_skip:
        v.build = f"skipped ({case.build_skip})"

    studio: dict[str, Any] = {}
    for label, _ in EXPORTS:
        r = step(f"export:{label}")
        if r is None or not r["ok"] or r["ret"] == EMPTY_EXPORT:
            continue
        path = run_dir / r["ret"]
        try:
            summary = summarize(path)
        except Exception as exc:  # noqa: BLE001 - reported as a case problem
            v.problems.append(f"export {label} unreadable: {exc}")
            continue
        studio.update({k: x for k, x in summary.items() if owner(k) == label})
        v.logix = v.logix or software_revision(path)
    if case.chain and version == 37:
        step("save_as")

    golden = HERE / run / case.golden
    if not golden.exists():
        v.problems.append(f"generated file missing: {golden} (run gen.py)")
    else:
        try:
            generated = summarize(golden)
        except Exception as exc:  # noqa: BLE001
            v.problems.append(f"generated file unreadable: {exc}")
        else:
            v.same, v.diffs = compare(generated, studio)
    return v


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generated_files_match(case: Any) -> list[str]:
    """Problems when the v37 and v38 copies of a golden differ."""
    a = HERE / run_name(37, case.vm) / case.golden
    b = HERE / run_name(38, case.vm) / case.golden
    if a.exists() and b.exists() and sha256(a) != sha256(b):
        return [f"v37 and v38 copies of {case.golden} differ"]
    return []


def show_log(case_id: str) -> None:
    """Print every ImportLog entry for a case on both versions."""
    for version in VERSIONS:
        run_dir = RESULTS / run_name(version, _case(case_id).vm)
        path = run_dir / "results.json"
        if not path.exists():
            print(f"v{version}: no results")
            continue
        for r in json.loads(path.read_text("utf-8")):
            if r["id"].startswith(f"{case_id}:") and r["op"] in IMPORT_OPS:
                rep = import_report(r["log"] + build_log(results_by_id(path), case_id))
                print(f"v{version} {r['id']}: {len(rep.entries)} entries")
                for e in rep.entries:
                    print("   " + e)


def _case(case_id: str) -> Any:
    for case in golden_cases.CASES:
        if case.id == case_id:
            return case
    raise SystemExit(f"unknown case {case_id!r}")


def promote(verdicts: dict[str, dict[int, Verdict]]) -> None:
    """Copy the verified goldens to tests/golden/ and write VERIFIED.json."""
    today = dt.date.today().isoformat()
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    files: dict[str, Any] = {}
    for case in golden_cases.CASES:
        src = HERE / run_name(37, case.vm) / case.golden
        shutil.copyfile(src, GOLDEN_DIR / case.golden)
        files[case.golden] = {
            "case": case.id,
            "sha256": sha256(src),
            "logix": {str(v): verdicts[case.id][v].logix for v in VERSIONS},
            "verified": today,
            "build": verdicts[case.id][37].build,
        }
    doc = {
        "about": (
            "Golden L5X files from tests/golden_cases.py, each imported into "
            "Logix Designer and checked by tools/sdk/check.py. A golden may change "
            "only after a new harness run passes (python tools/sdk/check.py "
            "--promote); tests/test_golden.py checks these hashes."
        ),
        "files": files,
    }
    (GOLDEN_DIR / "VERIFIED.json").write_text(
        json.dumps(doc, indent=2) + "\n", encoding="utf-8"
    )
    print(f"promoted {len(files)} golden files to {GOLDEN_DIR}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--verbose", action="store_true", help="list SAME keys too")
    ap.add_argument("--log", metavar="CASE", help="print the ImportLog of a case")
    ap.add_argument("--promote", action="store_true", help="write tests/golden/")
    args = ap.parse_args()
    if args.log:
        show_log(args.log)
        return 0

    verdicts: dict[str, dict[int, Verdict]] = {}
    failed = False
    for case in golden_cases.CASES:
        verdicts[case.id] = {}
        extra = generated_files_match(case)
        for version in VERSIONS:
            v = check_case(case, version)
            v.problems += extra
            verdicts[case.id][version] = v
            status = "PASS" if v.passed else "FAIL"
            failed |= not v.passed
            print(
                f"[{status}] {case.id:<14} v{version} build={v.build or '-'} "
                f"keys_same={v.same} diffs={len(v.diffs)} logix={v.logix or '?'}"
            )
            for line in v.imports:
                print(f"        import: {line}")
            for problem in v.problems:
                print(f"        PROBLEM {problem}")
            for line in v.diffs:
                print(f"        {line}")
            if args.verbose and v.same:
                print(f"        ({v.same} keys SAME)")
    if args.promote:
        if failed:
            print("not promoting: some cases fail", file=sys.stderr)
            return 1
        promote(verdicts)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
