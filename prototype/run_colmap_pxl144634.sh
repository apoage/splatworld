#!/usr/bin/env bash
# M1 ingest shakedown: COLMAP SfM on pxl_144634 foliage frames (204 imgs, 1440x1080).
# Validates the ingest path on real (hard) foliage before formalizing stages/ingest.py.
set -uo pipefail
CR="$HOME/miniconda3/bin/conda run --no-capture-output -n colmap"
W=/home/lukas/splatworld/assets/raw/pxl_144634
DB="$W/colmap/database.db"
mkdir -p "$W/colmap/sparse"
mark(){ echo; echo "===== $* ====="; }

mark "feature_extractor (GPU SIFT, OPENCV cam, single camera)"
$CR colmap feature_extractor \
  --database_path "$DB" --image_path "$W/images" \
  --ImageReader.single_camera 1 --ImageReader.camera_model OPENCV \
  --FeatureExtraction.use_gpu 1 --FeatureExtraction.gpu_index 0 2>&1 | tail -6

mark "sequential_matcher (GPU, overlap 10)"
$CR colmap sequential_matcher \
  --database_path "$DB" \
  --FeatureMatching.use_gpu 1 --FeatureMatching.gpu_index 0 \
  --SequentialMatching.overlap 10 2>&1 | tail -6

mark "mapper"
$CR colmap mapper \
  --database_path "$DB" --image_path "$W/images" \
  --output_path "$W/colmap/sparse" 2>&1 | tail -8

mark "reconstructed models"
ls -la "$W/colmap/sparse" 2>&1

mark "model_analyzer (largest model)"
if [ -d "$W/colmap/sparse/0" ]; then
  $CR colmap model_analyzer --path "$W/colmap/sparse/0" 2>&1 | tail -20
fi
mark "DONE_COLMAP"
