# Validation — M2b Phase D: real-asset decompose + held-out dB budget

**Date:** 2026-07-12 · **Task:** `tasks/2026-07-11-m2-decompose.md` Phase D
**Machine:** local dev box, 1× RTX 3090 (sm_86), CUDA 12.4 / cu124, `splat-relight` conda env.
**Ships as:** v0.8.0. Schema unchanged (SCHEMA_VERSION stays 1); code changes are confined to
`precompute/stages/decompose.py` + tests — see "Verification panel: gate/contract fixes" below.

> This is a **validation** doc (implementer doc exception). It records the real-data outcome of
> the M2b decompose stage on both photogrammetry scenes, the export of the relightable assets, and
> the two gate/contract defects the phase-D verification panel found (and that were fixed and
> re-validated before ship).

## Outcome: decompose reproduces held-out views within budget on BOTH real scenes

The held-out re-render **PSNR budget gate** (invariant #8, default-ON at 1.5 dB via
`DEFAULT_MIN_PSNR_DROP`) PASSes on both assets on a **like-for-like full-frame** measure:
decompose re-renders the held-out test views within **≤0.52 dB** of the `train_base` baseline. The
inverse solve does not just structurally run — it genuinely reproduces the input appearance on real
foliage/scene data.

| asset | Gaussians | train_base PSNR (full-frame) | decompose PSNR (full-frame, **gated**) | drop | budget floor (−1.5) | masked diag | budget_ok |
|---|---|---|---|---|---|---|---|
| pxl_131945 | 2,075,806 | 25.22 dB | 24.70 dB | 0.52 | 23.72 | 24.71 dB | **true** |
| pxl_144634 | 2,405,519 | 21.68 dB | 21.64 dB | 0.04 | 20.18 | 21.64 dB | **true** |

Both are 7000-iter runs (stage-1 normal to iter 3000, stage-2 material+env after), 19 / 26 held-out
test views respectively. The full-frame and foreground-masked PSNRs agree to ≤0.01 dB here because
both scenes are foliage-filling (the alpha>τ mask covers essentially the whole frame) — but the
**gate now uses the full-frame value** regardless, so it is comparable to `train_base` on any scene
(see the correctness fix below). Source metrics: `assets/built/<name>/metrics_decompose.json`
(`psnr_heldout_db` = full-frame gated, `psnr_heldout_masked_db` = diagnostic, `budget_ok` = gate
result), `metrics_train_base.json`.

### Wall times (single 3090, one asset per GPU)

| asset | train_base | decompose (final full-frame run) | note |
|---|---|---|---|
| pxl_131945 | 221.7 s | 351.8 s | clean throughout |
| pxl_144634 | 229.3 s | 391.0 s | train_base regenerated — see below |

Logs (scratchpad): final full-frame decompose runs `decompose_pxl_131945_fullframe.log`,
`decompose_pxl_144634_fullframe.log`; the pxl_144634 train_base regen `train_base_pxl_144634_regen.log`.

## Verification panel: gate/contract fixes (found in review, fixed + re-validated before ship)

A high-tier adversarial panel (correctness / fail-closed / regression / security + flow-verifier)
reviewed the initial phase-D result and found **two MAJORs** — both latent defects in the v0.7.0
`decompose` stage, exposed by first real-data use. They were fixed source-side (no `export.py`
change), the two real assets were re-run + re-exported, and the numbers above are the post-fix,
honest values. The flow-verifier independently confirmed the exported assets themselves were always
schema-valid and consumed the real solve (the shipped artifacts were never corrupt).

- **MAJOR (correctness) — budget comparison was not like-for-like.** `train_base` scored held-out
  PSNR over the **full frame** but `decompose` scored it over the **foreground (alpha>τ) mask
  only**; the gate subtracted PSNRs measured over different pixel sets, so a decomposition that
  botched the background could false-pass on a small-foreground scene. **Fix:** `held_out_psnr()`
  computes a full-frame PSNR matching `train_base.py` exactly (`((shaded.clamp(0,1)-gt)**2).mean()`)
  and the gate uses it; the foreground value is retained as a non-gated `psnr_heldout_masked_db`
  diagnostic. Fenced by `test_gated_psnr_is_full_frame_not_masked`.
- **MAJOR (fail-closed) — a gate-failed `decompose.ply` was consumable.** The `.ply`/`env_sh.json`
  were written *before* the fail-closed + budget gates, so a sub-budget solve left a `decompose.ply`
  on disk that a manual `export --from-decompose` (the exact path phase D used) would silently ship.
  **Fix:** `finalize_decompose()` runs every gate first and writes the `.ply`/`env_sh` **only on
  full success**; `metrics_decompose.json` (with a new tri-state `budget_ok`) is still written first
  so a failure stays inspectable. Fenced by `test_finalize_writes_only_on_success` (a 19.89 dB
  sub-budget case raises and leaves neither file).
- **MINOR (fail-closed) — baseline trusted blindly.** `decompose` read the baseline PSNR from the
  sibling `metrics_train_base.json` without checking it matched the `train_base.ply` it loaded — the
  exact divergence class that produced the 48k confound below. **Fix:** `read_verified_baseline_psnr()`
  refuses (early, before the optimization) if the metrics `n_gaussians` disagrees with the loaded
  `.ply` count. Fenced by `test_baseline_psnr_consistency_helper`.
- **MINOR (regression) — neutral-export byte-identity was unfenced.** Added a committed test
  (`test_neutral_export_byte_identical_and_allows_albedo_gt_1`) that exports the same train_base.ply
  twice in neutral mode and asserts byte-identity, and that the neutral path still permits albedo>1
  (unaffected by the decompose-path [0,1] tightening).

## Data-provenance finding: pxl_144634 `train_base.ply` was clobbered (caught + fixed)

