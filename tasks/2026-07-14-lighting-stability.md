> **STATUS (2026-07-15): SHIPPED as v0.14.0** (dark-factory run #6). `render_matrix.gd` finished from
> the run #5 WIP to a legitimate, repeatable **10/10** gate: 53-condition matrix, `LIGHTING_STABILITY_RESULT
> PASS`, exit 0 on the grounded `pxl_144634` (DISPLAY=:0). No engine finding — all 4 formerly-failing
> checks were harness-logic/threshold bugs (no DECISIONS row). Verified correctness+regression+flow-verifier
> (fault-injection confirmed the raw-invariance check still fires on a real leak). Full detail:
> `docs/validation-lighting-stability-2026-07-15.md`.
> **REMAINDER (not done):** Approach §4 / acceptance bullet 4 — the per-condition shimmer BASELINE table
> (gaussian_twinkle semantics over short orbit bursts at 3–4 matrix corners) — is NOT shipped: it needs
> temporal orbit-bursts, which the static-frame matrix does not produce, and it is explicitly BASELINE-only
> (de-scoped from gating). Carry as a small follow-on. Follow-on note: Ready #4 `flashlight-orb`'s engine-lit
> reference orb should reuse this tool's `sphere_consistency` helper.

# lighting-stability — prove the relight pass is stable across conditions + engine models

**Size/risk:** M / medium (godot/ tools lane — no GDGS edits, no shader changes unless a check
fails and names one). **Status:** READY (owner request 2026-07-14: "we have delighting and a
sort of weird internal lighting engine — test it so lighting is stable on multiple conditions
with multiple engine lighting models").

**Lane:** `godot/relight/tools/` (+ validation doc). Needs `DISPLAY=:0` (real renderer) — the
matrix render is NOT headless-CI-able; the metrics gate reads back rendered PNGs via `Image`.

## Problem
The relight compute pass is our own lighting engine. It has only ever been exercised on one
trajectory (the orbit demo: fixed color/energy/ambient/wrap). Nothing proves it is *stable*
across the condition space (elevation, azimuth, energy, ambient, color) or *consistent* with
the engine's own lighting model shading the meshes beside it. The D5 sparkle was one instance
of a broader class this harness must catch generically.

Note: the interactive **lighting-lab viewer** already shipped planner-side
(`godot/relight/tools/orbit_viewer.gd`, 2026-07-14 — presets/day-cycle/manual sun/live
energy-ambient-wrap). This task is the OFFLINE, machine-checkable harness.

## Approach
1. **`render_matrix.gd`** — generalize `render_orbit.gd`: fixed camera, render a bounded
   condition matrix into a gitignored out-root + `lighting_stability.json`:
   elevation {5°, 30°, 60°, 85°} × azimuth {0°, 90°, 180°, 270°} at defaults, plus 1-D sweeps:
   energy {0.25, 0.5, 1, 2, 4}, ambient {0, 0.2, 0.5}, color {white, warm, cool}, each ×
   modes {raw, relit, relit+trans_on}. (~60 renders, minutes on the 3090.)
2. **Stability checks (hard asserts, machine-checkable):**
   - no NaN/inf pixels; mean luma in (0.01, 0.98) for every relit condition (no blowout/blackout);
   - **raw invariance**: raw renders identical across ALL light conditions (light must not leak
     into the raw path);
   - **trans inertness**: relit == relit+trans_on identical while trans==0 (pre-M3 contract);
   - **azimuth 360° return**: az=0° vs az=360° render PSNR > 45 dB (no state drift in the pass
     across a full orbit);
   - **energy linearity**: on lit pixels, luma ratio between E and 2E within tolerance of 2×
     (shading is linear in light color by construction — catches hidden clamps/quantization);
   - **elevation smoothness**: mean-luma curve over elevation has no adjacent-step jump above
     threshold (catches normal/specular pops);
   - **ambient floor**: at ambient 0.5, the darkest percentile of asset pixels stays above a
     floor (no black shadows — CLAUDE.md mandate).
3. **Engine cross-model consistency**: place a gray Lambert sphere (Godot-lit reference mesh)
   in-frame under the SAME DirectionalLight3D. Check the sphere's lit hemisphere agrees with
   the splat asset's shading direction per condition (loose tolerance — a sign/convention
   check catching `light_dir_ws` space errors between our pass and the engine, not a
   photometric match).
4. **Per-condition shimmer baselines**: run `precompute/tools/gaussian_twinkle.py` semantics
   over short orbit bursts at 3-4 matrix corners; record numbers in the validation doc as
   BASELINE only — the shimmer-reduction gate belongs to normal-quality step 2, do NOT
   double-gate D5 here.
5. Mode B is M5 — keep the mode list in one place as the extension point, do not implement.

## Acceptance
- One command runs the matrix + emits `lighting_stability.json` with per-check pass/fail;
  exits nonzero on any hard-assert failure.
- All hard asserts pass on the grounded `pxl_144634` export.
- Cross-model consistency passes (or, if it fails INSIDE GDGS/engine internals, STOP and seed
  a DECISIONS row with the evidence — same rule as normal-quality's invariant #6).
- Shimmer/condition baseline table lands in the validation doc.
- Existing suite + smoke stay green; tree stays clean (all render output in gitignored
  out-roots).
