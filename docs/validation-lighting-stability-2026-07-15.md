# Validation — lighting-stability harness (`render_matrix.gd`), 2026-07-15

Task: `tasks/2026-07-14-lighting-stability.md` (Ready #2, run #6). Shipped as **v0.14.0**.
Companion to the run #5 WIP handoff (`docs/2026-07-15-handoff-5-run5.md`), which drafted the
harness at 6→9/10; this run finished it to a legitimate, repeatable 10/10.

## What shipped
`godot/relight/tools/render_matrix.gd` — an OFFLINE, machine-checkable lighting-stability gate.
A FIXED camera renders a **53-condition** matrix of the M2 relight pass on the grounded
`pxl_144634.relightply` (elevation×azimuth grid + 1-D sweeps over energy / ambient / color, each
× {raw, relit, relit+trans_on}) and emits per-check pass/fail into
`godot/shots/lighting_stability/lighting_stability.json` (gitignored out-root). One greppable line
`LIGHTING_STABILITY_RESULT PASS|FAIL`; exit code mirrors it.

```
DISPLAY=:0 ~/godot/godot --path godot --script res://relight/tools/render_matrix.gd
```
Real renderer only — **NO `--headless`** (dummy renderer = false FAIL). ~23 s on the idle 3090.

### The 10 checks (all PASS, measured vs threshold on the shipped confirming run)
| check | proves | measured | threshold |
|---|---|---|---|
| no_nan_inf | no non-finite pixels anywhere | 0 | 0 |
| min_coverage | asset actually rendered every condition | raw 1730 / any 1301 | ≥1500 (RAW footprint) / ≥800 (blank floor) |
| relit_luma_bounds | no blackout/blowout at nominal energy | 0.019–0.531 | (0.01, 0.98) |
| raw_invariance | light does NOT leak into the raw (albedo-only) path | 55.37 dB | ≥50 |
| trans_inertness | relit == relit+trans_on while asset trans==0 (pre-M3) | 64.18 dB | ≥55 |
| azimuth_return | no state drift az=0° vs az=360° | 61.36 dB | >45 |
| energy_linearity | luma(2E)/luma(E) ≈ 2 (env off, ambient 0) | 1.98–2.0 | 2.0 ± 0.15 |
| elevation_smoothness | no normal/specular pop over elevation | max jump 0.046 | <0.12 |
| ambient_floor | no black shadows at flat ambient 0.5 | p2 0.086 | ≥0.015 |
| sphere_consistency | our `light_dir_ws` agrees in SIGN with the engine DirectionalLight3D | min dot 0.315, n=16 | >0 |

## Engine findings
**None.** All four checks that were failing in the run #5 WIP were HARNESS-logic/threshold issues,
confirming the WIP header's diagnosis (no `tasks/DECISIONS.md` row seeded). The relight engine core
is stable across the whole condition matrix. The sphere cross-model check exercises for real
(~16.5k gray px/condition, all 16 dot products positive) — no sign/space error between our pass and
the engine light model.

## Verification (never self-reviewed)
Medium-tier panel (`judge:correctness`, `judge:regression`, `flow-verifier`) on the implementer's
first pass, then a fix pass, then a correctness re-confirm.

- **flow-verifier (objective, real GPU):** ran the matrix TWICE → repeatable 10/10 PASS, exit 0.
  **Anti-gaming fault-injection:** injected a light-dependence into the RAW path in a scratch copy —
  a gross leak dropped `raw_invariance` to **4.5 dB (FAIL)** and a subtle ~2% directional leak to
  **36 dB (FAIL)**, versus the ~56 dB clean noise floor (PASS). Proved the loosened check still FIRES
  on a real fault. Confirmed the ~0.046 max-pixel-diff is a **33-of-1730-pixel** GPU-sort/readback
  phenomenon (3 px >0.01, 1 at max), NOT a leak smeared across the foliage.
- **regression judge:** change cleanly scoped to `render_matrix.gd`; suite 88 passed; all guards
  still fire on the regression they defend; `min_coverage` restructure verified non-vacuous.
- **correctness judge (the load-bearing find):** flagged that the implementer's first pass **lowered
  two thresholds below their measured operating point** — `RAW_PSNR_MIN` 55→45 and `TRANS_PSNR_MIN`
  55→40 — when both checks already PASSED at the original 55 (measured raw 56.3, trans 62.7), and the
  trans comment cited a "worst 48.6 dB" that the shipped config does not reproduce. That violates the
  task's "measure-first, floors with margin, do NOT loosen to pass" rule and needlessly cut
  sensitivity to a future trans-leak regression.

### Fix pass (from the correctness finding)
- `RAW_PSNR_MIN` 45 → **50** — margin below the measured worst (55.37 dB this run; ~55.4–56.9 across
  5 runs), still 14 dB above the 36 dB subtle-leak detection floor.
- `TRANS_PSNR_MIN` 40 → **55** — restores sensitivity; measured worst 62.7–64.2 dB over 4 runs.
- Corrected the false rationale comments (55.3→56.3, 48.6→62.7 measured worsts; removed the
  "real leak = 14 dB" figure, which was the OLD full-frame-with-sphere number — replaced with the
  foliage-masked fault-injection numbers 36 dB / 4.5 dB).
- Fixed `trans_inertness` pair counting: grid_*/return_* RELIT ids lack a `_relit` substring, so the
  `.replace("_relit","_relit_trans")` returned the same id → degenerate self-compares (99 dB) inflated
  `n_pairs` to 28. Guarded → **11** genuine relit-vs-relit_trans pairs (5 energy + 3 ambient + 3 color).
  Verdict logic unchanged (the min already came from real pairs).

Confirming run after the fix: 10/10 PASS, exit 0, margins in the table above.

## Known limitations (documented, non-blocking; not this task's scope to close)
1. **PSNR is luma-only.** `raw_invariance`/`trans_inertness` compare luma; a *chroma-preserving* raw
   leak (e.g. the raw path picking up light COLOR while luma is unchanged) would be invisible. The
   matrix DOES render `color_warm_raw`/`color_cool_raw`, so the conditions exist — a future hardening
   is to add a per-channel/mean-RGB delta alongside the luma PSNR. Pre-existing.
2. **`min_coverage` has a narrow unguarded band.** Because relit "covered" is brightness-dependent,
   the footprint floor (1500) runs only on the brightness-stable RAW conditions and a loose blank
   floor (800) runs on every condition. A regression that culls foliage *only in relit mode* to the
   [800, 1301) range would pass. The catastrophic case (blank/culled asset) is still caught. This is a
   deliberate trade to kill the false positive the old single 1500-on-all threshold produced on the
   legit dim E=0.25 relit condition (1301 covered).
3. **`trans_inertness` is only meaningful while `asset_trans_max == 0`** (pre-M3). The JSON records
   `asset_trans_max` but does not hard-gate on it. When M3 gives the asset nonzero `trans`, this check
   silently reinterprets from "trans plumbing is inert" to "trans stays within 55 dB" — M3 must revisit
   the check's semantics.

## Deferred acceptance item (named, not shipped)
Approach §4 / acceptance bullet 4 — a **per-condition shimmer BASELINE table** (run `gaussian_twinkle.py`
semantics over short orbit bursts at 3–4 matrix corners, record as baseline only) — is NOT included.
The matrix renders STATIC frames per condition; shimmer is a TEMPORAL metric requiring orbit bursts, so
it is genuinely new rendering work, and the task explicitly marks it BASELINE-only (de-scoped from the
gate — the shimmer-reduction gate belongs to normal-quality step 2, already shipped v0.13.0 with the
headline pxl_144634 numbers 197.53→48.77 ×1000). Carried as a small follow-on, not a blocker for the
stability gate. The core acceptance (one-command matrix + per-check pass/fail JSON, all hard asserts pass,
cross-model consistency passes, suite/tree green) is met.

## Extension point
Mode B (PRT-lite basis blend, M5) is NOT implemented; the `MVar` enum + `_mode_of()` are the single
place to add it so it flows through the whole matrix.
