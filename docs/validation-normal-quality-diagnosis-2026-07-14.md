# Validation — normal-quality "sparkle" diagnosis (Step 1 of task 2026-07-13-normal-quality)

**Date:** 2026-07-14  **Repo HEAD at run:** `13b5c83`  **Schema:** v1 (unchanged)
**Scope:** Step 1 (DIAGNOSE FIRST) ONLY. No decompose-solver / normal-generation / shader
code was touched — Step 2 is gated on the verdict below. New diagnostic tooling + a cheap
scratch re-export only.

> **Revision note (post adversarial re-verify).** The first cut of this doc reported a
> screen-space temporal 2nd-difference ("d2") metric with RELIT ≈ 3.34 (×1000) at 26× RAW.
> An adversarial panel found that number is a **measurement artifact**: on 8-bit PNGs the d2
> of a *smooth* relight ramp is dominated by quantization, not twinkle. Those magnitudes are
> **discarded** as a twinkle measure (§2). The qualitative "RAW is flat ⇒ renderer
> deterministic ⇒ not sort/aliasing" conclusion survives and is kept (§5). The twinkle
> magnitude + attribution are now measured with a render-free, quantization-free per-Gaussian
> metric (§3–§4).

## TL;DR verdict

**SHADING CLASS — specifically SPATIAL neighbour-normal incoherence.** The sparkle is
neighbouring splats disagreeing in shading and that disagreement shimmering as the light
sweeps, driven by noisy decompose normals (local coherence 0.58, ‖mean‖ 0.20). Evidence:
the per-Gaussian **neighbour-shimmer** metric correlates with normal noise (Pearson **+0.534**;
monotonic 104→298 across noise deciles), while a k-NN normal smooth drops it **75%**
(197.5→48.8 ×1000) and keeps appearance sane. Sort/aliasing is ruled out (RAW render is
flat); floaters are ruled out (opacity-weighted metric + pruning had no effect).
**Step 2 is warranted, and an EXPORT-time k-NN normal smooth likely suffices — no
decompose-solver change is required as the first move.**

---

## 1. The two things measured, and where each metric lives

- **Sort/aliasing question** ("does the render sparkle even with no shading?") — answered by a
  short screen render: `godot/relight/tools/render_sparkle.gd` (RAW vs RELIT full orbit) +
  `godot/relight/tools/sparkle_metric.py`. **Qualitative only** (§5), because the screen d2 is
  8-bit-confounded (§2).
- **Twinkle magnitude + normal attribution** — answered render-free in float by
  `precompute/tools/gaussian_twinkle.py`, which replicates `relight.glsl` shading over the
  `render_sparkle.gd` orbit light path (§3). This is the metric the Step-2 gate uses.

## 2. Why the first screen numbers are discarded as a magnitude (the 8-bit d2 confound)

