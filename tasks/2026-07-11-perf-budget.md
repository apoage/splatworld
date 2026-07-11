# perf-budget — cut per-asset Gaussian count toward the runtime budget

**Size/risk:** M / medium. **Status:** READY.

## Problem
M1's `train_base` produced **2.39M gaussians** for one foliage asset. CLAUDE.md targets
**≤1.5M visible splats for the WHOLE carpet** (many instanced blocks), so per-asset budgets must
be far lower. Two levers: densification control (train fewer) + a post-train prune (cut floaters).

## Approach
1. **Densify tuning** in `train_base`: expose `--max-gaussians` (hard cap; stop growth when
   hit) and raise `DefaultStrategy.grow_grad2d` / tune `refine_stop_iter`. Target a
   configurable budget (e.g. 200–500k per middle-distance foliage block).
2. **Floater prune** in `export`: drop Gaussians with opacity below a threshold and/or isolated
   ones far from the SfM point hull / with extreme scale (the pale peripheral blobs seen in
   `scratchpad/m1_foliage_*.png`). Keep it a documented, metric'd pass.
3. Re-run on `pxl_144634`; compare held-out PSNR vs count (find the knee).

## Acceptance
- `metrics_train_base.json` / `metrics_export.json` report final count under the chosen budget.
- Held-out PSNR stays within a small dB drop of the uncapped baseline (21.71 dB) — record the
  count-vs-PSNR tradeoff so we pick the budget with eyes open.
- No NaN/degenerate Gaussians after prune (existing export assertions still pass).
