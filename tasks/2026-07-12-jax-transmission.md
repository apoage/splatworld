# transmission (M3) — per-Gaussian `trans` fit, JAX implementation (external contributor)

**Size/risk:** M / low-medium. **Status:** SEEDED for an external contributor (owner's friend)
— **NOT factory work** unless the owner reassigns it. Public repo, Apache-2.0; contribute via
PR. Phase 1 can start immediately; phase 2 unlocks when M2b `decompose` ships.

## What it is (CLAUDE.md stage 5, M3)
Recover per-Gaussian `trans` ∈ [0,1] for grass/leaf-labeled Gaussians from **backlit-view
brightness residuals**: views where the light source sits behind thin foliage show brightness
the opaque model can't explain; the residual, projected per-Gaussian, is the transmission
signal. v1 fallback stays acceptable: constant per label. This drives the runtime's
backlit/wrap term — the M3 "glow" toggle.

## Why JAX fits here (and the boundary)
No rasterizer sits in the fitting loop — this is pure per-Gaussian residual least-squares
(`vmap`/`jit` territory). The differentiable-rasterizer stages (train_base/decompose) are
PyTorch/gsplat and stay that way; do not import torch here, do not import jax there.

## Contract (hard rules)
- **Own env** (add `precompute/env-jax.yml`): torch cu124 pins cuDNN 9.1.x, current JAX needs
  ≥ 9.8 — they cannot share a pip env. `jax[cuda12]` on sm_86 is supported.
- **File-based handoff only** (the pipeline is per-stage resumable CLIs): a new
  `precompute/stages/transmission.py` reads the extended `asset.ply` + COLMAP model + source
  images, writes `trans` back + `metrics_transmission.json`. Runnable via
  `conda run -n splat-jax python -m precompute.stages.transmission ...`; `run.py` wires it
  into `STAGE_ORDER` between `label`-placeholder and `export`.
- **PLY bytes only via `precompute/core/ply_io.py`** (numpy, framework-agnostic — import it,
  never reimplement). Schema stays `splat_relight_schema 1`; `trans` field already exists.
- Every stage asserts a metric that FAILS if it broke (repo invariant).

## Phases
**1 — fitting core + golden test (no dependencies, start now):** synthetic fixture — N
Gaussians with KNOWN trans, known light behind them, brightness model from the runtime's own
wrap formula (CLAUDE.md) — recover `trans` within tolerance (mean abs error < 0.1). Pytest
under `precompute/tests/test_transmission.py`; must run in the JAX env, skipped (loudly) when
jax is not importable so the main suite stays green.

**2 — real assets (gated: M2b shipped):** run on `pxl_144634`/`pxl_131945` with real albedo
from decompose (current label = constant `leaf`, which is fine for foliage clips — the label
stage refines later). Acceptance: `trans` in [0,1], NaN-free; backlit-view re-render residual
(brightness MAE on the most-backlit held-out views) DROPS vs the trans=0 baseline — assert
the drop into metrics. Known-hard case `pxl_132311` (thin branches) is a stretch check, not
a gate.

## Notes
Thin-leaf translucency is the known-hard case — messy per-Gaussian results are expected; the
per-label constant fallback is the floor, not a failure. Coordinate frames: everything here
happens in COLMAP space (pre-export); the one conversion stays in `export`.
