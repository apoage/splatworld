> **STATUS (2026-07-17): SHIPPED as v0.19.0** (factory run #10). `sign_mode` toggle (0 signed /
> 1 wrap / 2 flip) in the relight pass + viewer key `N` + HUD; **mode 3 (confidence-blend)
> SKIPPED** — per-splat scales aren't in a bound buffer and the Gate forbids extending the
> material buffer for a prototype. Mode 0 byte-identical to v0.18.0 (measured). Analytic sign
> gate (fault-injection-proven per mode) + per-mode perf probe (~free: 7.95/7.76/7.75 ms @
> 2.4M/1080p). Panel green (correctness + regression + flow-verifier on the real 3090); suite
> 114. **EYEBALL DONE 2026-07-17 → D7 DECIDED = KEEP SIGNED (mode 0).** Owner A/B on pxl_144634
> sun-only: signed best (strong shadow force + self-cast clustering, still noisy); wrap too weak;
> flip-to-cam noisier. This OVERRIDES the 4-report sign-agnostic consensus (empirical arbiter).
> Closeup salt-and-pepper accepted as a property. The sign modes remain diagnostic tools, not the
> default. See DECISIONS D7 (DECIDED). Follow-on: sandbox to study closeup noise + isolate
> front/back (owner ask, planner building).

# sign-agnostic-prototype — D7 shading experiment behind a viewer toggle (owner A/B decides D7)

**Size/risk:** S–M / low-medium (runtime-only, additive, default OFF — the shipped signed
path stays byte-identical when the toggle is off; raw invariance must hold in every mode).
**Status:** READY (owner 2026-07-17: "prototype it in factory"). **This task does NOT decide
D7** — it produces the eyeball evidence; D7 stays OPEN until the owner's verdict.

**Lane:** `godot/relight/` (shader + pass + viewer). No decompose changes, no asset changes.

## Context
Three camera-based sign resolvers all hit a balance-invariant ~30% opposition floor on real
foliage (D7 row; v0.16.0 + v0.18.0 evidence) — grazing foliage normals carry no
camera-recoverable sign. The D7 candidates that make sign NOT matter are runtime-only and
cheap to A/B. Prototype them behind a mode switch so the owner can flip between them live on
the real asset in sun-only diagnostic mode (where the patch shadows are obvious).

## Approach — a `sign_mode` uniform (int) in the relight pass + viewer key `N` cycling it
**READ FIRST: `docs/d7-synthesis-2026-07-17.md`** — 4-report research consensus (2026-07-17);
the mode formulas below are updated to match it. Modes (HUD shows the active one):
- **0 signed** (current shipped behavior — default, byte-identical output when 0)
- **1 sign-free WRAP** (the consensus two-sided lobe — NOT plain abs, which reads flat, and
  NOT half-Lambert on signed N·L, which is NOT sign-agnostic):
  `direct = saturate((abs(dot(N,L)) + w) / (1+w)) / (1+w)` with `w ≈ 0.4` (a uniform;
  tweakable via the existing `,`/`.` wrap keys while in mode 1 is a nice-to-have).
- **2 flip-toward-camera**: `N' = N * sign(dot(N, V))` with `V` = splat→camera dir, then the
  normal signed shading — the published-3DGS convention (GaussianShader/GIR/2DGS). Needs
  camera world pos in the pass — add it to the binding-5 light UBO (headroom exists; do NOT
  touch the push constant). Watch for grazing-angle flicker during camera orbit (known
  failure mode — worth demonstrating to the owner).
- **3 (stretch, only if derivable without extending buffers)**: confidence blend of 2↔1 —
  `mix(mode1, mode2_front_lobe, conf)` with `conf` = a covariance-anisotropy planarity proxy
  (e.g. `1 − s_min/s_mid` — GDGS holds per-splat scales; if the pass can't reach them
  cheaply, SKIP mode 3, do not extend the material buffer for a prototype).
Wrap/backlit note: trans is still 0 (pre-M3), so the `back` term is inert in all modes — do
not redesign it here. The M3 replacement term is already decided by the research (Frostbite
phase form, synthesis §3) — note per-mode interactions in the validation doc only.

## Gates
- Mode 0 output byte-identical to v0.18.0 (regression); raw mode invariant to `sign_mode`.
- Analytic render-gate: one closed-form check per new mode (a splat with known N/L/V) — the
  run-#7/#8/#9 lesson: prove each formula with a fault-injection (break the abs/flip, gate
  must fail).
- Suite + smoke green; frame-time per mode recorded (expected ~free).

## Acceptance
- Viewer `N` cycles modes live with HUD label; owner A/B in sun-only mode D on both heroes:
  the deliverable is the owner's verdict per mode (do the patch shadows die? does anything
  else degrade — e.g. ground/bark shading direction, silhouette pop during camera orbit in
  mode 2?).
- Short findings note in the validation doc (incl. the M3 two-lobe implication per mode) —
  this becomes the D7 decision evidence.
