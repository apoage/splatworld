#!/usr/bin/env bash
# Standard 3DGS preprocessing: undistort images + produce a PINHOLE model, then
# convert that model to TXT for easy parsing by train_base.
set -uo pipefail
CR="$HOME/miniconda3/bin/conda run --no-capture-output -n colmap"
W=/home/lukas/splatworld/assets/raw/pxl_144634
mark(){ echo; echo "===== $* ====="; }

mark "image_undistorter -> dense (undistorted imgs + PINHOLE sparse)"
$CR colmap image_undistorter \
  --image_path "$W/images" \
  --input_path "$W/colmap/sparse/0" \
  --output_path "$W/colmap/dense" \
  --output_type COLMAP 2>&1 | tail -6

mark "model_converter dense/sparse -> TXT"
mkdir -p "$W/colmap/dense/sparse_txt"
$CR colmap model_converter \
  --input_path "$W/colmap/dense/sparse" \
  --output_path "$W/colmap/dense/sparse_txt" \
  --output_type TXT 2>&1 | tail -4

mark "results"
echo "undistorted images: $(ls "$W/colmap/dense/images" 2>/dev/null | wc -l)"
head -4 "$W/colmap/dense/sparse_txt/cameras.txt" 2>/dev/null
mark "DONE_UNDISTORT"