The screen metric took the temporal 2nd difference `d2_t = L_{t+1} − 2L_t + L_{t−1}` of luma
read from 8-bit PNGs (/255). d2 is zero for constant/**linear** luma, but a real relight ramp
is smooth-but-curved, and 8-bit rounding of a curved ramp injects an RMS floor. A **perfect,
zero-twinkle** smooth field (varied smooth per-pixel sinusoids), quantized to 8-bit, scores:

| frames N | perfect-smooth 8-bit d2 RMS (×1000) |
|---|---|
| 30  | 10.84 |
| 72  | 3.51  |
| 144 | 2.77  → iid-rounding floor `sqrt(0.5)/255·1000 = 2.773` |

The measured screen RELIT (**10.02 @30f** reproduced by the panel, **3.39 @72f** here) sits
right **on** that perfect-smooth floor — i.e. indistinguishable from a field with **no**
twinkle. The strong frame-count dependence is the tell: d2 ∝ dt² shrinks as N grows, so the
score just converges to the quantization floor, not to a stable twinkle value. **Conclusion:
the screen d2 measured quantization of the smooth ramp; its RELIT absolute (and the "26× over
RAW", which is only "RAW has no light ramp") carry no twinkle magnitude.**

## 3. The corrected metric (render-free, float, per-Gaussian)

`gaussian_twinkle.py` loads `decompose.ply` per-Gaussian normal/albedo/opacity (via
`precompute.core.ply_io`), converts normals COLMAP→Godot **exactly as export** (pre-align,
`R_align=None` — matches `gs_assets/pxl_144634.relightply`, the asset the owner saw), reads
ambient env-SH from the Godot-frame sidecar, and replicates `relight.glsl` in numpy over the
`render_sparkle.gd` orbit light path. Because the ambient term depends only on the fixed
normal, it is **constant over the light orbit**; the whole temporal signal is
`direct(t)=max(dot(N,L(t)),0)`. Two metric classes are computed (albedo-free / white light, to
isolate the normal-driven shading):

- **SELF twinkle** — per-Gaussian temporal high-freq of its *own* shaded luma (circular-
  detrended RMS). This is the literal "per-Gaussian temporal" formulation and it is
  quantization-free and frame-count-stable — **but it does NOT discriminate normal noise**:
  over a smooth light path `max(dot(N,L(t)),0)` is a smooth curve of ~equal temporal curvature
  for *any* normal direction, so every splat self-twinkles about equally. (Verified below:
  flat across noise deciles, r≈0, does not move under smoothing.) Kept as the counter-example.
- **NEIGHBOUR shimmer (PRIMARY)** — the visible sparkle is *spatial*: a splat disagreeing with
  its neighbours, shimmering as the light sweeps. Per Gaussian, with k-NN neighbours (k=8):
  ```
  shade_g(t)      = max(dot(N_g, L(t)), 0) + amb_lum_g          (albedo-free)
  contrast c_g(t) = shade_g(t) − mean_{neighbours} shade(t)
  shimmer_g       = std over t of c_g(t)      (temporal variation of the local disagreement)
  grain_g         = mean over t of |c_g(t)|   (avg local shading disagreement; secondary)
  ```
  Agreeing normals ⇒ `c_g` ≈ const ⇒ shimmer ≈ 0; disagreeing normals ⇒ `c_g` swings as the
  light moves ⇒ high shimmer. **Scene score = opacity-weighted mean of shimmer_g** (×1000 luma).

**Gate contract (fix these for reproducibility):** light path `EL_MID=45°, EL_AMP=35°`, azimuth
one full turn while elevation sweeps grazing→overhead→grazing (matches `render_sparkle.gd`);
**N=72 frames**; **k-NN=8**; circular-moving-average window **13**; **opacity-weighted** mean.
The metric is float and render-free ⇒ frame-count-stable (below), so re-running it on a fixed
asset is deterministic.

**Frame pinning (the baseline is NOT rotation-invariant).** shimmer varies ~±17 % across global
scene rotations (the light path is fixed in world space, so rotating the asset changes which
normals face the sweep). The 197.53 baseline is therefore pinned to the **pre-alignment**
`decompose.ply` with `R_align=None` — the no-align asset the owner saw. The gate is **defined on
`decompose.ply`** (COLMAP frame; the tool applies the single pure sign-flip, `R_align=None`) and
does **not** transfer to the now-alignment-enabled `asset.ply` export (a different global frame).
Step 2 must re-measure the baseline in whatever frame it ships and keep the before/after
comparison within one frame.

## 4. Baseline, attribution, and the k-NN smoothing preview

Asset `pxl_144634`, `decompose.ply`, 2,405,519 Gaussians. All scores ×1000 luma, opacity-weighted.

**Baseline**

| metric | value | note |
|---|--:|---|
| **neighbour shimmer (PRIMARY)** | **197.53** | frame-count stable: 197.5277 @72f vs 197.5279 @144f |
| neighbour grain | 221.09 | |
| self twinkle (non-discriminating) | 16.59 | frame-count stable, but see attribution |
| ‖mean normal‖ (unweighted) | 0.204 | D5 ≈0.20; task target ≥0.5 |
| mean local coherence ‖knn-mean normal‖ | 0.579 | 1 = neighbours aligned, 0 = isotropic |
| mean angle to knn-mean normal | 55.4° | |

**Attribution (a) — twinkle vs normal noise (angle to knn-mean normal)**

- Pearson **r(shimmer, noise) = +0.534**; r(shimmer, 1−coherence) = +0.278.
- Pearson r(self-twinkle, noise) = **−0.018** (≈0) — the temporal-only metric is blind to noise.
- Shimmer by noise decile is **monotonic** (self-twinkle is flat):

  | noise angle bin (deg) | shimmer ×1000 | self-twinkle ×1000 |
  |---|--:|--:|
  | 0.0–15.6   | 104.2 | 16.49 |
  | 31.6–39.4  | 174.4 | 16.86 |
  | 57.5–69.2  | 231.1 | 16.60 |
  | 107.7–179.9| 298.4 | 16.08 |

  Cleanest→noisiest normals: shimmer ~**2.9×**; self-twinkle flat. The sparkle tracks normal
  incoherence, exactly the D5 hypothesis.

  *Independent audit (coordinator) refuted a circularity worry:* on this same shading the metric
  reads **~2** for a perfectly-smooth normal field, **~242** for iid-random normals, and **~197**
  for the real asset (i.e. the real normals are near the random-noise end, not the smooth end),
  and a **non-k-NN** perturbation drives shimmer up monotonically — so the metric genuinely
  tracks normal incoherence rather than merely responding to k-NN structure.

**Attribution (b) — k-NN normal-smoothing preview (numpy, 2× mean of 8-NN + renormalize; no re-decompose)**

| quantity | before | after | change |
|---|--:|--:|--:|
| **neighbour shimmer (PRIMARY)** | 197.53 | 48.77 | **−75.3%** |
| neighbour grain | 221.09 | 45.15 | −79.6% |
| self twinkle | 16.59 | 17.01 | +2.5% (unmoved — wrong metric) |
| ‖mean normal‖ | 0.204 | 0.393 | ↑ (toward ≥0.5) |
| mean local coherence | 0.579 | 0.922 | ↑ |
| appearance mean luma (overhead light) | 0.938 | 0.936 | ≈unchanged |
| appearance p99 luma | 1.563 | 1.549 | ≈unchanged |

The smooth drops shimmer **75%** while **not** wrecking appearance and raising local coherence
0.58→0.92 (this is diagnostic evidence that the sparkle is normal-driven — it is **not** a Step-2
success criterion; see §6 on why the drop-% and the absolute alone are inadequate gates).
**Floaters ruled out:** the score is opacity-weighted so
low-opacity floaters barely contribute, yet shimmer is high and tracks normal noise — it comes
from the visible dense body, not peripheral blobs. (Corroborated screen-side in §5: pruning
19.6 % of low-opacity Gaussians left the screen number unchanged.)

## 5. Qualitative screen confirmation — NOT sort/aliasing (kept)

Screen d2 with **one shared foreground mask** (26,862 px = 3.60 % of frame, identical across
variants), locked at 72 frames (`--shared-mask`; magnitudes are quantization-confounded per §2,
used qualitatively only):

| variant | screen d2 ×1000 | luma_range ×1000 |
|---|--:|--:|
| RAW | **0.135** | 0.031 (flat) |
| RELIT | 3.392 | 97.5 |
| RELIT-pruned (opacity<0.02, −19.6%) | 3.362 | 97.6 |

**RAW is flat (0.135).** With a static camera + static geometry a baked capture is
pixel-identical every frame, so the renderer is deterministic — there is no sort-order /
temporal-aliasing non-determinism to attribute sparkle to. **⇒ NOT the sort/aliasing class; no
STOP / DECISIONS row is needed on that axis.** RELIT ≈ RELIT-pruned corroborates the floater
ruling. (The RELIT 3.39 is the §2 quantization floor, not a twinkle magnitude.)

## 6. Verdict + Step-2 recommendation

**Class = SHADING, sub-class = spatial neighbour-normal incoherence (noisy decompose normals).**
Sort/aliasing and floaters are ruled out. Proceed to Step 2.

- **Baseline: neighbour shimmer = 197.53 (×1000)** on `pxl_144634`/`decompose.ply` under the §3
  contract (N=72, k=8, window=13, opacity-weighted, this light path, COLMAP frame + pure
  sign-flip). Re-measure in whatever frame Step 2 ships (§3 frame-pinning) and compare before/after
  within that one frame.

- **What is NOT a valid Step-2 gate:**
  - **"≥50 % flicker drop" — DROPPED (tautological).** k-NN smoothing lowers the high-spatial-
    frequency content of *any* normal field, so shimmer drops 65–93 % regardless of whether the
    starting normals were bad: even a **perfectly-smooth** field drops **68.7 %** under the same
    2× smooth. A big drop therefore proves nothing about quality.
  - **The absolute `shimmer ≤ 98.8` alone — NOT sufficient (gameable by over-smoothing).**
    iid-random garbage normals, once 2×-smoothed, score **87.7 < 98.8** and would "pass" while
    encoding no real geometry. Keep `shimmer ≤ 98.8 (×1000)` as **one necessary signal**, never
    a standalone gate.
- **The actual Step-2 gate = `shimmer ≤ 98.8` AND both of:**
  - **(a) held-out re-render PSNR within the ≤1.5 dB budget** on the smoothed/shipped normals
    (task Acceptance + the decompose invariant). This is the load-bearing check — see next bullet.
  - **(b) an anti-over-smoothing guard** so "fixing" normals cannot just mean blurring them into a
    sphere: e.g. a local-coherence ceiling (reject if coherence saturates ~1.0 everywhere) and/or
    an appearance/PSNR floor. PSNR (a) is the primary guard; (b) is a cheap early tripwire.
- **Solver change vs export smoothing — CORRECTION.** A k-NN normal smooth can run at **export**
  time in numpy with **no decompose-solver change**, and the preview shows it can hit the shimmer
  signal cheaply. But the earlier claim that this is "budget-gate-safe because it touches only
  `nx/ny/nz`, not PSNR" was **wrong**: `nx/ny/nz` *drive* the re-render (`direct=dot(N,L)`), so
  smoothing them **does** change held-out PSNR. It is only "gate-safe" *today* because export runs
  **downstream** of the decompose PSNR gate, so nothing ever re-renders the smoothed normals —
  which means a plain export-time smooth is **unvalidated**. Therefore **Step 2 MUST re-render and
  validate held-out PSNR on the smoothed normals** (fold the smooth into decompose before its PSNR
  gate, or add a post-smooth re-render+PSNR check to export). Recommendation stands — export-time
  k-NN smooth as the cheap first move — **but only with a PSNR re-render attached**; a
  decompose-side neighbour/consistency regularizer is the heavier alternative held in reserve.
- **On the ‖mean normal‖≥0.5 target:** it only reached 0.39 at 2 smoothing iterations. ‖global
  mean normal‖ is a **blunt** health metric (a clean curved surface still averages low); local
  coherence (0.58→0.92) plus the PSNR-anchored gate above are the better joint criterion. More
  iterations / larger k raise ‖mean‖ further but risk over-flattening — tune against PSNR +
  shimmer + appearance, not ‖mean‖ alone.
- **M3 relevance:** the backlit term is `dot(−N, L)`; the same neighbour incoherence would mush
  transmission glow, so this fix is a genuine M3 prerequisite.

## 7. Tests

`~/miniconda3/bin/conda run --no-capture-output -n splat-relight python -m pytest precompute/tests -q`
→ 78 passed (was 76; +2 for the new frame-guard test). This step adds only new tools + a package
`__init__` + a test, and a `--shared-mask`/guard addition — no change to existing pipeline modules.

## 8. Files created / changed (this step)

- `precompute/tools/gaussian_twinkle.py` — NEW render-free per-Gaussian twinkle metric
  (numpy+scipy, CPU): self-twinkle (counter-example) + neighbour shimmer/grain (primary),
  normal-noise correlation, and the k-NN smoothing preview. **This is the Step-2 gate tool.**
  Includes a frame guard (`assert_decompose_ply`): a cheap PLY-header scan that refuses an
  exported `splat_relight_schema` asset.ply (detected by the schema header comment or the
  exported-only `label`+`trans` columns) so already-Godot-frame normals can't be double-converted.
- `precompute/tools/__init__.py` — NEW (makes `precompute.tools` a package, like `stages`).
- `precompute/tests/test_gaussian_twinkle_guard.py` — NEW: asserts the guard accepts a
  `decompose.ply` and refuses an exported `asset.ply`.
- `godot/relight/tools/render_sparkle.gd` — NEW single-mode full-orbit PNG dumper (real GPU),
  from the first cut; retained for the §5 qualitative sort/aliasing check.
- `godot/relight/tools/sparkle_metric.py` — screen d2 analyzer; UPDATED to add `--shared-mask`
  and a banner marking its magnitudes QUALITATIVE (8-bit-confounded).
- `docs/validation-normal-quality-diagnosis-2026-07-14.md` — this doc.
- Gitignored scratch: `godot/gs_assets/pxl_144634_diagprune.relightply` (+ `_env_sh.json`) —
  disposable opacity-0.02 pruned asset for the §5 floater check; regenerable via the export
  command below. Evidence PNGs (screen heatmaps + sample frames) are in an ephemeral scratch
  dir; regenerable from the durable tools.

**Not touched:** decompose/solver/normal-generation code, any `.glsl` shader, vendored
`addons/gdgs/`, `render_orbit.gd`, VERSION, CHANGELOG; no commit/build; nothing in `datasets/`
or `/media/lukas/gg/photoscan`.

## 9. Exact invocations

```
# scratch pruned asset (opacity<0.02) for the §5 floater check
conda run -n splat-relight python -m precompute.stages.export \
  --from-decompose assets/built/pxl_144634/decompose.ply \
  --env-sh assets/built/pxl_144634/env_sh.json --in assets/built/pxl_144634/decompose.ply \
  --prune-opacity 0.02 --out godot/gs_assets/pxl_144634_diagprune.relightply

# PRIMARY metric (render-free, the Step-2 gate)
conda run -n splat-relight python -m precompute.tools.gaussian_twinkle \
  --decompose assets/built/pxl_144634/decompose.ply \
  --env-sh godot/gs_assets/pxl_144634_env_sh.json --frames 72 --knn 8 --smooth-iters 2

# screen renders (real GPU, DISPLAY=:0, NO --headless) for the qualitative §5 check
DISPLAY=:0 RELIGHT_ASSET=res://gs_assets/pxl_144634.relightply RELIGHT_SPARKLE_MODE=raw|relit \
  RELIGHT_ORBIT_FRAMES=72 RELIGHT_SHOT_DIR=<scratch>/<mode> \
  ~/godot/godot --path godot --script res://relight/tools/render_sparkle.gd
conda run -n splat-relight python godot/relight/tools/sparkle_metric.py \
  --variant raw=<scratch>/raw --variant relit=<scratch>/relit \
  --variant relit_pruned=<scratch>/relit_pruned --shared-mask
```
