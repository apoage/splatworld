# QUEUE — the ranked dark-factory work order

The factory's single entry point (planner-maintained). STATUS banners on task files remain the
truth for what's done; this file only orders what's OPEN. The factory takes from the top, skips
gated rows (noting why), and treats FILLER rows as parallel/anytime slices. Rows under
**Parked — owner-gated** are NOT factory work: never take them. Last groomed:
**2026-07-18 late** — reconciled **run #14** (task 3a harness **v0.24.0**) AND executed **task 3b**
(the real perf measurement, owner-greenlit GPU one-shot). **M4 task 3 is now FULLY CLOSED.**
Verified at true 1080p on the 3090: **1.45M budget carpet = 277 fps (4.6× the 60fps floor)**, full
2.4M hero = 180.6 fps — the "perf constant unmeasured" risk is RESOLVED and the ≤1.5M budget is
generous (`docs/2026-07-18-perf-3b-findings.md`). Found+fixed a harness resolution defect during
3b (hardcoded `res=1920x1080`, window landed at 1152×648) → **planner hotfix v0.24.1** (screen
placement + `window_set_size` + true-size readback gate; headless byte-identical). **Next M4 track =
authoring (tasks 4/5 Splat Studio), owner-attended WYSIWYG** — now unblocked with a known ≤1.5M cap;
NOT unattended-factory work. So the factory's next unattended pickup remains FILLER (quality-pass
slice 6/7, docs-guide) or the pixel5 one-shot. NEW wall **D9** (mixed-scene material-buffer
ownership) gated to Moon-Stone. Earlier: run #13 M4 spine v0.22/v0.23; run #12 GDGS v0.21.0; **D8
RATIFIED**; upstream GDGS report/PR = **parked pending owner cross-validation**.

## Ready — take from the top