Before this run, pxl_144634's `train_base.ply` on disk was a **degenerate 48,023-Gaussian model**
— exactly the initial SfM point count, i.e. an init-only / early-stopped train_base — while its
`metrics_train_base.json` still claimed the real **2,394,584** Gaussian count. The mismatch
(a 2.39M-count baseline vs a 48k geometry) confounded the first decompose attempt, which
re-rendered at **19.89 dB** against the 2.39M-claimed baseline — correctly failing the gate.

**Resolution (orchestrator, before the phase-D export):**
- The corrupt file was preserved as evidence:
  - `<scratchpad>/CORRUPT_pxl_144634_train_base_48k.ply` (the 48,023-Gaussian model)
  - `<scratchpad>/pxl_144634_metrics_train_base_at_clobber.json` (the stale 2,394,584-count metrics)
- `train_base` was **regenerated** to the correct model with fresh, self-consistent metrics
  (N=2,405,519, PSNR 21.68 dB), and decompose was **re-run** — yielding the PASS above.
- pxl_131945 was **clean throughout** (no clobber, no confound).

The new `read_verified_baseline_psnr()` consistency check (MINOR fix above) now guards this exact
class at decompose time: the same mismatch would now abort with a self-describing refusal rather
than a suspicious low-PSNR result. Root cause of the original clobber is **not chased here** (out of
phase-D scope) — see the residual finding.

## Exported relightable assets (`export --from-decompose`)

Both assets were re-exported (foreground) from the fixed-code decompose output with:

```
python -m precompute.stages.export \
  --in assets/built/<name>/train_base.ply \
  --out assets/built/<name>/asset.ply \
  --from-decompose assets/built/<name>/decompose.ply \
  --env-sh assets/built/<name>/env_sh.json
```

This overwrites the neutral M1 `asset.ply` with the **real relightable asset** (real
albedo/normal/roughness from decompose, COLMAP→Godot coordinate conversion applied exactly once in
export), writes the flipped `asset_env_sh.json` sidecar (Godot frame, `godot_post_flip`), and
`metrics_export.json`. Both exits were **0**. The decompose path tightens `FIELD_RANGES` albedo to
[0,1].

Exported attribute ranges (from `metrics_export.json`, `decompose_mode: true`):

| asset | schema | element vertex == decompose N | albedo [min,max] | rough [min,max] | normal_unit_err | any_nan | NaN/Inf |
|---|---|---|---|---|---|---|---|
| pxl_131945 | 1 | 2,075,806 ✓ | [0.0347, 0.9822] | [0.0261, 0.9626] | 1.79e-07 | false | 0 / 0 |
| pxl_144634 | 1 | 2,405,519 ✓ | [0.0288, 0.9838] | [0.0399, 0.9619] | 1.79e-07 | false | 0 / 0 |

All within contract: albedo min ≥ 0 & max ≤ 1, roughness in [0,1], `normal_unit_err < 1e-3`,
0 NaN/Inf, `any_nan` false, PLY header comment `splat_relight_schema 1`, and each `asset.ply`
`element vertex` count matches its decompose N exactly. `trans`/`label` remain the export defaults
(0.0 / 2=leaf) — transmission is M3, the label stage is not run yet (expected placeholders).

## Checks

- `python -m pytest precompute/tests -q` → **42 passed** (+5 new gate/contract tests over the
  v0.7.0 baseline of 37; CUDA golden `test_golden_albedo_recovery` MAE 0.0011, not skipped).
- `SMOKE_REQUIRE_ASSET=1 bash precompute/smoke.sh` → **SMOKE OK**, M1 neutral render path intact
  (smoke deliberately excludes decompose).

## Conclusion

Decompose reproduces held-out views within the 1.5 dB budget on **both** real scenes (≤0.52 dB drop)
under a corrected, **like-for-like full-frame** comparison. This resolves the open question of
whether the synthetic golden test ("~50-Gaussian known-albedo recovery", MAE 0.0011) was an
**inverse crime** — i.e. only passing because the synthetic data was generated by the same forward
model it inverts. It was not: the same solve reproduces the true photogrammetry inputs on 2M+
Gaussian real scenes within budget. Phase D is done; all four phases (A/B/C/D) of M2b are complete.

## Residual finding (for the owner / recurring quality-pass)

`decompose` now self-guards its *own* baseline input (the consistency check above), but the **cause
of the pxl_144634 `train_base.ply` clobber remains unknown.** The known writers into
`assets/built/<name>/` (perf sweeps, smoke) write to `.perf/` / `.smoke/` scratch dirs, not the
canonical built asset, so the clobber source is not an obvious in-repo path.

**Recommendation:** the recurring quality-pass should add a **repo-wide built-asset consistency
check** that asserts, for every `assets/built/<name>/`, that each `*.ply`'s `element vertex` count
equals the `n_gaussians` in its sibling `metrics_*.json` — catching a stale/degenerate `.ply`
alongside the whole built tree, not just at the moment decompose happens to read one baseline.

**Known MINOR (re-verify panel, non-blocking — fast-follow):** `finalize_decompose` writes the
`.ply`/`env_sh` only on full gate success, so a *fresh* gate-failed run leaves nothing consumable.
But a gate-failed **re-run over a prior _passing_ output** does not unlink the earlier
(within-budget) `decompose.ply`, so a later manual `export --from-decompose <stale.ply>` could ship
a stale asset. This is **not reachable via `run.py`** (it aborts export on a nonzero decompose exit;
standalone `--stages export` uses the neutral path), and the harm is *staleness vs a changed
`train_base`*, not shipping a truly sub-budget solve. Fast-follow: have `finalize_decompose` unlink
(or atomically temp-write/rename) a pre-existing `decompose.ply`/`env_sh.json` on gate failure.
