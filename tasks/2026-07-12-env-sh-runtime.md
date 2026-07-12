# env-SH runtime — read the recovered environment light in the Godot ambient term

**Size/risk:** S–M / low-medium (coordinated exporter+importer step; NO schema change).
**Status:** GATED on DECISIONS **D4** + M2b phase D shipped (real assets produce the first
meaningful `env_sh.json`). Do not start before both.

**Lane:** `godot/` primarily; `precompute/` only if the sidecar format needs a tweak
(then exporter+reader change in the SAME commit).

## Problem
M2b decompose recovers a deg-2 SH environment light and `export` writes it as a
COLMAP→Godot-flipped `env_sh.json` sidecar — but the M2a runtime still shades with a flat
ambient constant. The recovered lighting is computed and then ignored.

## Approach
1. Godot-side reader for `env_sh.json` (next to the asset; missing sidecar → fall back to
   the flat constant, loudly logged once). SH basis/order/normalization constants must match
   `precompute/core/sh_env.py` — that module is the single source of truth; mirror its
   constants into the GDScript/GLSL with a comment pointing back at it.
2. Replace the flat `ambient` in the relight compute pass with `albedo * ambient_sh(N)`
   (CLAUDE.md shading model, verbatim — the formula already names it).
3. Gates: headless data gate asserts the sidecar parses and coefficients are finite;
   render gate (3090) asserts relit-with-sidecar ≠ relit-with-flat-fallback (checksum) and
   the ambient floor still holds (min luminance > 0 with light behind).

## Acceptance
- Real decomposed asset (phase D output) renders with its recovered ambient; toggling the
  sidecar off (env override) visibly changes the render (checksum proof).
- Missing-sidecar fallback keeps every existing M2a gate green (no regression on
  placeholder assets or the cactus M0 path).
- Constants provably shared: a comment-locked copy is acceptable, but a unit check (dump
  constants from `sh_env.py`, compare against the GDScript values in the data gate) is better.
