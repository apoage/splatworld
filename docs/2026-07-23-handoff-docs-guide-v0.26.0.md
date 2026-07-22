# Handoff — docs-guide (v0.26.0)

**Run:** 2026-07-23, dark-factory scoped run (queue Ready #1, ARMED).
**Task:** `tasks/2026-07-12-docs-guide.md` (filler-class, S/low risk, no GPU/owner gate).
**Shipped:** v0.26.0. Not pushed (`allow_push:false`).

## What shipped

| Deliverable | File | Notes |
|---|---|---|
| Pipeline guide | **NEW** `docs/pipeline.md` | clip → asset → Godot walkthrough; reproduces M1 from the guide alone |
| README pointer | `README.md` `## Docs` | pointers + read-order (`CLAUDE.md` → `pipeline.md` → `decisions.md`) |
| Docstring refresh | `precompute/core/gaussmath.py` | both quat directions + accurate vectorization note |

`docs/pipeline.md` covers: how to pick/record a clip (steady, texture anchor, the motion-blur
SKIP lesson); the stage table (ingest/train_base/decompose/export/transmission — each stage's
input→output and the `metrics_*.json` gate it must pass); the M1-neutral vs M2-relightable
distinction (export consumes decompose only when it's in `--stages`); the exact M1 reproduce
command + the fresh-clip caveat (run.py's raw-workspace guard); a knobs table; the Godot side
(mirror to `gs_assets/`, the `relight_smoke.gd` data gate, the interactive viewer + controls, the
`render_*` tools + `RELIGHT_SHOT_DIR` + the `DISPLAY=:0` resolution caveat); and `smoke.sh`.

Per the task's "verify, don't rewrite" instruction, the other core docstrings
(`schema.py`, `ply_io.py`, `colmap_io.py`, `run.py`) were checked against post-v0.5.0 reality
and found current — left untouched.

## Verification (independent panel — never self-review)

- **judge:correctness** — first pass found **1 BLOCKER + 1 MAJOR + 2 MINOR**; all fixed and
  **re-verified by the same judge** (no surviving BLOCKER/MAJOR, no new defect):
  - BLOCKER: the data-gate command used `smoke_test.gd` (the vanilla-`.ply` M0 gate, which loads
    via Godot's import system and **cannot** consume a `.relightply`) → switched to
    `relight_smoke.gd` (loads via `RelightPlyLoader`). The judge actually ran the original and got
    `SMOKE_RESULT FAIL` exit 1 — the static flow-verifier had marked it "runnable" (it only checked
    the script reads the env vars). **Objective execution beat the static check.**
  - MAJOR: the M2 env-sidecar mirror copied decompose's `env_sh.json` (`frame: colmap_pre_flip`),
    which `relight_env_sh.gd` **silently refuses** (flat-ambient fallback) → switched to export's
    `asset_env_sh.json` (`frame: godot_post_flip`; byte-identical to the working gs_assets sidecar).
  - MINOR: `--import` is a no-op on `.relightply` (removed + explained); `gaussmath` docstring
    wrongly called `rotmat_to_quat` "vectorized" (corrected).
- **flow-verifier** — every command block runnable from repo root; all 15 documented `run.py` flags
  exist; all paths present/step-created; Godot scripts read the documented env vars.
- **Objective**: pytest **141 passed**; `gaussmath` imports clean; the **corrected** doc data-gate
  command run headless → `RELIGHT_SMOKE_RESULT PASS` (exit 0), which also confirmed the post-flip
  env-SH sidecar loads (`env-SH sidecar OK: 27 coeffs finite`).

`smoke.sh` (the configured build) was intentionally **not** run: it gates on a 400-step GPU train
+ a vanilla-`.ply` Godot import, and nothing here touches pipeline behavior (docs + one docstring
comment). The fast layer (pytest) + the real `relight_smoke.gd` gate are the proportionate checks.

## Lane handling (for the planner reconcile)

`docs/` is planner-lane. Per the owner's decision this run ("write guide first, then arm"), the
guide + its two fix passes were authored **while disarmed** (planner role, which `lane_guard`
permits for `docs/`), and the code docstring + README + release ritual were done **armed**
(implementer). No `lane_guard` denial was worked around.

**Config drift to fix if guide-docs stay factory-scoped:** `.dark-factory/config.json`
`lanes.implementer_doc_exceptions` = `["handoff", "validation", "status"]` has no entry for a
pipeline/guide doc, so an armed implementer cannot write `docs/pipeline.md` directly. If the planner
wants future guide edits takeable unattended without the disarm/arm dance, add `"pipeline"` (or a
broader `"guide"`) to that list. Left as a planner call — the factory can't edit its own config.

## Where it stands

Scoped run complete; one task, stopped for planner reconcile. Tree clean apart from two untracked
planner-lane `lore/` handoffs (not the factory's to touch). No other in-scope unattended work is
armed. Factory disarmed.
