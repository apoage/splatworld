# Changelog

All notable changes. Versions are bumped by the dark-factory release ritual
(implementer lane); this initial entry was seeded by the orchestrator.

## [Unreleased]

## [0.22.0] — 2026-07-18
- **M4 task 2 — `precompute/tools/clean_relight.py`** (`tasks/2026-07-18-m4-carpet-authoring.md`):
  new CLI tool that reads one extended `.relightply` asset, applies removal filters, and writes a
  smaller cleaned asset + `metrics_clean.json`. Doubles as the variant-minting decimator that turns
  a 2.4M hero into a carpet-block variant (verified: 2.08M → 1.07M in one pass). Precompute-side
  only; nothing under `godot/` touched; no PLY schema change.
- **Filters** (all combine by logical AND on one keep mask): floater prune (reuses
  `stages.export.floater_prune_mask` verbatim — opacity/scale-std/isolation-std), AABB crop
  (keep-inside) / exclude (drop-inside) with per-axis unbounded components, label keep/drop
  whitelist/blacklist, and an explicit `--keep-index` selection (JSON array or newline ints) that
  INTERSECTS the rest — the feed for the later Godot cleanup mode (task 5).
- **Fail-closed**: a range/NaN/non-unit-normal/out-of-schema-label/out-of-range-index violation, or
  a zero-splat result without `--allow-empty`, exits nonzero and writes NOTHING (no-clobber of any
  pre-existing `--out`); every gate runs before `write_asset_ply`. All PLY bytes go through
  `core/ply_io.py`; `--in`/`--out` are required with no source-pointing defaults.
- **Verification**: adversarial panel green (correctness + regression + flow-verifier); flow-verifier
  exercised 6 filter cases with independently-computed keep-counts + a real 2.08M-asset decimation.
  Golden tests `precompute/tests/test_clean_relight.py` (20); full suite 141 passed.

## [0.21.0] — 2026-07-18
- **GDGS fullscreen/zoom tile-dropout FIXED** (`tasks/2026-07-18-gdgs-tile-dropout.md`;
  root-cause `docs/2026-07-18-gdgs-tile-dropout-report.md`). At fullscreen/4K the rasterizer
  dropped rectangular 16px-tile-aligned holes to background. Cause: GDGS sizes the radix-sort
  tile-gaussian **pair** buffers by splat count only (`point_count*10`), but the pair count is
  resolution/zoom-dependent → the unchecked `atomicAdd` allocator wrote out of bounds
  (silently discarded under `robustBufferAccess`) → those tiles read `num_splats=0` and
  rendered `final_alpha=0`. Our relight pass was exonerated (per-splat, resolution-independent).
- **Vendored GDGS diff — 3 coordinated edits (logged; re-apply on any re-vendor):**
  (1) `runtime/render/gaussian_gpu_state_cache.gd` — sort-pair budget now scales by
  `maxf(1.0, tile_grid_area / REFERENCE_TILE_COUNT=3600)` (1280×720 grid), floored to the
  original budget below the reference grid; stored in `RenderState.sort_capacity_per_half`.
  (2) `runtime/render/gaussian_renderer.gd` — the radix ping-pong half-stride now uses
  `sort_capacity_per_half` (load-bearing: must match (1) or the sort reads the wrong half →
  scrambled depth); trailing uniform slot carries the capacity. (3)
  `shaders/compute/gsplat_projection.glsl` — Uniforms pad → `int sort_capacity` + a safety-net
  clamp after the atomicAdd so any residual overflow is a clean tile drop, not an OOB write.
- **Empirical proof (DoD)** on the real 3090 (`relight/tools/render_probe.gd` extended to read
  back `sort_buffer_size` + count interior 16px holes): repro over the old capacity dropped
  ~750–800 tiles; post-fix same demand fits under capacity (≥3.3× headroom at the overflowing
  resolutions) → 0 holes. Reverting the 3 files reintroduces the holes (causal proof).
  Controlled re-validation at 1280×720 (demo render resolution) + deep zoom: max ratio 0.68
  (~1.5× headroom), 0 holes — the "zoomed in" symptom is covered at demo resolution.
  Worst-case VRAM ~8.6 GB (1.5M splats × 4K × 4 cached states), fine on the 24 GB 3090.
  `smoke_test.gd` PASS; `pytest precompute/tests` 120 passed. Full detail +
  `docs/decisions.md` paste-ready diff record: `docs/2026-07-18-gdgs-tile-dropout-validation.md`.
- Upstream report/PR to `ReconWorldLab/godot-gaussian-splatting` remains owner-gated (external).

## [0.20.0] — 2026-07-18
- **MILESTONE M3 (transmission — code): backlit grass/leaf glow stage + runtime A/B**
  (`tasks/2026-07-17-m3-transmission.md`). Gate opened by M2✓ + D5✓ + D7 DECIDED (keep
  signed, which un-breaks the `dot(−N,L)` backlit term). Ships the code deliverable; hero
  re-export on real data and the owner a-vs-b eyeball are the orchestrator/owner acceptance
  steps that follow.
- **New `precompute/stages/transmission.py`** — v1 CONSTANT-PER-LABEL `trans` (CLAUDE.md
  stage 5 accepts this; the thin-leaf backlit-residual estimate is a deliberately-deferred
  stretch). leaf(2)/grass(1) → configurable `--trans-leaf`/`--trans-grass` (default 0.5);
  bark(3)/ground(0) and any out-of-schema label stay exactly 0. Operates on the built
  extended `asset.ply` post-export (trans is a scalar, no coordinate conversion → frame-safe);
  reads/writes PLY bytes ONLY via `core.ply_io`. No schema change (`trans` already exists).
