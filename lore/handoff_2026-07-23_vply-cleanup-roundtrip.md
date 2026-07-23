# Handoff — .vply extension + SuperSplat cleanup round-trip (2026-07-23)

Previous: `lore/handoff_2026-07-22_splat-studio-hygiene-v0.25.2.md`

- **Branch:** main · **Working dir:** /home/lukas/splatworld
- **Session focus:** pushed prior work public; owner cleaned both heroes in SuperSplat + staged
  the cleaned clouds; decided + logged the `.vply` extension unification; armed (and, at chandoff,
  the factory is MID-RUN on) the `.vply` + cleanup-round-trip scoped task. Evaluated ArtiFixer /
  native-3D-diffusion (→ memory). Ran the cactus viewer.

## Confirmed compaction rubric (chandoff 2026-07-23)

```
KEEP IN FULL:
- .vply cleanup-round-trip factory run is ARMED + MID-RUN (implementer session active at chandoff).
  Task tasks/2026-07-23-vply-cleanup-roundtrip.md, 3 deliverables: (A) unify EVERY non-vanilla file
  on .vply — asset.ply→asset.vply, decompose.ply→decompose.vply, Godot .relightply→.vply;
  train_base.ply STAYS .ply (genuine standard 3DGS); bytes/header identical, NO schema bump, NO
  gdgs edit (.relightply is runtime-loaded raw). (B) baseline-refresh helper so
  decompose --in train_base_clean.ply gates honestly — 48k-clobber guard decompose.py:465 stays
  intact. (C) relight_to_vanilla.py downgrade tool (inverse of vanilla_to_relight). Single source
  = schema.ASSET_EXT. NEXT SESSION: check if run finished → planner-verify → re-decompose both
  cleaned heroes (GPU step) into asset.vply.
- SuperSplat cleanup DONE + staged non-destructively (owner-confirmed mapping):
  assets/built/pxl_144634/train_base_clean.ply = 1,406,945 splats (−42%);
  assets/built/pxl_131945/train_base_clean.ply = 1,029,572 (−50%). Originals train_base.ply intact,
  gitignored. Downloads copies still present.
- .vply decision logged docs/decisions.md (2026-07-23): no non-vanilla file wears .ply; uniformity
  deliberate.

COMPRESS + POINT:
- docs-guide v0.26.0 (shipped + planner-verified GREEN + PUSHED this session) → one line; mechanics
  in docs/2026-07-23-handoff-docs-guide-v0.26.0.md
- splat-cleanup tool survey + ArtiFixer / DiffSplat / DiGS-3D eval → memory
  reference-splat-cleanup-tools.md (buy-not-build; ArtiFixer = 2D-frame refiner not a splat cleaner)
- push state → this session pushed main+tags through v0.26.0; 2 planner commits (arm+amend) unpushed

DROP:
- the disarm→edit→commit→re-arm dance mechanics (recurring known pattern; git gate blocks planner
  commits while armed)
- cactus-viewer launch debugging (grep-pipe caused early exit; relaunched clean)

UNCERTAIN:
- cactus viewer left RUNNING (pid 273087, DISPLAY=:0) — not killed; next session may need to.
- whether decompose.ply actually carries the splat_relight_schema header (unverified; implementer
  determines during deliverable A).
```

## Git state (safety net)
```
5f6480b (HEAD) Planner: amend .vply run — decompose.ply -> decompose.vply for uniformity
4d9fcca Planner: arm scoped run — .vply extension + cleanup round-trip enablement
90b2c37 Planner: reconcile queue — docs-guide SHIPPED v0.26.0 (planner-verified)
476140a docs-guide v0.26.0: pipeline walkthrough + core docstrings + README Docs
6473b0e Planner: arm scoped run — docs-guide (docs/pipeline.md + core docstrings)
```
`git status --short`: only untracked `lore/handoff_2026-07-19_paint-v0251-qwen-eval3.md` +
`lore/handoff_2026-07-22_splat-studio-hygiene-v0.25.2.md` (+ this file). **origin/main pushed
through `90b2c37` (main + tags v0.25.1/v0.25.2/v0.26.0 on GitHub); 2 planner commits (`4d9fcca`,
`5f6480b`) unpushed** (allow_push:false — owner pushes on request). Factory ARMED, implementer
session `32f0319f-4586-47c5-bb82-2f409be24d20` active at chandoff.

## Next action
Check whether the `.vply` factory run completed; if so, planner-verify GREEN (pytest + new gates
mutation-proven in the MAIN tree + zero `.relightply` left + relight_smoke on a `.vply` asset),
reconcile the queue banner, then **re-decompose both staged cleaned heroes** (GPU step) into
relightable `asset.vply`. Read order: CLAUDE.md + MEMORY.md → docs/decisions.md tail →
tasks/QUEUE.md + DECISIONS.md → this handoff.
