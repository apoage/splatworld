# synthetic-plant-gt — Blender L-system plant → render → known per-face sign ground truth

**Size/risk:** M–L / medium (new offline capability; blender-mcp driven). **Status:** SCOPED —
owner idea 2026-07-17 ("synthetic splats like L-system in Blender, render it; blender-mcp is
installed"). NOT started — confirm approach with owner before a Blender session (rabbit-hole
risk). **Owner/planner track, not the dark-factory** (interactive Blender + research judgement).

## Why (two payoffs, one artifact)
1. **The research substrate the sign-recovery track needs.** D7's offline photometric
   sign-recovery (`prototype/open-problem-global-normal-sign.md`, M-0/M-C) is unfalsifiable on
   real assets — no oriented-vegetation benchmark exists (round-2 research, all 4 reports). The
   only honest validation is SYNTHETIC: an authored plant that CARRIES known per-face
   orientation → render multi-view under a known sun → reconstruct with OUR pipeline → transfer
   GT sign to each splat by nearest-source-face. Then M-0 (reflectance-contrast histogram) and
   M-C (the estimator) can be scored against truth.
2. **Stage-2 sandbox geometry.** The controlled known-orientation scene from the sandbox design
   (sign_sandbox) wants exactly this: a plant with known front/back per leaf face.

## Approach (blender-mcp)
1. **Generate** an L-system / procedural plant in Blender (splat-friendly: many quasi-planar
   leaf faces; two-sided leaves with DISTINCT adaxial/abaxial materials — waxy-dark top vs
   pale-matte bottom — so the reflectance-asymmetry cue (round-2 correction: reflectance, NOT
   transmission, carries the sign) actually exists in the render). Start ONE plant, simple.
2. **Render** a multi-view orbit (+ some below-horizon views so faces are seen from both sides —
   coverage is the binding constraint for the estimator's Tier-A/B) under a KNOWN directional
   sun + simple env. Export per-view camera poses + the sun direction.
3. **Carry GT**: export the mesh with per-face adaxial/abaxial labels so nearest-splat transfer
   after reconstruction yields per-splat true sign.
4. **Run our pipeline** on the rendered views (ingest→train_base→decompose→export) to get a
   `.relightply` whose splats can be scored against the mesh GT.
5. **Deliverables**: a reusable synthetic asset + its GT sign fixture; feeds M-0 (does the
   reflectance-contrast histogram separate?) and M-D (A/B resolved-sign vs sign-agnostic).

## Open questions to confirm with owner before starting
- Which L-system / addon (Sapling/tree-gen, or a custom geometry-nodes plant)? Simplest that
  gives two-sided leaves with per-face materials.
- Photorealism bar: the cue only needs the adaxial/abaxial reflectance DIFFERENCE to be
  present + a known sun; not a beauty render.
- Scope guard: ONE plant, one lighting condition first (M-0 de-risk), before any fleet.

## Acceptance (v1)
- One synthetic plant rendered multi-view with exported poses + sun + per-face GT labels.
- Reconstructed to a `.relightply` via our pipeline; per-splat GT sign transferred.
- M-0 histogram run on it: reflectance-contrast separation present (cue real) or not (stop).
- Everything under a gitignored scratch/synthetic dir until an owner keep decision (renders are
  large). Note in the validation doc.
