# QUEUE — the ranked dark-factory work order

The factory's single entry point (planner-maintained). STATUS banners on task files remain the
truth for what's done; this file only orders what's OPEN. The factory takes from the top, skips
gated rows (noting why), and treats FILLER rows as parallel/anytime slices. Rows under
**Parked — owner-gated** are NOT factory work: never take them. Last groomed:
**2026-07-14 late** (owner: orientation eyeball PASSED on the fixed viewer + D2 decided →
pixel5-variants ungated to Ready #3; step-2 GO on #1; lighting-stability #2; unreal parked).

## Ready — take from the top

| # | Task | Size | Note |
|---|------|------|------|
| ~~1~~ | ~~`tasks/2026-07-13-normal-quality.md` (STEP 2)~~ | M | ✅ **SHIPPED v0.13.0 (run #5, 2026-07-15).** D5 fix = k-NN normal smoothing folded into `decompose` (decompose-side, not export — reuses the trusted held-out-PSNR gate). Opt-in `--smooth-normals-iters` (default 0 = no-op). Real re-decompose of pxl_144634: PSNR −0.11 dB, shimmer 48.77 (−75%), coherence 0.579→0.922. **Fix is default-OFF ⇒ built/mirrored viewer asset UNCHANGED — rollout = filler slice 5 (now unblocked).** `docs/validation-normal-quality-step2-2026-07-15.md` |
| 2 | `tasks/2026-07-14-lighting-stability.md` | M | **WIP (run #5): `godot/relight/tools/render_matrix.gd` committed, RUNS end-to-end + emits JSON; 6/10 checks PASS (azimuth-360 return 59 dB, elevation smoothness, ambient floor, luma bounds, min-coverage, no-NaN). 4 checks FAIL — all HARNESS bugs, not engine findings — fix then re-run + verify:** (1) sphere_consistency n_px=0 — reference sphere placed above the camera frame, reposition into view; (2) energy_linearity ratio==1.0 — null ambient (ambient=0 + env cleared) for the sweep; (3) raw_invariance 14 dB — mask foliage (excludes the engine-lit sphere); (4) trans_inertness 45<55 dB — readback/sort noise at 4×, mask foliage + realistic threshold. Init bugs already fixed. Details: file header + `docs/2026-07-15-handoff-5-run5.md`. Needs DISPLAY=:0 |
| 3 | `tasks/2026-07-12-pixel5-variants.md` | M–L | **GATE OPEN**: D2 DECIDED (500k + opacity-0.02 prune) + orientation eyeball confirmed. Triage pixel5 clips + build ≥5 budgeted variants (M4 shortlist). Variants decompose fresh, so run with `--smooth-normals-iters 2` to bake in the D5 fix (no separate rollout needed for new variants). Prefer after slice 5 lands the fix on the existing assets |
| — | **recurring-quality-pass slice 5 (PARTIALLY DONE planner-side 2026-07-15)** | S–M | ~~Promote `.perf/normalsmooth/pxl_144634/` → `assets/built` + re-export + re-mirror~~ **DONE at reconcile #5** (originals backed up as `*_unsmoothed.*.bak`; ring_normal_dot_up=1.0, no NaN; viewer now loads the smoothed asset — owner eyeball pending). REMAINING factory work: re-decompose pxl_131945 with `--smooth-normals-iters 2` + re-export/re-mirror; then regen demo/gif (after slice 4). Doc-drift note: export docstring usage omits the required `--in` in the from-decompose example |

**Shipped in the 2026-07-12 factory runs (banners on task files):** ingest-stage (v0.2.0),
code-hardening (v0.3.0), smoke-loop (v0.4.0), perf-budget (v0.5.0), **M2a relight-runtime
(v0.6.0)**, **M2b decompose A/B/C (v0.7.0)**. See `docs/2026-07-12-handoff.md` + `-handoff-2-M2.md`.
**Run #3 (2026-07-12):** M2b phase D (v0.8.0), env-SH runtime (v0.9.0), relight-orbit video (v0.10.0)
— `docs/2026-07-12-handoff-3-run3.md`. **Run #4 (2026-07-14):** ground-alignment (v0.11.0),
normal-quality diagnosis / D5 step 1 (v0.12.0) — `docs/2026-07-14-handoff-4-run4.md`.
**Run #5 (2026-07-15):** normal-quality D5 fix / step 2 (v0.13.0); lighting-stability harness
drafted WIP (6/10 checks pass, 4 harness fixes pending) — `docs/2026-07-15-handoff-5-run5.md`.

## Filler — anytime, parallel-safe

- `tasks/recurring-quality-pass.md` — **recurring** code-quality / structure / doc-drift sweep
  (owner mandate 2026-07-12). One bounded pass per pickup; banner with date; never "done".
  Seeded slices: (1) ~~broken `single_asset.tscn`~~ FIXED in v0.6.0; (2) **root-cause the
  train_base.ply silent clobber** found in run #3 (a 48k init-only model overwrote the 2.39M
  asset while metrics still claimed 2.39M — guarded now by a baseline consistency check, but
  the writer is unidentified: suspect list = interrupted re-run, --steps smoke leftover
  writing to tracked assets/built, or an out-root default regression; check shell history +
  `.smoke/`/`.perf/` out-root code paths); (3) M2a MINORs (data gate should verify
  material-buffer CONTENTS; render gate analytic-shading check); (4) **neutralize GDGS's
  conditional −180° Z node default in every `.relightply`-loading tool** (render_orbit,
  render_sparkle, relight_render_gate, render_probe if applicable — NOT render_foliage, which
  renders vanilla plys and needs the correction): set `transform = Transform3D.IDENTITY`
  AFTER `add_child`, per the D3 rule; `relight_controller.gd` already fixed 2026-07-14 (the
  correction flipped the grounded asset upside down — owner report). MUST land before any
  demo/gif regen on grounded assets; (5) **regen the demo video + README gif on the grounded
  asset** (orientation owner-confirmed level 2026-07-14) — after slice 4, ideally after
  Ready #1 ships so the footage shows smoothed normals.
- `tasks/2026-07-12-docs-guide.md` — `docs/pipeline.md` walkthrough (clip → asset → Godot)
  + core docstrings + README "Docs" section. Acceptance: a fresh reader reproduces M1 from
  the guide alone.

## External — contributor lane (NOT factory work unless the owner reassigns)

- `tasks/2026-07-12-jax-transmission.md` — M3 `transmission` stage implemented in **JAX**
  (owner's friend). Phase 1 (fitting core + golden test, own `env-jax.yml`, file contract)
  can start now; phase 2 (real assets) gated on M2b. The factory does NOT take this row;
  if M3 arrives and the contribution hasn't, the planner re-decides.

## Parked — owner-gated (NOT factory work; the owner/planner executes these)

- **unreal-port (ON HOLD, owner 2026-07-14)**: future Unreal Engine implementation of the
  relight runtime, positioned as an **Epic MegaGrants candidate** (owner: "why not eventually").
  No work, no research until the owner reopens. The runtime contract is engine-agnostic by
  design (extended PLY + one compute shading pass); Godot stays the demo host. When reopened:
  M4 carpet footage is the natural centerpiece of a MegaGrants application.
- **data-release**: ⚠️ **clips embed GPS location + device tags — STRIP metadata
  (`ffmpeg -map_metadata -1 -c copy`, and exiftool the 4K JPG) before ANY public upload.**
  Attach `datasets/pixel4/PXL_20260711_144634633.LS.mp4` (~37 MB) as a
  GitHub Release asset + a README "Data" note, so M1 is reproducible. Deferred by owner;
  requires a remote write (`gh release`), which the factory's `allow_push: false` guard
  forbids by design. Data excluded from git for SIZE only (footage is the owner's; cactus
  samples are CC0).

## Gated — do NOT start (named gate must open first)

| Task | Gate |
|------|------|
| M3 — transmission (backlit grass/leaf glow + UI toggle) | M2 `decompose` shipped ✓ + normal-quality step 2 (Ready #1) — spec when both land |
| M4 — carpet (instanced blocks, 5–15 variants, hit 60fps@1080p). **Owner vision (2026-07-13): whole-scene coverage with distance-based splat decay (LOD) — challenges hero million-poly models; foliage "brushes". LOD = M4 stretch row when the gate opens.** **Demo north star (owner 2026-07-15, "Moon Stone Meadow" — doc in owner's HOME, not this repo): the M4 meadow doubles as the release-demo scene; day→night dusk lerp + player-cast fireballs. Implies NEW runtime rows when gate opens: point-light support in the relight pass (currently one directional; per-splat L dir + falloff, bounded N lights), touch-trigger + day/night state. Both day and night phases MUST run the relightable shader (honesty constraint)** | M2 shipped ✓ + asset variants ready (pixel5, Ready #3) |
| M5 — wind (shared noise field) + mode-B basis blend (stretch). Moon-Stone demo polish (fireball arcs, dusk sky) lands here if M4 ships lean | M4 shipped |

## Grooming rules
Planner re-ranks after each factory run + banners; a row leaves this file only by shipping
(banner) or being explicitly parked. If the factory finds the top row blocked in practice, it
takes the next and records why in its wrap-up. M3–M5 get their own `tasks/<date>-*.md` specs
when their gate opens.
