# recurring — quality & structure pass (filler; re-enterable, never "done")

**Size/risk:** S per pass / low. **Status:** RECURRING FILLER — take a pass when the top of
the queue is blocked or as a parallel slice. Banner each pass with its date + what was swept
(prepend, keep history); this file is never marked SHIPPED.

> **PASS 2026-07-17 (run #10): slice-4 — GDGS −180°Z neutralization in the demo/gif render tools
> (SHIPPED v0.19.1).** Added `gs.transform = Transform3D.IDENTITY` after `add_child` in
> `render_orbit.gd` + `render_sparkle.gd`, mirroring the proven `render_matrix.gd:210` pattern.
> Deliberately LEFT untouched: `render_probe.gd` (vanilla cactus ply — needs the correction),
> `relight_render_gate.gd` (aggregate-luma gate, orientation-invariant, green), `render_foliage.gd`.
> render_matrix + relight_controller already had the fix. Verified on real GPU (flow-verifier):
> both tools exit 0 + non-empty frames on pxl_144634, render_orbit gate PASS, render_matrix
> regression green, pytest 114. **Resolves the slice-4 blocker → slice-5 demo/gif regen is now
> code-unblocked** (still needs a real-GPU render run + owner eyeball for right-side-up — slice 5
> remains owner-gated; I cannot see pixels). Note: the sign-gate's `does-not-rebuild-the-buffer`
> comment about post-add_child IDENTITY is context-specific to its ±Z-invariant synthetic geometry —
> render_matrix's `sphere_consistency` gate empirically proves the pattern works on the real
> scene-render path, so no D3 contradiction.

> **PASS 2026-07-15 (run #6): slice-5 D5 rollout — pxl_131945 (the 2nd hero asset).** Re-decomposed
> `pxl_131945` with `--smooth-normals-iters 2 --smooth-normals-knn 8` (scratch-first → passed the
> fail-closed held-out-PSNR gate → promoted to `assets/built/pxl_131945/` + mirrored byte-identical
> to `godot/gs_assets/pxl_131945.relightply`; originals kept as `*_unsmoothed.*.bak`). Metrics:
> held-out PSNR **24.202 dB** (budget_ok, 0.48 dB headroom vs the 23.72 floor), coherence
> **0.576→0.925** (over_smooth_suspect false), unit normals, no NaN; smoothing cost 0.50 dB (7.5×
> pxl_144634's — albedo/rough BYTE-IDENTICAL, so normals-only). Verified flow-verifier + correctness
> (no BLOCKER/MAJOR; MINOR advisory: **owner eyeball recommended** on a relit render given the thin
> headroom — trivially reversible via the `.bak` + `git checkout` of the 4 JSONs). **REMAINING
> slice-5 work:** regen the demo video + README gif (still gated on slice-4 = GDGS −180°Z
> neutralization in the demo/gif render tools). Detail: `docs/2026-07-15-handoff-6-run6.md`.

## Purpose (owner mandate, 2026-07-12)
Keep space in the factory for **code quality reviews and keeping the project well structured**
— continuously, not as one-off cleanups.

## One pass = ONE bounded sweep (pick a lens, timebox it, banner it)
1. **Doc-drift sweep** — do CLAUDE.md (root + subtree) Commands/paths/claims still match the
   code? Dead pointers (files referenced that don't exist)? Stale "next"/status lines?
   Fix small drift directly (code-lane files); seed a DECISIONS row if a doc contradiction
   needs an owner call.
2. **Test-coverage nibble** — pick ONE untested core function, add a known-answer test.
   Priority order: whatever the current milestone touches next.
3. **Structure sweep** — duplication (shared math/constants living in two places), dead code,
   misplaced modules vs the CLAUDE.md layout. Consolidate one item, don't reorganize the world.
4. **Invariant audit** — grep the invariants in `.dark-factory/config.json` against reality
   (e.g. "every stage asserts a metric that fails if it broke" — do new stages comply?).
   Violations found = new READY task seeded (or fixed inline if S-sized).
5. **Metrics hygiene** — do all `metrics_*.json` parse as strict JSON, no NaN/Inf, ranges sane?

## Rules
- A pass touches EITHER code lanes (factory) or is documented for the planner (DECISIONS row /
  handoff doc) — never guess past a wall.
- Small and shippable: one pass = one commit behind a green verdict, same ritual as any task.
- Findings too big for the pass become new `tasks/<date>-*.md` seeds noted in the banner —
  the planner ranks them at the next grooming.
