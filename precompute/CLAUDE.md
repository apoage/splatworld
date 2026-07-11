# precompute/ — the offline pipeline

Turns raw multi-view images into a built relightable asset. Stages are resumable CLI
scripts; each writes a `metrics.json`. Runs in the `splat-relight` conda env (cu124, sm_86).

| Path | What |
|---|---|
| `core/schema.py` | THE schema contract (`splat_relight_schema`). Field list + version + labels. |
| `core/ply_io.py` | **The only place that touches PLY bytes.** Extended + standard-3DGS read/write, and the single COLMAP→Godot conversion (`diag(1,-1,-1)`). |
| `core/colmap_io.py` | COLMAP TXT model reader (intrinsics, world→cam poses, SfM points). |
| `stages/train_base.py` | Vanilla 3DGS via gsplat (`rasterization` + `DefaultStrategy`). |
| `stages/export.py` | Standard-3DGS PLY → extended schema. **Coordinate conversion happens here, exactly once.** |
| `run.py` | Driver: `--asset --stages --gpu`; round-robin for the trader 4×3090. |
| `tests/` | Golden tests (ply_io round-trip, coord invariance). Run before schema/decompose changes. |

## Gotchas / rules
- Run gsplat with `CUDA_HOME=$CONDA_PREFIX TORCH_CUDA_ARCH_LIST=8.6` (JIT compile). Full recipe: `docs/decisions.md`.
- **albedo = SH degree-0 ONLY.** Never bake higher SH into albedo.
- Schema change → bump `SCHEMA_VERSION` + update the Godot importer **in the same commit**. Reader/writer lives only in `ply_io.py`.
- Never write `assets/raw/` or `/media/lukas/gg/photoscan` — read-only source data.
- COLMAP runs in a SEPARATE `colmap` conda env (`conda run -n colmap ...`); GPU flags are `FeatureExtraction.use_gpu` / `FeatureMatching.use_gpu` on this COLMAP (4.1.0).
- Every stage asserts a metric that would FAIL if it broke (count / NaN / re-render PSNR).

**Status:** M1 done (`train_base` + `export`). M2 `decompose` is next — gated on DECISIONS **D1**.
