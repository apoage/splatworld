> **STATUS (2026-07-17): PARTIAL — infra + gate fixes SHIPPED as v0.18.0; the D6 hybrid EFFICACY is
> REFUTED on real foliage.** Shipped: the hybrid resolver implementation (visibility-witness orientation
> `d_peak` + coarse-voxel sign field, replacing the k_cam vote; MAJOR-1 confidently-wrong-sign fix +
> MAJOR-2 genuine trap test, both independently re-verified by fault injection) and the two gate defects
> (#1 fail-open exit → nonzero `GATE_REFUSED_EXIT=3`; #2 metrics clobber → refused file + no-clobber),
> both proven fail-closed in production. **NOT achieved:** the <5% multi-scale acceptance. Re-decompose
> of pxl_144634 (2.4M): 8-NN **30.03%** / adaptive **37.65%** default, **29.13% / 37.81%** voxel-dominant
> — a **balance-invariant ~30% floor** ≈ the pre-fix v0.16.0 result. Visibility-witness signs are
> confident but neighbor-inconsistent on real grazing normals; the voxel field only gets the residual.
> Assets UNCHANGED (fail-closed). **→ reopened as DECISIONS D7** (accept-the-look / anisotropy-gate /
> global MST / sign-agnostic shading). **M3 stays gated.** Owner eyeball + re-export/re-mirror NOT done
> (nothing passed the gate to ship). Refuted metrics: run-#9 handoff `docs/2026-07-17-handoff-9-run9.md`.

# grazing-normal-resolver — hybrid sign resolution (DECIDED D6) + gate exit/metrics fixes

**Size/risk:** M–L / medium-high (in-solve change to decompose + a new post-solve pass; every
existing gate applies — golden MAE, held-out PSNR ≤1.5 dB, shimmer ≤98.8, folded-coherence
tripwire, and the v0.16.0 multi-scale sign gate itself). **Status:** READY (owner "yes"
2026-07-16 on the D6 recommendation).

**Lane:** `precompute/` (decompose, core/normals.py, metrics).

## Context (all data 2026-07-16, planner re-decompose on the local 3090)
Camera-hemisphere orientation (v0.16.0) is PROVEN insufficient on real foliage: fail-closed at
8-NN opposition 29.58%/30.99% (gate 5%), adaptive-domain 35.4%/36.8%, on pxl_144634/pxl_131945.
The k_cam=3 vote flips 55–68% at init yet post-solve opposition matches the pre-fix audit —
camera and neighbor cues genuinely disagree where normals graze the views. Sign-aware smoothing
verified working (degenerate-mean 0.06–0.08%). Full refused-run metrics: planner scratchpad
`d6_refused_metrics_*.json`; key numbers in DECISIONS D6 (DECIDED) + `lore/notes_2026-07-16.md`.

## Approach (the decided hybrid — both parts O(N))
1. **Visibility-weighted orientation, in-solve**: for each Gaussian accumulate over ALL
   training views that actually see it (use the solve's existing per-view contribution /
   visibility weights — do NOT re-render extra passes) the weighted mean view direction;
   orient the normal against it. Replaces the k_cam=3 nearest-camera vote. Splats seen
   face-on get a decisive vote; edge-on views contribute ~0 weight, correctly.
2. **Coarse-voxel sign field for the grazing residual**: voxelize positions (voxel ≈ a few ×
   median 8-NN spacing); per voxel take the visibility-resolved majority axis/sign; propagate
   the field to low-confidence splats (|weighted view dot| below threshold) — neighbors decide
   where cameras can't. Iterate voxel-neighbor consensus 1–2 passes if needed. No MST/BFS.
3. **Gate defect #1 (fail-open exit)**: the FATAL sign-gate refusal currently exits rc=0 —
   must exit NONZERO so automation can't read refusal as success. Add a test.
4. **Gate defect #2 (metrics clobber)**: a refused run overwrites the tracked
   `metrics_decompose.json`, breaking the shipped artifact↔metrics pairing. Write refused-run
   metrics to `metrics_decompose_refused.json` (or under an out-root) and leave the tracked
   file matching the shipped artifacts. Add a test.
5. Re-run the D6 one-shot on both heroes (~8 min/asset local): gate must PASS <5%; then
   re-export + re-mirror + shimmer/suite; confidence metric (fraction resolved by cue (a) vs
   (b)) into metrics.

## Acceptance
- Multi-scale sign-opposition (8-NN AND adaptive-domain) **<5%** on both heroes; degenerate
  <0.5%; all pre-existing gates hold (golden, PSNR budget, shimmer, folded coherence).
- FATAL refusal exits nonzero (tested); refused metrics never clobber the shipped pairing
  (tested).
- Re-export + re-mirror both heroes; **owner eyeball (viewer sun-only mode D): the patchy fake
  shadows are largely gone** — residual reads as fine per-splat noise, not blotches.
- M3 note: this unblocks the backlit dot(−N,L) term — spec M3 when this ships.
