# normal-quality — diagnose the sparkle, fix the near-isotropic normals (DECISIONS D5)

**Size/risk:** M / medium-high (touches the decompose solve — golden + budget gates guard it).
**Status:** READY (D5 closed by owner eyeball 2026-07-13: relighting reads good overall, but
"some splats sparkling … would be bad for usable render" + small-arc response is weak).

**Lane:** `precompute/` (decompose/export); `godot/` only if diagnosis pins the renderer.

## Problem
Two observations, likely one root cause (decompose normals near-isotropic, ‖mean‖≈0.20):
(a) temporal sparkle on individual splats during the light orbit — unusable for real renders;
(b) relighting responds to large light moves but barely to small arcs. The appearance-PSNR
budget cannot see either (it re-renders the same views the solve fit).

## Approach — diagnose FIRST, then fix by cause
1. **Sparkle metric + attribution** (tool over orbit frames, reuse render_orbit): per-pixel
   temporal high-frequency flicker count/variance. Render the SAME orbit in raw and relit
   modes: sparkle in raw too ⇒ sort-order/aliasing (GDGS-side class); relit-only ⇒ shading
   (normals/specular) class. Also test with floaters pruned (opacity-0.02) — floaters
   catching the light are a known suspect. Record the attribution table before touching
   any solver code.
2. **Normal-quality fixes in decompose** (the D5 class, expected main thread):
   - anisotropy/consistency term: penalize normals deviating from the local
     depth-derived-normal beyond a window (the machinery exists — stage-1 already uses
     depth consistency; strengthen/extend into stage 2 instead of detaching entirely);
   - neighbor smoothing regularizer on normals (k-NN or screen-space);
   - specular/direct clamp on low-confidence normals at EXPORT (per-Gaussian confidence =
     agreement between refined normal and shortest-axis prior — cheap, no runtime cost;
     schema unchanged, folded into rough).
3. **If (and only if) diagnosis says sort/aliasing:** document precisely and STOP — GDGS
   internals are a separate owner call (vendored plugin, invariant #6); seed a DECISIONS row
   with the evidence rather than patching.

## Acceptance
- Attribution table in the validation doc (raw-vs-relit-vs-pruned flicker numbers).
- If shading-class: flicker metric on the orbit render drops ≥ 50% vs baseline; ‖mean normal‖
  materially up (target ≥ 0.5 on pxl_144634); golden albedo test still MAE < 0.05; re-render
  budget gate still holds (≤ 1.5 dB); small-arc responsiveness demonstrably improved
  (two adjacent-azimuth renders differ by a luma delta above the old baseline's).
- M3 note: the backlit term is dot(−N, L) — this task is M3's prerequisite; its quality bar
  is "transmission glow won't mush," not perfection.
