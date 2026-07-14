# Validation — ground-alignment (2026-07-14, implementer)

Task: `tasks/2026-07-13-ground-alignment.md`. Estimate world-up from the camera rig
and compose it into export's single COLMAP→Godot conversion so the ground reads as
ground. This doc records the adversarial-panel fix pass + the open correctness
question for the owner. (Data assertions are the implementer gate; the owner eyeball
is the physical-correctness gate.)

## Result summary

Full suite: **76 passed** (`conda run -n splat-relight python -m pytest precompute/tests -q`).

Both real assets re-exported (aligned, `--from-decompose` + `--env-sh` + `--sparse`);
`|dot(ring_normal, +Y_godot)| = 1.000` for each (the applied conversion levels the ring):

| asset | ring_normal_dot_up | method | confidence | residual_rms | disagreement° | alignment_suspect | n_cam |
|---|---|---|---|---|---|---|---|
| pxl_144634 | 1.000 | plane_fit | 0.720 | 0.360 | **43.5** | **TRUE** | 204 |
| pxl_131945 | 1.000 | plane_fit | 0.595 | 0.839 | 22.0 | false | 145 |

`ring_normal_dot_up` is now computed by transporting the estimated up **through the
real `ply_io.colmap_to_godot`** (same `R_align` as the geometry), so it is a genuine
self-consistency check of the applied transform's **C-matrix (position/normal) branch**
— not a tautology — while still not asserting physical correctness of the estimate. (It
does not witness the quaternion branch; see "What changed" item 3.)

## The disagreement finding (open question for the owner)

Two independent up cues exist per capture: the **camera-ring plane normal** (LS plane
fit through camera centers) and the **mean camera up-vector** (−R row 1). On a
symmetric level walkaround these should nearly coincide. They do not:

- **pxl_144634: 43.5° apart** → flagged `alignment_suspect=true`, LOUD stderr WARNING
  printed at export.
- pxl_131945: 22.0° apart → below the 25° threshold, not flagged (confidence 0.595).

A large split means the ring plane may not be gravity — e.g. the operator walked a
non-level loop, or the capture was genuinely pitched down at the subject (both plausible
for handheld phone foliage captures). The camera-ring heuristic cannot disambiguate
"tilted ground truth" from "tilted capture path". **`ring_normal_dot_up=1.0` is true by
construction regardless and proves nothing about gravity.**

**Owner action required:** eyeball the two grounded assets in the viewer. If pxl_144634
(the 43.5° outlier) does NOT read level, the plane-normal cue is wrong there and the
mean-camera-up cue (or the future EIS-gyro path, task's optional future work) should be
preferred. Both candidate ups are recorded in `metrics_export.json > alignment`
(`up_colmap` = plane normal, `mean_camera_up_colmap`) so the choice can be revisited
without re-running decompose.

Design decision (kept): alignment is **applied by default even when suspect** — a
default hard-fail would block these very assets, and the owner eyeball is the arbiter.
`--strict-align` opts into a fail-closed "reject on doubt" gate (degenerate fit OR
confidence < 0.5 OR disagreement > 25°) for unattended/batch runs.

## What changed (fix pass, all in `precompute/` lane)

1. **env-SH sidecar validated BEFORE any write.** Load/rotate the ambient SH, validate
   input+rotated for shape (9,3), NaN/Inf, and absurd magnitude (`|coeff| > 100` ⇒
   diverged/garbage env) — all `raise SystemExit` (survives `python -O`) BEFORE
   `write_asset_ply`, so a bad `--env-sh` can no longer clobber a prior good asset.ply.
   The file is written only after all gates pass.
2. **Suspect alignment is loud + optionally gated** (see above): `up_camera_disagreement_deg`
   + `alignment_suspect` in metrics, a stderr WARNING when suspect, and `--strict-align`.
3. **`ring_normal_dot_up` de-tautologised AND fail-closing.** It is carried through the
   real `ply_io.colmap_to_godot` (same `R_align` as the geometry, `rot=None`) so it
   witnesses the **C-matrix (position/normal) branch** of the composed conversion — a
   regression there (dropped `R_align`, Cᵀ instead of C) drops it below 0.98. It does
   NOT exercise the quaternion branch (`q_conv`); that path is covered by
   `test_ply_io` / `test_export_align`, not by this metric (the applied code is correct —
   `rotmat_to_quat(C)` matches to ~2e-16). On the **aligned path only** a pre-write gate
   now `raise SystemExit` if `ring_normal_dot_up < 0.98` (CLAUDE.md "a metric that FAILS
   if the stage broke"). The `--no-align` path is left ungated — it legitimately reports
   the raw tilt (~0.85/0.90) for A/B.
4. **`--no-align`/no-sparse sidecar byte-identical** — the `aligned` key is emitted ONLY
   when alignment is applied. Verified: a fresh `--no-align` sidecar md5-matches the
   pre-alignment sidecar committed at git HEAD (`9ca6405…`); asset.ply no-align == no-sparse
   (`15f0f56…`).
5. **Aligned decompose export requires `--env-sh`** — otherwise geometry rotates while a
   stale sidecar keeps the old frame (lit from the wrong side). Hard `SystemExit` (pass
   `--env-sh`, or `--no-align`).
6. **Sidecar reconciliation (reverse stale-sidecar case).** FIX 5 only guarded the
   forward case. The reverse: after an aligned decompose export writes `asset.ply` +
   an aligned `_env_sh.json`, a later NEUTRAL export (or any run writing no sidecar) to
   the SAME `--out` (run.py uses the canonical `assets/built/<name>/asset.ply`, so
   mode-iterating one asset reuses the path) overwrote the asset but left the STALE
   aligned sidecar — the v0.9.0 reader (`relight_env_sh.gd`, keyed off `<stem>_env_sh.json`)
   would then light the new asset from the old frame. Now: a run that writes a sidecar
   writes it; a run that writes NONE deletes any pre-existing `<out>_env_sh.json`. So
   asset.ply and its sidecar can never disagree on frame.
7. **`--env-sh` on a neutral export warns** (loud stderr) instead of being silently
   dropped; harmless, so a warning (not `SystemExit`), and FIX 6 clears any stale sidecar.

## Deferred (NOT done here — owner-eyeball-gated)

- **Demo video + README gif regeneration on the grounded asset** (task step 4). Premature
  until the owner confirms the alignment is physically correct (esp. pxl_144634 @ 43.5°) —
  otherwise we'd regenerate twice. The gif/README are planner-owned. This is the flow
  verifier's "stale godot/gs_assets demo mirror" note; left for a planner follow-up.
- **EIS-gyro (mp4 `mett` track) true-gravity extraction** — optional future work per the task.
