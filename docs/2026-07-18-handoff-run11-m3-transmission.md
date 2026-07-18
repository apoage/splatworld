# Handoff — dark-factory run #11: MILESTONE M3 transmission (code) — v0.20.0 (2026-07-18)

Previous: `docs/2026-07-16-handoff-7-run7.md` (+ later runs #8–#10 recorded in CHANGELOG /
task banners). Chain focus this run: **shipped the M3 transmission code deliverable**; the
milestone's acceptance (hero re-export + owner a-vs-b eyeball) is the remaining owner-gated step.

- **Branch:** main · **Working dir:** /home/lukas/splatworld · **Tag:** `v0.20.0`
- **Task:** `tasks/2026-07-17-m3-transmission.md` (banner added)
- **Guard rail:** armed → all work behind lane/commit/stop hooks; nothing pushed (`allow_push:false`).

## Shipped

| Version | Item | Verification |
|---|---|---|
| v0.20.0 | M3 transmission (code): constant-per-label `trans` stage + runtime backlit A/B | Panel green (correctness + regression + flow-verifier + fix-reverify); suite **120 passed** (118 prior + 2 new); real-data CPU run on pxl_144634 (2.4M) |

### What landed
**precompute**
- `precompute/stages/transmission.py` (new) — v1 CONSTANT-PER-LABEL trans (CLAUDE.md stage 5
  explicitly accepts this; the thin-leaf backlit-residual per-splat estimate is a deliberately
  deferred stretch). leaf(2)/grass(1) → `--trans-leaf`/`--trans-grass` (default 0.5);
  bark(3)/ground(0) and any out-of-schema label stay exactly 0. Operates on the built
  `asset.ply` post-export (trans is scalar → no coordinate conversion → frame-safe); PLY bytes
  only via `core.ply_io`. No schema change (`trans` already in schema).
