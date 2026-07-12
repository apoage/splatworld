# QUEUE — the ranked dark-factory work order

The factory's single entry point (planner-maintained). STATUS banners on task files remain the
truth for what's done; this file only orders what's OPEN. The factory takes from the top, skips
gated rows (noting why), and treats FILLER rows as parallel/anytime slices. Rows under
**Parked — owner-gated** are NOT factory work: never take them. Last groomed:
**2026-07-12** (post-run: ingest/code-hardening/smoke-loop/perf-budget SHIPPED v0.2.0→v0.5.0;
only M2 remains, held for owner go-ahead; D2 now data-backed, D3 seeded).

## Ready — take from the top

| # | Task | Size | Note |
|---|------|------|------|
| 1 | `tasks/2026-07-11-m2-decompose.md` | L | **M2** — GI-GS hybrid vendor+port (D1 DECIDED). ⚠️ Milestone-scale/high-risk: touches the schema contract + relight thesis, front-loads a risky external CUDA build-verify (GI-GS on sm_86/cu124). The 2026-07-12 run STOPPED here by design — wants its own (ideally attended) session + owner confirmation of vendoring scope. Step 1 = private reference build-verify; license exclusions in the task Notes are hard rules |

**Shipped in the 2026-07-12 factory run (banners on task files):** ingest-stage (v0.2.0),
code-hardening (v0.3.0), smoke-loop (v0.4.0), perf-budget (v0.5.0). See `docs/2026-07-12-handoff.md`.

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
| M3 — transmission (backlit grass/leaf glow + UI toggle) | M2 `decompose` shipped |
| M4 — carpet (instanced blocks, 5–15 variants, hit 60fps@1080p) | M2 shipped + asset variants ready |
| M5 — wind (shared noise field) + mode-B basis blend (stretch) | M4 shipped |

## Grooming rules
Planner re-ranks after each factory run + banners; a row leaves this file only by shipping
(banner) or being explicitly parked. If the factory finds the top row blocked in practice, it
takes the next and records why in its wrap-up. M3–M5 get their own `tasks/<date>-*.md` specs
when their gate opens.
