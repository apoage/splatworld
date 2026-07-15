# Handoff #6 — dark-factory run #5: normal-quality D5 fix (shipped) + lighting-stability (WIP)

Previous: `lore/handoff_2026-07-14_run4-ground-align-normal-diag.md`
(chain: m2-build → run3-m2-complete → planner-viewer-feedback → run4-ground-align-normal-diag → **this**)

- **Branch:** main · **Working dir:** /home/lukas/splatworld
- **Session focus:** Ran the dark-factory over the 2026-07-14-late-groomed queue (owner "factory armed
  now"). Shipped **v0.13.0 normal-quality STEP 2** — the D5 sparkle fix (k-NN normal smoothing folded
  decompose-side, before its trusted held-out-PSNR gate; opt-in `--smooth-normals-iters`, default
  0 = exact no-op), validated on a real re-decompose (PSNR −0.11 dB, shimmer −75.3%, coherence
  0.579→0.922). Started **lighting-stability** (Ready #2): `render_matrix.gd` committed as WIP — runs
  end-to-end + emits JSON, 6/10 checks pass, 4 harness-logic fixes pending. Verification via
  correctness+regression+flow-verifier panels (all clean). Factory disarmed; nothing pushed.
  **Post-run (planner reconcile #5, commits 721ef1a + 489de5d):** slice-5 rollout landed for
  pxl_144634 (smoothed asset promoted to built + gs_assets mirror, originals `*_unsmoothed.*.bak`,
  viewer now loads smoothed — owner eyeball pending); Moon-Stone demo items attached to M4/M5.

## Compaction rubric (chandoff 2026-07-15)

```
KEEP IN FULL:
- Run #5 disarmed, implementer lane clean, nothing pushed. SHIPPED v0.13.0 = normal-quality
  STEP 2 (D5 fix): k-NN normal smoothing folded DECOMPOSE-side (before its trusted held-out-PSNR
  gate), opt-in --smooth-normals-iters (default 0 = EXACT no-op). lighting-stability = WIP only.
- lighting-stability (Ready #2) NOT shipped: render_matrix.gd committed, runs + emits JSON, 6/10
  checks PASS; 4 FAIL are ALL HARNESS bugs (NOT engine findings, no DECISIONS row) → the 4 fixes:
  (1) sphere off-frame n_px=0 → reposition into view; (2) energy sweep not ambient-nulled
  (ratio==1.0) → ambient=0 + env cleared; (3) raw_invariance 14dB includes engine-lit sphere →
  mask foliage; (4) trans_inertness 45<55dB readback noise → mask foliage + realistic threshold.
- Planner reconcile #5 (OUTSIDE my lane) already did slice-5 rollout for pxl_144634: promoted the
  smoothed decompose → assets/built + gs_assets mirror (originals *_unsmoothed.*.bak); viewer loads
  smoothed, OWNER EYEBALL PENDING. REMAINING: re-decompose pxl_131945 --smooth-normals-iters 2 +
  demo/gif regen. New pixel5 variants: decompose with --smooth-normals-iters 2 (bake in fix).

COMPRESS + POINT:
- Entire v0.13.0 build->3-lens-panel->GPU-validate->ship narrative -> docs/validation-normal-quality-
  step2-2026-07-15.md + CHANGELOG [0.13.0] + docs/2026-07-15-handoff-5-run5.md. Do NOT re-narrate.
- 3 verification panels (correctness+regression+flow-verifier) -> collapse to "all clean; flow-verifier
  independently reproduced shimmer 48.77 + coherence 0.9222". Do NOT re-list per-lens findings.
- lighting-stability harness detail -> render_matrix.gd WIP header + handoff #5.

DROP (this session's process noise -- all pure infra friction):
- ALL stop-gate/yield friction, TaskOutput transcript dumps, PID-wait/Monitor mechanics, background
  task IDs, the render auto-backgrounding dance, the implementer's mid-session usage-limit death +
  resume + TaskStop.
- Intermediate lighting-matrix survey/partial-run states (48-PNG runs, rate measuring).

VERBATIM ANCHORS:
- v0.13.0 = normal-quality D5 fix (step 2/2). Commits 578582d (v0.13.0) · fc108c2 (run#5 wrap-up WIP).
  Tags -> v0.13.0. Suite 88 passed.
- Fix validation (real re-decompose pxl_144634): PSNR 21.572 (-0.11dB, <=1.5 OK), shimmer 48.77
  (-75.3% vs 197.53 baseline, <=98.8 OK), coherence 0.579->0.922, over_smooth_suspect=false.
  Gate = shimmer<=98.8 (necessary-NOT-sufficient) AND held-out PSNR<=1.5dB AND coherence tripwire.
- core/normals.py smooth_normals_knn (self+kNN mean, renormalize, iterate; == gaussian_twinkle preview).
- Godot pixel tools: DISPLAY=:0, NO --headless (--headless = false FAIL). render_matrix.gd needs it.

UNCERTAIN (flag for correction):
- Next priority: finish lighting-stability (4 harness fixes) vs pixel5-variants vs the pxl_131945/
  demo-regen tail of slice 5.
- Whether committing render_matrix.gd as WIP (fails its own checks) on main was the right call vs
  stash/branch -- done, but flagging.
- lore/notes_2026-07-15 (planner) flags a competitor fork (LonKeyDotae/godot-gaussian-splatting-relight,
  at our pinned commit be61f8f) + "Moon Stone Meadow" demo north star -> point-light/day-night/fireball
  runtime work implied for M4/M5. Planner-lane; may become load-bearing.
```

## Git state (safety-net, not for the rubric)

```
$ git log -5 --oneline
489de5d Slice-5 rollout artifacts: smoothed decompose+export metrics for pxl_144634; ignore .bak backups; render_matrix uid
721ef1a Reconcile run #5: slice-5 rollout on pxl_144634 (smoothed asset live in viewer); attach Moon-Stone demo items to M4/M5; survey + demo lore
fc108c2 docs: dark-factory run #5 handoff + lighting-stability WIP harness
578582d normal-quality: k-NN normal smoothing fix, decompose-side + PSNR-gated (v0.13.0, D5 step 2 of 2)
353d81d Handoff #5 (factory run4) + planner postscript: alignment eyeball PASSED, pixel5 ungated

$ git status --short
(clean)
```
Tags v0.2.0 … **v0.13.0**. Factory disarmed. Nothing pushed.

## Next action

Highest user-visible value = the **slice-5 tail**: owner-eyeball the now-smoothed pxl_144634 in the
viewer, then re-decompose **pxl_131945** with `--smooth-normals-iters 2` + re-export/re-mirror, then
regen the demo/gif. Then either **finish lighting-stability** (the 4 harness fixes in
`render_matrix.gd`'s WIP header) or **pixel5-variants → M4** (decompose fresh with the fix baked in).
M3 (transmission) is unblocked now that normal-quality step 2 shipped.
