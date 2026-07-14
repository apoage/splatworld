# Handoff #5 — dark-factory run #4: ground-alignment + normal-quality diagnosis (2026-07-14)

Previous: `lore/handoff_2026-07-13_planner-viewer-feedback.md`
(chain: m2-build → run3-m2-complete → planner-viewer-feedback → **this**)

- **Branch:** main · **Working dir:** /home/lukas/splatworld
- **Session focus:** Ran the dark-factory over the 2026-07-13-groomed queue (owner "run factory").
  Shipped **v0.11.0 ground-alignment** (full — world-up from the camera ring composed into export's
  single COLMAP→Godot conversion; env-SH sidecar rotated identically) and **v0.12.0 normal-quality
  D5 diagnosis** (STEP 1 of 2 — the sparkle is attributed + a render-free measurement tool built;
  the FIX is seeded, not built). Design/verification via read-only Workflows (ultracode); code
  through the guard-railed implementer + adversarial panels. Factory disarmed at end; nothing pushed.
  **Post-run (planner/owner thread, commits db1ebe4 + 422936b):** D2 DECIDED, step-2 GO, lighting-lab
  viewer shipped, lighting-stability harness seeded, unreal-port parked.

## Compaction rubric (chandoff 2026-07-14)

```
KEEP IN FULL:
- Run #4 disarmed, tree clean, nothing pushed. Shipped v0.11.0 ground-alignment (FULL) +
  v0.12.0 normal-quality D5 diagnosis (STEP 1 of 2 — the FIX is NOT built, only seeded).
- normal-quality STEP-2 gate (load-bearing, subtle): `shimmer <= 98.8` is necessary-NOT-
  sufficient (gameable by over-smoothing garbage) -> step 2 MUST ALSO validate held-out
  re-render PSNR <=1.5 dB on the smoothed/SHIPPED normals + an anti-over-smoothing guard.
  Sparkle verdict = spatial neighbour-normal incoherence (not sort/aliasing, not floaters).
- pxl_144634 alignment_suspect=true (43.5deg plane-normal vs camera-up) -> OPEN owner eyeball;
  both candidate ups recorded in metrics (up_colmap = plane-normal, mean_camera_up_colmap),
  so the cue can be switched with NO re-decompose. pxl_131945 clean (22deg).
- Owner post-run decisions (commits db1ebe4 + 422936b, already in QUEUE): D2 DECIDED (500k +
  opacity prune) + step-2 GO; D3 handled (suppress GDGS conditional -180Z node default on the
  relightply path); an albedo-saturation report was refuted with data. Ready = (1) normal-quality
  STEP 2, (2) NEW tasks/2026-07-14-lighting-stability.md; unreal-port PARKED (Epic MegaGrants
  candidate); lighting-lab viewer shipped planner-side.

COMPRESS + POINT (one line each; do not re-summarize):
- Entire run-#4 build->panel->fix->re-verify->ship narrative for v0.11.0 + v0.12.0
  -> docs/2026-07-14-handoff-4-run4.md + CHANGELOG [0.11.0]/[0.12.0] + the two validation docs.
- 5 verification workflows / ~20 agent-verdicts -> collapse to: every finding fixed+re-verified;
  only the 2 decision-changing findings above survived. Do NOT re-list per-lens findings.
- ground-alignment SH-rotation + fail-closed + byte-identity fix detail
  -> docs/validation-ground-alignment-2026-07-14.md + CHANGELOG [0.11.0].
- sparkle-metric evolution (8-bit d2 confound -> self-temporal non-discriminating ->
  neighbour-shimmer) -> docs/validation-normal-quality-diagnosis-2026-07-14.md.

DROP:
- All TaskOutput blocking/re-blocking/timeout mechanics, journal reads, /workflows task IDs,
  agent IDs, and the workflow-aggregator Promise.all Type-error (first panel; recovered).
- The DISCARDED intermediate sparkle numbers (screen 3.343 / 26x — superseded; only the final
  per-Gaussian shimmer=197.53 baseline matters, and it lives in the validation doc).
- Per-fix-pass minutiae of the 5 ground-alignment fixes across 2 fix passes (-> changelog/doc).

VERBATIM ANCHORS (unchanged):
- v0.11.0 = ground-alignment; v0.12.0 = normal-quality D5 diagnosis (step 1/2). Tags -> v0.12.0.
  Commits cddf80b (handoff) · 3d55acd (v0.12.0) · 13b5c83 (v0.11.0). Suite 78 passed.
- ground-alignment: single conversion C = M @ R_align in ply_io.colmap_to_godot; env-SH rotated
  identically (real deg-2 SH rotation, sh_env.sh_rotation_matrix/rotate_env_sh). SCHEMA_VERSION 1.
- normal-quality: precompute/tools/gaussian_twinkle.py (render-free per-Gaussian shimmer);
  baseline shimmer=197.53 (x1000), pinned to pre-alignment decompose.ply/R_align=None, NOT
  rotation-invariant (±17%). Frame-guard refuses asset.ply.
- Godot pixel tools: DISPLAY=:0 ~/godot/godot --path godot --script <tool>, NO --headless
  (--headless = dummy renderer = false FAIL). Needed by the lighting-stability row.

UNCERTAIN (flag for correction):
- normal-quality step 2 (owner said GO) approach: export-time k-NN smoothing (preview -75%,
  appearance-stable) vs a decompose-side neighbour regularizer — real held-out-PSNR validation
  unbuilt, so which path is open.
- Whether the owner keeps pxl_144634's default plane-normal alignment or switches to camera-up
  (the 43.5deg suspect — not addressed in the owner's post-run commits).
- Ready #2 lighting-stability scope taken from the QUEUE note only — tasks/2026-07-14-lighting-
  stability.md (owner-authored post-run) NOT yet read.
```

