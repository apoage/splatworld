# Handoff — Splat Studio v0.25.0 (GLM worker) + dark-factory multiline design/scaffold (2026-07-19)

Previous: `lore/handoff_2026-07-18_d8-readme-run13-arm.md`
(chain: … #10 cactus-gdgs-m4design → #11 d8-readme-run13-arm → **#12 this**)

- **Branch:** main · **Working dir:** /home/lukas/splatworld
- **Session focus:** reconciled run #14 (3a `carpet_perf` harness v0.24.0) → executed **task 3b** perf
  (v0.24.1 resolution hotfix; verified **277 fps @ 1.45M/1080p, 4.6×** — M4 perf risk RESOLVED) →
  finalized the **first alt-model factory run**: **Splat Studio 4a v0.25.0, GLM-5.2-implemented +
  Claude-verified** (GLM worker died on a provider cap mid-ritual → planner reconcile) → that death
  motivated designing **dark-factory multiline** (DECISIONS **D10** + `docs/2026-07-19-dark-factory-
  multiline-design.md`) and **scaffolding a separate testing project at `~/factory-multiline`** (own git
  @ `6ff6705`). All splatworld work pushed.

## Confirmed compaction rubric (chandoff 2026-07-19)

```
KEEP IN FULL:
- SPLATWORLD shipped+pushed (main @ b06003c): v0.24.0 (3a carpet_perf harness) + v0.24.1 (3b resolution
  hotfix: harness now forces+verifies a true 1920x1080 window via DisplayServer.window_set_size, screen
  placement, fail-closed on mismatch; the first 3b run was VOID — rendered 1152x648 on the wrong monitor)
  + v0.25.0 (M4 task 4 Splat Studio 4a: scatter_core.gd toolkit + op/stroke model + CarpetLoader.
  resync_materials + mutation-proven splat_studio_smoke.gd + 4b Fill/Stamp). 3b VERIFIED perf: budget
  carpet 1.45M=277fps, 2.4M hero=180.6fps @ true 1080p on the 3090.
- Splat Studio was GLM-5.2 (dark-factory worker) implemented, CLAUDE-verified (4-lens panel: gate
  mutation-proven real, no BLOCKER/MAJOR) after the GLM session died on its provider limit pre-ritual.
  Owner cleared the GLM session; planner disarmed + committed + tagged. NOT "model graded itself" — same
  df harness on GLM. Follow-ups -> tasks/2026-07-19-splat-studio-followups.md: #1 Paint cross-dab Poisson
  spacing (borderline-MAJOR: fresh SpatialHash per dab -> min_dist not enforced across a stroke) + close
  the smoke gap; then id/target op-key drift, resync is_queued_for_deletion guard, log hygiene, viewer
  wiring (splat_studio.gd is standalone Node+CanvasLayer, NOT wired onto orbit_viewer.gd), rest of 4b belt.
- DARK-FACTORY MULTILINE (the model-failover architecture, owner-decided B route): Claude Max
  ORCHESTRATE-ONLY + disposable worker-agent lines (one per provider,model) over MCP + main handles
  worker death/reroute. A route (=GLM-in-Claude-Code, today's setup) rejected: can't handle death.
  INVARIANTS: L2 (task-level failover, BUILD it) not L1 (off-the-shelf routers only reroute one HTTP
  call); worker returns a PATCH scored by the orchestrator from a PRISTINE git ref as a different UID
  (gate-immutability beam — reject any patch touching gate paths + held-out oracle; test-gaming is the
  DEFAULT agent behavior); no learned router (static priority + circuit breaker; gate is pass/fail NEVER
  a routing signal); WAIT-or-reroute on a cap, NEVER escalate to Claude to implement; cache lives within
  a line, dies on provider switch (never stateless claude -p); worker contract = MCP Tasks primitive
  (taskId=idempotency, tasks/get/result/delete); never dispatch without a hard lease; idempotent
  re-dispatch via git-worktree-per-attempt + reset. Harness rec: opencode+opencode-mcp (only off-the-shelf
  agent-over-MCP) > OpenHands > Goose. Design = docs/2026-07-19-dark-factory-multiline-design.md; DECISIONS
  D10 (OPEN: harness pick + build-go).
- FLEET REALITY (2026-verified): GLM primary (burns 3x quota at peak); Kimi co-primary; Qwen3-Coder-30B
  local (4-bit AWQ-Marlin ~17GB, NOT FP8, ~50-73 tok/s) scoped-impl + judge; NVIDIA NIM ~40rpm + Gemini
  Flash 1500 RPD free lanes (dedicated GCP project or billing kills free tier); Cerebras tier-E (8192-token
  context CAP, ~1M/day); Colibri = frontier GLM-5.2 744B GPU-free but ~0.3 tok/s (10x below guess) + serve
  tool-calling BROKEN (#401) + runaway-CPU bug -> caged async JUDGE experiment ONLY, dedicated NVMe+watchdog.
- ~/factory-multiline = separate testing repo (git @ 6ff6705): README/CLAUDE/DESIGN/MODELS + tasks/
  QUEUE+DECISIONS (M0=B decided; M1 harness / M2 durability / M3 toy-target / M4 gate-uid OPEN) + 6 base
  tasks (thin-vertical, l2-state-machine, mcp-worker-opencode, gate-immutability-beam, provider-registry,
  model-benchmarks). First slice = thin vertical; first REAL target later = the Splat Studio Paint fix.

COMPRESS + POINT:
- All research detail -> docs/2026-07-19-dark-factory-multiline-design.md + the two research output files
  (runs wf_42efecd4-d5a fleet-options, wf_358bd85a-615 harness/orchestration). Verify-panel detail ->
  the run #14/Splat-Studio handoffs. Perf detail -> docs/2026-07-18-perf-3b-findings.md.

DROP:
- The blow-by-blow of the 3b resolution debugging (kept: hotfix v0.24.1 forces+verifies true 1080p).
- The mutation-test transcript of the verify panel (kept: gate mutation-proven, no BLOCKER/MAJOR).
- The AI-newsletter dump + the A-vs-B deliberation (kept: B chosen, why).
- Every provider citation URL (they're in the design doc / output files).

VERBATIM ANCHORS:
- splatworld main @ b06003c (pushed, synced 0/0); tags v0.24.0, v0.24.1, v0.25.0.
- ~/factory-multiline (SEPARATE git @ 6ff6705, no remote).
- New splatworld files this session: godot/relight/scatter_core.gd, splat_studio.gd,
  tools/splat_studio_smoke.gd, carpet_loader.gd (resync_materials); docs/2026-07-18-perf-3b-findings.md,
  docs/2026-07-19-handoff-splat-studio-glm.md, docs/2026-07-19-dark-factory-multiline-design.md;
  tasks/2026-07-19-splat-studio-followups.md; DECISIONS D10.
- Perf scratch (gitignored, godot/gs_assets/): perf_pxl144634_s14 / perf_pxl131945_s14 .relightply +
  perf_carpet_{baseline,budget}.instances.json.
- Memory added: reference-display0-render-resolution (DP-2 2560x1440 / HDMI-1 1600x1200; real-display
  renders must window_set_size+verify).

ORIGINAL-PROGRAM (splatworld) OPEN THREADS — return here:
- Splat Studio follow-ups (Paint fix #1) — a natural FIRST real multiline target once that harness exists.
- M3 acceptance still owner-gated (hero re-export + a/b backlit eyeball -> unblocks demo/gif regen).
- M4 authoring: tasks 5 (cleanup-select) / 6 (Blender addon) after Splat Studio.
- Latent: render<->viewer orientation discrepancy; D9 (mixed-scene material buffer) gated to Moon-Stone.

UNCERTAIN:
- Whether the next build is multiline (in ~/factory-multiline, D10 harness pick first) or back to
  splatworld's own queue (Splat Studio follow-ups / M3 acceptance) — owner's call.
```

## Git state (safety net)
```
b06003c Design: dark-factory multiline (B route) + DECISIONS D10
4aa554b Reconcile GLM Splat Studio run: disarm, verdict, banner, follow-ups, queue, handoff
c4430eb M4 task 4 — Splat Studio (v0.25.0): GLM-5.2 implementer output, Claude-verified
```
`main` pushed @ b06003c, synced 0/0. Tags … v0.24.0, v0.24.1, **v0.25.0**. Factory **disarmed**
(state.json armed:false, gitignored). `~/factory-multiline` = separate repo @ `6ff6705`.

## Next action
Owner picks the fork: (a) build **dark-factory multiline** in `~/factory-multiline` (start D10 harness
pick → the thin-vertical slice), or (b) resume the **original splatworld program** (Splat Studio
follow-ups incl. the Paint fix, or the owner-gated M3 acceptance). The Paint fix is the bridge — a clean
first real target for multiline once its harness works. Fresh-session read order (splatworld): CLAUDE.md
+ MEMORY.md → docs/decisions.md tail → tasks/QUEUE.md + DECISIONS.md → latest lore (this) → the relevant
task file. For multiline: `~/factory-multiline/README.md` → CLAUDE.md → DESIGN.md → tasks/QUEUE.md.

Sequence: **#12**.
