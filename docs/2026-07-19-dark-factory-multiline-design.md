# Dark-factory multiline — architecture design (v1, recommended)

**2026-07-19.** How to keep the factory building when any one model provider caps, by splitting
orchestration (Claude, stays up) from implementation (a fleet of worker agents on other providers,
disposable). Owner-named **"dark-factory multiline"**; **B route** (main dispatches to worker agents
over MCP + handles their death — NOT A route, which is today's "run GLM in Claude Code with df" and
can't handle death). Synthesized from research runs `wf_42efecd4-d5a` + `wf_358bd85a-615` (full briefs
in the session transcript). **Open choices flagged in §9.**

## 1. The shape

```
  ┌──────────────────────────────────────────────────────────────────────┐
  │ MAIN = Claude Code on Claude Max (OAuth). ORCHESTRATE-ONLY, never      │
  │ implements. Runs the L2 state machine: assign → dispatch → verify →    │
  │ reroute/wait. If Max caps, main pauses (owner pings) — accepted.       │
  └───────────────┬──────────────────────────────────────────────────────┘
                  │ MCP Tasks primitive: dispatch(taskId) · tasks/get (heartbeat) ·
                  │ tasks/result (DIFF) · tasks/delete (cancel+reap)
     ┌────────────┼────────────┬────────────┐   each worker line = ONE (provider, model)
     ▼            ▼            ▼            ▼
  [GLM line]  [Kimi line]  [Qwen-local] [free lanes…]   ← persistent agent sessions
   opencode/OpenHands, pinned provider, produces a PATCH (not a verdict)
     │
     ▼ patch handed back
  ┌──────────────────────────────────────────────────────────────────────┐
  │ GATE-IMMUTABILITY BEAM (orchestrator side, worker can't reach):        │
  │ apply patch to a FRESH checkout @ trusted ref → REJECT if it touches   │
  │ gate paths → force-restore gate files → hash-pin → run pytest+godot    │
  │ smoke + judges as a DIFFERENT UID. Worker's own test runs = advisory.  │
  └──────────────────────────────────────────────────────────────────────┘
```

## 2. The two failover layers (the finding that reframes everything)

- **L1 — request-level** (one HTTP call reroutes on 429): LiteLLM, claude-code-router, claude-code-mux.
  Every off-the-shelf "provider failover" is L1. Necessary sugar **inside** each worker; it CANNOT see a
  wedged agent loop or reset a dirty git tree.
- **L2 — task-level** (the whole agentic task, mid-flight): detect a worker's crash/hang/quota-death
  after minutes of work, throw away its half-finished mess, re-dispatch the SAME task to another
  `(provider,model)`. **This is our mandate, and we BUILD it** (small — ~a few hundred lines). A-route
  has neither layer around the task; that's why it "dies completely until pinged."

## 3. Harness for the worker (see §9 for the pick)

Ranked for "model-agnostic, headless, full-repo agent, driven over MCP, cache warm across a task":
1. **opencode + `opencode-mcp`** — the ONLY off-the-shelf "agent over MCP": `opencode serve` (persistent
   sessions, cache warm) + the bridge exposes `run`/`fire`/`reply`/`check` = dispatch/background/continue/
   poll, maps 1:1 onto our worker contract. 75+ providers. Fastest path. (Bridge is 3rd-party — pin/fork it.)
2. **OpenHands Software Agent SDK** — strongest autonomous-SWE quality + a Docker sandbox per task
   (a feature for untrusted diffs); LiteLLM = whole fleet; REST/WS agent server → wrap in a thin MCP server.
   Heaviest footprint.
3. **Goose (Block)** — lean, Rust, MCP-native, headless recipes; confirmed auto prompt-caching. Drive it
   behind a small MCP wrapper.
- **Claude Agent SDK** — best caching but Anthropic-wire ONLY (native for GLM/Kimi; needs a proxy shim for
  OpenAI-compat lanes). A special line, not the general worker.
- **Rejected:** `claude -p` (stateless → loses cache — your call, confirmed correct); Aider (weak
  autonomous loop, no native MCP); OpenAI-Agents-SDK/smolagents/LangGraph (frameworks — you'd BUILD the
  coding agent); Roo Code (archived May 2026).

## 4. The L2 failover state machine (the core build, ~few hundred lines)

`SQLite lease table + git-worktree-per-attempt + per-line circuit breaker + static-priority router + 30s sweeper.`

