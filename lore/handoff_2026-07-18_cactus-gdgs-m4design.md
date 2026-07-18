# Handoff — planner: cactus sandbox + GDGS tile-dropout fix (v0.21.0) + M4 authoring-tools design (2026-07-18)

Previous: `lore/handoff_2026-07-17_d7-signed-sandbox-synthetic.md`
(chain: … run8-flashlight-orb → #9 d7-signed-sandbox-synthetic → **#10 this**)

- **Branch:** main · **Working dir:** /home/lukas/splatworld
- **Session focus:** Reconciled run #11 (M3 v0.20.0). Built the cactus into the relight sandbox via
  a new vanilla→relightable converter (orientation lesson: the interactive viewer is the arbiter).
  Root-caused + shipped the GDGS fullscreen/zoom tile-dropout fix (v0.21.0, run #12). Designed M4 as
  AUTHORING TOOLS (owner steer) via a design workflow → spec + D8 walls. Reconciled run #12.

## Confirmed compaction rubric (chandoff 2026-07-18)

```
KEEP IN FULL:
- GDGS fullscreen/zoom tile-dropout: root-caused (wf_93bf8a1c-a50, HIGH conf) + SHIPPED v0.21.0
  (run #12, 8030116) = 3-file logged vendored diff (resolution-aware sort-pair budget via
  REFERENCE_TILE_COUNT=3600 + matching ping-pong stride + shader overflow clamp). Empirical proof
  794 holes→0, 3.3x headroom, causal revert. decisions.md entry logged (invariant #6). Our relight
  pass EXONERATED. Report docs/2026-07-18-gdgs-tile-dropout-report.md doubles as the UPSTREAM PR to
  ReconWorldLab/godot-gaussian-splatting (owner-gated, external action).
- Cactus in sandbox RESOLVED: cactus_142k.relightply via NEW converter precompute/tools/
  vanilla_to_relight.py (--coord colmap --normal-orient outward, UNSMOOTHED). The INTERACTIVE VIEWER
  is the orientation arbiter (render_sparkle showed --coord none upright but the viewer showed it
  upside down; flipped to match the viewer; render<->viewer discrepancy cause UNRESOLVED). Smoothing
  HELPS planar foliage, HURTS spiky (cactus coherence 0.725->0.709; owner "worse") -> off for
  high-freq. Moving-light "traveling spots" = INTRINSIC per-splat reshading limit; only lever =
  shading-model terminator-softening A/B toggle (OFFERED, not built).
- M4 DESIGNED (wf_ed5f9c8a-f62) -> spec tasks/2026-07-18-m4-carpet-authoring.md: Contract-First
  hybrid (Godot in-viewer scatter "Splat Studio" PRIMARY + Blender bpy addon SECONDARY +
  carpet/<name>.instances.json TRS-only contract; cleanup = Godot-select -> Python-write via
  clean_relight.py which ALSO mints the <=1.5M variant fleet; net-new runtime = RelightPass.
  set_materials_multi; GDGS untouched). Spine task (set_materials_multi + carpet_loader) testable
  NOW on the 2 heroes = Ready #2. 7 walls bundled as DECISIONS D8 (OPEN; spine INDEPENDENT of them,
  factory stopped there correctly).
- GDGS instancing facts (load-bearing for M4): shared resource by REFERENCE identity; per-node
  transform set AFTER add_child (D3); cost = TOTAL points not node count (budget 1.5M as one asset);
  relight single-variant instancing-aware, multi-variant NEEDS set_materials_multi; TRS-only uniform
  scale (relight.glsl normal = mat3 rotation-only); sort *10 overflows if a block goes near-camera.

COMPRESS + POINT:
- Reconcile runs #11 (M3 v0.20.0) + #12 (GDGS v0.21.0) pushed -> this git block + docs/*handoff-run11
  /run12*; one line each.
- GDGS investigation reader-by-reader detail -> docs/2026-07-18-gdgs-tile-dropout-report.md +
  -validation.md.
- Synthetic plant verified modeled (12 two-sided leaves, adaxial/abaxial GT) but owner "okish, not
  l-sys" -> assets/synthetic/plant01 + tasks/2026-07-17-synthetic-plant-gt.md; one line.
- M4 design proposals detail -> the spec + wf_ed5f9c8a-f62.

DROP:
- render_sparkle-vs-interactive orientation ARCHAEOLOGY (viewer.tscn root check, _update_cam reads,
  failed screenshot-tool attempt) — keep only the CONCLUSION (colmap = viewer-upright).
- cactus --coord none<->colmap flip-flop iterations — keep only the final (colmap).
- the failed R-camera-reset Edit (never applied; orbit_viewer.gd UNCHANGED).
- exit-code-144 pkill/subshell noise; viewer relaunch churn; background-task completion pings.

VERBATIM ANCHORS: main @ fca1c95 (pushed), tags -> v0.21.0; conda python = /home/lukas/miniconda3/
envs/splat-relight/bin/python (conda not on PATH); REFERENCE_TILE_COUNT=3600 in
gaussian_gpu_state_cache.gd; workflows wf_93bf8a1c-a50 (GDGS, DONE) + wf_ed5f9c8a-f62 (M4, DONE);
cactus render via render_sparkle.gd on DISPLAY=:0.

UNCERTAIN:
- render<->viewer orientation discrepancy: latent bug worth chasing? (may bite demo render tools vs
  in-viewer). Unresolved — just flipped to match the viewer.
- plant->gaussian-splat reconstruction still wanted? (owner said "make gaussian splat of it" then
  pivoted; transforms->COLMAP converter SCOPED not built; train_base inits from SfM points -> needs
  an init point cloud).
- D8 ratification pending owner (one "yes" unlocks the whole M4 spine as factory work).
- Terminator-softening A/B toggle: build it, or leave the moving-light shimmer as an accepted limit?
```

## Git state (safety-net, not for the rubric)

```
$ git log -6 --oneline
fca1c95 Reconcile run #12 + M4 design: decisions.md vendored-diff entry, M4 spec, D8 wall
d9cc7e0 Handoff run #12: tile-dropout shipped (v0.21.0); M4 stopped on OPEN D8
8030116 Fix GDGS fullscreen/zoom tile-dropout: resolution-aware sort-pair buffers (v0.21.0)
b975179 Prepare factory: GDGS fullscreen tile-dropout — full report + factory-ready task (Ready #1)
67a9efd tool: vanilla_to_relight — add optional sign-aware normal smoothing (D5) + coherence metric
a02f132 tool: vanilla_to_relight — wrap a third-party 3DGS ply into a neutral relightply for the sandbox

$ git status --short   # main == origin/main, clean
(clean)
```
Tags v0.2.0 … **v0.21.0**. Factory disarmed. main pushed @ fca1c95.

## Next action

Owner's call: **ratify DECISIONS D8** (one "yes" on the Contract-First hybrid ratifies all 7
sub-walls and makes the entire M4 spine — set_materials_multi + carpet_loader + clean_relight.py +
carpet_perf, all testable now on the 2 heroes — factory-takeable next run). Also owner-gated: the
**upstream GDGS report/PR** (fix now validated). Ready #1 (GDGS) is SHIPPED; Ready #2 (M4 spine) is
the next factory job once D8 is ratified. Fresh-session read order: CLAUDE.md + MEMORY.md →
docs/decisions.md tail → tasks/QUEUE.md + DECISIONS.md → latest lore (this + notes_2026-07-18.md) →
the M4 spec.

Sequence: **#10**.
