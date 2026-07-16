# Handoff — dark-factory run #7 (2026-07-16)

Previous: [lore/handoff_2026-07-15_run5-normalfix-lightingwip.md](handoff_2026-07-15_run5-normalfix-lightingwip.md) · sequence #7

- **Branch:** main
- **Working dir:** /home/lukas/splatworld
- **Session focus:** Dark-factory implementer run #7 — shipped the queue's two owner-visible
  shading defects (relit-energy v0.15.0, normal-sign-consistency infra v0.16.0), seeded D6,
  deferred flashlight-orb. Full detail in `docs/2026-07-16-handoff-7-run7.md`.

## Compaction rubric (confirmed 2026-07-16)

KEEP IN FULL:
- Run #7 result: 2 ships — v0.15.0 relit-energy (env-SH energy calibration), v0.16.0 normal-sign
  INFRA + fail-closed gate. Factory DISARMED, tree clean, nothing pushed (planner later pushed tags).
- D6 (OPEN wall): normal-sign efficacy UNPROVEN — camera-hemisphere orient fixes only the
  along-view sign; grazing foliage normals unresolved (~17–49% synthetic residual); gated on the
  scheduled fail-closed re-decompose. The live decision.
- flashlight-orb next-run trap: the relight pass has NO per-splat WORLD position (task claims it
  does); a point light needs a GDGS means-buffer binding + a UBO (push constant is full).

COMPRESS + POINT:
- The whole verification saga (~14 subagent panels + the 3 fix/verify cycles on #2's gate + all
  synthetic opposition numbers) → one line per ship; see docs/2026-07-16-handoff-7-run7.md (holds
  every load-bearing number, the D4 planner note, and both scheduled one-shot commands).

DROP:
- Stop-gate feedback + my "holding/waiting" replies between subagent notifications (mechanical).
- Subagent-launch metadata / agentIds.
- Scratchpad drafts (verify-checklist.md, release-*.md) — superseded by committed artifacts.

VERBATIM ANCHORS:
- 825d74f, 2708b29, e8874a4; tags v0.15.0, v0.16.0; docs/2026-07-16-handoff-7-run7.md; DECISIONS D6.

UNCERTAIN:
- Synthetic residual figures (17–49% grazing; 1.84% vs 9.50% fixture gap; CASE-D 5.88%): treated
  as collapsible (they live in the handoff).
- Planner remainder (add the D4-runtime note to docs/decisions.md): **now DONE** by the planner in
  ce6005d (reconcile run #7 — also pushed tags).

## Git state
```
ce6005d Reconcile run #7: D4-runtime recalibration entry placed; run notes; tags pushed  (HEAD, planner)
e8874a4 docs: dark-factory run #7 handoff (relit-energy v0.15.0 + normal-sign infra v0.16.0)
2708b29 normal-sign-consistency: sign-consistency infra + fail-closed multi-scale gate (v0.16.0)
825d74f relit-energy: DC-normalize env-SH ambient to the ambient slider (v0.15.0)
d737444 normal-sign-consistency task (Ready #2): requeue with audit numbers
```
`git status --short`: clean.

## Next action
Answer the two open questions in `docs/2026-07-16-handoff-7-run7.md`: (1) launch the D6
re-decompose overnight (arbiter of the normal-sign fix; needs idle-GPU green light) and on which
box; (2) relit-energy owner eyeball (V toggle = subtle shape/tint, no bloom). Next Ready task =
flashlight-orb (#3) — mind the world-position/UBO caveat before writing shader code.
