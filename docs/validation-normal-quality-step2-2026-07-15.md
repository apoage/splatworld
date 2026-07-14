# Validation — normal-quality STEP 2: the fix (task 2026-07-13-normal-quality)

**Date:** 2026-07-15  **Repo HEAD at run:** `353d81d`  **Schema:** v1 (unchanged)
**Scope:** STEP 2 (the fix). STEP 1 (diagnosis) shipped v0.12.0. This ships the normal
smoothing + the real held-out-PSNR validation the corrected gate requires.

## TL;DR

The D5 sparkle fix is **k-NN normal smoothing folded into `decompose`**, gated by
decompose's own fail-closed held-out re-render PSNR budget (invariant #8). On a real
re-decompose of `pxl_144634` with `--smooth-normals-iters 2`, all three acceptance
criteria pass:

| criterion | result | gate | verdict |
|---|--:|---|---|
| held-out re-render PSNR (**load-bearing**) | 21.572 dB (train_base 21.682 → **−0.11 dB**) | ≤ 1.5 dB drop | ✓ `budget_ok:true` |
| neighbour shimmer, SHIPPED normals | **48.77** ×1000 (baseline 197.53 → **−75.3%**) | ≤ 98.8 (necessary) | ✓ |
| anti-over-smoothing tripwire | local coherence 0.579 → **0.922**; `over_smooth_suspect:false` | < 0.985 ceiling | ✓ |

Appearance is preserved (the unsmoothed decompose scored 21.639 dB, so smoothing cost
**0.067 dB**), coherence rose 0.58→0.92 without saturating, ‖mean normal‖ 0.204→0.393,
normals unit (err 1.2e-7), no NaN. The numbers reproduce the step-1 numpy PREVIEW on a
genuine re-solve (preview predicted coherence 0.579→0.922, shimmer→48.77 — matched exactly).

The smoothing CODE touches only `normal_np` (albedo/rough/xyz are passed through untouched —
verified by the correctness/regression judges). This scratch artifact is a *fresh independent
re-solve* (not baseline+smoothing), so its albedo/rough differ from the original built asset
only by negligible run-to-run solver variance (albedo max\|Δ\|=0.076, but std 0.235 and range
match the baseline to ~6 sig figs; xyz byte-identical) — not normals leaking into albedo.

## Design decision — decompose-side, not export-side (was UNCERTAIN in the handoff)

The diagnosis §6 left the fork open: smooth at **export** (re-export only, no re-decompose)
vs **decompose** (fold in before its PSNR gate). The corrected gate makes the held-out
re-render PSNR on the smoothed normals **mandatory** — and once you must build+run a
renderer either way, export-side is NOT cheaper: decompose *already owns a trusted,
fail-closed held-out-PSNR gate*. Folding the smooth in before that gate:

- reuses the exact invariant-#8 validation for free — no new renderer, no duplicated gate,
  no risk of an eval whose test split diverges from decompose's;
- produces ONE canonical smoothed `decompose.ply`, so export / `gaussian_twinkle` / the
  gs_assets mirror all just work with no frame bookkeeping;
- costs nothing for pixel5 variants (they decompose fresh → smoothed normals for free).

The only cost — re-decomposing the two *already-built* assets — is a scheduled GPU one-shot
the PSNR requirement forces regardless of path. Export-side (a bolt-on re-render+PSNR check)
is the heavier alternative, held in reserve.

Smoothing is applied to the FINAL COLMAP-frame normals, **before** both the held-out PSNR
eval and the `decompose.ply` write, so the gate validates exactly the normals that ship. It
is rigid-equivariant (linear neighbour-sum + renormalize), so export's single COLMAP→Godot
rotation is unaffected (proven: `test_normals.py::test_frame_equivariance`).

## What changed

- **NEW `precompute/core/normals.py`** — `smooth_normals_knn` (average each unit normal over
  its self+k-NN neighbourhood, renormalize, iterate; byte-for-byte the step-1
  `gaussian_twinkle.py` preview transform — `test_matches_gaussian_twinkle_preview_transform`
  asserts it), `local_coherence` (the over-smoothing tripwire), `knn_indices`,
  `mean_normal_norm`. numpy + scipy, CPU, chunked for multi-million-Gaussian assets.
- **`precompute/stages/decompose.py`** — opt-in `--smooth-normals-iters` (default **0 = exact
  no-op**, a normal run stays byte-identical) / `--smooth-normals-knn` (default 8). Smoothing
  block after the final `normal_np`, before the PSNR eval + write; the eval `normal` re-sourced
  from `normal_np` (bit-identical to `F.normalize(_normal)` when off — verified `torch.equal`
  diff 0.0). New `normal_smooth` metrics block (coherence/‖mean‖ before-after,
  `over_smooth_suspect`). Coherence is a cheap TRIPWIRE (a flat ground asset legitimately
  saturates it → it only WARNS); **PSNR is the fail-closed guard**.
- **NEW `precompute/tests/test_normals.py`** — 10 tests (no-op exactness, unit preservation,
  denoising, near-idempotence on clean fields, antipodal NaN-safety, coherence contrast,
  frame-equivariance, preview equivalence, tiny-fixture). Suite **78 → 88**.

## Verification (never self-reviewed)

- **Correctness judge — no findings.** All 5 load-bearing claims verified, incl. empirical
  bit-identity of the iters=0 path (`torch.equal` diff 0.0), fail-closed degenerate handling
  (antipodal → zero vector → `normal_unit_err`=1.0 → FATAL before any write), non-circular
  frame-equivariance, and the preview-match.
- **Regression judge — no regressions.** 88 passed; default-off byte-identity of a full run;
  no downstream JSON / CLI / import / invariant breakage (`run.py`'s decompose call omits the
  flags → defaults off).
- **Flow-verifier (artifacts).** [see verdict `panel.flow_verifier`]

## Rollout status (NOT done here — filler slice 5)

The fix is opt-in and default-off, so the currently built/mirrored `pxl_144634.relightply`
the viewer loads is UNCHANGED (still the unsmoothed normals). Re-shipping the built + mirrored
assets with smoothed normals (+ `pxl_131945`, + the demo/gif regen) is the queue's
recurring-quality-pass **slice 5**, now unblocked. The validated smoothed decompose for
pxl_144634 is preserved at `.perf/normalsmooth/pxl_144634/` (gitignored) ready to promote.

## Exact invocations

```
# the fix, on a real asset (scratch out-root — no clobber of assets/built)
CUDA_HOME=$CONDA_PREFIX TORCH_CUDA_ARCH_LIST=8.6 conda run -n splat-relight \
  python -m precompute.stages.decompose \
    --in <built>/train_base.ply --sparse <raw>/colmap/dense/sparse_txt \
    --images <raw>/colmap/dense/images --out <scratch>/decompose.ply \
    --smooth-normals-iters 2 --gpu 0

# shimmer of the shipped normals (necessary signal; CPU)
conda run -n splat-relight python -m precompute.tools.gaussian_twinkle \
  --decompose <scratch>/decompose.ply --env-sh godot/gs_assets/pxl_144634_env_sh.json \
  --frames 72 --knn 8 --smooth-iters 0     # PRIMARY neighbour shimmer -> 48.77

# tests
conda run -n splat-relight python -m pytest precompute/tests -q     # 88 passed
```

## Files

NEW `precompute/core/normals.py`, `precompute/tests/test_normals.py`, this doc.
CHANGED `precompute/stages/decompose.py`. Not touched: any `.glsl`, the schema/version of the
PLY, `ply_io.py` write path, vendored `addons/gdgs/`, `datasets/`, `/media/lukas/gg/photoscan`.
