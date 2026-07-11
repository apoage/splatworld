# QUEUE — the ranked dark-factory work order

The factory's single entry point (planner-maintained). STATUS banners on task files remain the
truth for what's done; this file only orders what's OPEN. The factory takes from the top, skips
gated rows (noting why), and treats FILLER rows as parallel/anytime slices. Last groomed:
**2026-07-11** (orchestrator setup; M0 + M1 shipped).

## Ready — take from the top

| # | Task | Size | Note |
|---|------|------|------|
| 1 | `tasks/2026-07-11-ingest-stage.md` | S–M | formalize the validated COLMAP recipe into `stages/ingest.py` so `run.py` covers ingest→train_base→export end to end |
| 2 | `tasks/2026-07-11-perf-budget.md` | M | cut per-asset Gaussian count toward the runtime budget — M1 asset is 2.39M vs the ≤1.5M-for-the-whole-carpet target (densify tuning + export floater prune) |

## Filler — anytime, parallel-safe

- (none yet — seed XS–S hygiene slices as they appear)

## Gated — do NOT start (named gate must open first)

| Task | Gate |
|------|------|
| `tasks/2026-07-11-m2-decompose.md` | DECISIONS **D1** (which inverse-rendering impl to vendor) |
| M3 — transmission (backlit grass/leaf glow + UI toggle) | M2 `decompose` shipped |
| M4 — carpet (instanced blocks, 5–15 variants, hit 60fps@1080p) | M2 shipped + asset variants ready |
| M5 — wind (shared noise field) + mode-B basis blend (stretch) | M4 shipped |

## Grooming rules
Planner re-ranks after each factory run + banners; a row leaves this file only by shipping
(banner) or being explicitly parked. If the factory finds the top row blocked in practice, it
takes the next and records why in its wrap-up. M3–M5 get their own `tasks/<date>-*.md` specs
when their gate opens.
