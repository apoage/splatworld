> **STATUS (2026-07-23): SHIPPED as v0.26.0.** All three parts landed — NEW `docs/pipeline.md`
> (clip→asset→Godot walkthrough; M1 reproducible from the guide alone; M1-neutral vs M2-relightable
> paths; knobs table; Godot open/data-gate/viewer/render + smoke.sh; links-not-duplicates), README
> `## Docs` section, and `core/gaussmath.py` docstring brought current (other core docstrings verified
> current → untouched). Independent panel (correctness judge + flow-verifier) caught + confirmed-fixed
> a BLOCKER (data-gate `smoke_test.gd`→`relight_smoke.gd`) + a MAJOR (env sidecar pre-flip→post-flip)
> + 2 MINOR; corrected `relight_smoke.gd` gate run headless → PASS; pytest 141. Handoff:
> `docs/2026-07-23-handoff-docs-guide-v0.26.0.md`. Nothing remaining. Not pushed.

# docs-guide — hand-written pipeline guide + core docstrings

**Size/risk:** S / low. **Status:** READY (filler-class; owner asked "do we have documentation
building in some task?" — this is it. Deliberately NOT a generated-docs site: mkdocs/Sphinx is
overhead this repo doesn't earn yet).

## Problem
The repo's documentation is records (decisions.md, task banners, CLAUDE.md invariants) — there
is no *guide*: a fresh reader cannot go clip → asset → Godot without reverse-engineering
run.py and the task files.

## Approach
1. `docs/pipeline.md` — the walkthrough: record a clip (what footage works — steady, texture
   anchor, the motion-blur SKIP lesson) → `run.py --asset <name> --stages ingest,train_base,export`
   (each stage: what it does, the knobs that matter — `--fps`, `--steps`, `--max-gaussians`,
   `--min-psnr` — and the metrics_*.json it must pass) → open in Godot (import, smoke_test,
   render tools + `RELIGHT_SHOT_DIR`) → `smoke.sh` as the health check. Link, don't duplicate:
   env recipe stays in decisions.md, schema stays in CLAUDE.md/schema.py.
2. Module docstrings brought current on `core/schema.py`, `core/ply_io.py`, `core/colmap_io.py`,
   `core/gaussmath.py`, `run.py` (one-paragraph contract + invariants each; several already
   exist — verify against post-v0.5.0 reality rather than rewriting).
3. README: add a short "Docs" section pointing at pipeline.md + decisions.md + the guide's
   position in the read-order.

## Acceptance
- A reader following ONLY `docs/pipeline.md` on a machine with the env already built can
  reproduce M1 on `pxl_144634` (or any pixel4 clip) without opening a task file.
- Every command in the guide is copy-paste runnable from repo root (verify each one).
- No content duplicated from decisions.md/CLAUDE.md — pointers instead (doc-drift protection).
