"""Generate the Studio 5000 harness runs (Linux). Usage: uv run python tools/sdk/gen.py

Runs every case in tests/golden_cases.py through the L5X tools (twice, to prove the
output is deterministic) and writes one folder per VM run:

    tools/sdk/run{37,38}_{blank,example,chain}/
        <golden>.L5X ...    the generated files the run imports
        manifest.json       the steps runner.py executes on the VM

Then push a folder with go.sh and check the results with check.py.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from harness import EXPORTS, HERE, VERSIONS, VMS, WS, base_for, load_cases, run_name

from l5x_mcp.registry import ProjectRegistry

golden_cases = load_cases()


def generate_case(case: Any) -> bytes:
    """Run a case in a fresh root; return its bytes, checked for determinism."""
    outputs = []
    for _ in range(2):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copy(
                golden_cases.FIXTURES_DIR / golden_cases.SOURCE,
                root / golden_cases.SOURCE,
            )
            out = golden_cases.run_case(ProjectRegistry(root), case)
            outputs.append(out.read_bytes())
    if outputs[0] != outputs[1]:
        raise SystemExit(f"{case.id}: output differs between runs (not deterministic)")
    return outputs[0]


def steps_for(version: int, case: Any) -> list[dict[str, Any]]:
    """Manifest steps for one case on one version: import, build, exports."""
    cid = case.id
    steps: list[dict[str, Any]] = []
    if not case.chain:
        if case.import_op == "import_rungs":
            prog, routine = case.rungs_target
            steps.append(
                {
                    "id": f"{cid}:import",
                    "op": "import_rungs",
                    "file": case.golden,
                    "xpath": f"Controller/Programs/Program[@Name='{prog}']"
                    f"/Routines/Routine[@Name='{routine}']",
                    "pos": 0,
                    "replace": 0,
                }
            )
        else:
            steps.append(
                {
                    "id": f"{cid}:import",
                    "op": "import",
                    "file": case.golden,
                    "xpath": "Controller",
                    "coll": "overwrite",
                    "coe": False,
                }
            )
    steps.append({"id": f"{cid}:build", "op": "build"})
    for label, xpath in EXPORTS:
        steps.append(
            {
                "id": f"{cid}:export:{label}",
                "op": "export",
                "xpath": xpath,
                "name": f"{cid}_{label}",
                # An empty collection is fine here; a missing object still fails
                # the key comparison in check.py.
                "optional": True,
            }
        )
    if case.chain and version == 37:
        # The v38 chain converts this saved copy, so the v37 run must save it.
        steps.append(
            {"id": f"{cid}:save_as", "op": "save_as", "name": f"{cid}_v37.ACD"}
        )
    return steps


def main() -> None:
    """Write the run folders for every version and VM."""
    contents: dict[str, bytes] = {}
    for case in golden_cases.CASES:
        contents[case.golden] = generate_case(case)
        print(f"generated {case.golden} ({len(contents[case.golden])} bytes)")

    for version in VERSIONS:
        for vm in VMS:
            cases = [c for c in golden_cases.CASES if c.vm == vm]
            run = run_name(version, vm)
            folder = HERE / run
            if folder.exists():
                shutil.rmtree(folder)
            folder.mkdir()
            steps: list[dict[str, Any]] = []
            for case in cases:
                (folder / case.golden).write_bytes(contents[case.golden])
                steps.extend(steps_for(version, case))
            manifest = {
                "run": run,
                "base": base_for(version, vm),
                "dir": f"{WS}/projects/{run}",
                "steps": steps,
            }
            text = json.dumps(manifest, indent=1)
            (folder / "manifest.json").write_text(text, encoding="utf-8")
            print(f"{run}: {len(cases)} cases, {len(steps)} steps")


if __name__ == "__main__":
    main()
