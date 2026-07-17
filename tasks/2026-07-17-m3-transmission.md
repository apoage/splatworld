# M3 — transmission: backlit grass/leaf glow + UI toggle

**Size/risk:** M / medium (new precompute stage + re-export + runtime is already wired). **Status:**
READY — gate OPEN: M2 decompose shipped ✓, D5 normals fixed ✓, **D7 decided KEEP SIGNED** (2026-07-17)
which UN-BREAKS the `dot(−N,L)` backlit term (it was only degenerate under the rejected sign-agnostic
modes). Milestone M3 per CLAUDE.md.

**Lane:** `precompute/` (a `transmission` stage + export) + `godot/` only if the A/B below picks it.

## What already exists (do NOT rebuild)
- Runtime backlit term is ALREADY in `relight.glsl`: `back = trans * pow(max(dot(-N,L),0)*0.5+0.5,
  wrap_power)`, gated by the `trans_on` push-constant, wired to the viewer's "Transmission" toggle —
  currently INERT because every shipped splat has `trans = 0` (placeholder). M3 makes `trans` nonzero.
- The `label` field exists (export sets it; heroes are uniformly label=2/leaf today).
- The schema already has `trans` (per-Gaussian f32). NO schema change.

## Approach
1. **`precompute/stages/transmission.py`** — assign per-Gaussian `trans` for grass/leaf labels.
   **v1 = CONSTANT PER LABEL** (CLAUDE.md explicitly accepts this; thin-leaf per-splat translucency
   is the known-hard case, do NOT block on it): e.g. leaf/grass → `trans≈0.5`, bark/ground → 0.
   Writes `metrics_transmission.json` (per-label counts + trans range/NaN). Resumable stage.
   - Stretch (only if cheap): backlit-view brightness-residual estimate per CLAUDE.md stage 5 — but
     v1 constant is the acceptance bar; keep the residual path behind a flag.
2. **Export**: carry `trans` through `export.py` from the transmission stage (a `--from-transmission`
   or fold into the decompose export path). Re-export + re-mirror the heroes with nonzero leaf trans.
3. **DESIGN FORK — A/B the backlit formula (do NOT pre-decide; owner eyeball picks, like D7):**
   - **(a) shipped `dot(−N,L)` wrap** — matches CLAUDE.md + the signed direct lobe; BUT inherits the
     ~30% wrong-sign noise (a back-lit wrong-sign leaf glows on the wrong side). Owner accepts sign
     noise as property, but backlight makes it more visible.
   - **(b) Frostbite view–light PHASE form** `pow(saturate(dot(V, −(L+d·N))), p)` (D7 research,
     `docs/d7-synthesis-2026-07-17.md`) — sign-robust (view-driven), so the glow does NOT inherit the
     sign noise; thickness-gated to avoid glowing bark. Add as a second `trans_mode` (binding-5 meta.w,
     free) so the viewer `N`-style toggles between (a)/(b) for the owner A/B. Mode (a) stays default /
     byte-identical when selected.
4. Perf: transmission adds one more per-splat term; measure on/off @ 2.4M (expect ~free, like the
   flashlight). The fireball money-shot (Moon-Stone) needs this + point lights (flashlight shipped).

## Validation / gates
- `metrics_transmission.json`: per-label trans assignment, range [0,1], no NaN; a metric that fails if
  the stage mis-assigns (e.g. bark trans > 0).
- Re-export gate: heroes get nonzero leaf trans; existing golden + PSNR-budget + sign gates hold.
- `render_matrix` / a new backlit render check: with the sun BEHIND the asset (az≈180 from camera),
  relit+trans shows leaf glow that relit-alone does not; raw invariance still holds; frame-time on/off
  recorded.
- **Owner eyeball is the acceptance gate** (viewer: 5=backlit pose + Transmission toggle): does backlit
  grass/leaf glow read right, and which A/B formula (a vs b) wins.

## Notes
- External contributor lane: `tasks/2026-07-12-jax-transmission.md` (friend's JAX transmission) covers
  the SAME stage. If that contribution has landed, planner re-decides who owns this; otherwise the
  factory builds our torch/numpy version above (phase-1 JAX was gated on M2b, now unblocked too).
- M3 is the last runtime piece before the Moon-Stone demo stack is complete (relight ✓, env-SH ✓,
  point-light/flashlight ✓, transmission = here).
