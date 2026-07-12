# perf-budget — cut per-asset Gaussian count toward the runtime budget

> **STATUS (2026-07-12): SHIPPED as 0.5.0.** Tooling (`--max-gaussians` cap +
> `CappedDefaultStrategy`, `export` floater prune, +4 tests → 29) and the count-vs-PSNR
> sweep are the durable deliverable; verified by correctness+flow panel over one fix cycle
> (one MAJOR fixed: empty-after-prune clobber → guard now fires before the write).
> **Provisional gate ≤500k @ ≥20.7 dB is UNACHIEVABLE** for `pxl_144634` (best ≤500k =
> 19.51 dB; 20.7 needs ~1.1–1.2M) — an honest finding, not a failure. Committed asset left
> untouched. Tradeoff table + recommendation → `docs/validation-perf-budget-2026-07-12.md`;
> DECISIONS **D2** enriched with the data (owner sets the final budget). Verdict:
> `.dark-factory/verdicts/current.json`.

**Size/risk:** M / medium. **Status:** SHIPPED (0.5.0); final budget → owner (DECISIONS D2).

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
   `docs/img/m1_foliage_*.png`). Keep it a documented, metric'd pass.
3. Re-run on `pxl_144634`; compare held-out PSNR vs count (find the knee).

## Acceptance (provisional numeric gates — judges check THESE)
- `metrics_export.json` reports final count **≤ 500 000** on `pxl_144634`.
- Held-out PSNR **≥ 20.7 dB** (≤ 1.0 dB drop from the 21.71 dB uncapped baseline in
  `docs/decisions.md`).
- A count-vs-PSNR tradeoff table (≥ 3 budget points, e.g. 200k/350k/500k) lands in the task's
  validation doc — the FINAL per-asset budget is an owner call, seeded as DECISIONS **D2**;
  the 500k gate above is provisional until D2 is decided.
- No NaN/degenerate Gaussians after prune (existing export assertions still pass).
