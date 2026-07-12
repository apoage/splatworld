# ingest — formalize the validated COLMAP recipe into a stage

**Size/risk:** S–M / low. **Status:** READY.

## Problem
`ingest` (video → frames → COLMAP SfM → undistort → PINHOLE TXT model) was validated as a
scratch shell script on `pxl_144634` (204/204 frames, 0.90px) but is not yet a pipeline stage,
so `run.py` can't drive ingest→train_base→export end to end.

## Approach
Add `precompute/stages/ingest.py` wrapping the validated commands. **The recipe of record is
the two committed scripts `prototype/run_colmap_pxl144634.sh` + `prototype/undistort_pxl144634.sh`**
(exact flags, validated 204/204 @ 0.90px); `docs/decisions.md` has the narrative + results.

**Input interface:** `--video <path-to-clip>` (e.g. `datasets/pixel4/PXL_20260711_131945488.LS.mp4`)
plus `--asset <name>`; convention: `pxl_<HHMMSS>` from the clip timestamp (e.g.
`PXL_20260711_144634633.LS.mp4` → `pxl_144634`). Derive the default name from the filename when
`--asset` is omitted. `assets/raw/<name>/` is the ingest WORKSPACE (writable); source clips under
`datasets/` are read-only.
1. `ffmpeg -vf fps=N` frame extraction (arg: `--fps`, default 10) → `assets/raw/<name>/images/`
   as `frame_%04d.jpg` (the naming train_base's loader expects).
2. COLMAP `feature_extractor` (GPU SIFT, OPENCV, single_camera) — **flags are
   `FeatureExtraction.use_gpu` / `FeatureMatching.use_gpu`** on this COLMAP (4.1.0), not
   `SiftExtraction`/`SiftMatching`.
3. `sequential_matcher` (video) → `mapper` → `image_undistorter` (PINHOLE) →
   `model_converter` TXT → `assets/raw/<name>/colmap/dense/sparse_txt`.
4. Invoke colmap via the isolated `colmap` conda env (`conda run -n colmap ...`).
5. Write `metrics_ingest.json`: registered/total frames, points, mean track length, mean
   reproj error. Resumable (skip stages whose outputs exist).
6. Wire into `run.py` `STAGE_ORDER` as the first stage.

## Acceptance
- `python precompute/run.py --asset pxl_131945 --stages ingest,train_base,export` runs clean on
  the fresh clip `datasets/pixel4/PXL_20260711_131945488.LS.mp4` (the "spider's nest" clip —
  unprocessed, owner-flagged as interesting). If SfM registers < 50% of its frames, that is a
  data finding, not a task failure — record it in metrics and fall back to re-validating on
  `PXL_20260711_144634633.LS.mp4` (must reproduce ≥ 204 registered frames, ≤ 1.0 px reproj).
- `metrics_ingest.json` asserts registered_frames > 0 and mean reproj_error finite and < 2.0 px;
  the stage exits nonzero if COLMAP registers nothing.
