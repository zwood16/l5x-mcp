# Studio 5000 verification harness

Imports the files our write tools generate into real Logix Designer (v37 and v38) through
the Logix Designer SDK on the Windows VM, then exports what Studio made of them and
compares it with our files. Files that pass become the golden fixtures in
`tests/golden/`, so the pytest suite never needs Windows or Rockwell software.

**Rule: pytest never calls the SDK.** `tests/test_golden.py` regenerates every case with
the tools and compares bytes with `tests/golden/` and hashes with `VERIFIED.json`. Nothing
under `tests/` imports from `tools/`.

## Files

| File | Runs on | Purpose |
|---|---|---|
| `../../tests/golden_cases.py` | anywhere | The cases: name, tool calls, kwargs, golden file, VM base. The single source of truth (pytest and the harness both import it). |
| `harness.py` | Linux | Run names, VM paths, which exports to take after each case. |
| `gen.py` | Linux | Runs each case (twice, to prove determinism) and writes `run{37,38}_{blank,example,chain}/` with the files and a `manifest.json`. |
| `go.sh <run-dir>` | Linux | Pushes a run folder to the VM, runs `runner.py`, and pulls `out/<run>` into `results/<run>/`. Uses `$VM_SH`, default `~/.copilot/skills/studio5000-sdk/scripts/vm.sh`. |
| `runner.py` | VM | Opens one base project and runs the manifest steps (`import`, `import_rungs`, `build`, `export`, `save_as`), recording each step's SDK messages and ImportLog in `results.json`. Adapted from py_l5x. |
| `check.py` | Linux | Judges every case on v37 and v38 and, with `--promote`, writes the goldens. |

## Workflow

```bash
uv run python tools/sdk/gen.py                 # cases -> run folders (+ determinism check)
for r in run37_blank run37_example run37_chain run38_blank run38_example run38_chain; do
  tools/sdk/go.sh tools/sdk/$r                 # run on the VM (~30 s each, chain may take longer)
done
uv run python tools/sdk/check.py               # PASS/FAIL per case and version
uv run python tools/sdk/check.py --log CASE    # ImportLog entries for one case
uv run python tools/sdk/check.py --promote     # only if everything passes: write tests/golden/
uv run pytest -q tests/test_golden.py
```

Order matters for one reason: `run38_chain` converts the ACD that `run37_chain` saves on the
VM, so run the v37 chain first. The `run38_*` folders import the same files as the v37 folders.

## What a case passes

On each version, a case passes when all of these hold:

1. Every step ran ok (`import`, `build`, `save_as`, and the exports that exist).
2. **Every ImportLog entry is `Info`, and the Summary reports 0 warnings and 0 errors.**
   Studio drops tag data with only a warning, so warnings count as failures.
   The SDK delivers an import's ImportLog after the import call returns, so it lands in the
   next step's messages (the build). `check.py` reads both.
3. **`build()` succeeds** (the project must build). The chain builds on v37 and v38.
4. **Every key our file has is in Studio's export with the same value**: controller and
   program tags with their values, operand comments, UDT members, AOI parameters and local
   tags, rungs and their comments, ST lines, routine types, programs and their main routine,
   tasks and their scheduled programs. Studio may add keys we did not write; those are ignored.
   Dict values compare on the keys we wrote, lists must match length and content.
   A tag with no `<Data>` in our file is not compared by value (Studio fills in type defaults).

`check.py` prints `keys_same`, and one `DIFF`/`MISSING` line per mismatch.

### Exports

Each case is followed by exports of five whole collections (`DataType` User, AOI definitions,
controller tags, programs, tasks) on that base. The collections are merged per case, but each
export contributes only the object type it is for, because partial exports include stubs of
other objects (a task export holds program stubs with no attributes). Exports are optional:
an empty collection is not a failure, and a missing object still fails step 4.

## Build skips

**None.** Every case builds, including the components that import into the example project
(`comp_routine`, `comp_rungs`, `exp_routine`, `exp_rungs`). A future case that references
module I/O tags can't build in `blank`: give it `vm="example"` (its modules exist there), or
set `build_skip` on its `Case` with the reason. `check.py` then reports `build=skipped (reason)`.

## Golden location (deviation from the original plan)

The goldens live in **`tests/golden/`**, not `tests/fixtures/golden/`. The existing test
`tests/test_registry.py::test_discover_finds_fixtures` asserts that a recursive discovery under
`tests/fixtures/` finds exactly 9 `.L5X` files. Goldens under `fixtures/` would make it find
23. To move them, change `GOLDEN_DIR` in `tests/golden_cases.py`; `check.py` and
`tests/test_golden.py` both read it from there. Then run `check.py --promote` again.

## Verification record

Logix Designer v37 (SoftwareRevision `37.00` in the exports) and v38 (`38.03`), on the
VM's installed SDK. The promoted hashes and the Logix versions are in `tests/golden/VERIFIED.json`.

## Tool issues found while verifying

1. **`set_tag_values` can't set an element of an array added with no value.**
   Repro: `add_tags(tags=[{"name":"Arr","data_type":"DINT","dimensions":4}])`, then
   `set_tag_values(values={"Arr[2]": 9})` raises `L5XError: Element [2] not found in 'Arr'`.
   With `"value": [0,0,0,0]` on the add it works. `add_tags` documents omitting `value` as
   "Studio uses the type's defaults", so the element should exist. The chain works around it
   by giving `ChArr` an explicit value (`golden_cases.py`, `CH_CTRL_TAGS`).

2. **ST boolean literals `TRUE`/`FALSE` import without complaint, then fail the build.**
   Repro: `create_aoi_file` with a ST line `Done := TRUE;` imports cleanly; `build()` fails with
   `RxSTX_E_TAG_NOT_FOUND - Referenced tag is undefined`. Studio's ST takes `1`/`0`. The tools
   don't check ST (the docs say so), so this is a caller error the tools could warn about.
   The case uses `1`/`0`.

3. **Observation, not a failure:** `create_rungs_file` numbers the new rungs from the target
   routine's current rung count. Importing into `MainRoutine` (which has 1 rung) writes
   `Rung Number="1"`. Studio ignores the number on `import_rungs`, imports and builds it fine,
   and the rung is at position 0 after the import. Consider numbering from 0 in the file.

## Harness notes

- ImportLog bodies arrive after the import call (see "What a case passes"). A missing or
  incomplete ImportLog fails the case rather than passing silently.
- Imports and builds are cumulative: once a build fails, every later build in the same run
  reports the same error. `gen.py` therefore builds after every import, so the first failing
  build names the case. Keep it that way.
- Each VM run opens its base once (about 15 s), and each base is only read. Nothing is saved
  except the `save_as` in the chain run, which writes into `out/`.
- The chain runs in `run37_chain` and `run38_chain`. v38 uses a copy of the saved v37 ACD,
  converted with `LogixProject.convert` (the runner copies it first, so the v37 file is kept).
- `go.sh` does not delete base projects. Only `projects\<run>` and `out\<run>` are replaced.
