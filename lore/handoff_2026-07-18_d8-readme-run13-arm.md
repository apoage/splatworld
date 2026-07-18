# Handoff — planner: D8 ratified + README honest-refresh + run #13 reconcile + armed for perf (2026-07-18)

Previous: `lore/handoff_2026-07-18_cactus-gdgs-m4design.md`
(chain: … #9 d7-signed-sandbox-synthetic → #10 cactus-gdgs-m4design → **#11 this**)

- **Branch:** main · **Working dir:** /home/lukas/splatworld
- **Session focus:** Ratified D8 (M4 green). Rebuilt the stale GitHub README with an honest
  "live testing environment" framing after the owner rejected my over-selling (foliage is poor
  model quality). Reconciled + pushed factory run #13 (M4 spine + decimator), seeded D9. Split
  task-3's DoD and cleared D3 so the top row is unambiguous, then confirmed ready → owner ARMED
  the factory for run #14 (task 3 perf harness).

## Confirmed compaction rubric (chandoff 2026-07-18)

```
KEEP IN FULL:
- Governance: D8 RATIFIED (M4 green); D9 SEEDED (OPEN, gated to a Moon-Stone mixed scene) =
  set_materials_multi overwrites the ONE global material buffer → carpet + any other registered
  splat node shifts every si.y → whole-scene mis-shade; rec = fail-closed registry-count assert
  now + per-node offset scheme later. D3 SETTLED (spine implements it). Upstream GDGS PR = parked
  pending owner cross-validation.
- Honest-framing pivot (durable → memory feedback-honest-framing-not-hype): foliage splats are
  POOR model quality ("somewhat working," not beauty); present splatworld as a live/under-dev
  TESTING ENVIRONMENT (A/B toggles visible on purpose); lead demos with the CACTUS (clean CC0,
  legible relight), foliage shown honestly as the rough real target.
- Run #13 SHIPPED + reconciled: M4 spine set_materials_multi + carpet_loader.gd (v0.23.0) +
  clean_relight.py decimator (v0.22.0); coupling = shader materials[si.y] ↔ GDGS registry
  first-seen (add_child) order. Next = task 3 perf, SPLIT: 3a factory builds carpet_perf.gd
  (DoD = tool, NOT a headless fps number — dummy renderer won't rasterize); 3b real ≥60fps is a
  scheduled DISPLAY=:0 one-shot, never a factory gate. Authoring tasks 4/5 held until the perf
  number + built owner-attended. Owner ARMED for run #14.

COMPRESS + POINT:
- README refresh (7 real shots, honest rewrite) → the README + docs/img/*.png + notes_2026-07-18.
- Run #13 reader detail → docs/2026-07-18-handoff-run13-m4-spine-decimator.md.

DROP:
- Screenshot-curation archaeology (viewing ~17 shots, grid-vs-foliage, my first over-sold
  "gorgeous" take the owner corrected) — keep only the conclusion + the honest-framing rule.
- Metadata-scan grep false positives; tag lexical-sort confusion; the arming-vs-disarming typo.

VERBATIM ANCHORS:
- main @ d2e65ef (pushed, synced 0/0 before arming); tags v0.22.0, v0.23.0.
- Foliage hero: res://gs_assets/pxl_144634.relightply (+ pxl_131945; env sidecar auto-binds by name).
- Viewer: RELIGHT_ASSET=res://gs_assets/<name>.relightply DISPLAY=:0 ~/godot/godot --path godot res://scenes/viewer.tscn
- set_materials_multi @ relight_pass.gd:155; carpet_loader.gd; clean_relight.py; pytest 141;
  conda python /home/lukas/miniconda3/envs/splat-relight/bin/python.
- 7 README shots: docs/img/relight_cactus_{sun1,sun2,sun3,flashlight}.png,
  foliage_{relit_day,night_flashlight,facing_debug}.png.

UNCERTAIN:
- Will the 3b perf one-shot clear ≥60fps, or force an LOD/decimation rethink?
- Still-open owner threads: M3 a/b backlit eyeball (gates demo/gif regen); render↔viewer
  orientation discrepancy (latent); plant→splat reconstruction still wanted?
- D9 fix timing (assert now vs per-node offset) — decided when a mixed scene actually lands.
```

## Git state (safety-net, not for the rubric)

Planner's last commit before the factory armed:
```
d2e65ef Pre-arm run #14: split task-3 DoD (build vs GPU measure), clear D3 ambiguity
7d7b0ff Reconcile run #13 + seed D9: groom M4 queue, mixed-scene wall
3c97883 docs: dark-factory handoff run #13 — M4 spine + decimator (v0.22.0, v0.23.0)
1be6146 M4 task 1 (spine): multi-variant carpet instancing (v0.23.0)
7976afd M4 task 2: clean_relight.py splat-cleanup + variant decimator (v0.22.0)
91d1d29 README: honest live-testing-environment refresh with real relight shots
```
`main` was pushed @ d2e65ef, synced 0/0, clean. Tags v0.2.0 … **v0.23.0**.
**Factory is now ARMED** for run #14 (task 3) — its commits are the implementer's, unpushed by
design; the git gate blocks planner commits/tags while armed. **THIS handoff file is written to
disk UNCOMMITTED** (same as #10) — commit it at the next reconcile when the factory disarms.

## Next action

Factory is running run #14 = M4 **task 3a** (build `carpet_perf.gd` harness; DoD = the tool +
structure self-check, NOT a headless fps number). On disarm: reconcile as usual (independent
pytest + creds/GPS scan + push + tags), commit this handoff, then line up the **3b perf one-shot**
on `DISPLAY=:0` (2.4M hero + ~1.5M carpet, assert ≥60fps → dated findings doc). That number then
decides whether Splat Studio (tasks 4/5, owner-attended) is next or the budget forces an LOD
rethink. Fresh-session read order: CLAUDE.md + MEMORY.md → docs/decisions.md tail → tasks/QUEUE.md
+ DECISIONS.md → latest lore (this + notes_2026-07-18.md) → the M4 spec.

Sequence: **#11**.
