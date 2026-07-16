# Handoff — dark-factory run #8 (2026-07-16)

Previous: [lore/handoff_2026-07-16_run7-relit-normalsign.md](handoff_2026-07-16_run7-relit-normalsign.md) · sequence #8

- **Branch:** main
- **Working dir:** /home/lukas/splatworld
- **Session focus:** Dark-factory implementer run #8 — shipped flashlight-orb (v0.17.0): camera
  point/spot light + engine-lit reference orb in the relight pass (first shading-contract change
  since M2a; Moon-Stone point-light prerequisite pulled forward). Full detail in
  `docs/2026-07-16-handoff-8-run8.md`.

## Compaction rubric (confirmed 2026-07-16)

KEEP IN FULL:
- Run #8 shipped flashlight-orb v0.17.0. Load-bearing architectural fact: the task's "world position
  already available" premise was WRONG — added per-splat object-space position to OUR material buffer
  (32→48 B, new pos_label slot) and transform by instance_model_matrices[si.x]; NO GDGS edit, NO PLY
  schema bump, push constant stays 48 B, light params in a new binding-5 buffer. FlashLight[4] = the
  documented N=2–4 fireball extension point (M4/M5). Factory disarmed, tree clean.
- Open walls unchanged: D6 (normal-sign efficacy, gates M3) + D3 (M4 orientation). flashlight-orb
  owner eyeball (F/O feel) is the pending acceptance gate. pixel5-variants (#4) = scheduled overnight
  GPU one-shot, best after D6.

COMPRESS + POINT:
- The whole verification arc (high-tier 5-panel + fix cycle 1 + fail-closed re-verify of the gate
  range-term fail-open) → one line; see docs/2026-07-16-handoff-8-run8.md (numbers + the two
  unblocking questions + operational notes: stale-import, one-godot-per-:0).

DROP:
- API-turbulence churn: the implementer's transient 529 death, its repeated auto-resume notifications
  running gates concurrently (:0 contention), classifier-unavailable messages, stop-gate feedback, the
  background pid-wait task, the SendMessage schema-load retry — all mechanical, non-load-bearing.
- My "holding/waiting" turns between task notifications.

VERBATIM ANCHORS:
- commits 574e60c (flashlight-orb), 892b60a (run #8 handoff); tag v0.17.0;
  docs/2026-07-16-handoff-8-run8.md; tasks/DECISIONS.md D6 + D3.

UNCERTAIN:
- Frame-time within-noise datapoint (~8 ms/frame @ 2.4M): collapsible (lives in the handoff +
  validation doc).
- Stale-import / one-godot-per-:0 gotchas: kept as a COMPRESS pointer, not full (in the handoff's
  operational notes).
- (RESOLVED since the rubric draft) the run #7 lore file was still untracked mid-session; the planner
  has since committed it + pushed v0.17.0 in the run #8 reconcile (3bbf71f) — no longer a loose thread.

## Git state
```
3bbf71f Reconcile run #8: v0.17.0 pushed; handoff #7 lore committed; run notes  (HEAD, planner)
892b60a docs: dark-factory run #8 handoff (flashlight-orb v0.17.0)
574e60c flashlight-orb: camera point/spot light + reference orb in the relight pass (v0.17.0)
ce6005d Reconcile run #7: D4-runtime recalibration entry placed; run notes; tags pushed
e8874a4 docs: dark-factory run #7 handoff (relit-energy v0.15.0 + normal-sign infra v0.16.0)
```
`git status --short`: ` M assets/built/pxl_144634/metrics_decompose.json` — a built-asset metrics file
modified post-run (NOT this session's implementer work; likely planner/decompose activity — verify
before committing/reverting).

## Next action
Owner: (1) flashlight-orb eyeball in the viewer (F flashlight / O orb feel) — the acceptance gate; if
good, that track closes. (2) Decide whether to launch the D6 re-decompose overnight (arbiter of the
v0.16.0 normal-sign fix + M3 unblocker; needs idle-GPU green light + which box); pixel5-variants runs
right after. Next factory Ready task is still gated behind those. Also: check the stray
`metrics_decompose.json` modification.