## Git state (safety-net, not for the rubric)

```
$ git log -5 --oneline   # (owner planner-thread commits sit on top of the factory's)
422936b Viewer orientation: suppress GDGS conditional -180Z node default on relightply path (D3 rule); refute albedo-saturation report with data; D2 DECIDED (500k + opacity prune); step-2 GO
db1ebe4 Reconcile run #4: lighting-lab viewer (presets/day-cycle/manual sun); seed lighting-stability harness; park unreal (MegaGrants candidate)
cddf80b docs: dark-factory run #4 handoff + queue groom
3d55acd normal-quality: sparkle diagnosis + render-free shimmer metric (v0.12.0, step 1 of 2)
13b5c83 ground-alignment: estimate world-up from the camera ring, compose into export's single conversion (v0.11.0)

$ git status --short
(clean)
```
Tags v0.2.0 … **v0.12.0**. Factory disarmed. Nothing pushed.

## Next action

Next factory run's top track is **normal-quality STEP 2** (owner: step-2 GO): implement the D5 fix
(export-time k-NN normal smoothing or a decompose neighbour regularizer), then RE-RENDER + validate
held-out PSNR ≤1.5 dB on the smoothed normals (the `shimmer ≤ 98.8` gate alone is gameable). Ready #2
= the lighting-stability harness. With **D2 DECIDED (500k + opacity prune)**, pixel5-variants → M4 are
now unblockable once asset variants build. Owner eyeball on pxl_144634's alignment still open.

**Planner postscript (2026-07-14 late, after this file was written):** the alignment eyeball
PASSED — owner confirmed the fixed viewer reads level, so pxl_144634 KEEPS the plane-normal
default (the 43.5° suspect split was a noisy camera-up cue; flag mechanism stays). pixel5-variants
ungated → Ready #3. Demo/gif regen seeded as quality-pass slice 5. See `lore/notes_2026-07-14.md`
+ QUEUE (groomed "2026-07-14 late", commit 2a6faae).
