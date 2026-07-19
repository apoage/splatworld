# Handoff — Splat Studio 4a (v0.25.0): GLM-5.2 worker run + Claude finalize (2026-07-19)

First **alternative-model dark-factory run**: the implementer thread ran **GLM-5.2 in Claude Code**
(via a GLM-compatible endpoint) on the scoped single task `tasks/2026-07-18-splat-studio.md`.

## What happened
- GLM-5.2 implemented M4 task 4 (Splat Studio): `scatter_core.gd` (655 L) + `splat_studio.gd` (381 L)
  + `splat_studio_smoke.gd` (922 L) + `CarpetLoader.resync_materials`, ran 3 judge fix→verify cycles
  (closed 4 BLOCKERs + MAJORs), reached gate PASS — then **died on a provider usage-limit (5-hour,
  UTC+8 reset) mid-release-ritual**, at the "write verdict" step, before committing. Work left
  uncommitted; `state.json` stuck `armed:true`.
- **Planner reconcile (Claude, this session):** independent objective gates (`splat_studio_smoke` PASS,
  `carpet_smoke`/`carpet_perf` PASS, **pytest 141**) + a **4-lens Claude adversarial panel**
  (`wf_edb575ae-e41`: gate-integrity, scatter_core correctness, loader/resync, guardrails). Verdict:
  **GREEN on the gated 4a scope, no BLOCKER/MAJOR.** Disarmed the dead session, committed GLM's exact
  output (`c4430eb`), tagged **v0.25.0**, wrote the verdict, filed follow-ups. **Push HELD for owner
  review** (first GLM-authored public output). Owner will clear the dead GLM session.

## Verify highlights
- **The gate is real (mutation-proven):** the auditor broke determinism, resync, and replay on a
  scratch copy — the gate FAILED correctly each time. Not a paper gate. (It's the same dark-factory
  harness Claude uses; the implementer writes code + smoke per the DoD, then judges review.)
- **Determinism holds cross-process** (two Godot runs → byte-identical instances) — replay-later works.
- **`resync_materials` sound** — `load_carpet` byte-identical, tree-order==material-order invariant
  across all 3 cases, single-carpet/no-D9, GDGS untouched; 3 hard desync attacks failed.
- **Guardrails clean** — no schema change, no GDGS edit, TRS-only, no EditorImportPlugin.

## Follow-ups (`tasks/2026-07-19-splat-studio-followups.md`)
1. **Paint cross-dab Poisson spacing** (borderline-MAJOR): fresh SpatialHash per dab → min_dist not
   enforced across a stroke; + close the smoke gap (Poisson only asserted on `fill_region`).
2. nudge/delete `id` vs documented `target`. 3. `resync_materials` `is_queued_for_deletion()` guard
   (latent). 4. log/stderr hygiene + middle-variant erase coverage. 5–6. viewer wiring + rest of 4b belt
   (owner-attended). Good worker-fleet starters (narrow, gate-checkable).

## Strategic pivot: the worker-fleet failover architecture
This run proved the driving problem and the fix. **Core insight (owner):** if main == worker (one
model/session), a provider cap kills everything until manually pinged; **split them and a robust main
reroutes a dead worker to another provider and keeps going.**

- **Forced by the platform:** Claude Code native sub-agents can only target Claude tiers — the ONLY way
  to run a non-Claude/local worker in-loop is an **MCP tool** (or swapping the whole session's backend).
- **Design:** robust **Claude-Max main = orchestrator + verifier** (cheap in that role) ↔ **MCP worker**
  = a headless agentic coder (Claude Agent SDK / OpenHands) pointed at a provider ↔ returns the diff to
  main ↔ main runs the **immutable** gates + Claude judges ↔ on worker death/429 or gate-fail, main
  **reroutes/escalates** across the provider fleet.
- **Two make-or-break rules:** (a) main's own lane must not die → Bedrock/Vertex Claude (separate quota,
  no subscription caps) or subscription-until-cap-then-metered; (b) the gate must be **immutable to the
  worker** (a weak model will edit tests to pass) — lock `precompute/tests/` goldens + the smoke harness
  out of the worker's write scope.
- **Owner's provider fleet (independent quotas):** GLM (api key + coding plan — this run), Kimi K3
  (sub + api key), Cerebras (fast, runs older GLM), NVIDIA (NIM), Google free tier; local
  Qwen3-Coder-30B / Devstral Small 2 on the dev 3090 (vLLM native `/v1/messages`). Trader 4×3090 =
  whole idle GPUs only, never MPS-share.
- **GAP:** the factory-worker MCP-compatible harness does **not exist yet** — it's the next build.
- **Quick win (off-the-shelf, no build):** `claude-code-router`/LiteLLM in front with an ordered
  fallback chain → the session auto-reroutes on 429 instead of dying.
- Full research: `wf_42efecd4-d5a` (6 briefs — Claude-Code backends, serving stacks, model fits,
  Colibri [too slow, 0.05–2 tok/s], MCP/verifier-gated patterns, token/access lanes).

## Next
1. Owner: review + push v0.25.0 (or leave local). Clear the dead GLM session.
2. Capture this architecture as a `docs/` design note + a DECISIONS row, then scope the MCP-worker
   harness as a build task (worker agent framework + provider fleet + failover + gate-lockdown).
3. Paint fix (#1) is a natural first worker-fleet task once the harness exists.
