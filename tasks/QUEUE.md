# QUEUE — the ranked dark-factory work order

The factory's single entry point (planner-maintained). STATUS banners on task files remain the
truth for what's done; this file only orders what's OPEN. The factory takes from the top, skips
gated rows (noting why), and treats FILLER rows as parallel/anytime slices. Rows under
**Parked — owner-gated** are NOT factory work: never take them. Last groomed:
**2026-07-12** (pre-arming review: specs hardened, code-review findings seeded, quality
filler added per owner mandate).

## Ready — take from the top

| # | Task | Size | Note |
|---|------|------|------|
| 1 | `tasks/2026-07-11-ingest-stage.md` | S–M | formalize the validated COLMAP recipe (`prototype/*.sh` = recipe of record) into `stages/ingest.py`; input interface + acceptance clip now specified |
| 2 | `tasks/2026-07-12-code-hardening.md` | M | fix the confirmed 2026-07-12 review findings: silent-failure traps (train_base asserts nothing, schema version unchecked, OPENCV silently accepted), diagnostics, structure, contract tests |
| 3 | `tasks/2026-07-11-perf-budget.md` | M | cut per-asset Gaussian count toward the runtime budget (provisional gates: ≤ 500k @ ≥ 20.7 dB); tradeoff table feeds DECISIONS **D2** |

## Filler — anytime, parallel-safe

- `tasks/recurring-quality-pass.md` — **recurring** code-quality / structure / doc-drift sweep
  (owner mandate 2026-07-12). One bounded pass per pickup; banner with date; never "done".

## Parked — owner-gated (NOT factory work; the owner/planner executes these)

- **data-release**: attach `datasets/pixel4/PXL_20260711_144634633.LS.mp4` (~37 MB) as a
  GitHub Release asset + a README "Data" note, so M1 is reproducible. Deferred by owner;
  requires a remote write (`gh release`), which the factory's `allow_push: false` guard
  forbids by design. Data excluded from git for SIZE only (footage is the owner's; cactus
  samples are CC0).

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
