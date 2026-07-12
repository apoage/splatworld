# pixel5-variants — triage + batch-build the new walkaround clips (feeds M4)

**Size/risk:** M / low (all shipped tooling; long-running GPU batch, no new code expected).
**Status:** READY (after the M2 chain — phase D / env-SH / video ship first; this is
run-filler-scale but GPU-serial, so it queues last).

**Lane:** `precompute/` execution + metrics; task/validation docs.

## Problem
M4 carpet needs **5–15 asset variants**. New source landed: `datasets/pixel5/` — 9 walkaround
foliage clips (all 1440×1080 @ 30 fps, 14–27 s; walkaround coverage should beat pixel4's
partial arcs on geometry). Nothing is ingested or built from them yet.

## Approach (shipped tooling only — ingest v0.2.0, budget cap v0.5.0)
1. **Triage pass**: `run.py --asset pxl5_<HHMMSS> --stages ingest` each clip
   (`--video datasets/pixel5/PXL_20260712_<HHMMSS>*.LS.mp4`, default fps). Produce a
   registration table (registered/total, reproj px) in the validation doc. A clip
   registering < 80% is flagged, not fought — walkarounds are expected to register well.
2. **Variant build**: for every clip that triages clean, `train_base --max-gaussians 500000`
   (D2's provisional budget + opacity-0.02 prune) → `export`. If M2b phase D shipped by the
   time this runs, build the relightable path (decompose in the stage list); else neutral
   assets are fine — decompose can be re-run per-asset later (stages are resumable).
3. Report per-variant: count, held-out PSNR, wall time. This table is the M4 variant
   shortlist AND more data for the open D2 budget call.

## Gates
- Every ingested clip has `metrics_ingest.json` passing the stage's own assertions.
- Every built variant passes the existing train/export gates (count ≤ cap, PSNR finite,
  no NaN); `smoke.sh` stays green (untouched pipeline).
- ≥ 5 variants built end-to-end (the M4 minimum) OR an honest finding explaining which
  clips failed triage and why.

## Notes
- Source clips are read-only (`datasets/` protected). `assets/raw/pxl5_*` is the workspace.
- GPU-serial on the local 3090 (~5 min/variant expected); do not parallelize on-box.
- The single 4K JPG (`PXL_20260712_165829554.jpg`) is a still — ignore for SfM.
