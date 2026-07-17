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
Modes (HUD shows the active one):
- **0 signed** (current shipped behavior — default, byte-identical output when 0)
- **1 two-lobe abs**: `direct = abs(dot(N, L))` — sign-agnostic; the physically-sane model
  for thin scatterers (two-sided foliage lighting).
- **2 flip-toward-camera**: `N' = (dot(N, V) < 0) ? -N : N` with `V` = splat→camera dir, then
  the normal signed shading — the standard trick in published relightable-3DGS systems (a
  splat is only ever visible from one side). Needs camera world pos in the pass — add it to
  the binding-5 light UBO (there is headroom; do NOT touch the push constant).
- **3 (stretch, only if a spare material channel exists — do NOT extend the buffer for the
  prototype)**: confidence blend of 0↔1 (e.g. by ‖pre-normalization smoothed-normal length‖
  or covariance anisotropy if already available).
Wrap/backlit note: trans is still 0 (pre-M3), so the `back` term is inert in all modes —
do not redesign it here; just note in the validation doc how each mode would interact with a
future two-lobe transmission split (feeds the M3 spec).

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
