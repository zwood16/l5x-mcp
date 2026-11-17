"""Generic Logix Designer SDK runner (runs on the Windows VM).

Adapted from py_l5x's tools/sdk/runner.py.
Usage: uv run python runner.py <manifest.json>

Manifest (see tools/sdk/README.md):
{
  "run": "run37_blank",                 # output -> out/<run>/
  "base": "C:/.../base.ACD",            # or an .L5X, or {"create": {...}},
                                        # or {"convert": {"path", "rev", "copy"}}
  "dir":  "C:/.../projects/run37_blank",  # where relative case files live
  "steps": [
    {"id": "c:import", "op": "import", "file": "c.L5X",
     "xpath": "Controller", "coll": "overwrite", "coe": false},
    {"id": "c:import", "op": "import_rungs", "file": "r.L5X",
     "xpath": "<routine xpath>", "pos": 0, "replace": 0},
    {"id": "c:export:tag", "op": "export", "xpath": "Controller/Tags/Tag",
     "name": "c_tag", "optional": true},
    {"id": "c:build", "op": "build"},
    {"id": "c:save", "op": "save_as", "name": "final.ACD"}
  ]
}

Each step's outcome (ok/error + the SDK messages emitted during it, including
the ImportLog) goes to out/<run>/results.json. The base is opened or converted
in memory only; nothing is written back to it unless a save_as step runs, and
save_as writes into out/<run>/. "convert" with copy=true converts a copy, so the
original file is never changed.
"""

import asyncio
import json
import shutil
import sys
import time
import traceback
from pathlib import Path

from logix_designer_sdk import (
    ImportCollisionOptions,
    LogixProject,
    OperationMode,
    PartialImportOption,
)
from logix_designer_sdk.exceptions import LogixSdkError
from logix_designer_sdk.logging import OperationEvent

OUT_ROOT = Path(r"C:\Users\zwood\ldsdk\out")
COLL = {
    "overwrite": ImportCollisionOptions.OVERWRITE_ON_COLL,
    "discard": ImportCollisionOptions.DISCARD_ON_COLL,
    "cancel": ImportCollisionOptions.CANCEL_ON_COLL,
}
T0 = time.perf_counter()
#: Returned by an optional export that found no objects (recorded as ok).
EMPTY = "<empty>"


class Collector(OperationEvent):
    """Collects SDK status/error messages so each step can report its own."""

    def __init__(self) -> None:
        super().__init__()
        self.msgs: list[str] = []

    def set_progress(self, project_file, value):  # noqa: D102
        pass

    def log_status_message(self, project_file, msg):  # noqa: D102
        self.msgs.append(f"INFO {msg}")

    def log_error_message(self, project_file, msg):  # noqa: D102
        self.msgs.append(f"ERROR {msg}")

    def take(self) -> list[str]:
        out, self.msgs = self.msgs, []
        return out


def step(msg: str) -> None:
    print(f"[{time.perf_counter() - T0:6.1f}s] {msg}", flush=True)


async def run_step(p: LogixProject, s: dict, case_dir: Path, out: Path):
    op = s["op"]
    f = str(case_dir / s["file"]) if "file" in s else None
    if op == "import":
        await p.partial_import_from_xml_file(
            s.get("xpath", "Controller"),
            f,
            COLL[s.get("coll", "overwrite")],
            s.get("coe", False),
        )
    elif op == "import_target":
        await p.partial_import_with_target_from_xml_file(
            s["xpath"], s.get("target", ""), f, PartialImportOption.LEAVE_EDITS
        )
    elif op == "import_rungs":
        await p.partial_import_rungs_from_xml_file(
            s["xpath"],
            s.get("pos", 0),
            s.get("replace", 0),
            f,
            PartialImportOption.LEAVE_EDITS,
        )
    elif op == "export":
        dest = out / f"{s['name']}.L5X"
        if dest.exists():
            dest.unlink()
        try:
            await p.partial_export_to_xml_file(s["xpath"], str(dest))
        except LogixSdkError as e:
            # An optional export of a collection with no objects fails with
            # "doesn't exist"; there is nothing to compare, so that is not an error.
            if s.get("optional") and "doesn't exist" in str(e):
                return EMPTY
            raise
        return dest.name
    elif op == "get" and s["type"] == "raw":
        from logix_designer_sdk import DataType

        v = await p.get_tag_value(
            s["xpath"], OperationMode.OFFLINE, DataType.BYTE_ARRAY
        )
        return f"{len(v)} bytes: {v.hex()}"
    elif op == "get":
        fn = getattr(p, f"get_tag_value_{s['type']}")
        v = await fn(s["xpath"], OperationMode.OFFLINE)
        return v.hex() if isinstance(v, bytes) else v
    elif op == "set":
        fn = getattr(p, f"set_tag_value_{s['type']}")
        await fn(s["xpath"], OperationMode.OFFLINE, s["value"])
    elif op == "build":
        await p.build()
    elif op == "save_as":
        await p.save_as(str(out / s["name"]), force=True)
    else:
        raise ValueError(f"unknown op {op}")
    return None


async def main(manifest_path: str) -> None:
    m = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    out = OUT_ROOT / m["run"]
    out.mkdir(parents=True, exist_ok=True)
    case_dir = Path(m.get("dir", Path(manifest_path).parent))
    col = Collector()
    base = m["base"]
    if isinstance(base, dict) and "convert" in base:
        # {"convert": {"path": ".../in.ACD", "rev": 38, "copy": true}}: converts to a
        # new major revision. SDK's convert works in place, so copy first if asked.
        cv = base["convert"]
        path = Path(cv["path"])
        if cv.get("copy"):
            copied = out / path.name
            shutil.copyfile(path, copied)
            path = copied
        step(f"converting {path} to v{cv['rev']}")
        proj = await LogixProject.convert(str(path), cv["rev"], col)
    elif isinstance(base, dict):
        c = base["create"]
        acd = out / f"base_{time.strftime('%H%M%S')}.ACD"
        proj = await LogixProject.create_new_project(
            str(acd),
            c.get("rev", 37),
            c.get("proc", "1756-L85E"),
            c.get("name", "Exp"),
            col,
        )
    else:
        try:
            proj = await LogixProject.open_logix_project(base, col)
        except LogixSdkError:
            step("OPEN FAILED; SDK log:")
            for line in col.take():
                if any(
                    k in line for k in ("Exception", "Text", "CDATA", "Target", "ERROR")
                ):
                    print("   ", line[:300])
            raise
    step(f"opened base; startup msgs: {len(col.take())}")
    results = []
    with proj as p:
        for s in m["steps"]:
            r = {"id": s["id"], "op": s["op"]}
            try:
                r["ret"] = await run_step(p, s, case_dir, out)
                r["ok"] = True
            except LogixSdkError as e:
                r["ok"] = False
                r["err"] = f"{type(e).__name__}: {e}"
            except Exception as e:  # noqa: BLE001
                r["ok"] = False
                r["err"] = f"PY {type(e).__name__}: {e}"
                traceback.print_exc()
            r["log"] = col.take()
            results.append(r)
            flag = "OK " if r["ok"] else "ERR"
            extra = f" -> {r.get('ret')}" if r.get("ret") is not None else ""
            err = "" if r["ok"] else " :: " + r["err"][:300]
            step(f"{flag} {s['id']} ({s['op']}){extra}{err}")
            (out / "results.json").write_text(
                json.dumps(results, indent=1), encoding="utf-8"
            )
    step("done")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
