# DECISIONS — the single blocked-on-human surface

One row per call. Recommendation FIRST — the owner should be able to answer with one word.
OPEN rows are walls: the factory never guesses past one; the planner seeds rows here instead of
scattering open questions across task files. Answered rows move to DECIDED with the date.

## OPEN

| # | Decision | Recommendation | Context |
|---|----------|----------------|---------|
| D2 | Final per-asset Gaussian budget for foliage blocks? | Wait for the count-vs-PSNR tradeoff table from `tasks/2026-07-11-perf-budget.md`, then pick the knee. Until decided, the task's provisional gate applies: ≤ 500k @ ≥ 20.7 dB held-out. (Not a wall for the task itself — it PRODUCES the data for this call.) | `tasks/2026-07-11-perf-budget.md`; CLAUDE.md perf target |

## DECIDED

| # | Decision | Outcome | Date |
|---|----------|---------|------|
| D1 | Inverse-rendering impl for `decompose` | **GI-GS** (github.com/stopaimme/GI-GS, MIT, ICLR 2025), hybrid vendor+port: vendor its MIT Python layer (losses/training/materials), re-host G-buffers on gsplat, pure-PyTorch env light, drop indirect pass v1. NEVER vendor its Inria rasterizer fork or nvdiffrast. Everything authored stays Python/PyTorch — no new languages. Owner note: partial reimplementation accepted. Evidence: `docs/d1-survey-2026-07-12.md` | 2026-07-12 |
| D0 | Compute env + SfM approach | Dev on local 3090 (cu124, sm_86); batch on trader 4×3090; `ingest` = fresh COLMAP SfM (no dataset ships usable poses) | 2026-07-11 |
| D0b | Render host + Godot version | Vendor GDGS @ `be61f8f` (v2.2.0) into `godot/addons/gdgs`; Godot **4.7** (needed a push-constant patch, logged in decisions.md) | 2026-07-11 |
| D0c | train_base implementation | Compact self-contained trainer on gsplat core API (`rasterization` + `DefaultStrategy`), not the heavy gsplat examples (nerfview/pycolmap/numpy<2 conflicts) | 2026-07-11 |
