# QUEUE — the ranked dark-factory work order

The factory's single entry point (planner-maintained). STATUS banners on task files remain the
truth for what's done; this file only orders what's OPEN. The factory takes from the top, skips
gated rows (noting why), and treats FILLER rows as parallel/anytime slices. Rows under
**Parked — owner-gated** are NOT factory work: never take them. Last groomed:
**2026-07-12** (next-run prep: owner go-ahead for M2 GIVEN; M2 split into M2a runtime +
M2b decompose — independent lanes, each shippable alone; docs-guide filler seeded).

## Ready — take from the top

| # | Task | Size | Note |
|---|------|------|------|
| 1 | `tasks/2026-07-12-m2-relight-runtime.md` | M | **M2a** — extended-PLY importer + relight compute pass + orbiting light in Godot. Independent of decompose: verifies on the EXISTING placeholder-attribute asset. Lane: `godot/`. Also fixes the broken `single_asset.tscn` |
| 2 | `tasks/2026-07-11-m2-decompose.md` | L | **M2b** — GI-GS hybrid vendor+port onto gsplat (D1 DECIDED, go-ahead given). Phased A→D, each independently shippable; phase-A build-verify stall is a finding, not a run-sink. License guardrails are HARD rules (`scaffold/` gitignored). Lane: `precompute/` |

**Shipped in the 2026-07-12 factory run (banners on task files):** ingest-stage (v0.2.0),
code-hardening (v0.3.0), smoke-loop (v0.4.0), perf-budget (v0.5.0). See `docs/2026-07-12-handoff.md`.

## Filler — anytime, parallel-safe

- `tasks/recurring-quality-pass.md` — **recurring** code-quality / structure / doc-drift sweep
  (owner mandate 2026-07-12). One bounded pass per pickup; banner with date; never "done".
  First seeded slice: the broken `res://scenes/single_asset.tscn` red ERROR during
  `godot --import` (flagged in the smoke-loop banner).
- `tasks/2026-07-12-docs-guide.md` — `docs/pipeline.md` walkthrough (clip → asset → Godot)
  + core docstrings + README "Docs" section. Acceptance: a fresh reader reproduces M1 from
  the guide alone.

## Parked — owner-gated (NOT factory work; the owner/planner executes these)

- **data-release**: attach `datasets/pixel4/PXL_20260711_144634633.LS.mp4` (~37 MB) as a
  GitHub Release asset + a README "Data" note, so M1 is reproducible. Deferred by owner;
  requires a remote write (`gh release`), which the factory's `allow_push: false` guard
  forbids by design. Data excluded from git for SIZE only (footage is the owner's; cactus
  samples are CC0).

## Gated — do NOT start (named gate must open first)

| Task | Gate |
|------|------|
| M3 — transmission (backlit grass/leaf glow + UI toggle) | M2 `decompose` shipped |
| M4 — carpet (instanced blocks, 5–15 variants, hit 60fps@1080p) | M2 shipped + asset variants ready |
| M5 — wind (shared noise field) + mode-B basis blend (stretch) | M4 shipped |

## Grooming rules
Planner re-ranks after each factory run + banners; a row leaves this file only by shipping
(banner) or being explicitly parked. If the factory finds the top row blocked in practice, it
takes the next and records why in its wrap-up. M3–M5 get their own `tasks/<date>-*.md` specs
when their gate opens.