```
QUEUED ─(pick highest-priority CLOSED-breaker line in tier; worktree from baseline_sha; open MCP task; lease=now+T)→
LEASED ─(heartbeats/progress via tasks/get)→ RUNNING ─(worker returns diff)→ VERIFYING ─(IMMUTABLE gate)→
   PASS → DONE (commit diff to integ branch)
   FAIL / any fault → FAILED_ATTEMPT → RESET (git worktree remove --force; attempt++; if provider-fault trip line breaker)
        → REROUTE DECISION → {another healthy line & attempt<MAX → QUEUED on next line}
                             {only faulted line left & fault=429 → WAIT (backoff; NEVER escalate to Claude) → QUEUED same line}
   attempt≥MAX → DEAD_LETTER (human only)
```

**Fault → detector → action:**
| Fault | Detector | Action |
|---|---|---|
| 429 / quota | HTTP 429 on dispatch | trip line breaker (immediate cooldown); WAIT if it's the only line, else reroute. **Never escalate to Claude.** |
| crash / silent death | heartbeat stale >90s, MCP `failed`/`unknown`, or PID exit | reap → RESET → reroute |
| hang / loop | StuckDetector: ≥3 identical actions + flat progress ≥3 heartbeats | `tasks/delete` → RESET → reroute to a **different model** |
| lease expiry | sweeper: inflight deadline passed | treat as death → RESET → reroute |
| gate FAIL | immutable gate returns fail | RESET → retry; after K, **deterministic** tier escalation (rule, not learned) |

Tunables: heartbeat 5–10s (emitted from INSIDE the worker loop, not a sidecar); stale >90s; breaker trips at M fails/window; backoff 10s→…→5min; MAX≈5–10; sweeper 30s. **Never dispatch without a hard lease/timeout** (ref: claude-code #49150 — Task() has no timeout, wedges the orchestrator).

**No learned router** ("When Routing Collapses", arXiv 2602.03478 — learned routers collapse to one model):
route = first healthy (CLOSED-breaker) line in the task-tier's **static priority list**. The gate is a
pass/fail arbiter, **never** a routing signal (feeding "who passed most" into selection starves the fleet
to one line — defeats the whole point).

## 5. Worker contract = MCP Tasks primitive (Nov-2025 spec)

Don't invent one. Each worker line is an MCP server whose task ops are: client-generated **`taskId`** (the
idempotency key — spec-designed for idempotent retries), states `submitted→working→{completed|failed|
cancelled|input_required|unknown}`, `tasks/get` (poll = heartbeat + progress), `tasks/result` (the diff),
`tasks/delete` (cancel+reap). Worker runs a full agentic loop in a git worktree, hands back a **diff**.
**Cache is per-provider/per-session and DIES on any provider switch** — so it lives within a line, never
across a reroute; WAIT-vs-reroute is a deterministic cost compare (429 cooldown vs cold-prefill+redo).

## 6. Gate immutability — the safety beam (do NOT skip; this is load-bearing)