- **`metrics_transmission.json` with a non-vacuous fail-if-broken metric** (invariant #7):
  besides per-label counts / range / NaN and the opaque-label guard, a POSITIVE
  landed-assignment gate asserts that each requested constant > 0 with ≥1 Gaussian of that
  label actually landed (`trans_min == trans_max == expected`, exact f32) — the guard that
  fires on real (uniformly-leaf) pipeline data where the bark/ground==0 check is vacuous.
  Plus total-consistency accounting (`n_other_label`, `counts_consistent`). All gates
  fail-closed (`raise SystemExit`) pre-write → a broken run never clobbers a prior good asset.
- **`run.py`**: `transmission` wired into `STAGE_ORDER` after `export`; `--trans-leaf` /
  `--trans-grass` passthrough. NOTE: `--stages all` now appends transmission, so an
  end-to-end rebuild produces transmissive (leaf trans=0.5) assets — `metrics_export.json`
  (trans=0) is superseded by `metrics_transmission.json` afterward.
- **Runtime backlit A/B** (`godot/relight/relight.glsl`, `relight_pass.gd`,
  `tools/orbit_viewer.gd`): backlit term factored into `back_lobe(N,L,V,trans,wrap_power,
  trans_mode)` used at BOTH the sun and flashlight-loop sites. `trans_mode` on binding-5
  `meta.w` (was free; push constant untouched): **mode 0 TRANS_WRAP** = shipped
  `trans*pow(max(dot(−N,L),0)*0.5+0.5,wrap_power)`, **byte-identical** default; **mode 1
  TRANS_PHASE** = Frostbite view–light phase `trans*pow(clamp(dot(V,−normalize(L+0.3·N)),0,1),
  wrap_power)` (sign-robust, view-driven — does not inherit the D7 ~30% wrong-sign noise).
  Viewer key **T** cycles the formula (+ "trans lobe" dropdown); default mode 0. GDGS untouched.
- Suite: 120 passed (118 prior + 2 new, incl. a negative-proof test that fails if the
  landed-assignment gate is removed).

## [0.19.1] — 2026-07-17
- **quality-pass slice 4: GDGS −180°Z neutralization in the demo/gif render tools**
  (`recurring-quality-pass.md`). `render_orbit.gd` and `render_sparkle.gd` now set
  `gs.transform = Transform3D.IDENTITY` after `add_child`, mirroring the already-proven
  `render_matrix.gd:210` pattern, so GDGS's conditional −180°Z node correction (meant for
  raw y-down 3DGS plys) does NOT fire on our already-Godot-convention `.relightply` grounded
  heroes (D3 rule; the correction previously flipped grounded assets upside down).
  Deliberately left untouched: `render_probe.gd` (vanilla cactus ply — needs the correction),
  `relight_render_gate.gd` (aggregate-luma gate, orientation-invariant, green), `render_foliage.gd`
  (vanilla plys). Verified on the real GPU: render_orbit RELIGHT_ORBIT_RESULT PASS + 48
  non-empty frames, render_sparkle 24 frames exit 0, render_matrix regression green
  (sphere_consistency + raw_invariance), pytest 114. **Unblocks slice-5 demo/gif regen** on
  grounded assets (still owner-eyeball-gated for right-side-up correctness).

## [0.19.0] — 2026-07-17
- **sign-agnostic-prototype: D7 shading experiment behind a live `sign_mode` toggle
  (`tasks/2026-07-17-sign-agnostic-prototype.md`).** Runtime-only, additive, default OFF —
  produces the owner A/B eyeball evidence for the OPEN D7 decision; does NOT decide D7.
- **`sign_mode` uniform in the relight pass** (`godot/relight/relight.glsl`,
  `relight_pass.gd`) with a `direct_lobe()` helper both the sun and flashlight direct terms
  route through. Modes match `docs/d7-synthesis-2026-07-17.md` §4:
  - **0 signed** — `max(dot(N,L),0)`, the shipped v0.18.0 path, **byte-identical** when off.
  - **1 sign-free WRAP** — `clamp((abs(dot(N,L))+w)/(1+w),0,1)/(1+w)`, w≈0.4 (abs first;
    NOT half-Lambert, NOT plain abs). Live-tweakable via `,`/`.` while in mode 1.
  - **2 flip-toward-camera** — `N' = dot(N,V)>=0 ? N : -N` then signed; V = splat→camera
    from the camera world pos added to the binding-5 UBO (208→224 B; push constant untouched).
  - **3 confidence-blend — SKIPPED**: per-splat covariance scales aren't in any buffer the
    pass binds, and extending the material buffer for a prototype is forbidden by the Gate.
- **Viewer key `N`** cycles modes live with a HUD label (`godot/relight/tools/orbit_viewer.gd`).
- **Analytic sign gate** (`relight_sign_gate.gd`): closed-form per-mode check on a synthetic
  ±Z splat cluster; each formula proven by fault injection (drop abs / drop flip → gate FAILs),
  plus a raw-invariance check (raw output invariant to `sign_mode`). Per-mode perf probe
  (`relight_sign_perf.gd`): signed 7.95 / wrap 7.76 / flip 7.75 ms @ 2.4M splats, 1080p (~free).
- Verified on the real GPU (DISPLAY=:0, 3090): SIGN_GATE + RELIGHT_RENDER + FLASH_GATE +
  RELIGHT_SMOKE PASS; pytest 114 passed. **Remainder: owner A/B eyeball in sun-only mode D on
  both heroes = the D7 decision evidence** (do patch shadows die in mode 1/2? any mode-2 orbit
  silhouette pop or ground/bark direction degrade?).

## [0.18.0] — 2026-07-17
- **grazing-normal-resolver: D6 hybrid sign resolver + two gate-defect fixes
  (`tasks/2026-07-16-grazing-normal-resolver.md`).** Ships the resolver INFRASTRUCTURE and the
  bugfixes; the real-data efficacy target is **REFUTED** (see below) — assets UNCHANGED (fail-closed).
- **Hybrid sign resolver (cue a + cue b), replacing the k_cam nearest-camera vote as the default
  decompose sign pass** (`core/normals.py`: `visibility_weighted_reference`, `voxel_sign_field`,
  `resolve_normal_signs`; wired into `decompose.py` at init + post-solve). Cue (a): orient each
  Gaussian toward its MOST-face-on view (`d_peak`, the peak visibility witness), confident only when
  the face-on-emphasised aggregate `ref` corroborates it — a crowd of one-sided grazing views can no
  longer drag the sign to the wrong hemisphere (the confidently-wrong-domain failure). Cue (b):
  coarse-voxel majority sign field for the low-confidence residual (no MST/BFS, O(N)). CLI knobs:
  `--sign-vis-min-face`, `--sign-vis-min-coherence`, `--sign-voxel-mult`, `--sign-voxel-passes`.
  Falls back to the v0.16.0 `make_normals_sign_consistent` path when per-view projection data is absent.
- **EFFICACY REFUTED on real foliage.** Re-decompose of pxl_144634 (2.4M splats): 8-NN opposition
  **30.03%** / adaptive **37.65%** at default balance; **29.13% / 37.81%** voxel-dominant
  (`--sign-vis-min-coherence 0.9`). The ~30% floor is **balance-invariant** and matches the pre-fix
  v0.16.0 camera-hemisphere result — visibility-witness orientations are high-confidence but
  neighbor-inconsistent on real grazing normals, and neither camera- nor voxel-dominant balance
  resolves the front/back ambiguity. The <5% gate correctly REFUSED (fail-closed); hero assets left
  untouched. **D6 reopened as D7** for the next approach (or an accept-the-look decision). M3 stays gated.
