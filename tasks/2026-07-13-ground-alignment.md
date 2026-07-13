# ground-alignment — orient assets so the ground reads as ground (owner report)

**Size/risk:** S–M / medium (touches export's coordinate contract — the one-conversion
invariant applies). **Status:** READY.

**Lane:** `precompute/` (export + a colmap_io helper).

## Problem (owner, 2026-07-13, from the interactive viewer)
The asset renders ~"120°/90°" tilted — the gravel path is not down. Root cause (owner's
framing, correct): the phone's g-sensor knew "down" at capture time, but **no usable IMU
data reaches the pipeline**, so orientation is a guess. SfM's world frame is gauge-arbitrary
and export's COLMAP→Godot `diag(1,-1,-1)` is a pure axis relabel — nothing estimates "up."
Every asset (and the upcoming pixel5 variants) inherits a random tilt.

**Probe result (2026-07-13):** the Pixel clips DO embed motion data — mp4 `mett` track 3
(~276 KB, per-frame float records, quaternion-like) is almost certainly the EIS gyro stream,
but in Google's undocumented format (NOT standard CAMM). Reverse-engineering it is OPTIONAL
future work (would give true gravity); this task uses the camera-ring heuristic, which is
~30 lines and expected within a few degrees on walkaround captures. Not representative in the viewer, the demo
video, or any M4 scatter.

## Approach
1. `core/colmap_io.py` (or a small `core/orient.py`): estimate world up from the camera rig —
   for walkaround/orbit captures, least-squares plane fit through camera centers; up = plane
   normal, sign chosen so the average camera up-vector (COLMAP y-down ⇒ camera up = −R row 1)
   has positive dot with it. Fallback when the fit is degenerate (collinear centers): average
   camera up-vector directly. Emit a confidence (plane-fit residual) into metrics.
2. `stages/export.py`: compose the up-alignment rotation WITH the existing conversion —
   still exactly ONE transform applied in ONE place (update the ply_io/export docs in the
   same commit; the invariant's wording stays true: orientation bugs are export's).
   Flag `--no-align` preserves old behavior for A/B.
3. **The env-SH sidecar MUST rotate with the asset** (same composed rotation through
   `core/sh_env.py`'s SH-rotation or re-derive the flip constants) — a lit-from-the-wrong-side
   asset is worse than a tilted one. Unit-check: rotating asset+env together leaves the
   relit render invariant up to the camera.
4. Rebuild `pxl_144634.relightply` + sidecar; note in the validation doc that the demo video
   and README gif should be regenerated on the grounded asset (follow-up slice or same run
   if cheap).

## Acceptance
- New golden test: synthetic camera ring with known tilt → recovered up within 5°;
  degenerate-fallback case covered.
- Real assets: exported `pxl_144634`/`pxl_131945` have the camera-ring plane horizontal in
  Godot (assert |dot(ring_normal, +Y)| > 0.98 in metrics_export).
- Existing tests stay green; `--no-align` path byte-identical to previous export.
- Eyeball (owner, viewer): gravel reads as ground.