Editing/gaming tests is the **default** agent behavior and scales with capability (ImpossibleBench: GPT-5
cheated 76%, Opus 46%). A weak worker won't be subtle — it'll `sed` the assert or `pytest.skip`. Locks the
worker can reach are advisory (bubblewrap escapes; Claude Code deny-hook bug #37210). **The beam:**

> The worker produces a **patch, not a verdict**. The orchestrator applies it to a **fresh checkout at a
> trusted ref**, **rejects any patch that touches a gate path**, **force-restores** the gate files from the
> ref, **hash-pins** them, and runs the gate **as a different UID outside the worker's sandbox**. A worker
> that spent its whole episode weakening asserts scores against tests that don't have its edits.

Layers (ranked by trust): **L0** separation of duties (worker=diff, gate=orchestrator's — already our
two-thread shape); **L1** the git-restore beam above (total trust — the beam); **L2** held-out oracle
(public test subset the worker iterates vs a **private superset** the orchestrator scores with — the exact
analog of our existing "re-render PSNR vs **held-out** views" rule; hiding tests drives cheating ≈0);
**L3** fs isolation (bubblewrap **allowlist** mounts, gate dirs unmounted or `--ro-bind`, gate files owned
by a different UID `0444`); **L4** hooks (advisory early-warning only); **L5** a semantic anti-gaming judge
(the local Qwen reads the diff for the 4 tells: new/edited asserts, skip/xfail, monkeypatched comparisons,
input-specific constants).
**Gate pathspec for this repo (off-limits to workers):** `precompute/tests/`, `precompute/core/ply_io.py`,
the `metrics.json` assertion code, `godot/relight/tools/smoke_test.gd` (+ the other `relight/tools` gates),
`tasks/DECISIONS.md`, `.dark-factory/config.json`, `docs/decisions.md`.

## 7. Provider × model registry + fleet reality (2026-verified)

Config-driven `{provider, model, capability-tier, context, speed, quota, endpoint-compat, role}`; static
priority per task-tier; capability-based routing. Corrections to earlier assumptions in **bold**:

| Line | Compat | Role | Notes (verified) |
|---|---|---|---|
| **GLM / Z.ai** | Anthropic | primary implementer | strong; **burns 3× quota at peak, 2× off-peak → make the breaker cooldown peak-aware** |
| **Kimi / Moonshot** | Anthropic + OpenAI | co-primary implementer | Claude-Code-shaped |
| **Qwen3-Coder-30B local** (dev 3090) | OpenAI (vLLM) | scoped implementer + parallel judge | **4-bit AWQ-Marlin ~17GB (NOT FP8 — Ampere has no FP8 path, falls back to w8a16); ~50–73 tok/s; prefix-caching via persistent server**; gate off when you're using the dev GPU |
| **NVIDIA NIM** | OpenAI | free lane | **~40 RPM free (bump to ~200)** — low-throughput |
| **Gemini Flash** | Gemini | free lane | **1,500 RPD / 15 RPM = a real lane; Pro only 50 RPD (hoard). Enabling billing on a GCP project KILLS its free tier → dedicated project per free lane** |
| **Cerebras** | OpenAI | tier-E, short tasks only | **8,192-token context CAP + ~1M tok/day, 2,600 tok/s** — fast but tiny-context + low stability; only short tasks that fit 8k |
| **Colibri (GLM-5.2 744B, GPU-free)** | OpenAI | caged async JUDGE experiment | frontier-strength (62.1 SWE-bench Pro), GPU-free so it fits the trader box's CPU/RAM/NVMe — **BUT ~0.3 tok/s on CPU (10× below the 3 tok/s estimate; 3 needs GPUs), serve-mode tool-calling BROKEN (#401 → no implementer), live runaway-CPU bug (#341). Only as a watchdogged, cgroup-caged, DEDICATED-NVMe async judge. Experiment, not infra.** |

**Trader-box coexistence:** GPUs stay untouched. Qwen uses a WHOLE idle GPU (`CUDA_VISIBLE_DEVICES` pin +
idle-gate before launch, per the existing trader invariant). Colibri is GPU-free but hammers NVMe
(~3GB/s) → **dedicated NVMe drive the trader never touches** (non-negotiable) + cgroup v2 cpuset/io.max +
NUMA-pin (dual-socket) + a hard watchdog on the #341 runaway signature.

## 8. Build vs adopt vs keep

- **BUILD (small):** the L2 state machine (§4) + the gate-immutability beam (§6) + the MCP dispatch glue.
- **ADOPT:** the MCP Tasks primitive (worker contract); **opencode+opencode-mcp** (or OpenHands) as the
  worker; claude-code-router / claude-code-mux + LiteLLM **inside each worker** for L1 failover + provider
  pinning (configure fallbacks — LiteLLM has a no-fallback mid-stream-429 hang bug #26015).
- **KEEP unchanged:** the immutable gate (pytest + headless godot smoke + judge panel) as a pure pass/fail
  arbiter; the two-thread lane/hook machinery (extend hooks with the gate pathspec).
- **DON'T:** learned router (collapse); stateless `claude -p` (cache loss); dispatch without a hard lease;
  run L1-only and expect it to catch a wedged agent; trust a worker-reachable lock as the gate boundary.

## 9. Open choices + next steps

1. **Harness pick:** **opencode+opencode-mcp** (fastest to a working MCP worker, off-the-shelf dispatch/poll)
   vs **OpenHands** (more capable + sandboxed, but you build the MCP wrapper). *Recommendation: opencode
   first* — the gate-immutability beam (§6) already provides the isolation, so OpenHands's sandbox is
   redundant for v1; revisit if opencode's autonomous quality disappoints.
2. **Build go?** If yes, first slice = a **thin vertical**: one worker line (GLM), the L2 lease+worktree
   loop, the git-restore gate beam, on ONE real task = the **Splat Studio Paint fix**
   (`tasks/2026-07-19-splat-studio-followups.md` #1 — narrow, gate-checkable). Prove dispatch → death →
   reroute → gate → commit end-to-end, then add lines (Kimi, Qwen-local) + the judge panel + Colibri-judge.
3. **Colibri:** bounded experiment as an async judge only, after the core loop works — needs a dedicated
   NVMe + watchdog first.

Ties to [[project-moonstone-meadow-demo]] indirectly (keeps the factory fed). Supersedes nothing; the
single-line dark-factory stays valid for attended runs.