- **Gate defect #1 — fail-open exit (FIXED):** a FATAL sign/PSNR-gate refusal now exits a NONZERO
  integer (`GATE_REFUSED_EXIT=3`; any string/0/None code normalized), so automation (`run.py`) cannot
  read a refusal as success. The FATAL reason is mirrored to stderr as well as stdout.
- **Gate defect #2 — metrics clobber (FIXED):** the tracked `metrics_decompose.json` describes the
  SHIPPED artifacts, so a refused run now writes `metrics_decompose_refused.json` (gitignored) and
  leaves the tracked file byte-identical; the tracked file is written only after all gates pass, and a
  stale refused file is unlinked on the next success. Both defects proven fail-closed in production by
  the two real re-decompose runs (both refused, exit 3, no clobber).
- Tests: `test_resolver_orients_by_peak_witness_not_aggregate` (genuine aggregate-vs-witness trap that
  fault-injects), refused-run nonzero-exit + no-clobber tests. Suite 107 → 114.

## [0.17.0] — 2026-07-16
- **flashlight-orb: aggressive local lighting (point/spot) + engine-lit reference orb
  (`tasks/2026-07-15-flashlight-orb.md`). First change to the relight shading contract since M2a.**
  Owner request (post-D5 eyeball): "more aggressive lighting options like flashlight, and a reference
  orb." Strategically this is the Moon-Stone-demo point-light prerequisite (fireballs) pulled forward
  as a viewer feature — same shading math, one camera-attached local light.
