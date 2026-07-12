# smoke-loop — one-command end-to-end pipeline check (the automatic debugging loop's backbone)

> **STATUS (2026-07-12): SHIPPED as 0.4.0.** `precompute/smoke.sh` (+ `run.py --out-root`/
> `--min-psnr`, `.gitignore .smoke/`). Verified by flow + correctness panel over one fix cycle:
> green `SMOKE OK (22s)` with byte-identical clean tree, negative rc≠0 names the stage,
> `SMOKE_REQUIRE_ASSET=1` hard-fails a missing-asset skip (commit-gate safe), false-green
> attacks refuted (tee/pipefail/conda rc propagation; masked `--import` can't false-pass).
> Verdict: `.dark-factory/verdicts/current.json`.
> **PLANNER follow-up (config lane):** wire `commands.build = SMOKE_REQUIRE_ASSET=1 bash
> precompute/smoke.sh` so the release ritual runs smoke before every commit — done at wrap-up.
> Note: a pre-existing broken `res://scenes/single_asset.tscn` emits a red (non-fatal) ERROR
> during `godot --import`; flagged for a cleanup slice.

**Size/risk:** S–M / low. **Status:** SHIPPED (0.4.0); commands.build wiring at wrap-up.
(Built on `2026-07-12-code-hardening` items 1 (train_base assertions) and 10 (smoke_test.gd parametrization).)

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
