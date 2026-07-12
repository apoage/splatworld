# Handoff #2 — M2 build (2026-07-12)

Previous: `lore/handoff_2026-07-11_m0-m1-published.md` (#1, M0+M1 published)

- **Branch:** main
- **Working dir:** /home/lukas/splatworld
- **Session focus:** Ran the dark-factory across two armed stretches. First: shipped the
  queued backlog (ingest, code-hardening, smoke-loop, perf-budget → v0.2.0–v0.5.0). Then,
  after the owner's "green go", built the M2 milestone: **M2a relight runtime (v0.6.0)** and
  **M2b decompose port phases A/B/C (v0.7.0)**. Design + license triage done via read-only
  Workflows (ultracode on); code through the guard-railed implementer + adversarial panels.
  Stopped before M2b **phase D** (real-asset dB-budget validation — scheduled real-data work).
  Full narrative: `docs/2026-07-12-handoff.md` + `docs/2026-07-12-handoff-2-M2.md`.

## Compaction rubric (confirmed)

```
KEEP IN FULL:
- Current state: factory DISARMED, tree CLEAN, tags v0.2.0–v0.7.0. M0/M1 done; M2 built
  except phase D. Nothing pushed (allow_push:false; owner pushes).
- The 2 open owner questions that gate the next run:
  (1) env-SH sidecar → Godot ambient_sh(N) reader (runtime still uses flat ambient);
  (2) phase-D go? (real-asset decompose dB-budget validation on pxl_144634/pxl_131945).
- Open DECISIONS: D2 (foliage budget, data-backed, owner picks), D3 (M4 orientation, gated M4).
- JAX/M3 transmission = EXTERNAL contributor lane, NOT factory work.
- Operational lesson: dark-factory implementer subagents must validate in the FOREGROUND
  (a backgrounded sweep once returned with nothing written).

COMPRESS + POINT:
- Entire per-task implement→verify→fix→ship narrative for all 7 ships (v0.2.0–v0.7.0)
  → see docs/2026-07-12-handoff.md + docs/2026-07-12-handoff-2-M2.md + task-file banners.
  Collapse each shipped task to one line (version · what · gate).
- M2b GI-GS port design + license triage → see docs/validation-m2b-phaseC-portplan-2026-07-12.md
  and the decisions.md 2026-07-12 M2 entry. Don't re-summarize the vendoring rules.
- GI-GS build recipe / architecture → see docs/validation-m2b-phaseA-gigs-buildverify-2026-07-12.md.
- M2a GDGS one-seam insertion detail → see docs/validation-m2a-relight-runtime-2026-07-12.md
  + decisions.md (invariant-#6 record).

DROP:
- All "Holding — factory armed" stop-gate exchanges (repetitive; ~a dozen turns).
- Monitor idle-detection false-positives, re-arms, and journal/transcript-extraction mechanics.
- Blow-by-blow of individual verifier findings that were fixed then re-verified (outcomes
  live in the task banners + .dark-factory/verdicts). Keep only findings still OPEN.
- Tool-schema-fetch / SendMessage-loading detours.

VERBATIM ANCHORS (must survive unchanged):
- HEAD chain: 7b7b70d (reconcile) · 857b68e (v0.7.0 phase C) · 2a3fbd3 (v0.6.0 M2a).
- decompose.py material-LR fix = offset `iteration - pbr_iteration` (bug #6 fence; must
  NOT regress to `- 30000`). Budget gate default = 1.5 dB (invariant #8, default-ON).
- Vendor set: precompute/vendor/gigs/ = LICENSE + NOTICE + pbr_math.py (8 import-free fns only).
- Golden test: albedo MAE 0.001 (synthetic; gate <0.05). SCHEMA_VERSION still 1.
- scaffold/ and godot/gs_assets/*.relightply are gitignored (local-only).

UNCERTAIN (flag for correction):
- Does the synthetic golden MAE 0.001 predict real-asset convergence? It's an "inverse crime"
  (same forward path); real thin-leaf foliage is untested — phase D is the real test.
- Should the next run start phase D autonomously, or wait for the env-SH owner answer first?
- Whether wiring the Godot env-SH reader is in phase-D scope or a separate M2-completion step.
```

## Git state (safety-net, not for the rubric)

```
$ git log -5 --oneline
7b7b70d docs+tasks: reconcile M2 run — decisions.md (M2a GDGS diff invariant #6, M2b A–C, env-SH owner call) + QUEUE groom
ba898ab docs: handoff #2 — M2 build (v0.6.0 M2a runtime + v0.7.0 M2b decompose A/B/C)
857b68e feat(precompute): M2b Phase C — decompose stage (GI-GS port onto gsplat, pure-torch env)
8c661c1 test(m2b): Phase B — prove gsplat N-channel G-buffer + gradient flow (de-risks the port)
d1b09e1 docs(m2b): Phase A reference build-verify — GI-GS builds+trains on sm_86/cu124

$ git status --short
 M NOTICE   # stat/mode-only, EMPTY content diff — not this session's edit; benign, investigate before committing
```
Tags: v0.2.0 … v0.7.0. Factory disarmed (`.dark-factory/state.json` armed:false).

## Next action

Answer the 2 owner questions (env-SH sidecar wiring? phase-D go?), then either arm the
factory for **M2b phase D** (`tasks/2026-07-11-m2-decompose.md` → phase D: real-asset
decompose on the 3090, meet ≥ train_base−1.5 dB budget, `export --from-decompose`) or wire
the Godot env-SH reader first. Everything else (D2/D3) is non-blocking.
