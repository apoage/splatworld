# Handoff — 2026-07-19 — Paint cross-dab spacing v0.25.1 (Kimi K3 alt-model eval #2)

Scoped factory run (queue banner: ONE task only): Splat Studio follow-up #1,
`tasks/2026-07-19-paint-cross-dab-spacing.md`. **SHIPPED as v0.25.1** (commit `663a562`, tag
`v0.25.1`). Second alt-model implementer eval after the GLM v0.25.0 run — same protocol:
worker implements, panel verifies, planner reconciles.

## Shipped

| version | item | verification |
|---|---|---|
| v0.25.1 | Paint cross-dab Poisson spacing: one stroke-wide `SpatialHash` in the `apply_ops` paint branch (new optional `shared_grid` param on `sample_disc`), min_dist>0 only | medium panel (correctness + regression + flow-verifier): **no BLOCKER/MAJOR, no findings survived any lens** |
| | Gate gap: `_check_paint_poisson` in `splat_studio_smoke.gd` — multi-dab repro through `apply_ops`, asserts every stroke-wide pair ≥ min_dist + replay byte-identity | red→green proven twice independently (implementer + flow-verifier with md5-verified tree restore): HEAD fails with exactly the spec's 28 pairs / gap²=0.0002; fix passes, min gap²=0.1621 vs md²=0.1600 |
| | Objective gates | pytest **141 passed**; `splat_studio_smoke` / `carpet_smoke` / `carpet_perf` / `smoke_test` all PASS exit 0; build smoke (`SMOKE_REQUIRE_ASSET=1 precompute/smoke.sh`) OK incl. real train_base+export on the 3090 |

## Decision-changing findings

None. No DECISIONS row needed. D9/D10 untouched (D10's first-slice prediction — "worker dies on
a cap" — was confirmed again, see below).

## What the panel established (beyond the implementer's report)

- **Correctness judge**: old-vs-new full-precision byte-diff over 8 configs — only the two
  intended cases moved (multi-dab md>0: 36→25; task repro: 32→19). Direct shared-grid probe:
  dab2 at a saturated center places 0. Hostile forms (string/NaN/INF/negative min_dist, malformed
  paths, min_dist = 2·radius saturation) all degrade exactly as before. Grid math: cell = min_dist
  → 3×3 neighborhood provably exhaustive, exact Euclidean rejection → no under/over-reject.
- **Regression judge**: 17-case byte-equality matrix (executed, not read); guard parity between
  the apply_ops branch and the old per-dab `_num` guard across every hostile min_dist form;
  `sample_disc` has exactly one live caller; smoke diff purely additive; nothing else parses the
  SPLAT_STUDIO labels.
- **Flow-verifier**: re-ran every claimed artifact itself; tree restored byte-identical (md5)
  after its red-test swap; confirmed scope = the 3 expected files only.

## Known behavior change (intended, spec'd)

Multi-dab paint + min_dist>0 now places FEWER instances (cross-dab culling). A v0.25.0-era saved
doc containing such a stroke will trip `open_doc`'s integrity replay on load — the tripwire
working as designed, not a defect. No such docs exist in the repo (regression judge grepped).

## Eval notes — Kimi K3 worker (alt-model eval #2)

- Implementation itself was one-shot clean: correct minimal diff, honest red→green self-evidence,
  and it correctly refused scope creep (left banner/version/commit to the orchestrator, flagged
  the pre-existing `%g` latent instead of fixing it).
- **Worker-death pattern repeated**: the whole verify panel (3 agents) died mid-run on the
  provider's 403 usage-limit — same failure class as the GLM worker on v0.25.0, this time hitting
  verification instead of implementation. Resumed all three from transcripts via SendMessage
  after quota refreshed; each completed with full context. This is now **two for two** on
  alt-model runs hitting provider-cap death → D10's B-route rationale (main handles worker
  death/reroute) keeps accumulating evidence.
- **Concurrency hazard found (process, not code)**: two verify agents independently swapped
  `scatter_core.gd` to HEAD for red-tests and raced each other — the correctness judge briefly
  observed pre-fix behavior from the flow-verifier's swap and burned cycles reconciling. For
  future panels: red-tests that mutate shared working-tree files should be serialized or done on
  a scratch copy (the gate-integrity auditor's mutation-proven approach on a copy is the model).
- Implementer left two untracked temp files (`godot/scatter_old_tmp.gd`,
  `godot/relight/tools/_regress_probe.gd`) — caught by the panel, deleted pre-commit. Minor
  hygiene note for worker prompting.

## Where it stands

- Splat Studio follow-ups: **#1 DONE (v0.25.1)**. Remaining: #2–#4 factory-gateable MINORs
  (op-key drift, resync `queue_free` guard, log hygiene — good next worker slice), #5–#6
  owner-attended (viewer wiring + rest of 4b belt). Then M4 task 5 (cleanup-select) / 6 (Blender).
- Pre-existing latent for the planner: `splat_studio_smoke.gd:148` uses unsupported `%g` in a
  failure-branch message (cosmetic; only fires if that check ever fails). Candidate to fold into
  the #4 log-hygiene slice.

## Unblock questions for the planner

1. Take #2–#4 as the next scoped worker run (same one-task protocol), or batch them into one
   "MINOR hygiene" task file?
2. Fold the `%g` latent into #4 (log hygiene) explicitly?

## Planner reconcile — independent verification (2026-07-19, Claude/orchestrator)

Because this is an alt-model eval and the verify panel was itself Kimi K3, the planner re-verified
independently rather than trusting the factory self-report. **Verdict: CONFIRMED GREEN.**

- **Diff trace** (`git show 663a562`): fix is minimal + correct — `shared_grid` optional param threads
  one stroke-wide `SpatialHash` through the paint branch; `fill_region` untouched; `min_dist==0` leaves
  both grids null; single-dab starts with an identical empty grid → all three byte-identity claims hold
  by construction. Scope = exactly `scatter_core.gd` + `splat_studio_smoke.gd` + follow-up note +
  VERSION/CHANGELOG (implementer lane). Tree clean, nothing pushed (matches `allow_push:false`).
- **Green re-run** (main tree, my invocation): `splat_studio_smoke` exit 0; new check prints
  `19 instances across 2 dabs; every pair >= min_dist (min gap^2=0.1621 vs md^2=0.1600); replay-stable OK`.
- **Independent mutation proof**: reverted ONLY `scatter_core.gd` to pre-fix `042003a` in the main tree
  (auto-restored via trap), kept the v0.25.1 gate → `_check_paint_poisson` went RED with exactly
  `28 of 32 placed across the stroke violate min_dist (closest gap^2=0.0002 vs md^2=0.1600)`, exit 1.
  So the gate is non-vacuous and catches this precise bug; it is not graded-its-own-homework.
  (Note: a worktree mutation is NOT viable here — a fresh worktree lacks the gitignored `.godot/`
  class cache, so GDGS `class_name GaussianSplatNode` fails to parse; mutate the main tree with a
  restore trap instead. Corroborates the panel's red-test-race finding — do red-tests serialized in the
  live tree, not on parallel copies.)
- **Regression**: `pytest precompute/tests -q` → **141 passed** (13.7s), independently re-run.

Process findings for the multiline track (separate repo): worker-cap death is now 2-for-2 on
alt-model runs (GLM impl-side, Kimi verify-side) → D10 B-route evidence; and red-test tree-mutation
must be serialized. Both recorded here + in the eval notes above.
