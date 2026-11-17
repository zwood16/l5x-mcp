"""Definitions shared by gen.py and check.py (no SDK, runs on Linux).

A VM run is one (Logix major version, base project) pair. Each run opens one
base, imports and builds the cases that use it, and exports the project
collections after every case. Each case is therefore checked against the
state right after its own import.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
TESTS = REPO / "tests"
RESULTS = HERE / "results"

#: Windows workspace on the VM (the studio5000-sdk skill's layout).
WS = "C:/Users/zwood/ldsdk"

VERSIONS = (37, 38)
VMS = ("blank", "example", "chain")

_BASE_FILES = {
    (37, "blank"): "base/blank.ACD",
    (38, "blank"): "base/blank_v38.ACD",
    (37, "example"): "base/example_base.ACD",
    (38, "example"): "base/example_base_v38.ACD",
}

#: What runner.py returns for an optional export that found no objects. Keep in
#: sync with EMPTY in runner.py.
EMPTY_EXPORT = "<empty>"

#: Collections exported after each case: every object a case can create or
#: depend on. check.py merges them and compares each generated key. Empty
#: collections are allowed (the export is optional).
EXPORTS: tuple[tuple[str, str], ...] = (
    ("dt", "Controller/DataTypes/DataType[@Class='User']"),
    ("aoi", "Controller/AddOnInstructionDefinitions/AddOnInstructionDefinition"),
    ("tag", "Controller/Tags/Tag"),
    ("prog", "Controller/Programs/Program"),
    ("task", "Controller/Tasks/Task"),
)


def run_name(version: int, vm: str) -> str:
    """Run folder name, e.g. ``run37_blank``."""
    return f"run{version}_{vm}"


def base_for(version: int, vm: str) -> Any:
    """The runner's ``base`` value for a (version, vm) run.

    - blank / example: an existing ACD under projects\\base.
    - chain v37: the chain's generated L5X, opened directly.
    - chain v38: a copy of the v37 chain's saved ACD, converted to v38.
    """
    if vm == "chain":
        if version == 37:
            return f"{WS}/projects/{run_name(37, 'chain')}/chain_final.L5X"
        src = f"{WS}/out/{run_name(37, 'chain')}/chain_final_v37.ACD"
        return {"convert": {"path": src, "rev": 38, "copy": True}}
    return f"{WS}/projects/{_BASE_FILES[(version, vm)]}"


def load_cases() -> Any:
    """Import tests/golden_cases.py (it has no SDK dependency)."""
    if str(TESTS) not in sys.path:
        sys.path.insert(0, str(TESTS))
    import golden_cases

    return golden_cases
