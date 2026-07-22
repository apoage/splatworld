# Handoff — Splat Studio hygiene batch, v0.25.2 (alt-model eval #3)

**Date:** 2026-07-22
**Task:** `tasks/2026-07-19-splat-studio-hygiene.md` (SHIPPED, banner on file)
**Commit/tag:** `26a293e` / `v0.25.2` (LOCAL — not pushed; `allow_push:false`)
**Run type:** scoped single-task dark-factory run (alt-model eval #3). One task, then stop
for planner reconcile — per the QUEUE Ready directive.

## What shipped

The three factory-gateable MINORs from the v0.25.0 verify panel, batched with the
pre-existing `%g` failure-branch latent. Four items, three code files + two task-doc edits.

| Item | File | Change |
|---|---|---|
| #2 op-key alias | `scatter_core.gd` | new `_op_target_id(op)` — `id` canonical, `target` accepted as alias on read; wired into `_apply_nudge` + `_apply_delete`. Missing/non-numeric key still no-ops (no SCRIPT ERROR); disc-delete `center`+`radius` branch untouched. Task-doc example (`2026-07-18-splat-studio.md`) corrected to `"id"` with a `target`-also-accepted note. |
| #3 resync guard | `carpet_loader.gd` | `resync_materials` skips `is_queued_for_deletion()` nodes so a `queue_free()`'d node's resource never enters the ordered unique set. `load_carpet` + resync happy-path byte-identical. |
| #4a honest OK prints | `splat_studio_smoke.gd` | OK prints gate on a per-check `n0 := problems.size()` snapshot (not global array / bare `else`) + added missing `return` in `_check_undo`. Logging honesty only — no assertion weakened. |
| #4b spam kill | `splat_studio_smoke.gd` | ~25 `!is_inside_tree()` error lines gone — `_check_resync` is now a coroutine that `await`s an in-tree frame before the aux `GaussianSceneRegistry` registers nodes. |
| #4c middle-erase | `splat_studio_smoke.gd` | new [A,B,C]→[A,C] erase coverage: ordered uniques == tree order, prior si.y unshifted. |
| #4d `%g` latent | `splat_studio_smoke.gd` | failure-branch `%g` (unsupported by GDScript `String %`) → `%.4f`. |

Two new non-vacuous smoke checks added: `_check_op_key_alias` (#2) and
`_check_resync_queued_free` (#3), both mutation-proven red→green.

## Verification

Medium-tier panel `[judge:correctness, judge:regression, flow-verifier]` — **no
BLOCKER/MAJOR, no findings** from any lens.

- **correctness:** id-canonical precedence + no-op degradation confirmed; all three new
  assertions mutation-proven non-vacuous; `%.4f` valid.
- **regression:** `load_carpet` byte-identical (change isolated to `resync_materials`);
  id-vs-target output identical for valid-id AND missing-key ops (the old `-1.0` fallback
  matched no real instance → same observable no-op as the new `null`); OK-print refactor
  is logging-honesty only; sole behavior delta (op with non-numeric `target` + `center`/
  `radius`) is **unreachable** — the producer (`splat_studio.gd`) never emits `target`.
- **flow-verifier:** all DoD claims verified; `is_inside_tree` grep=0; red→green proven for
  #2 and #4c; the 11 ERROR/8 WARNING lines remaining are all intended degrade-path
  `push_error`/`push_warning` from the hostile-JSON / finite-reject / protected-path checks.

Objective gates (orchestrator re-ran on the final tree): `splat_studio_smoke` PASS (exit 0),
`carpet_smoke` / `carpet_perf` / `smoke_test` PASS, pytest **141 passed**, precompute build
smoke PASS (48023-pt asset).

## Note for the planner: concurrent `git reset` observed mid-run

The flow-verifier reported (and the reflog confirms `e2a7e01 HEAD@{0}: reset: moving to
HEAD`) that a concurrent process ran a `git reset` while the panel was executing. It briefly
unstaged/reverted `carpet_loader.gd` + `scatter_core.gd`; the verifier restored them and the
orchestrator independently re-confirmed the final tree intact (5 files modified, all markers
present, `%g` count 0) before committing. **No lost work** — the commit contains the full
batch. If another session is touching git in this repo, worth checking whether it's an
overlapping planner action. This run left the tree clean and nothing pushed.

## Where it stands / next

M4 authoring track: Splat Studio 4a core (v0.25.0) + Paint cross-dab (v0.25.1) + this
hygiene batch (v0.25.2) are all in. Remaining Splat Studio residuals **#5 + #6 are
owner-attended 4b** (viewer wiring + rest of the tool belt) — NOT factory work. Next
unattended-factory pickups per the queue remain FILLER (quality-pass slice 6/7, docs-guide)
or the pixel5 scheduled one-shot; the main M4 authoring push is owner-attended WYSIWYG.
D9 (mixed-scene material-buffer ownership) stays gated to Moon-Stone.
