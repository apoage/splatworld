#!/usr/bin/env bash
# smoke.sh — one-command end-to-end pipeline health check (the automatic
# debugging loop's backbone; tasks/2026-07-12-smoke-loop.md).
#
# Three stages, fast + loud + machine-checkable:
#   1. pytest precompute/tests            (unit layer, seconds)
#   2. a 400-step train_base,export smoke train on pxl_144634 via run.py
#      (the hardened stage assertions are the pass/fail signal; --min-psnr 12
#      is the floor appropriate for 400 steps)
#   3. the Godot data gate (smoke_test.gd) on the artifact just produced
#
# On success:  prints `SMOKE OK (<total>s)` and exits 0.
# On failure:  exits nonzero, naming the failing stage + last 30 log lines.
# Skip-friendly: if assets/raw/pxl_144634 is absent (fresh clone), exits 0 with
#   a LOUD `SMOKE SKIPPED (no local asset)` — a skipped smoke is NOT a green one.
#   Set SMOKE_REQUIRE_ASSET=1 (as the commit gate does) to turn that skip into a
#   HARD FAILURE, so the pre-commit gate can never report green without running.
#
# CLEAN-TREE CONTRACT: every output (400-step ply/asset/metrics/logs, the Godot
# import copy) lands in the gitignored .smoke/ scratch dir or gitignored godot
# paths — NEVER in tracked assets/built/pxl_144634/. `git status --porcelain`
# is empty after a run. This matters because the planner wires
# commands.build = `bash precompute/smoke.sh`, run before every factory commit,
# and the factory requires a clean tree to commit.
#
# Overridable via env: SMOKE_STEPS SMOKE_MIN_PSNR SMOKE_MIN_COUNT SMOKE_REQUIRE_ASSET GODOT_BIN CONDA
# -E (errtrace): the ERR trap must fire for failures INSIDE the run() helper
# (a pipeline in a shell function), else a failing stage would exit silently.
set -Eeuo pipefail

ASSET="${SMOKE_ASSET_NAME:-pxl_144634}"    # override only for testing the skip path
SMOKE_STEPS="${SMOKE_STEPS:-400}"
SMOKE_MIN_PSNR="${SMOKE_MIN_PSNR:-12}"     # 400-step floor; --min-psnr 99 forces a fail
SMOKE_MIN_COUNT="${SMOKE_MIN_COUNT:-10000}"
GODOT_BIN="${GODOT_BIN:-$HOME/godot/godot}"
CONDA="${CONDA:-$HOME/miniconda3/bin/conda}"
ENV_NAME="splat-relight"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO"

SCRATCH="$REPO/.smoke"                      # gitignored (see .gitignore)
BUILT_ROOT="$SCRATCH/built"                 # run.py --out-root; all built outputs here
LOG="$SCRATCH/smoke_last.log"
# Godot loads .ply only via its import system, so the fresh artifact is copied
# into the (gitignored) gs_assets dir, imported, gated, then removed.
GS_PLY="$REPO/godot/gs_assets/smoke_train_base.ply"

# --- skip path: fresh clone / CI-less env has no local asset -----------------
# Default (SMOKE_REQUIRE_ASSET unset): friendly skip, exit 0. But the commit gate
# (commands.build) keys on exit code alone, so a green skip there would mean "did
# NOT run" reads as "passed". Set SMOKE_REQUIRE_ASSET=1 (as the gate does) to turn
# a would-be skip into a HARD FAILURE instead.
if [ ! -d "$REPO/assets/raw/$ASSET" ]; then
  echo ""
  if [ "${SMOKE_REQUIRE_ASSET:-}" = "1" ]; then
    echo "############################################################"
    echo "#  SMOKE FAILED: required asset assets/raw/$ASSET absent (SMOKE_REQUIRE_ASSET=1)"
    echo "#  Refusing to report green without running the smoke train."
    echo "############################################################"
    exit 1
  fi
  echo "############################################################"
  echo "#  SMOKE SKIPPED (no local asset)"
  echo "#  assets/raw/$ASSET is absent — cannot run the smoke train."
  echo "#  A skipped smoke is NOT a green smoke."
  echo "############################################################"
  exit 0
fi

mkdir -p "$SCRATCH"
: > "$LOG"

STAGE="<setup>"                             # current stage, named by the failure trap

cleanup() { rm -f "$GS_PLY" "$GS_PLY.import"; }   # gitignored, but keep it tidy/idempotent

fail() {
  local rc=$?
  echo ""
  echo "!!!! SMOKE FAILED at stage: $STAGE (rc=$rc)"
  echo "---- last 30 lines of $LOG ----"
  tail -n 30 "$LOG" 2>/dev/null || true
  echo "-------------------------------------------------------------"
  exit "$rc"
}
trap fail ERR
trap cleanup EXIT

# run a command with its stdout+stderr teed to the log (pipefail => the command's
# nonzero status, not tee's, propagates and trips the ERR trap).
run() { "$@" 2>&1 | tee -a "$LOG"; }

START=$(date +%s)

# --- stage 1: unit tests ------------------------------------------------------
STAGE="pytest"
echo "=== smoke [1/3] $STAGE ===" | tee -a "$LOG"
run "$CONDA" run --no-capture-output -n "$ENV_NAME" \
    python -m pytest precompute/tests -q

# --- stage 2: 400-step train_base + export (into gitignored scratch) ----------
# decompose is deliberately EXCLUDED here (heavy inverse-render optimization; the
# golden gate lives in test_decompose.py, run in stage 1). Without decompose in
# --stages, export stays on the M1 neutral placeholder path (still a valid asset).
STAGE="train_base+export"
echo "=== smoke [2/3] $STAGE (steps=$SMOKE_STEPS min_psnr=$SMOKE_MIN_PSNR out=$BUILT_ROOT) ===" | tee -a "$LOG"
run "$CONDA" run --no-capture-output -n "$ENV_NAME" \
    python precompute/run.py --asset "$ASSET" --stages train_base,export \
    --steps "$SMOKE_STEPS" --min-psnr "$SMOKE_MIN_PSNR" \
    --out-root "$BUILT_ROOT" --gpu 0

SMOKE_PLY="$BUILT_ROOT/$ASSET/train_base.ply"
if [ ! -f "$SMOKE_PLY" ]; then
  echo "expected artifact missing: $SMOKE_PLY" | tee -a "$LOG"
  false   # trip the ERR trap under this stage name
fi

# --- stage 3: Godot data gate on the artifact just produced -------------------
STAGE="godot_gate"
echo "=== smoke [3/3] $STAGE (min_count=$SMOKE_MIN_COUNT) ===" | tee -a "$LOG"
cleanup                                     # clear any stale copy from a prior run
cp "$SMOKE_PLY" "$GS_PLY"
# Import the fresh ply (others are md5-cached and skipped). Pre-existing broken
# scenes may print errors and a nonzero rc here; that is NON-fatal — the
# authoritative gate is smoke_test.gd below, which fails if the .res is missing.
run "$GODOT_BIN" --headless --path godot --import \
    || echo "[smoke] --import returned nonzero (continuing; gate is smoke_test.gd)" | tee -a "$LOG"
export SMOKE_ASSET="res://gs_assets/smoke_train_base.ply"
export SMOKE_MIN_COUNT
run "$GODOT_BIN" --headless --path godot --script res://relight/tools/smoke_test.gd
unset SMOKE_ASSET SMOKE_MIN_COUNT

# --- done ---------------------------------------------------------------------
STAGE="done"
END=$(date +%s)
echo ""
echo "SMOKE OK ($((END - START))s)"
