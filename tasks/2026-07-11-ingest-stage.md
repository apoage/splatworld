# ingest — formalize the validated COLMAP recipe into a stage

**Size/risk:** S–M / low. **Status:** READY.

## Problem
`ingest` (video → frames → COLMAP SfM → undistort → PINHOLE TXT model) was validated as a
scratch shell script on `pxl_144634` (204/204 frames, 0.90px) but is not yet a pipeline stage,
so `run.py` can't drive ingest→train_base→export end to end.

## Approach
Add `precompute/stages/ingest.py` wrapping the validated commands (recipe in
`docs/decisions.md` and `scratchpad/run_colmap_pxl144634.sh` + `undistort_pxl144634.sh`):
1. `ffmpeg -vf fps=N` frame extraction (arg: `--fps`, default 10) → `assets/raw/<name>/images/`.
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
- `python precompute/run.py --asset <name> --stages ingest,train_base,export` runs clean on a
  fresh clip.
- `metrics_ingest.json` asserts registered_frames > 0 and reproj_error is finite/small; the
  stage exits nonzero if COLMAP registers nothing.
