# `label` stage — per-Gaussian material classifier (heuristic v1)

**Size/risk:** M / medium (new pipeline stage + touches `export` label handling + `run.py`
STAGE_ORDER + `transmission` label→trans mapping). **Status:** READY — owner-decided 2026-07-24
(DECISIONS 2026-07-24 M3 entry). **Why now:** M3 transmission is code-complete but VALUE-GATED —
`export` blankets ONE constant label (`--label`, default 2=leaf) over every Gaussian, so
`transmission` paints the whole asset uniform `trans=0.5` (pot/bark/ground wrongly translucent).
This stage is CLAUDE.md pipeline **stage 4**; it does NOT reorder M4/M5 — it fills the gap those
milestones always needed.

## The physical priors (owner, 2026-07-24) — the spec, not decoration
- **Clay pot / ground / bark ≈ OPAQUE** — pot is "a little translucent but really little,
  effectively none for all practical purposes." These must map to `trans ≈ 0`.
- **Cactus flesh ≈ TINY** translucency; **leaf / grass ≈ REAL** translucency (the only classes that
  should glow backlit).
- A classifier that leaves the pot glowing is WRONG. The gate must be able to fail on that.

## Deliverable — `precompute/stages/label.py` (heuristic v1: height + color)
Segment Gaussians into the schema labels (`0=ground 1=grass 2=leaf 3=bark`; **extend as needed** per
CLAUDE.md — e.g. add `4=opaque/hardsurface` for pot/rock/pottery so the trans map has a clean
opaque bucket. Adding a u8 enum VALUE is NOT a schema-version bump — bytes/field unchanged).

- **Input:** the post-`decompose` asset (`decompose.vply` — has geometry + albedo). Reads xyz +
  albedo via `core/ply_io.read_*`. **Output:** per-Gaussian `label` written back (in-place rewrite
  of the label column, same fail-closed pre-write pattern as `transmission.py` — never clobber a
  good file on a bad flag).
- **Heuristic v1 (cheap, in-repo, NO new deps):**
  - **Height band** (world-up axis, post-decompose frame — document which axis): ground = lowest
    band; grass low-mid; leaf/bark mid-high. Use a robust percentile split, not a hardcoded
    absolute (assets differ in scale).
  - **Color** (albedo): green-dominant (`g > r,b` by a margin) → grass/leaf; brown/low-green +
    structural/low height → bark/ground; **terracotta/red-dominant, low-green, compact & opaque →
    the opaque bucket (pot)**. Expose the thresholds as CLI flags with sane defaults.
  - Keep it a small number of interpretable rules — this is v1, not a learned model.
- **Wiring:**
  - Add `label` to `run.py` `STAGE_ORDER` in the correct slot: `... decompose, label, export,
    transmission ...` (label BEFORE export; export must consume real labels).
  - **`export` must STOP blanketing** — when a per-Gaussian label column already exists (label stage
    ran), export PRESERVES it instead of overwriting with the `--label` constant. Keep `--label` as
    the fallback only when no label stage output exists (back-comp for neutral wraps).
  - **`transmission` label→trans map** reflects the priors: leaf(2)/grass(1) → the `--trans-*`
    values (default 0.5); ground(0)/bark(3)/opaque(4) → exactly `0.0`. (Transmission already zeroes
    non-leaf/grass — verify it honors the full label set including the new opaque bucket.)

## Gate (non-vacuous — MUST be able to fail)
1. **Golden synthetic** (extend `tests/`): a tiny scene with KNOWN geometry+color — a low brown
   ground slab, green leaf cluster up high, a red compact opaque blob (pot proxy). After `label`,
   assert each region gets its expected class within tolerance; a test that FAILS if the classifier
   returns all-one-label (the current blanket behavior) or if the pot proxy is labeled leaf/grass.
2. **Distribution check on a real hero** (`metrics_label.json`): label histogram spans ≥2 classes
   with no single class ≥ ~95% (would fail if it silently degenerated to blanket-leaf).
3. **End-to-end trans consequence:** after `label`→`export`→`transmission`, the opaque-region
   Gaussians have `trans == 0.0` and leaf/grass have `> 0` — i.e. a test that fails if the pot
   glows. This is the owner's pot-must-not-glow requirement made executable.

## Scope / stop
- v1 heuristic ONLY. **SAM-mask projection is v2** (accurate, needs source images + a SAM dependency
  → that is ask-before-adding-a-dep territory per CLAUDE.md; do NOT add it in this task).
- One stage + the minimal export/transmission/run.py wiring + the gates. Stop for planner reconcile.
- After this ships, the planner re-runs `label`→`export`→`transmission` on the heroes and the
  cactus, then the M3 demo/gif becomes meaningful (per-material glow) — that regen is a separate
  step, NOT part of this task.
