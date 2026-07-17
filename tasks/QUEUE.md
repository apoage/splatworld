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
| ~~2~~ | ~~`tasks/2026-07-14-lighting-stability.md`~~ | M | ✅ **SHIPPED v0.14.0 (run #6)** — repeatable 10/10 gate, 53 conditions, fault-injection-proven checks. Follow-on = quality-pass slice 7 (shimmer baseline table). `docs/validation-lighting-stability-2026-07-15.md` |
| ~~1~~ | ~~`tasks/2026-07-15-relit-energy.md`~~ | S–M | ✅ **SHIPPED v0.15.0 (run #7, 2026-07-16).** DC-normalized the env-SH ambient (unit sphere-mean) + scaled by the ambient slider in `relight.glsl`/`set_env_sh`; the ~4× "bloom" is gone. Panel green (correctness+regression+flow-verifier); render_matrix 10/10 on the 3090, `\|env-flat\|=0.00014`. **Remainders:** planner adds the D4-runtime note to docs/decisions.md; owner eyeball (V toggle = subtle shape/tint, not an energy jump). `docs/2026-07-16-handoff-7-run7.md` |
| ~~2~~ | ~~`tasks/2026-07-15-normal-sign-consistency.md`~~ | M | ✅ **SHIPPED v0.16.0 (run #7, 2026-07-16)** — sign-consistency INFRA (init+post-solve camera-hemisphere orient, sign-aware smoothing) + a density-invariant **fail-closed** multi-scale gate. Suite 107; verified across 3 fix/verify cycles (caught 2 gate fail-opens). **Efficacy on real foliage UNPROVEN** — camera-orient resolves only the along-view component; ~17–49% synthetic residual at grazing normals → gated on the scheduled re-decompose (**D6**, fail-closed). `docs/2026-07-16-handoff-7-run7.md` |
| ~~1~~ | ~~`tasks/2026-07-16-grazing-normal-resolver.md`~~ | M–L | ⚠️ **PARTIAL v0.18.0 (run #9)** — resolver infra + both gate-defect fixes SHIPPED (FATAL → exit 3; refused metrics → sidecar; both proven twice in production); **the D6 hybrid itself REFUTED on real foliage (~30% balance-invariant floor) → reopened as D7**. Assets untouched (fail-closed). Banner on the task file |
| ~~1~~ | ~~`tasks/2026-07-17-sign-agnostic-prototype.md`~~ | S–M | ✅ **SHIPPED v0.19.0 (run #10). D7 DECIDED = KEEP SIGNED** (owner eyeball 2026-07-17 overrode the sign-agnostic consensus; DECISIONS D7). Sign modes remain diagnostic tools |
| — | **sandbox / viewer A/B (planner tooling, stage 1 DONE 2026-07-17, uncommitted→committing)** | M | Facing-debug overlay (key G, binding-5 meta.z) + light-from-below (sun el −1.55..1.55 + gimbal guard + key 6) + clickable A/B panel (toggles + az/el/energy/amb sliders + sign/dbg dropdowns) + WASD/arrows fly-through. Gates green, signed byte-identity held. **STAGES 2–3 (unbuilt, speced in the design workflow):** controlled synthetic known-orientation scene (dial wrong-sign fraction, A/B vs GT, two-sided grass) + numeric single-splat inspector. Overlaps `synthetic-plant-gt` (shared synthetic-GT substrate) |
| — | **weird-shadow diagnostic (owner report 2026-07-17, cheap)** | S | Owner: "weird shadows in sun az 180–359°." Planner hypothesis = sign-domain clustering when the sun swings to the back hemisphere. Self-check via G→N.L overlay sweeping az; if magenta blooms in 180–359 = the known D7 property, if uncorrelated = a real new bug (then investigate). Also: floater/tall-grass dark streaks = dot(N,L)<0 (same sign artifact) + stray floaters → floater half fixed by quality slice 6 opacity prune |
| ~~3~~ | ~~`tasks/2026-07-15-flashlight-orb.md`~~ | M | ✅ **SHIPPED v0.17.0 (run #8, 2026-07-16)** — camera point/spot + engine-lit reference orb; per-splat world pos added to OUR material buffer (32→48 B, no PLY/GDGS change); light params in a binding-5 UBO = the N=2–4 fireball extension point. Frame cost within noise @ 2.4M. **REMAINDER: owner F/O eyeball** (acceptance gate). `docs/validation-flashlight-orb-2026-07-16.md` |
| 4 | `tasks/2026-07-12-pixel5-variants.md` | M–L | **Run as a SCHEDULED overnight/idle one-shot** (validation-tier rule — full pipeline per clip, hours; run #6 handoff). D2 note: heroes keep full count; the 500k + opacity-0.02 budget applies to VARIANT exports (M4 carpet blocks). Decompose fresh with `--smooth-normals-iters 2` — **prefer AFTER Ready #2 ships so variants inherit sign-consistent normals** |
| — | **recurring-quality-pass slice 5 — asset rollout DONE** | S–M | pxl_144634 (planner, reconcile #5) + pxl_131945 (factory run #6, rode the gate: −0.50 dB, headroom 0.48 — owner eyeball pending, trivially reversible via `.bak` + `git checkout` of 4 JSONs). **REMAINING: demo/gif regen — gated on slice 4** (the −180°Z sweep of the 4 remaining render tools). Doc-drift note: export docstring usage omits the required `--in` in the from-decompose example |
| — | **quality-pass slice 7** | S | per-condition **shimmer BASELINE table** (gaussian_twinkle over short orbit bursts at 3–4 matrix corners) — the de-scoped lighting-stability remainder, baseline-only, never a gate |
| — | **quality-pass slice 6 (aesthetic, owner 2026-07-15, LOW priority)** | S | **Splat cleanup on the hero assets** — "just aesthetic" per owner: run export's existing prune flags (`--prune-opacity 0.02`, try `--prune-scale-std` / `--prune-isolation-std` per the v0.5.0 sweep findings — isolation/scale were harmful on FOLIAGE PSNR but the goal here is visual tidiness, so eyeball-gate it) on pxl_144634/pxl_131945; owner eyeball decides keep/revert (originals stay in built/, mirrors swappable) |

**Shipped in the 2026-07-12 factory runs (banners on task files):** ingest-stage (v0.2.0),
code-hardening (v0.3.0), smoke-loop (v0.4.0), perf-budget (v0.5.0), **M2a relight-runtime
(v0.6.0)**, **M2b decompose A/B/C (v0.7.0)**. See `docs/2026-07-12-handoff.md` + `-handoff-2-M2.md`.
**Run #3 (2026-07-12):** M2b phase D (v0.8.0), env-SH runtime (v0.9.0), relight-orbit video (v0.10.0)
— `docs/2026-07-12-handoff-3-run3.md`. **Run #4 (2026-07-14):** ground-alignment (v0.11.0),
normal-quality diagnosis / D5 step 1 (v0.12.0) — `docs/2026-07-14-handoff-4-run4.md`.
**Run #5 (2026-07-15):** normal-quality D5 fix / step 2 (v0.13.0); lighting-stability harness
drafted WIP (6/10 checks pass, 4 harness fixes pending) — `docs/2026-07-15-handoff-5-run5.md`.
**Run #6 (2026-07-15):** lighting-stability finished to 10/10 (v0.14.0) + pxl_131945 D5 rollout.
**Run #7 (2026-07-16):** relit-energy env-SH energy calibration (v0.15.0) + normal-sign infra +
fail-closed multi-scale gate (v0.16.0; efficacy gated on the D6 re-decompose) —
`docs/2026-07-16-handoff-7-run7.md`.

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

- **synthetic-plant-gt (owner idea 2026-07-17, `tasks/2026-07-17-synthetic-plant-gt.md`)**:
  Blender L-system plant (two-sided leaves, distinct adaxial/abaxial materials) → multi-view
  render under known sun → reconstruct via our pipeline → per-splat GT sign by nearest-face.
  The synthetic-ground-truth substrate the D7 sign-recovery research (M-0/M-C) needs + stage-2
  sandbox geometry. blender-mcp installed. Planner/owner track (interactive Blender), NOT the
  factory. SCOPED — confirm approach (which L-system, photorealism bar) before a Blender
  session (rabbit-hole risk). HIGH strategic value.
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
