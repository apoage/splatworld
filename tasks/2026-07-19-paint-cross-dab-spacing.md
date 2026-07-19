> **STATUS (2026-07-19): SHIPPED as v0.25.1** — one stroke-wide `SpatialHash` threaded through the
> paint branch (`shared_grid` param on `sample_disc`); repro 28 violating pairs → 0 (32→19 instances,
> cross-dab culling as intended). New `_check_paint_poisson` gate red→green-proven (flow-verifier,
> md5-restored tree). Medium panel (correctness/regression/flow-verifier): no BLOCKER/MAJOR.
> fill/min_dist==0/single-dab byte-identical (17-case old-vs-new matrix). pytest 141, all 4 smokes
> PASS, build smoke OK. Kimi K3 alt-model eval #2. No remainders. Handoff:
> `docs/2026-07-19-handoff-paint-cross-dab-v0.25.1.md`.

# M4 — Splat Studio follow-up #1: Paint cross-dab Poisson spacing + close the gate gap

Splat Studio 4a shipped GREEN in v0.25.0; the Claude verify panel flagged one borderline-MAJOR
residual (`tasks/2026-07-19-splat-studio-followups.md` §1). Fix it and close the gate gap that let it
ship. Scope is this task only — do NOT pick up follow-ups #2–#6.

## Bug

`ScatterCore.sample_disc` (`godot/relight/scatter_core.gd:261-309`) news a fresh `SpatialHash` per dab
(`scatter_core.gd:285-287`). The `apply_ops` paint branch (`scatter_core.gd:367-391`) shares one `rng`
across a stroke's dabs but not the hash grid, so `min_dist` rejection holds *within* a dab but not
*across* overlapping dabs. Contradicts the 4a-a contract ("SpatialHash reused by fill, **paint**, and
pick") and the intended stroke-wide spacing.

Verified repro (fails today, must pass after): a paint op `radius=1.0, path=[[0,0],[0.2,0]]`,
`cfg={count:30, min_dist:0.4, ground_y:0, variants:[{id:"a",weight:1}], yaw:[0,0], scale:[1,1]}`,
`master_seed=3` → ~32 instances, **28 pairs closer than min_dist** (closest ≈0.013).

## Fix

Make a paint stroke's `min_dist` spacing hold across dabs — one shared neighbour grid for the whole
stroke, so a dab rejects points too close to points placed by earlier dabs. Preserve determinism
(no Time/random seeds, no unordered iteration; replay reproduces `instances[]` byte-identically).

## Close the gate gap

`_check_poisson` (`godot/relight/tools/splat_studio_smoke.gd:124-155`) asserts the min_dist floor on
`fill_region` only — that's why this slipped. Add a smoke assertion that runs a multi-dab paint op
through `apply_ops` and checks every accepted pair across the whole stroke is ≥ min_dist. It must fail
on the current code and pass after the fix (a check that can't fail is not a fix).

## DoD

- Cross-dab spacing enforced: the repro yields 0 pairs closer than min_dist across the stroke.
- New paint-Poisson smoke assertion added, wired into the runner, red→green across the fix.
- `~/godot/godot --path godot --headless --script res://relight/tools/splat_studio_smoke.gd` exits 0
  (all checks incl. the new one); sibling smokes still pass (`carpet_smoke.gd`, `carpet_perf.gd`
  structure self-check, `smoke_test.gd`).
- `conda run -n splat-relight python -m pytest precompute/tests -q` → 141 passed.
- No regression: `fill_region`, `min_dist==0` paint, single-dab paint, and `load_carpet` stay
  byte-identical; determinism + stroke-replay checks green.

## Constraints

- Touch only `godot/relight/scatter_core.gd` and `godot/relight/tools/splat_studio_smoke.gd` (plus a
  one-line "#1 done" note in the follow-ups file). No unrelated refactor.
- Never weaken/skip/delete an existing assertion to make the suite pass — fix the code, not the gate.
- GDGS (`godot/addons/gdgs/`), the PLY schema/`ply_io.py`, and `precompute/` stay untouched. No new
  runtime dependency, no schema bump.

## Risk tier: medium — `[judge:correctness, judge:regression, flow-verifier]`
