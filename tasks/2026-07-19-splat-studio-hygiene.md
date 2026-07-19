# M4 — Splat Studio hygiene batch (follow-ups #2 + #3 + #4, + the %g latent)

Batches the three factory-gateable MINORs from `tasks/2026-07-19-splat-studio-followups.md` (#2 op-key,
#3 resync guard, #4 test/log hygiene) into one cohesive run, plus the pre-existing `%g` format latent.
Scope = these four items only. #5/#6 are owner-attended (viewer wiring + rest of 4b belt) — do NOT touch.

> Line-number caveat: v0.25.1 inserted `_check_paint_poisson` (~+41 lines), so the followups file's
> line refs are stale. Locate by function/behavior, not by the quoted line numbers.

## #2 — nudge/delete op key: accept `id` and `target`

The producer (`splat_studio.gd` `commit_nudge`/`commit_delete`) emits `"id"`; the consumers
(`scatter_core.gd` `_apply_nudge`/`_apply_delete`) read `"id"`. Works today, but the task doc
(`tasks/2026-07-18-splat-studio.md`) illustrated `"target"`, so a hand-authored op following the doc
silently no-ops.
- Resolve so an op keyed by EITHER `id` or `target` resolves identically (`id` canonical, `target`
  accepted as an alias on read, in both `_apply_nudge` and `_apply_delete`). Keep the hostile-doc
  discipline — a missing/non-numeric key still degrades to a no-op, never a SCRIPT ERROR.
- Fix the task-doc example to the canonical `"id"` (leave a one-line "(`target` also accepted)" note).
- Add a smoke assertion proving both keys hit the same instance (must fail if only one key is honored).

## #3 — `resync_materials` needs an `is_queued_for_deletion()` guard

`carpet_loader.gd` `resync_materials` walks `carpet_parent.get_children()` (~line 268) and keeps any
`GaussianSplatNode` with a non-null `gaussian` — including a `queue_free()`'d node, which lingers until
frame-end. Not hit today (the shipped `_rebuild` frees synchronously), but a future deferred Nudge/Delete
doing `queue_free(); resync_materials()` in one frame would mis-shade for ≥1 frame.
- Skip `n.is_queued_for_deletion()` nodes in the walk.
- Add coverage: a node marked `queue_free()` before `resync_materials` must be excluded from the ordered
  unique set (assert the cached order / material count reflects the exclusion). `load_carpet` and the
  existing resync happy-path stay byte-identical.

## #4 — test/log hygiene in `splat_studio_smoke.gd` (+ the %g latent)

- **(a) Honest OK prints:** several per-check "OK" prints are gated on `problems`/array size rather than
  on that check actually passing, so a human can see both "…OK" and a "FAIL:" for one check in a run
  (sentinel/exit stay correct — this is log honesty only). Gate each "OK" print on the check's own
  asserts, and add the missing `return` after the problem-append in the undo check so it doesn't fall
  through to its OK print.
- **(b) Kill the benign error spam:** ~25 `ERROR: Condition "!is_inside_tree()"` lines come from the aux
  `GaussianSceneRegistry` in the resync check registering nodes before they're in-tree. Register only
  after in-tree (or read `si.y` without the transform sync) so a real future error isn't buried.
  (Confirmed live: the current smoke run emits these from `_check_resync`.)
- **(c) Middle-variant erase coverage:** the resync check erases only the trailing variant
  ([A,B,C]→[A,B]). Add a middle-variant erase ([A,B,C]→[A,C]) and assert ordered uniques == tree order
  with the prior si.y unshifted.
- **(d) %g latent:** the `_check_poisson` failure-branch message uses `%g` (unsupported by GDScript
  `String %`), which would itself error the moment that branch fires. Change to a supported format
  (e.g. `%f`/`%.4f`). Cosmetic + failure-branch-only, but fix it while in the file.

## DoD

- `~/godot/godot --path godot --headless --script res://relight/tools/splat_studio_smoke.gd` exits 0
  with the new #2 both-keys assertion and the #4c middle-erase assertion present and passing; the
  `!is_inside_tree()` spam is gone from its output.
- New assertions are non-vacuous: the #2 key-alias check fails if `target` is not honored; the #4c
  middle-erase check fails on a wrong ordered set. (State how you proved red→green.)
- Sibling smokes still pass: `carpet_smoke.gd`, `carpet_perf.gd` (structure self-check), `smoke_test.gd`.
- `conda run -n splat-relight python -m pytest precompute/tests -q` → 141 passed.
- No regression: `load_carpet` byte-identical; the resync happy-path (add-existing / add-new / erase-last)
  unchanged; `scatter_core` determinism + stroke-replay + paint-poisson checks green; `fill_region`,
  `min_dist==0`/single-dab paint output byte-identical.

## Constraints

- Touch only: `godot/relight/scatter_core.gd`, `godot/relight/carpet_loader.gd`,
  `godot/relight/tools/splat_studio_smoke.gd`, and the doc example in `tasks/2026-07-18-splat-studio.md`
  (plus a "#2–#4 done" note in the followups file). No unrelated refactor.
- Never weaken/skip/delete an existing assertion to make the suite pass — the OK-print change is about
  honesty, it must not reduce what any check verifies.
- GDGS (`godot/addons/gdgs/`), the PLY schema/`ply_io.py`, and `precompute/` untouched. No new runtime
  dependency, no schema bump.

## Risk tier: medium — `[judge:correctness, judge:regression, flow-verifier]`
(`resync_materials` is the M4 material-buffer path — regression on `load_carpet`/resync byte-identity is
the main risk; the smoke changes must stay non-vacuous.)