- **Per-splat world position (the task's premise was wrong — corrected):** the pass had NO world
  position available (it binds only the screen-space culled buffer + material/instance buffers). Added
  per-Gaussian OBJECT-SPACE position to OUR material GPU buffer (grown 2→3 vec4, 32→48 B; new
  `pos_label` slot, xyz = centered object-space position, filled from the already-parsed loader
  positions) and transform it to world in the shader with the SAME `instance_model_matrices[si.x]`
  already used for the normal. NOT a PLY schema change — `.relightply` already stores x/y/z; this is a
  runtime GPU-buffer layout addition only (no `SCHEMA_VERSION` bump; ply_io.py untouched).
- **Shader (`relight.glsl`):** additive point/spot term after the RAW early-return —
  `L = normalize(flash_pos - pos_ws)`, inverse-square × smooth range window, `smoothstep` spot cone —
  reusing the same albedo/normal/trans as the directional term. Light params live in a NEW binding-5
  storage buffer (`ivec4 meta` + fixed `FlashLight[4]` array, N=1 now); the push constant stays exactly
  48 B / 3 vec4. Layout documented as the N=2–4 fireball extension point (adding lights is a CPU-setter
  change only — no shader/descriptor churn).
- **Viewer (`orbit_viewer.gd`):** `F` toggles a camera-attached flashlight (warm white, tight cone),
  `O` toggles a gray Lambert reference orb (engine-lit by the same DirectionalLight3D) + a real
  `SpotLight3D` mirroring the flashlight so the orb stays honest in flashlight mode; HUD shows
  `flash=`/`orb=`. Shared `orb_placement()` helper (reused by the sphere_consistency check).
- **Gates:** new `relight_flashlight_gate.gd` (synthetic closed-form analytic gate for the point-light
  term) + two always-on tail phases in `relight_render_gate.gd` (RAW-with-flashlight no-leak;
  relit-with-flashlight adds-light); `flashlight_perf.gd` frame-time probe. Raw-mode invariance provably
  holds with the flashlight ON.
- **Gate hardened fail-closed (verification cycle):** the analytic gate was initially fail-OPEN on the
  range/falloff term (its only splat sat at range_win≈0.98, hiding a dropped range clamp under
  tolerance). Fixed with a non-trivial-range phase (range_win≈0.31) + a dedicated out-of-range→0 hard
  discriminator; re-verified by fault injection (`falloff = inv_sq;` now FAILS with a 10× tolerance
  margin). Also clamped the cone `smoothstep` to avoid a NaN when inner==outer (the fireball extension
  path) and bumped SETTLE to 40 to kill cold-cache false-fails.
- **Frame-time baseline (Moon-Stone fireball budget):** flashlight on/off delta is within noise at
  2.4M splats / 1080p (~8 ms/frame; GDGS sort/rasterize dominates one extra local light) —
  `docs/validation-flashlight-orb-2026-07-16.md`.
- **Verified (never self-reviewed):** high-tier panel (correctness + fail-closed + regression +
  security/invariants + flow-verifier), then a dedicated fail-closed re-verify after fix cycle 1.
  render_matrix 10/10; suite 107; world-position correctness confirmed spatially (lit blob tracks the
  light). No GDGS edits, no schema bump, push constant unchanged.

## [0.16.0] — 2026-07-16
- **normal-sign-consistency: sign-consistency infrastructure + fail-closed multi-scale domain gate
  (`tasks/2026-07-15-normal-sign-consistency.md`). Ships the SUBSTRATE, not a proven patch-shadow fix.**
  Owner report (viewer, sun-only): patchy fake shadows on foliage, "splats not synchronized in angle."
  Audit: 28.5–29.2% of 8-NN neighbor normal pairs sign-opposed in decompose output; sign-naive
  `smooth_normals_knn` coalesced them into ~0.1-unit random-signed DOMAINS (the patch shadows).
- **Root cause:** `shortest_axis_normals` init used an arbitrary per-Gaussian eigenvector sign and never
  oriented to the dominant camera hemisphere (contradicting the CLAUDE.md gotcha); stage-1's per-view
  depth-normal targets don't enforce a global sign.
- **Change:** orient init + post-solve normals to the camera hemisphere (`make_normals_sign_consistent`,
  default-on); `smooth_normals_knn` is now SIGN-AWARE (flip each neighbor to self before averaging — no
  longer byte-identical to the old gaussian_twinkle preview); tripwire folded to sign-independent
  `folded_coherence`; new multi-scale sign metrics (`signed_opposition_frac` at 8-NN + a PER-POINT
  ADAPTIVE domain radius = 4× each point's own 8-NN spacing) with a coverage-fraction floor; a
  fail-closed gate raises before any artifact write when opposition ≥5%, sign-aware degenerate-mean
  ≥0.5%, or <90% of points can be certified at their own domain scale. PSNR budget unchanged, still
  load-bearing.
- **Gate hardened density-invariant + fail-closed over 3 verification cycles:** verification caught and
  drove out a uniform off-gauge fail-open (fixed world-unit radius → asset-relative) and a
  density-nonuniform fail-open (a dense-ground majority "verified" the gate while sparse foliage went
  unmeasured → per-point adaptive radius + coverage-fraction floor). Re-verify confirms a foliage-dominant
  broken cloud is caught at 33.4% adaptive / 13.1% 8-NN, and CASE-D / duplicate-heavy raise through the
  real gate; the good path still ships.
- **KNOWN LIMITATION / efficacy UNPROVEN (tasks/DECISIONS D6):** camera-hemisphere orientation resolves
  only the along-view sign component. Synthetic evidence at hero coherence with realistic grazing /
  away-facing foliage normals shows 17–49% residual opposition — the approach ALONE is likely
  insufficient to eliminate the owner's patch shadows, and the scalable global resolver (MST) does not
  scale to million-Gaussian assets. The always-on fail-closed gate makes deferral safe: the SCHEDULED
  re-decompose is the arbiter — if the heroes exceed 5% it REFUSES to ship (built/mirrored viewer assets
  stay as-is). In-loop fixtures prove the MECHANISM (camera-resolvable regime → ~1–2%) and honestly
  RECORD the hard-regime residual; they are NOT evidence the heroes pass.
- **Verified (never self-reviewed):** correctness + fail-closed + regression + flow-verifier panel, then
  re-verify panels after two fix passes (fail-closed re-verified a third time). Golden green (MAE 0.0011,
  CUDA), suite 107 passed.

## [0.15.0] — 2026-07-16
- **relit-energy: DC-normalize the env-SH ambient to the ambient slider
  (`tasks/2026-07-15-relit-energy.md`).** Owner report (both heroes): relit looked like "bloom with
  extra saturation" — made-up light/shadow patches + hue shift. Root cause: `relight.glsl` applied the
  recovered env-SH ambient at weight 1.0 (`ambient_rgb = ambient_sh(N)`), IGNORING the ambient slider,
  while the sidecar coeffs are the FULL recovered capture illumination — so relit ≈ unit sun + full
  capture light ≈ ~4× energy (audit: env ambient luma 0.84–0.88 = 4.2–4.4× the 0.2 flat design; 23–27%
  of splats clipping >1.0 → the hue-shift/bloom). Flow-verifier measured the pre-fix multiplier at 4.01×.
- **Fix (runtime-side only):** `RelightPass.set_env_sh` now scales all 9 c_lm by `1/(SH_C0·luma(c00))`
  so the sphere-mean luma of `ambient_sh(N)` == 1.0 (every l≥1 SH band integrates to zero over the
  sphere ⇒ the mean is exactly `SH_C0·c00`); `relight.glsl` multiplies the env branch by the ambient
  slider (`pc.light_color.w · ambient_sh(N)`). The slider now drives env strength exactly like the flat
  fallback (same energy budget); the env contributes only directional shape + relative tint.
  `sh_env.py`, the `*_env_sh.json` sidecar bytes, and the export A_l·π folding are UNTOUCHED — exports
  stay engine-agnostic ground truth; normalization is runtime-only. (Recalibrates D4's runtime wiring;
  the data contract is unchanged — planner to log the D4 note in `docs/decisions.md`.)
- **Gates:** new headless data gate in `relight_smoke.gd` asserts unit sphere-mean luma on the BOUND
  coeffs (synthetic + real sidecar) via an exact 6-point octahedral quadrature; `relight_render_gate.gd`
  rewritten — the old "env must DIFFER from flat" assertion was INVERTED by this fix (env now MATCHES the
  flat energy budget by design), replaced by an energy-budget-match check (|env−flat| ≤ 0.05; a
  regression to weight-1.0 reads ~0.34) plus a new phase-6 slider-scaling probe (env@0.5 − env@0.2 ≥
  0.03; pre-fix the env ignored the slider). `render_matrix.gd` re-passes 10/10 on the 3090 (deterministic
  ×2); env-on grid luma dropped from bloomy (~4×) to 0.15–0.30. Suite 95 passed.
- **Verified (never self-reviewed):** correctness + regression + flow-verifier panel, all green.
  Correctness hand-derived the SH sphere-mean identity; regression confirmed the cactus/raw/flat paths
  stay byte-identical and the push constant is unchanged (48 B); the flow-verifier ran all four gates on
  the real RTX 3090 after a forced shader reimport (a `.glsl` edit needs `godot --headless --import`
  before a `--script` render or the run uses the stale cached import — noted for CI).

## [0.14.0] — 2026-07-15
- **lighting-stability harness (`tasks/2026-07-14-lighting-stability.md`).** Finished the run #5 WIP
  `godot/relight/tools/render_matrix.gd` into a legitimate, repeatable **10/10** offline gate. A FIXED
  camera renders a **53-condition** matrix of the M2 relight pass on the grounded `pxl_144634.relightply`
  (elevation×azimuth grid + energy/ambient/color 1-D sweeps × {raw, relit, relit+trans_on}) and emits
  per-check pass/fail into `godot/shots/lighting_stability/lighting_stability.json`. One greppable line
  `LIGHTING_STABILITY_RESULT PASS|FAIL`; exit code mirrors it. Real renderer only (`DISPLAY=:0`, NO
  `--headless`), ~23 s on the 3090.
- **10 machine-checkable checks:** no-NaN, min-coverage (two-tier: RAW footprint + universal blank floor),
  relit luma bounds, raw-invariance (light must not leak into the albedo-only path), trans-inertness
  (relit == relit+trans_on while asset trans==0), azimuth-360° return (no state drift), energy-linearity
  (luma(2E)/luma(E)≈2, env off + ambient 0), elevation smoothness, ambient floor, and an engine
  cross-model sphere-consistency check (our `light_dir_ws` agrees in sign with the engine
  DirectionalLight3D). **No engine finding surfaced** — all four previously-failing checks were
  harness-logic/threshold bugs; no `tasks/DECISIONS.md` row.
- **Verified (never self-reviewed):** correctness + regression + flow-verifier panel. The correctness
  judge caught the first implementer pass having lowered two PSNR floors (`RAW` 55→45, `TRANS` 55→40)
  *below* their measured operating point on a false rationale; the fix pass corrected them to `RAW 50` /
  `TRANS 55` — margin under the measured worsts (raw 55.4–56.9 dB, trans 62.7–64.2 dB over 4–5 runs),
  the false comments replaced with the flow-verifier's fault-injection numbers (a subtle ~2% raw leak
  reads 36 dB, gross 4.5 dB — the loosened check still fires on a real fault), and the degenerate
  `trans_inertness` self-compares removed (`n_pairs` 28→11 genuine pairs). Suite unchanged at 88.
  Full analysis: `docs/validation-lighting-stability-2026-07-15.md`.

## [0.13.0] — 2026-07-15
- **normal-quality FIX (`tasks/2026-07-13-normal-quality.md`, D5 — STEP 2 of 2).** k-NN normal
  smoothing that removes the orbit "sparkle" step 1 attributed to spatial neighbour-normal
  incoherence. Folded into `decompose` (not export) so decompose's own fail-closed held-out
  re-render PSNR gate (invariant #8) validates the SHIPPED normals — no new renderer, no
  duplicated gate. Opt-in `--smooth-normals-iters` (default **0 = exact no-op**, a normal run
  stays byte-identical) / `--smooth-normals-knn` (default 8).
- **New `precompute/core/normals.py`** — `smooth_normals_knn` (average each unit normal over its
  self+k-NN neighbourhood + renormalize, iterated; byte-for-byte the step-1 `gaussian_twinkle.py`
  preview transform), `local_coherence` (over-smoothing tripwire), `knn_indices`,
  `mean_normal_norm`. numpy+scipy, CPU, chunked; rigid-equivariant so export's single
  COLMAP→Godot rotation is unaffected.
- **Validated on a real re-decompose of `pxl_144634`** (`--smooth-normals-iters 2`): held-out
  PSNR **21.572 dB, −0.11 dB** vs train_base (≤1.5 dB budget ✓, `budget_ok:true`); neighbour
  shimmer on the shipped normals **48.77 ×1000, −75.3%** vs the 197.53 baseline (≤98.8 ✓); local
  coherence **0.579→0.922** without saturating the 0.985 over-smoothing ceiling
  (`over_smooth_suspect:false`); appearance preserved (unsmoothed decompose was 21.639 dB → cost
  0.067 dB), albedo untouched, normals unit. Reproduces the step-1 numpy preview exactly on a
  genuine re-solve. Full analysis: `docs/validation-normal-quality-step2-2026-07-15.md`.
- **Corrected gate satisfied** (per step 1): `shimmer ≤ 98.8` is *necessary-not-sufficient*
  (gameable by over-smoothing) → paired with the load-bearing held-out re-render PSNR ≤1.5 dB on
  the smoothed/shipped normals + an anti-over-smoothing coherence tripwire. Suite 78→88 (+10).
- **Rollout deferred** (recurring-quality-pass slice 5, now unblocked): the fix is default-off, so
  the built/mirrored `pxl_144634.relightply` the viewer loads is unchanged; re-shipping the built +
  mirrored assets with smoothed normals (+ `pxl_131945`, + demo/gif regen) is the next unit. The
  validated smoothed decompose is preserved at `.perf/normalsmooth/pxl_144634/`.

## [0.12.0] — 2026-07-14
- **normal-quality DIAGNOSIS (`tasks/2026-07-13-normal-quality.md`, D5 — STEP 1 of 2, fix NOT included).**
  Attributes the orbit "sparkle" the owner flagged. **Verdict: SHADING class = spatial neighbour-normal
  incoherence** from the near-isotropic decompose normals. Sort/aliasing RULED OUT (a RAW baked orbit is
  temporally flat, 0.135 ×1000 → renderer is deterministic, not a GDGS-side sort/AA issue → no owner/GDGS
  decision needed); floaters RULED OUT (opacity-0.02 prune moved the metric ~0%).
- **New render-free measurement tooling** — `precompute/tools/gaussian_twinkle.py`: a quantization-free,
  float, per-Gaussian **neighbour-shimmer** metric (std over the orbit of each Gaussian's local shading
  contrast vs its k-NN), replicating `relight.glsl` + the `render_orbit` light path in numpy (no GPU).
  Baseline **shimmer = 197.53 (×1000)**, frame-count-stable, and normal-attributable (r=+0.53 vs normal
  noise, monotonic across noise deciles; a numpy k-NN smoothing preview drops it −75% while appearance
  holds). Superseded a first screen-space metric that was confounded by **8-bit PNG quantization** (it
  measured quantization of the smooth relight ramp, not twinkle — caught by adversarial verification).
  `godot/relight/tools/render_sparkle.gd` (single-mode orbit dumper) + `sparkle_metric.py` retained for
  the qualitative RAW-flatness (sort/aliasing) check. Frame-guard refuses an exported `asset.ply`
  (COLMAP-frame `decompose.ply` only). Suite 76→78.
- **Step 2 (the fix) is seeded, not built** — it is the expensive-real-data unit. Candidate first move:
  export-time k-NN normal smoothing (or a decompose-side neighbour regularizer). **Corrected gate:**
  `shimmer ≤ 98.8` is *necessary but not sufficient* (gameable by over-smoothing garbage), so Step 2
  MUST also validate held-out re-render PSNR (≤1.5 dB) on the smoothed/shipped normals **and** an
  anti-over-smoothing guard. Full analysis: `docs/validation-normal-quality-diagnosis-2026-07-14.md`.

## [0.11.0] — 2026-07-14
- **ground-alignment stage** (`tasks/2026-07-13-ground-alignment.md`, owner viewer feedback: assets
  render tilted because SfM has no gravity). `export` now estimates world-up from the camera rig
  (LS plane fit through camera centers via new `core/orient.py`; sign from the mean camera up-vector;
  degenerate/collinear fallback to camera-up; confidence + residual emitted) and composes that
  rotation INTO the single COLMAP→Godot conversion — still exactly ONE transform in ONE place
  (`C = M @ R_align` in `ply_io.colmap_to_godot`). New `--sparse` input, `--no-align` (byte-identical
  A/B), `--strict-align` (opt-in fail-closed on doubt).
- **env-SH sidecar rotates IDENTICALLY with the asset** — added a real degree-2 SH rotation
  (`core/sh_env.sh_rotation_matrix`/`rotate_env_sh`, built from the sampling identity, block-diagonal
  1+3+5) composed with the same `C`, so a grounded asset is never lit from the wrong side. Physical
  invariance verified to <1e-9 (rotating asset+env together leaves the relit result invariant).
  `flip_env_sh_colmap_to_godot` retained for the `--no-align` path (numerically identical to before).
- **Fail-closed hardening (from the adversarial panel):** env-SH sidecar is now loaded, rotated, and
  validated (shape/NaN/Inf/magnitude) BEFORE any write — a bad `--env-sh` can no longer clobber a
  prior good `asset.ply`. `ring_normal_dot_up` is computed through the real conversion (catches a
  C-matrix transform regression) and fail-closes on the aligned path (`< 0.98` → `SystemExit`).
  Sidecar reconciliation: a run that writes no sidecar deletes any stale `<out>_env_sh.json`, so
  `asset.ply` and its sidecar can never disagree on frame. Aligned decompose export requires `--env-sh`.
- **Suspect-alignment telemetry:** `metrics_export.alignment` now records `up_camera_disagreement_deg`,
  both candidate ups (`up_colmap` plane-normal + `mean_camera_up_colmap`), confidence, residual, and
  `alignment_suspect`; a LOUD stderr warning fires when suspect (degenerate OR confidence<0.5 OR
  disagreement>25°). **pxl_144634 flags suspect (43.5° plane-vs-camera-up split) — the physical
  "does the ground read level" call is the owner's eyeball** (seeded to DECISIONS; both cues recorded
  so it can be revisited without re-running decompose). pxl_131945 not suspect (22.0°). SCHEMA_VERSION
  unchanged (1). Suite 45→76. Validation: `docs/validation-ground-alignment-2026-07-14.md`.
- **Deferred (owner-eyeball-gated):** demo video + README gif regeneration on the grounded asset (and
  re-mirroring `godot/gs_assets`) — premature until the alignment is confirmed correct on pxl_144634.

## [0.10.0] — 2026-07-12
- **relight-orbit demo video** (`tasks/2026-07-12-relight-orbit-video.md`, owner request — the
  run finale): the M2 relighting, finally SEEN moving. New `godot/relight/tools/render_orbit.gd`
  (real-GPU, no-`--headless` orbit render) → `docs/media/relight_orbit.mp4` + `.gif`, embedded in
  the README Status section. Single take on the real phase-D decomposed `pxl_144634` asset with
  the recovered **env-SH ambient**: ~1 s RAW (baked) then a RELIT 360° light orbit — the cut
  itself shows relighting is live.
- **Orbit shape is deliberate (DECISIONS D5 in action):** the light does one 360° azimuth turn
  *while* its elevation sweeps grazing→overhead→grazing. A pure-azimuth orbit would read as
  near-static because the real decomposed foliage normals are near-isotropic (global-mean luma is
  ~azimuth-invariant); the elevation sweep is what makes the relighting visibly respond.
- **Machine gates (video beauty is the owner's eyeball call):** `RELIGHT_ORBIT_RESULT PASS`,
  180 frames, env-SH used; relit covered-luma std **0.0287** (≫ 0.003 floor; ~18% swing over the
  orbit — the data evidence that relighting responds), raw→relit spatial cut MAD **0.078** (≫ 0.02),
  no black/popping frames. ffmpeg exit 0 both; **gif 0.33 MB** (README deliverable, clears the size
  floor), **mp4 0.105 MB** — below the task's 0.2 MB floor but a valid h264 clip (compact because
  the sparse foliage sits on a static dark background; encoder not inflated, nothing re-rendered).
  Independently re-verified by a flow-verifier (gate re-run + ffprobe + regression).
- **No product change** — no PLY schema change (SCHEMA_VERSION 1), no shading/relight-pass edit, no
  vendored `addons/gdgs/` edit; the only code is the new render tool. `pytest` → 45 passed.

## [0.9.0] — 2026-07-12
- **env-SH runtime ambient (DECISIONS D4)** (`tasks/2026-07-12-env-sh-runtime.md`): the Godot
  runtime now shades with the environment light M2b `decompose` recovered instead of a flat
  constant. A new `godot/relight/relight_env_sh.gd` reads the `asset_env_sh.json` sidecar
  (`frame: godot_post_flip`, deg-2 real-SH, RGB) written next to the asset; `relight.glsl`
  evaluates `ambient_sh(N)=Σ c_lm Y_lm(N)` and the ambient term is now `albedo·ambient_sh(N)`
  (CLAUDE.md shading model). The sidecar coeffs already fold in `A_l/π` and are pre-flipped, so
  the shader applies the SH basis and **nothing else** — no coordinate re-flip, no re-`A_l/π`
  (the #1 correctness trap); the reader **refuses** any non-`godot_post_flip` sidecar.
- **Flat fallback, byte-identical.** Missing / unreadable / non-finite / wrong-frame sidecar →
  the existing flat ambient constant, logged once via `push_warning`, never crashes. A
  push-constant flag (`misc.w`) toggles env-vs-flat; the 27 floats reach the shader via a
  dedicated 144-byte std430 storage buffer at binding 4 (9×`vec4`, packed by `RelightPass.
  set_env_sh`) — the push-constant (48 B) has no room. Fallback path is byte-identical M2a.
- **Constants unit-checked.** New `precompute/tests/test_godot_env_sh_constants.py` dumps the
  SH basis constants + 9-term band order from `core/sh_env.py` (single source of truth) and
  asserts the `relight.glsl` literals match to float32 — a drifted constant or swapped band
  silently tints the ambient, so this fails closed.
- **Gates.** Headless data gate (`relight_smoke.gd`): sidecar parses to 27 finite coeffs.
  Render gate (`relight_render_gate.gd`, 3090/`DISPLAY=:0`): relit-with-sidecar ≠
  flat-fallback (**|ΔL|=0.243**, env override toggles the sidecar off) and the ambient floor
  holds with the light behind (env shadow p2=0.098 ≥ 0.01). `pytest precompute/tests` →
  **45 passed** (3 new); cactus M0 `smoke_test.gd` + `relight_smoke.gd` still PASS.
- **Directional-assertion recalibration.** The gate's env-independent "shading responds to
  light direction" check compared two too-similar OBLIQUE angles; the real decomposed asset's
  near-isotropic foliage normals (‖mean-normal‖≈0.2, CLAUDE.md "foliage normals are noisy")
  make the global-mean luminance proxy insensitive to that small arc (|Δ|≈0.004 ≤ 0.01 tol).
  Recalibrated to a **well-separated** OVERHEAD-vs-GRAZING pair where the response genuinely
  differs (|Δ|=0.056, 5.5× the 0.01 tol) — the tolerance was NOT weakened. The normal-isotropy
  itself is flagged as a decompose-normal-quality question for a DECISIONS row.
- **No schema change** — SCHEMA_VERSION stays 1 (asset schema + Godot importer untouched); no
  vendored `addons/gdgs/` edit (the relight pass is our existing one-seam insertion). Code
  confined to `godot/relight/` + one read-only `precompute/tests/` unit check.

## [0.8.0] — 2026-07-12
- **M2b Phase D — real-asset decompose validation + relightable-asset export**
  (`tasks/2026-07-11-m2-decompose.md`): completes M2b (all four phases A/B/C/D done). The
  held-out re-render **PSNR budget gate** (invariant #8, default-ON at 1.5 dB) PASSes on both
  real photogrammetry scenes — decompose reproduces the held-out views within **≤0.52 dB** of
  `train_base` on a **like-for-like full-frame** measure: **pxl_131945** 25.22→24.70 dB
  (2,075,806 Gaussians; masked diagnostic 24.71), **pxl_144634** 21.68→21.64 dB (2,405,519;
  masked 21.64). This resolves the "synthetic golden = inverse crime" open question with
  real-data evidence.
- **`export --from-decompose`** run for both assets — overwrites the M1 neutral `asset.ply` with
  the real relightable asset (real albedo/normal/roughness, COLMAP→Godot conversion once in
  export) + flipped `asset_env_sh.json` sidecar. Exported ranges in contract: albedo ⊂ [0.029,
  0.984], roughness ⊂ [0.026, 0.963], `normal_unit_err` 1.79e-07, 0 NaN/Inf, each `element
  vertex` count == its decompose N.
- **Gate/contract fixes** (found by the phase-D verification panel; both were latent defects in
  the v0.7.0 decompose stage, surfaced by real-data use):
  - *(MAJOR, correctness)* the budget comparison was **not like-for-like** — `train_base` scored
    held-out PSNR full-frame but `decompose` scored it over the foreground (alpha>τ) mask only.
    `decompose` now gates on a **full-frame** PSNR matching `train_base` exactly (`held_out_psnr`);
    the foreground value is retained as a non-gated `psnr_heldout_masked_db` diagnostic.
  - *(MAJOR, fail-closed)* a gate-**failed** `decompose.ply` used to be written *before* the gates
    (consumable by a manual `export --from-decompose`). `decompose` now writes the `.ply`/`env_sh`
    **only after every fail-closed + budget gate passes** (`finalize_decompose`); metrics (with a
    new tri-state `budget_ok`) are still written first so a failure stays inspectable.
  - *(MINOR, fail-closed)* the baseline PSNR was trusted blindly from `metrics_train_base.json`;
    `decompose` now **refuses** if that file's `n_gaussians` disagrees with the loaded
    `train_base.ply` count (`read_verified_baseline_psnr`) — the exact class of the clobber below,
    checked early before burning GPU.
  - *(MINOR, regression)* added a committed test fencing M1 **neutral-export byte-identity**.
- **Finding:** pxl_144634's `train_base.ply` had been clobbered with a degenerate 48,023-Gaussian
  (init-only) model while its metrics still claimed 2.39M — this confounded the first decompose
  (19.89 dB). Caught, corrupt file + stale metrics preserved as evidence, `train_base`
  regenerated (2,405,519, 21.68 dB), decompose re-run (the PASS above). The new baseline
  consistency check now guards this class at decompose time. Details:
  `docs/validation-m2b-phaseD-2026-07-12.md`.
- **No schema change** — SCHEMA_VERSION stays 1 (asset schema + Godot importer untouched); code
  changes are confined to `precompute/stages/decompose.py` + tests. `pytest precompute/tests` →
  **42 passed** (5 new gate/contract tests; CUDA golden MAE 0.0011); `smoke.sh` → SMOKE OK.

## [0.7.0] — 2026-07-12
- **M2b Phase C — `decompose` stage** (`tasks/2026-07-11-m2-decompose.md`): the real
  inverse-rendering solve that replaces M1's placeholder attributes. Ports GI-GS's
  two-stage decomposition (geometry/normal → PBR material/env) onto the gsplat N-channel
  G-buffer proven in phase B, with a **pure-PyTorch degree-2 SH environment light** replacing
  the excluded nvdiffrast/nvdiffrec split-sum. Recovers per-Gaussian albedo (SH deg-0,
  light-free) / normal / roughness + a scene env-SH. **No new CUDA; everything authored is
  Python/PyTorch.**
- **License:** only GI-GS's clean-MIT layer is vendored — `precompute/vendor/gigs/` = MIT
  LICENSE + NOTICE + `pbr_math.py` (8 import-free functions, extracted verbatim). The Inria
  `diff-gaussian-rasterization` fork, `nvdiffrast`, and `nvdiffrec` are NEVER copied
  (reference build stays in gitignored `scaffold/`); verified no restricted code in the tree
  or history.
- **Golden test** (`test_decompose.py`): ~50-Gaussian synthetic scene, known albedo under a
  known SH env, env DC pinned — decompose recovers albedo to **MAE 0.0010/channel** (<0.05).
  Plus a depth→normal world-frame test and 3 fail-closed/guard tests (tests 30→37). All gates
  are `-O`-safe; the held-out re-render **PSNR budget is default-ON** (invariant #8); the
  frozen-albedo guard is per-channel; export gates run **before** the write (no clobber).
- **Wiring:** `decompose` is between `train_base` and `export` in STAGE_ORDER; `export
  --from-decompose` consumes real attributes (FIELD_RANGES albedo tightened to [0,1] on that
  path) and writes a flipped env-SH sidecar, else keeps the M1 neutral path **byte-identical**.
  Schema unchanged (SCHEMA_VERSION 1). Phase D (real-asset dB budget) is the remaining phase.

## [0.6.0] — 2026-07-12
- **M2a — relight runtime in Godot** (`tasks/2026-07-12-m2-relight-runtime.md`): the visible
  half of milestone M2. Extended-PLY importer + one shading compute pass + demo scene, built
  entirely in `godot/relight/` with the vendored GDGS plugin touched at **exactly one seam**
  (a `RelightPass.run(state, point_count)` call in `gaussian_renderer.gd` between the
  projection and sort passes — writes the per-splat `culled_splats.color` the rasterizer
  consumes; early-returns with no materials so standard splats are byte-identical).
- `relight_ply_loader.gd` + `RelightGaussianResource` read `splat_relight_schema 1` (reusing
  GDGS's binary reader/builder verbatim, no double-activation) into a std430 material buffer;
  `relight.glsl` implements the CLAUDE.md shading model verbatim (direct + wrap-translucency,
  inert at trans=0 until M3, + a flat ambient floor); `single_asset.tscn` (previously missing
  → the `--import` error, now fixed) with an orbiting `DirectionalLight3D` and a raw/relit UI
  toggle. No `precompute/` changes; verifies on the existing placeholder-attribute asset.
- **Gates** (the factory can't see pixels): headless `relight_smoke.gd` (schema/ranges/NaN,
  albedo bound [0,4]) + GPU `relight_render_gate.gd` on `DISPLAY=:0` — proves relit≠raw
  (|ΔL|=0.335), light-orbit changes shading (|ΔL|=0.058), and an ambient luminance floor
  (0.027 ≥ 0.01, no black shadows). Cactus M0 gate still PASSes. Verified by a
  correctness+regression+flow panel (GPU byte-compare confirmed the OFF-path unchanged).

## [0.5.0] — 2026-07-12
- **Gaussian-budget tooling** (`tasks/2026-07-11-perf-budget.md`) toward the ≤1.5M-whole-carpet
  target. `train_base` gains `CappedDefaultStrategy` (`--max-gaussians` hard cap — stops
  densification growth + trims tail overshoot; uncapped path byte-identical to stock),
  plus `--grow-grad2d`/`--refine-stop-iter`. `export` gains a documented, metric'd
  `floater_prune_mask` (opacity / kNN-isolation / extreme-scale, all default OFF; pre/post
  counts in metrics). Both add `-O`-safe gates; an all-pruned export now fails closed
  BEFORE writing (no clobber of a prior asset). +4 prune tests (25→29 total).
- **Count-vs-PSNR sweep on `pxl_144634`** → `docs/validation-perf-budget-2026-07-12.md`
  (the data for DECISIONS D2): 200k→16.88 dB · 350k→18.91 dB (knee) · 500k→19.51 dB ·
  uncapped 2.39M→21.71 dB. opacity-0.02 prune trims ~14% of splats for ~0 dB; isolation/scale
  pruning is harmful for foliage and left off.
- **Finding:** the provisional gate ≤500k @ ≥20.7 dB is physically **unachievable** for this
  foliage (20.7 dB needs ~1.1–1.2M) — an honest outcome that feeds D2. The committed M1 asset
  is deliberately left untouched (not re-baked to a sub-gate budget); D2 sets the final budget.

## [0.4.0] — 2026-07-12
- **`precompute/smoke.sh`** — one-command end-to-end pipeline health check (owner mandate:
  "a working automatic debugging loop"). Three stages: `pytest` → 400-step
  `train_base,export` on `pxl_144634` (the hardened `-O`-safe stage gates are the pass/fail
  signal, `--min-psnr 12` floor) → Godot `smoke_test.gd` data gate on the fresh artifact.
  `set -Eeuo pipefail` + ERR/EXIT trap: on any failure exits nonzero naming the stage + last
  30 log lines; on success prints `SMOKE OK (<N>s)` (~22 s on the 3090).
- **Clean-tree by construction.** All smoke outputs route to a gitignored `.smoke/` via a new
  backward-compatible `run.py --out-root` override (default `assets/built`), so the tracked
  M1 metrics are never clobbered — required because this becomes the pre-commit `commands.build`
  gate. `git status` is byte-identical before/after every run, including the failure path.
- **Skip-friendly, but gate-safe.** Absent local asset → loud `SMOKE SKIPPED` (exit 0) for
  CI-less clones; `SMOKE_REQUIRE_ASSET=1` turns a would-be skip into a HARD FAILURE so the
  commit gate can never report green without actually running.
- `run.py` also gained `--min-psnr` passthrough and an empty-`--out-root` reject.

## [0.3.0] — 2026-07-12
Hardening pass on the M0/M1 code — 15 confirmed silent-failure/diagnostic/structure
fixes from the pre-arming review (`tasks/2026-07-12-code-hardening.md`). Tests **5 → 25**.
- **Fail-closed stages (`-O`-safe).** Every pipeline-stage metric gate is now
  `raise SystemExit`, not bare `assert` (asserts are stripped under `python -O`, which
  would silently restore "exit 0 when broken"). `train_base` asserts `n_final>0`,
  finite PSNR, `psnr>=--min-psnr` (default 15.0); `export` asserts no-NaN, unit normals,
  non-negative albedo, and `schema.validate_ranges` (now a real consumer of `FIELD_RANGES`).
- **Loud failures instead of silent-wrong.** `read_asset_ply` enforces the
  `splat_relight_schema` header (rejects foreign/version-mismatched PLYs); distorted
  (OPENCV) COLMAP models are rejected naming the `dense/sparse_txt` convention;
  `run.py` rejects unknown flags, normalizes `--asset`, and gates its raw-dir check on
  raw-reading stages only; `images.txt` parser fixed for empty-POINTS2D lines and
  filenames with spaces.
- **Faithful export.** Albedo is no longer clamped (pre-decompose base color legitimately
  exceeds 1; live max 1.823); `FIELD_RANGES` albedo bound widened to `[0,4.0]` as a
  garbage-net. M2/decompose will tighten it to `[0,1]` once albedo is true reflectance.
- **Structure + tests.** quat→R / `SH_C0` consolidated into `core/gaussmath.py`; new
  tests for the schema gate, channel-major `f_rest` ordering, colmap_io parsing, gaussmath
  round-trips, and `shortest_axis_normals`. Godot tools: env-configurable output dirs,
  `SHOT_SAVED`/exit only on verified save.
- Item 14: the false `ply_io.py` GDGS-orientation NOTE corrected to measured reality (a
  180°-about-Y net map: up-preserved, azimuth yaw-flipped — an M4 identity-vs-scatter-basis
  inconsistency, seeded as DECISIONS **D3**). decisions.md entry + CLAUDE.md `--all-assets`
  wording (item 15) are planner-lane, reconciled at the run's wrap-up.

## [0.2.0] — 2026-07-12
- **`ingest` stage** — formalized the validated COLMAP recipe (`prototype/*.sh`) into
  `precompute/stages/ingest.py` and wired it as the first stage in `run.py`'s `STAGE_ORDER`,
  so one command drives ingest→train_base→export end to end (video → frames → GPU-SIFT SfM →
  sequential match → mapper → PINHOLE undistort → TXT model). Input: `--video` + `--asset`
  (name auto-derived from the clip; clip auto-discovered under `datasets/` by anchored
  `PXL_<date>_<HHMMSS>` token, ambiguity refused).
- **Resumable + fail-closed.** Per-step completion sentinels (`.frames.done`/`.features.done`/
  `.match.done`, each written only after its step exits 0) drive resume; a `model_complete`
  short-circuit skips all SfM for model-only checkouts (needs neither the clip nor the colmap
  env — the trader batch box). A forced re-extract invalidates all frame-derived state
  (db/sparse/dense/sentinels) so it genuinely rebuilds rather than shipping a stale model.
  `metrics_ingest.json` fails the stage (nonzero, `-O`-safe) on zero registration, non-finite
  or ≥2.0 px reproj, or `dense/images ≠ registered_frames`.
- Proven on the fresh "spider's-nest" clip `pxl_131945`: **145/145 frames registered @
  0.6425 px** reproj → train_base **25.22 dB** held-out → export schema 1, end to end.

## [0.1.0] — 2026-07-11
Foundational milestones, built before the factory was set up:
- **M0** — GDGS render path in Godot 4.7 + bidirectional splat/mesh depth occlusion
  (required a GDGS↔Godot-4.7 push-constant patch; see `docs/decisions.md`).
- **M1** — precompute pipeline end to end: frames → COLMAP SfM → undistort → gsplat
  `train_base` → `export` (extended schema). Proven on `pxl_144634` foliage
  (204/204 frames registered, 2.39M gaussians, 21.71 dB held-out PSNR).
- Precompute scaffold: `schema.py` contract, `ply_io.py` (+ golden tests 5/5),
  `colmap_io.py`, `train_base.py`, `export.py`, `run.py`.
- Toolchain on the local 3090: Godot 4.7, torch/gsplat cu124, COLMAP (isolated env).
