# Splat Studio — follow-ups (from the Claude verify panel on the GLM-5.2 v0.25.0 run)

Splat Studio 4a core shipped GREEN in v0.25.0 (GLM-5.2 implemented, Claude-verified). The
adversarial panel surfaced these residuals — none blocked the core; ordered by severity. Each is
narrowly-scoped with an objective check, so this is a good **worker-fleet** task once the MCP harness
lands (or a quick Claude slice). Source: `docs/2026-07-19-handoff-splat-studio-glm.md` + the verify
run `wf_edb575ae-e41`.

## 1. [godot, borderline-MAJOR, TOP] Paint cross-dab Poisson spacing + close the gate gap
> **SPLIT OUT → `tasks/2026-07-19-paint-cross-dab-spacing.md`** (standalone scoped task, 2026-07-19,
> Kimi K3 alt-model eval). The full spec + DoD live there; this section is the origin record.
> **#1 DONE 2026-07-19** — one stroke-wide `SpatialHash` threaded from the `apply_ops` paint branch through every `sample_disc`; new `_check_paint_poisson` gate red (28/32 pairs < min_dist) → green; studio/carpet/perf/base smokes PASS, pytest 141.

`scatter_core.gd`: `sample_disc` allocates a FRESH `SpatialHash` per dab, and the `apply_ops` paint
branch shares only the `rng` across dabs — so `min_dist` is enforced *within* a dab but NOT *across*
overlapping dabs in one paint stroke (verified: `radius=1.0, path=[[0,0],[0.2,0]], min_dist=0.4,
count=30, seed=3` → 32 instances, **28 pairs closer than min_dist**, closest ≈0.013). Contradicts
spec 4a-a ("SpatialHash reused by fill, **paint**, and pick") + DoD check 3 (stated unscoped).
- **Fix:** thread ONE `SpatialHash` (created in the paint branch) through every `sample_disc` call of
  the stroke, so cross-dab neighbours are rejected. (Or explicitly rescope min_dist to per-dab + narrow
  DoD check 3 to fill — but the spec intent is stroke-wide spacing, so fix it.)
- **Gate gap to close (this is why it slipped):** `splat_studio_smoke.gd` only asserts Poisson on
  `fill_region`. Add a `_check_poisson`-style assertion on a **multi-dab paint op** (every accepted
  pair ≥ min_dist across the whole stroke). Determinism/replay are unaffected — keep those green.

## 2. [godot, MINOR] nudge/delete op key: `id` vs documented `target`
Producer (`splat_studio.gd:187,194`) and consumer (`scatter_core.gd:413,428`) key nudge/delete by
`"id"`; the task doc illustrated `"target"` (`tasks/2026-07-18-splat-studio.md`). Internally consistent
(works), but a hand-authored doc following the *documented* schema silently no-ops. **Fix:** pick one —
accept both keys on read, or update the task-doc example to `"id"`. Add a smoke assertion for whichever
is canonical.

## 3. [godot, MINOR/latent] `resync_materials` needs an `is_queued_for_deletion()` guard
`carpet_loader.gd:268-278` keeps any child still in `get_children()`, including a `queue_free()`'d node
(stays until frame-end). Not triggered today (shipped `_rebuild` frees synchronously), but a FUTURE
deferred Nudge/Delete slice doing `queue_free(); resync_materials()` same-frame would mis-shade for ≥1
frame. **Fix:** skip `n.is_queued_for_deletion()` in the walk (or document "free synchronously before
resync" as a precondition). Cheap insurance; do it before building the deferred-delete UI.

## 4. [godot, MINOR] test/log hygiene in `splat_studio_smoke.gd`
(a) Per-check "OK" prints are gated on `a.size() > 0`, not on the actual asserts, so a human reading
logs can see "…OK" and a "FAIL:" for the same check in one run (the sentinel/exit are still correct).
Gate the "OK" print on the check actually passing; add `return` after the `_check_undo:464-465` problem
append. (b) ~25 benign `ERROR: Condition "!is_inside_tree()"` lines from the aux `GaussianSceneRegistry`
in check 8 — register nodes only after they're in-tree (or read `si.y` without the transform sync) so a
real future error isn't buried. (c) Extend erase-last coverage to a **middle-variant** erase
([A,B,C]→[A,C]), not just the trailing variant.

## 5. [godot, owner-attended 4b] Viewer wiring (spec deviation)
`splat_studio.gd` is a standalone `Node`+`CanvasLayer`, not wired onto `orbit_viewer.gd` as the task
said (reuse `_add_slider/_add_option/_sync_ui`). Arguably better for headless testing, and within the
4b partial-credit boundary, but the "mode/panel on the viewer" deliverable is unfinished. Decide: keep
standalone (update the spec) or wire onto the viewer. Owner-attended (visual), not a factory gate.

## 6. [godot, owner-attended 4b] The rest of the tool belt
Paint-drag interaction, Nudge (ground-drag + Shift-height), Delete (click/paint-erase), MultiMesh
ghosts, `UndoRedo` widget, budget + est-fps meters, near-camera AABB warning. Deferred at the
partial-credit boundary; build owner-attended after #1.

## DoD
Fixes #1–#4 are factory-gateable (headless smoke additions + `pytest`/sibling-smoke regression clean).
#5–#6 are owner-attended (visual). Keep GDGS + PLY schema untouched; keep `load_carpet` byte-identical.
