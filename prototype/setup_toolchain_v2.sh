#!/usr/bin/env bash
# v2: Miniconda + Godot already installed. Create the two conda envs using ONLY
# conda-forge + nvidia (avoids Anaconda 'defaults' ToS/commercial-licensing gate).
set -uo pipefail
CONDA="$HOME/miniconda3"
CONDA_BIN="$CONDA/bin/conda"
run(){ "$CONDA_BIN" run --no-capture-output "$@"; }
mark(){ echo; echo "===== $* ====="; }

# ---- 0. condarc: conda-forge only, strict priority (durable ToS avoidance) ----
mark "STEP 0  configure channels (conda-forge only)"
"$CONDA_BIN" config --add channels conda-forge
"$CONDA_BIN" config --set channel_priority strict
"$CONDA_BIN" config --remove channels defaults 2>/dev/null || true
"$CONDA_BIN" config --show channels

# ---- 1. splat-relight env ----
mark "STEP 1  create env splat-relight (python 3.11)"
"$CONDA_BIN" create -n splat-relight --override-channels -c conda-forge python=3.11 pip -y

mark "STEP 1a  torch/torchvision (cu124)"
run -n splat-relight pip install --index-url https://download.pytorch.org/whl/cu124 torch torchvision

mark "STEP 1b  python deps"
run -n splat-relight pip install numpy plyfile opencv-python-headless imageio imageio-ffmpeg scipy tqdm rich

mark "STEP 1c  cuda-toolkit 12.4 (to build gsplat kernels)"
"$CONDA_BIN" install -n splat-relight --override-channels -c nvidia -c conda-forge "cuda-toolkit=12.4.*" -y || echo "CUDA_TOOLKIT_INSTALL_FAILED"

mark "STEP 1d  build+install gsplat (sm_86 only)"
run -n splat-relight bash -c 'export CUDA_HOME="$CONDA_PREFIX" TORCH_CUDA_ARCH_LIST="8.6"; pip install gsplat' || echo "GSPLAT_INSTALL_FAILED"

# ---- 2. colmap env (isolated) ----
mark "STEP 2  create env colmap (conda-forge)"
"$CONDA_BIN" create -n colmap --override-channels -c conda-forge colmap -y || echo "COLMAP_INSTALL_FAILED"

# ---- 3. VERIFY ----
mark "VERIFY  torch + cuda + matmul"
run -n splat-relight python -c "import torch;print('torch',torch.__version__);print('cuda_available',torch.cuda.is_available());print('device',torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NONE');print('capability',torch.cuda.get_device_capability(0) if torch.cuda.is_available() else 'NONE');x=torch.randn(2048,2048,device='cuda');print('matmul_finite',bool((x@x).sum().isfinite().item()))" 2>&1

mark "VERIFY  gsplat"
run -n splat-relight python -c "import gsplat;print('gsplat',gsplat.__version__)" 2>&1

mark "VERIFY  numpy/plyfile/opencv"
run -n splat-relight python -c "import numpy,plyfile,cv2,scipy,imageio;print('numpy',numpy.__version__,'plyfile ok','cv2',cv2.__version__)" 2>&1

mark "VERIFY  colmap"
run -n colmap colmap -h 2>&1 | head -4

mark "DONE"