| # | Task | Size | Note |
|---|------|------|------|
| — | **M4 tasks 4/5/6 — authoring UI (owner-attended, NOT unattended-factory) — NEXT M4 TRACK** | L+M+M | Task 4 Splat Studio in-viewer scatter + task 5 cleanup-select mode = WYSIWYG; acceptance is owner **visual eyeball** (screenshots never a factory gate) → build WITH the owner in the loop. **Now UNBLOCKED: the 3b perf number is in hand** — budget meter uses a confident ≤1.5M "green" cap (4.6× headroom at 1080p). Task 6 Blender `bpy` addon = secondary producer, needs a headless-blender tooling check first (rabbit-hole risk). All build on the shipped spine and **must respect D9** (mixed-scene material-buffer ownership) |
| ~~—~~ | ~~**M4 task 3b — REAL perf measurement (GPU one-shot)**~~ | S | ✅ **DONE 2026-07-18 (owner-greenlit).** Verified true 1080p on the 3090: **budget carpet 1.45M = 277 fps (4.6×)**, full 2.4M hero = 180.6 fps — ≤1.5M budget clears 60fps with wide headroom. Minted stride-14 variants via `clean_relight.py`; found+fixed a harness resolution defect mid-run (**hotfix v0.24.1**). `docs/2026-07-18-perf-3b-findings.md` |
| ~~1~~ | ~~`tasks/2026-07-18-m4-carpet-authoring.md` (task 3a — perf harness)~~ | M | ✅ **SHIPPED v0.24.0 (run #14, 2026-07-18).** `godot/relight/tools/carpet_perf.gd` — deterministic union-AABB orbit, prints `CARPET_PERF count/frame-ms/fps` + a `PERF_FPS_MIN` (60) assert-scaffold. **DoD = the tool + a STRUCTURE self-check** (`CARPET_PERF_RESULT` = load/parity/count only); the fps gate enforces (nonzero exit) **only on a real display**, so headless never fabricates a number (MINOR fix: perf miss drives exit code alone, sentinel stays structure-only, so 3b tells "harness worked" from "perf passed"). Additive-only; GDGS/loader/relight_pass untouched. Real measurement = **task 3b** (above). `docs/2026-07-18-handoff-run14-carpet-perf.md` |
| ~~1~~ | ~~`tasks/2026-07-13-normal-quality.md` (STEP 2)~~ | M | ✅ **SHIPPED v0.13.0 (run #5, 2026-07-15).** D5 fix = k-NN normal smoothing folded into `decompose` (decompose-side, not export — reuses the trusted held-out-PSNR gate). Opt-in `--smooth-normals-iters` (default 0 = no-op). Real re-decompose of pxl_144634: PSNR −0.11 dB, shimmer 48.77 (−75%), coherence 0.579→0.922. **Fix is default-OFF ⇒ built/mirrored viewer asset UNCHANGED — rollout = filler slice 5 (now unblocked).** `docs/validation-normal-quality-step2-2026-07-15.md` |
| ~~2~~ | ~~`tasks/2026-07-14-lighting-stability.md`~~ | M | ✅ **SHIPPED v0.14.0 (run #6)** — repeatable 10/10 gate, 53 conditions, fault-injection-proven checks. Follow-on = quality-pass slice 7 (shimmer baseline table). `docs/validation-lighting-stability-2026-07-15.md` |
| ~~1~~ | ~~`tasks/2026-07-15-relit-energy.md`~~ | S–M | ✅ **SHIPPED v0.15.0 (run #7, 2026-07-16).** DC-normalized the env-SH ambient (unit sphere-mean) + scaled by the ambient slider in `relight.glsl`/`set_env_sh`; the ~4× "bloom" is gone. Panel green (correctness+regression+flow-verifier); render_matrix 10/10 on the 3090, `\|env-flat\|=0.00014`. **Remainders:** planner adds the D4-runtime note to docs/decisions.md; owner eyeball (V toggle = subtle shape/tint, not an energy jump). `docs/2026-07-16-handoff-7-run7.md` |
| ~~2~~ | ~~`tasks/2026-07-15-normal-sign-consistency.md`~~ | M | ✅ **SHIPPED v0.16.0 (run #7, 2026-07-16)** — sign-consistency INFRA (init+post-solve camera-hemisphere orient, sign-aware smoothing) + a density-invariant **fail-closed** multi-scale gate. Suite 107; verified across 3 fix/verify cycles (caught 2 gate fail-opens). **Efficacy on real foliage UNPROVEN** — camera-orient resolves only the along-view component; ~17–49% synthetic residual at grazing normals → gated on the scheduled re-decompose (**D6**, fail-closed). `docs/2026-07-16-handoff-7-run7.md` |
| ~~1~~ | ~~`tasks/2026-07-16-grazing-normal-resolver.md`~~ | M–L | ⚠️ **PARTIAL v0.18.0 (run #9)** — resolver infra + both gate-defect fixes SHIPPED (FATAL → exit 3; refused metrics → sidecar; both proven twice in production); **the D6 hybrid itself REFUTED on real foliage (~30% balance-invariant floor) → reopened as D7**. Assets untouched (fail-closed). Banner on the task file |
| ~~1~~ | ~~`tasks/2026-07-17-sign-agnostic-prototype.md`~~ | S–M | ✅ **SHIPPED v0.19.0 (run #10). D7 DECIDED = KEEP SIGNED** (owner eyeball 2026-07-17 overrode the sign-agnostic consensus; DECISIONS D7). Sign modes remain diagnostic tools |
| ~~1~~ | ~~`tasks/2026-07-17-m3-transmission.md`~~ | M | ✅ **CODE SHIPPED v0.20.0 (run #11, 2026-07-18).** New `transmission` stage (v1 constant-per-label trans, leaf/grass→0.5 default, bark/ground exactly 0; non-vacuous landed-assignment gate) + runtime backlit A/B (`back_lobe`, binding-5 `meta.w`: mode 0 shipped `dot(−N,L)` wrap byte-identical default, mode 1 sign-robust Frostbite phase; viewer key **T**). Suite 120 ✓, panel green. JAX contributor lane had NOT landed → factory built the torch/numpy fallback per the task's clause. **MILESTONE ACCEPTANCE still owner-gated** → see Parked. `docs/2026-07-18-handoff-run11-m3-transmission.md` |
| — | **demo/gif regen (NOW gated on the M3 a/b pick)** | S | Slice 4 fixed render_orbit/render_sparkle orientation (v0.19.1) → regenerate the demo video + README gif on the grounded/smoothed/energy-calibrated/D7-signed hero, **now showing M3 backlit glow**. Sequence AFTER the owner picks the a/b backlit formula (run #11 handoff remainder #4) — the fireball money-shot is a direct input to that call (formula (a) inherits the D7 ~30% wrong-sign mis-glow; (b) avoids it). Visible payoff |
| — | **sandbox / viewer A/B (planner tooling, stage 1 DONE 2026-07-17)** | M | Facing-debug overlay (key G, binding-5 meta.z) + light-from-below (sun el −1.55..1.55 + gimbal guard + key 6) + clickable A/B panel (toggles + az/el/energy/amb sliders + sign/dbg dropdowns) + WASD/arrows fly-through. Gates green, signed byte-identity held. **STAGES 2–3 (unbuilt, speced in the design workflow):** controlled synthetic known-orientation scene (dial wrong-sign fraction, A/B vs GT, two-sided grass) + numeric single-splat inspector. Overlaps `synthetic-plant-gt` (shared synthetic-GT substrate) |
| — | **weird-shadow diagnostic (owner report 2026-07-17, cheap)** | S | Owner: "weird shadows in sun az 180–359°." Planner hypothesis = sign-domain clustering when the sun swings to the back hemisphere. Self-check via G→N.L overlay sweeping az; if magenta blooms in 180–359 = the known D7 property, if uncorrelated = a real new bug (then investigate). Also: floater/tall-grass dark streaks = dot(N,L)<0 (same sign artifact) + stray floaters → floater half fixed by quality slice 6 opacity prune |
| ~~3~~ | ~~`tasks/2026-07-15-flashlight-orb.md`~~ | M | ✅ **SHIPPED v0.17.0 (run #8, 2026-07-16)** — camera point/spot + engine-lit reference orb; per-splat world pos added to OUR material buffer (32→48 B, no PLY/GDGS change); light params in a binding-5 UBO = the N=2–4 fireball extension point. Frame cost within noise @ 2.4M. **REMAINDER: owner F/O eyeball** (acceptance gate). `docs/validation-flashlight-orb-2026-07-16.md` |
| 4 | `tasks/2026-07-12-pixel5-variants.md` | M–L | **Run as a SCHEDULED overnight/idle one-shot** (validation-tier rule — full pipeline per clip, hours; run #6 handoff). D2 note: heroes keep full count; the 500k + opacity-0.02 budget applies to VARIANT exports (M4 carpet blocks). Decompose fresh with `--smooth-normals-iters 2` — **prefer AFTER Ready #2 ships so variants inherit sign-consistent normals**. **Drift (run #11): `--stages all` now APPENDS `transmission`** → an end-to-end rebuild yields leaf `trans=0.5` assets (`metrics_transmission.json` supersedes `metrics_export.json`'s trans=0). Intended M3 direction; and since export currently labels every Gaussian leaf(2), the WHOLE variant becomes trans=0.5 until a real `label` stage lands — fine for all-foliage clips |
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
**Run #8 (2026-07-16):** flashlight-orb point/spot + reference orb (v0.17.0).
**Run #9 (2026-07-16):** grazing-normal resolver infra + gate-defect fixes (v0.18.0; D6 hybrid
REFUTED on real foliage → reopened D7).
**Run #10 (2026-07-17):** D7 sign-agnostic prototype (v0.19.0) + slice-4 orient fix (v0.19.1);
**D7 DECIDED = KEEP SIGNED** (owner eyeball).
**Run #11 (2026-07-18):** MILESTONE M3 transmission CODE (v0.20.0) — constant-per-label trans
stage + runtime backlit A/B; runtime stack now feature-complete in code —
`docs/2026-07-18-handoff-run11-m3-transmission.md`.
**Run #12 (2026-07-18):** GDGS fullscreen/zoom tile-dropout fix (v0.21.0) — resolution-aware
radix-sort pair buffers (3-file logged vendored diff); empirical proof 794 holes→0, 3.3× headroom
(`docs/2026-07-18-gdgs-tile-dropout-validation.md`). Our relight pass exonerated. **Upstream PR
parked pending owner cross-validation.**
**Run #13 (2026-07-18):** MILESTONE M4 spine — `RelightPass.set_materials_multi` +
`carpet_loader.gd` (v0.23.0) + `clean_relight.py` splat-cleanup/variant decimator (v0.22.0). The
multi-variant material-concat coupling (shader `materials[si.y]` ↔ registry first-seen order)
verified on all hard cases (B-first / interleaved / declared-unused / shared-path); all-or-nothing
fail-closed load. NEW finding → **D9** (mixed-scene buffer ownership) —
`docs/2026-07-18-handoff-run13-m4-spine-decimator.md`.
**Run #14 (2026-07-18):** M4 **task 3a** — `carpet_perf.gd` frame-time HARNESS (v0.24.0):
deterministic union-AABB orbit, `CARPET_PERF count/frame-ms/fps` + `PERF_FPS_MIN` scaffold; DoD =
tool + structure self-check (headless never fabricates fps; the gate enforces only on a real
display — MINOR fix separated the structure sentinel from the perf exit code). Additive-only.
Real ≥60 fps measurement = task 3b (scheduled GPU one-shot). `docs/2026-07-18-handoff-run14-carpet-perf.md`.
**Task 3b + hotfix v0.24.1 (2026-07-18, planner/owner, out-of-band from the factory):** executed the
real perf one-shot (owner-greenlit DISPLAY=:0) — **1.45M budget carpet = 277 fps, 2.4M hero = 180.6
fps, verified 1080p, ≤1.5M budget clears 60fps by 4.6×**. Mid-run found+fixed a harness resolution
defect (window landed 1152×648 not 1080p) → v0.24.1 (screen placement + `window_set_size` + true-size
readback gate; headless byte-identical). `docs/2026-07-18-perf-3b-findings.md`.

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

- **GDGS upstream report/PR (owner postponed 2026-07-18)**: the v0.21.0 tile-dropout fix is
  validated (794 holes→0), and `docs/2026-07-18-gdgs-tile-dropout-report.md` already doubles as a
  paste-ready issue/PR to `ReconWorldLab/godot-gaussian-splatting`. Owner wants to **cross-validate
  it themselves before any external filing** — hold until the owner reviews and green-lights. External
  action (public issue/PR) regardless, so never factory work.
- **M3 acceptance — hero re-export + a-vs-b eyeball (THE milestone gate, run #11)**: (1) re-export
  the heroes with nonzero leaf trans (in-place overwrite was classifier-blocked in the factory →
  owner runs it; exact loop in `docs/2026-07-18-handoff-run11-m3-transmission.md` remainder #1);
  (2) viewer: pose **5** (backlit) + Transmission ON + key **T** to switch (a) `dot(−N,L)` wrap ↔
  (b) Frostbite phase — does backlit glow read right, which formula wins? `wrap_power` live-tunable
  (`,`/`.`), `TRANS_DISTORT=0.3` shader const. (3) GPU backlit render check (sun az≈180, needs
  `DISPLAY=:0`). The a/b pick then unblocks the demo/gif regen. Default `trans=0.5` for leaf is a
  starting strength — owner may want it dialed before the demo regen.
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
