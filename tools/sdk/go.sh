#!/usr/bin/env bash
# go.sh <run-dir>
#
# Pushes a run folder (tools/sdk/run*/, made by gen.py) to the VM, runs its
# manifest with runner.py, and pulls out/<run> back to tools/sdk/results/<run>/.
#
#   tools/sdk/go.sh tools/sdk/run37_blank
#
# VM_SH overrides the vm.sh helper (default: the studio5000-sdk skill in ~/.copilot).
# The runner's exit code is returned, but results are pulled either way.
set -euo pipefail

VM_SH="${VM_SH:-$HOME/.copilot/skills/studio5000-sdk/scripts/vm.sh}"
if [ ! -x "$VM_SH" ]; then
  echo "vm.sh not found or not executable: $VM_SH (set VM_SH)" >&2
  exit 2
fi

HERE="$(cd "$(dirname "$0")" && pwd)"
d="$(cd "$1" && pwd)"
run="$(basename "$d")"

"$VM_SH" cmd "if exist projects\\$run rmdir /s /q projects\\$run & if exist out\\$run rmdir /s /q out\\$run" >/dev/null
"$VM_SH" put "$d" projects >/dev/null

rc=0
"$VM_SH" run "$HERE/runner.py" "C:\\Users\\zwood\\ldsdk\\projects\\$run\\manifest.json" || rc=$?

mkdir -p "$HERE/results"
rm -rf "$HERE/results/$run"
"$VM_SH" get "out/$run" "$HERE/results/" >/dev/null || echo "could not pull out/$run" >&2
echo "runner exit=$rc; results in $HERE/results/$run"
exit "$rc"
