# recurring — quality & structure pass (filler; re-enterable, never "done")

**Size/risk:** S per pass / low. **Status:** RECURRING FILLER — take a pass when the top of
the queue is blocked or as a parallel slice. Banner each pass with its date + what was swept
(prepend, keep history); this file is never marked SHIPPED.

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
