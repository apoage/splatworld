# smoke-loop — one-command end-to-end pipeline check (the automatic debugging loop's backbone)

**Size/risk:** S–M / low. **Status:** READY (after `2026-07-12-code-hardening` — depends on
its items 1 (train_base assertions) and 10 (smoke_test.gd parametrization)).

## Problem (owner mandate, 2026-07-12: "we should have a working automatic debugging loop")
The factory's implement → verify → fix cycle needs a fast, loud, machine-checkable signal to
iterate against. Today the only end-to-end check is a full training run driven by hand, and
failures surface as opaque mid-stage tracebacks. There is no single command that answers
"is the pipeline healthy?" in under ~3 minutes.

## Approach
Add `precompute/smoke.sh` (bash, `set -euo pipefail`), runnable from repo root:
1. `python -m pytest precompute/tests -q` (unit layer, seconds).
2. `python precompute/run.py --asset pxl_144634 --stages train_base,export --steps 400`
   (smoke-scale train on the existing ingested asset; ~1 min on the 3090; the hardened
   stage assertions from code-hardening are the pass/fail signal — use a `--min-psnr`
   floor appropriate for 400 steps, e.g. 12 dB).
3. `SMOKE_ASSET=assets/built/pxl_144634/train_base.ply SMOKE_MIN_COUNT=10000 ~/godot/godot
   --path godot --headless --script res://relight/tools/smoke_test.gd`
   (data gate on the artifact just produced — closes the loop through the Godot side).
On ANY failure: exit nonzero immediately and print the failing stage's name + last 30 log
lines (trap + tee to `assets/built/pxl_144634/smoke_last.log`). On success print one line:
`SMOKE OK (<total>s)`.

## Wiring (the "automatic" part)
- The factory's judges/flow-verifier use `smoke.sh` as the canonical "did I break the
  pipeline?" probe; iterate fix → rerun until it exits 0.
- After this ships, the PLANNER sets `commands.build` in `.dark-factory/config.json` to
  `bash precompute/smoke.sh` so the release ritual runs it before every commit
  (the factory cannot edit config — note the request in your handoff/validation doc).
- Skip-friendly: if `assets/raw/pxl_144634` is absent (fresh clone), exit 0 with
  `SMOKE SKIPPED (no local asset)` so CI-less environments don't hard-fail — but print
  it loudly; a skipped smoke is not a green smoke.

## Acceptance
- `bash precompute/smoke.sh` exits 0 on the current healthy tree in < 3 min (3090) and
  prints `SMOKE OK`.
- Negative check: with an injected failure (e.g. `--min-psnr 99`), it exits nonzero and the
  last lines name the failing stage.
- Runs green twice in a row (no state leakage between runs; overwrite outputs cleanly).
