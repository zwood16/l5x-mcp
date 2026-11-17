"""Golden L5X outputs: regenerate each case and compare bytes with tests/golden/.

The goldens were imported into Logix Designer v37 and v38 by the SDK harness in
tools/sdk (see tools/sdk/README.md). This test never runs the SDK or imports
anything from tools/: it only replays the cases in tests/golden_cases.py and
checks the hashes recorded in tests/golden/VERIFIED.json. A golden can change only
after a new harness run passes and the goldens are promoted again.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from golden_cases import CASES, FIXTURES_DIR, GOLDEN_DIR, SOURCE, run_case

from l5x_mcp.registry import ProjectRegistry

VERIFIED_FILE = GOLDEN_DIR / "VERIFIED.json"
VERIFIED = json.loads(VERIFIED_FILE.read_text(encoding="utf-8"))["files"]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A fresh root holding a copy of the source fixture; outputs land here."""
    shutil.copy(FIXTURES_DIR / SOURCE, tmp_path / SOURCE)
    return tmp_path


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_regenerated_bytes_match_golden(case, root):
    out = run_case(ProjectRegistry(root), case)
    golden = GOLDEN_DIR / case.golden
    assert golden.exists(), f"missing golden {golden}; run the harness and promote"
    assert out.read_bytes() == golden.read_bytes()


def test_goldens_and_verified_manifest_agree():
    names = {case.golden for case in CASES}
    assert set(VERIFIED) == names
    assert {p.name for p in GOLDEN_DIR.glob("*.L5X")} == names


@pytest.mark.parametrize("name", sorted(VERIFIED))
def test_golden_sha256_matches_verified(name):
    entry = VERIFIED[name]
    assert _sha256(GOLDEN_DIR / name) == entry["sha256"], (
        f"{name} changed since it was verified on Logix Designer; re-run the harness"
    )
    assert set(entry["logix"]) == {"37", "38"}
    assert entry["verified"]