- `metrics_transmission.json` with a **non-vacuous** fail-if-broken metric (invariant #7): a
  POSITIVE landed-assignment gate — each requested constant > 0 with ≥1 Gaussian of that label
  must land (`trans_min == trans_max == expected`, exact f32). This is the guard that fires on
  real (today uniformly-leaf) pipeline data, where the bark/ground==0 check is vacuous by
  construction. Plus total-consistency accounting (`n_other_label`, `counts_consistent`). All
  gates fail-closed (`raise SystemExit`) pre-write → a broken run never clobbers a good asset.
- `run.py` — `transmission` wired into `STAGE_ORDER` **after** `export`; flag passthrough.

**godot runtime backlit A/B**
- `relight.glsl` — backlit term factored into `back_lobe(N,L,V,trans,wrap_power,trans_mode)`,
  used at BOTH the sun and flashlight-loop sites. `trans_mode` on binding-5 `meta.w` (was free;
  push constant untouched): **mode 0 TRANS_WRAP** = shipped `trans*pow(max(dot(−N,L),0)*0.5+0.5,
  wrap_power)`, **byte-identical** default; **mode 1 TRANS_PHASE** = Frostbite view–light phase
  `trans*pow(clamp(dot(V,−normalize(L+0.3·N)),0,1),wrap_power)` (sign-robust, view-driven — does
  NOT inherit the D7 ~30% wrong-sign noise).
- `relight_pass.gd` — `set_trans_mode(int)` writes `meta.w` (offset 12). GDGS untouched.
- `tools/orbit_viewer.gd` — key **T** cycles the formula (+ "trans lobe" dropdown); default mode 0.

## Verification detail
- 3-member medium panel (correctness / regression / flow-verifier) on the core: no BLOCKER/MAJOR.
  Confirmed shader mode-0 byte-identity line-by-line at both sites; `meta.w` offset correct, no
  collision; flashlight loop still passes local `Lf`; smoke.sh uses `--stages train_base,export`
  so transmission never runs in the commit gate; clobber-safety proven (bad flag → nonzero, md5
  unchanged); pure idempotent trans mutation.
- All three independently flagged ONE real MINOR: the fail-if-broken metric was vacuous on real
  all-leaf data. **Fixed** (landed-assignment gate + negative-proof test
  `test_landed_assignment_gate_fires_on_broken_mask`). Orchestrator directly checked the subtle
  f32-vs-python-float exactness risk: `expected = float(np.float32(val))` matches the stored
  float32, so `--trans-leaf 0.3`-style values do NOT falsely fire.
- Real-data CPU validation (non-destructive, to scratchpad): pxl_144634 2.4M Gaussians, all leaf
  → trans=0.5, `assigned_ok:true`, `counts_consistent:true`, `n_other_label:0`, no NaN.

## Remainders (NOT shipped — owner-gated / GPU-scheduled real-data tier)
1. **Hero re-export + re-mirror.** The in-place overwrite of `assets/built/<name>/asset.ply` was
   classifier-blocked (mutates real built data the owner may want to control), so it is deferred
   to the owner. `.relightply` is a byte copy of `asset.ply`. Commands:
   ```
   for A in pxl_144634 pxl_131945; do
     conda run -n splat-relight python -m precompute.stages.transmission \
       --in assets/built/$A/asset.ply --out assets/built/$A/asset.ply --trans-leaf 0.5 --trans-grass 0.5
     cp assets/built/$A/asset.ply godot/gs_assets/$A.relightply
   done
   ```
   (Baked trans=0.5 still shows trans-OFF via the runtime `trans_on` toggle, so a re-exported hero
   supports the full A/B without a second asset.)
2. **Owner a-vs-b eyeball — THE acceptance gate.** Viewer: pose **5** (backlit) + Transmission
   toggle ON + press **T** to switch (a) wrap ↔ (b) phase. Does backlit grass/leaf glow read
   right; which formula wins? `wrap_power` is live-tunable (`,`/`.`) and `TRANS_DISTORT=0.3` is a
   shader constant if the phase lobe needs tuning.
3. **GPU backlit render check** (sun az≈180 from camera): relit+trans shows leaf glow that
   relit-alone does not; raw invariance holds; frame-time on/off recorded. Needs `DISPLAY=:0`.
4. **Demo/gif regen showing M3 glow** — sequence AFTER the owner picks a/b (the queue's
   "demo/gif regen" row). Watch the Moon-Stone fireball money-shot: under backlight the D7 ~30%
   wrong-sign splats will mis-glow with formula (a); (b) avoids it — a real input to the a/b call.

## Watch-outs / drift for the planner
- **`--stages all` now appends transmission** → an end-to-end rebuild produces transmissive
  (leaf trans=0.5) assets; `metrics_export.json` (trans=0) is superseded by
  `metrics_transmission.json` afterward. Intended M3 direction; noted so it isn't a surprise in
  the pixel5-variants overnight build.
- **Per-label selectivity is inert until a real `label` stage lands.** export.py assigns every
  Gaussian `label=2` (leaf), so on real assets the whole thing becomes trans=0.5 — fine for the
  all-foliage clips, but ground/bark won't be distinguished until labeling exists.
- **Uncommitted planner file left in the tree:** `lore/handoff_2026-07-17_d7-signed-sandbox-
  synthetic.md` (planner lane — the factory did not touch or commit it; it was already untracked
  at session start). Left for the planner to commit.
- **JAX contributor lane** (`tasks/2026-07-12-jax-transmission.md`) had NOT landed (no branch, no
  file), so the factory built the torch/numpy version per the M3 task's fallback clause. If the
  JAX PR arrives later, the planner re-decides ownership; the file contract matches
  (`metrics_transmission.json`, ply_io-only, no schema change).

## Where it stands
M3 code complete and tagged. The Moon-Stone demo runtime stack is now feature-complete in code
(relight ✓, env-SH ✓, point-light/flashlight ✓, transmission ✓). The next real progress needs the
owner's a-vs-b eyeball (remainder #2), which then unblocks the demo regen.
