# Handoff #1 — 2026-07-11 — M0+M1 shipped & published; apothekary + dark-factory adapted

- **Branch:** `main`  **Working dir:** `/home/lukas/splatworld`
- **Session focus:** Cold start (repo had only `CLAUDE.md`) → built + verified **M0** (GDGS
  render path in Godot 4.7, splat+mesh occlusion) and **M1** (frames → COLMAP SfM →
  gsplat `train_base` → `export`); then adopted the **apothekary layered memory workflow**
  + **dark-factory** as the orchestrator/planner; **published the repo public**.

## Confirmed compaction rubric

```
KEEP IN FULL:
- State (one line): M0 + M1 DONE and PUBLISHED at github.com/apoage/splatworld; apothekary
  memory + dark-factory adapted but factory NOT armed; next = M2 `decompose`.
- The single OPEN wall: DECISIONS D1 — which inverse-rendering impl to vendor for `decompose`
  (survey of GS-IR / GaussianShader / R3DG still pending).
- Deferred backlog (owner's calls): arm the factory; M2 (gated D1); independent M0/M1 code
  review; data-release (footage as a GitHub Release).
- Role: interactive sessions = PLANNER/orchestrator (two-thread contract).

COMPRESS + POINT:
- Entire M0/M1 build + the CUDA/gsplat/COLMAP/Godot env-debugging saga → one line; full
  recipe + results live in docs/decisions.md.
- Apothekary + dark-factory adaptation → the repo is the record: tasks/QUEUE.md,
  tasks/DECISIONS.md, MEMORY.md index, subtree CLAUDE.md, lore/notes_2026-07-11.md.
- Milestone metrics (204/204 frames, 2.39M gaussians, 21.71 dB, GDGS push-constant patch) →
  one line; detail in docs/decisions.md.

DROP:
- All raw tool output: nvidia-smi / conda-solve / ffprobe / nvcc-error / ls / find dumps.
- Screenshots (m0_shot.png, m1_foliage_*.png) — eyeballed, not load-bearing.
- Resolved env-failure chain (Anaconda ToS, libfaiss/openimageio, arch 10.3, CUDA 13.1,
  gcc 15) as narrative — the FIXES are in decisions.md; the failures are noise.
- 244 GB dataset inventory exploration → pointer only.

VERBATIM ANCHORS:
- github.com/apoage/splatworld (public, branch main, commit c413060)
- M2 gate = DECISIONS D1
- Memory: ~/.claude/projects/-home-lukas-splatworld/memory/ (unpublished; GPU-server creds pointer)
- Asset in flight: pxl_144634

UNCERTAIN (resolved → pointer):
- Env-recipe values + perf-budget concern live in docs/decisions.md / their task files, not inline.
```

## Git state
```
git log -5 --oneline:
  c413060 Initial commit: splatworld M0+M1 — relightable Gaussian-splat foliage pipeline

git status --short:
  M tasks/QUEUE.md          (planner: added data-release filler row)
  ?? lore/handoff_2026-07-11_m0-m1-published.md   (this file)
```
(Uncommitted planner edits — commit when convenient; nothing armed or pushed.)

## Next action
All deferred — owner's call: (a) survey decompose impls → resolve **DECISIONS D1** (unblocks
M2); (b) set up + arm the dark factory on the READY queue (`ingest-stage`, `perf-budget`);
(c) independent M0/M1 code review; (d) data-release. **Fresh-session read order:**
`CLAUDE.md` + `MEMORY.md` index → `docs/decisions.md` → `tasks/QUEUE.md` + `DECISIONS.md` →
latest `lore/` note → this handoff.

Sequence: **#1** (no prior handoff).

> **CORRECTION (2026-07-12):** the "Git state" block above understated the dirty set — the
> same session continued past this handoff (pre-arming review). All planner edits, the
> recovered `prototype/` + `docs/img/` artifacts, and the new task files were committed as
> one batch on 2026-07-12; see `lore/notes_2026-07-12.md` + `docs/decisions.md` (2026-07-12).
