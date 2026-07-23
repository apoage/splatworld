# Handoff — Splat Studio hygiene batch v0.25.2 verified (2026-07-22)

- **Branch:** main · **Working dir:** /home/lukas/splatworld
- **Session focus:** independently reconciled the scoped dark-factory hygiene run →
  **v0.25.2 CONFIRMED GREEN** (mutation-proven). Nothing rolled back; ship stands.

## Confirmed compaction rubric (chandoff 2026-07-22)

```
FRAMING: record dark-factory work as plain scoped runs + planner verification. Do NOT
attribute or distinguish which model ran a run, and drop all "alt-model eval #N" framing —
that was assumption, not fact, and is not a distinction worth carrying.

KEEP IN FULL:
- v0.25.2 SHIPPED + planner-verified GREEN. Splat Studio hygiene batch:
  #2 nudge/delete resolve by id OR target (new _op_target_id helper in scatter_core.gd);
  #3 resync_materials skips is_queued_for_deletion() nodes (carpet_loader.gd);
  #4a honest OK prints (per-check n0 := problems.size() gate) + undo return;
  #4b !is_inside_tree() spam killed (async _check_resync + await process_frame);
  #4c middle-variant erase coverage; #4d %g -> %.4f.
  Independent verify: pytest 141; all 4 Godot smokes PASS; the two new gates
  (op-key alias + resync-qfree) MUTATION-PROVEN red->green in the MAIN tree with a restore
  trap; is_inside_tree runtime spam = 0; load_carpet byte-identical; scope/lanes clean.
  Commits 26a293e (code) + 7534095 (handoff), tag v0.25.2.
- Git anomaly RESOLVED: a mid-run `git reset --hard` (reflog: e2a7e01 HEAD@{2}) briefly
  reverted scatter_core/carpet_loader; recovered before commit. Final tree complete, no
  lost work (net diff vs e2a7e01 has the full expected fileset).
- Splat Studio follow-ups #1-#4 ALL DONE (v0.25.1 paint cross-dab + v0.25.2 hygiene).
  Remaining #5/#6 = owner-attended 4b (viewer wiring + rest of tool belt), NOT factory-takeable.
- REUSABLE GOTCHA: mutation/red-tests run in the MAIN tree, never a worktree — a fresh
  worktree lacks the gitignored .godot/ class cache so GDGS class_name GaussianSplatNode
  fails to parse. Use git checkout <ref> -- <file> + a restore trap.
- NEXT: owner-attended 4b viewer work is the M4 critical path (planner lean: hold the
  factory for that rather than burn a pass on filler — quality-pass 6 / docs-guide / pixel5).

COMPRESS + POINT:
- v0.25.2 mechanics + verification detail -> docs/2026-07-22-handoff-splat-studio-hygiene-v0.25.2.md
- hygiene spec -> tasks/2026-07-19-splat-studio-hygiene.md (bannered SHIPPED)

DROP:
- All model-identity / eval-numbering narrative across the session (which model ran what).
- The context-scrub plan I proposed (file rewrites, commit-message rewrite) — owner declined.
- Blow-by-blow of the earlier failed/floundered worker run; keep only the GOTCHA.

UNCERTAIN:
- Cosmetic: async _check_resync leaves a spurious _check_resync:546 frame in unrelated
  later error backtraces (log-readability only, no pass/fail impact) — fix someday or ignore.
```

## Git state (safety net)
```
7534095 (HEAD) docs: handoff — Splat Studio hygiene batch v0.25.2
26a293e Splat Studio hygiene batch v0.25.2 (#2 op-key alias + #3 resync qfree guard + #4 test/log hygiene)
e2a7e01 Planner: verify v0.25.1 (mutation-proven green) + arm hygiene batch
35a3220 Reconcile paint cross-dab run: banner v0.25.1 SHIPPED, task spec, handoff
663a562 Splat Studio follow-up #1 (v0.25.1): Paint cross-dab Poisson spacing + gate gap
```
`git status --short`: only `?? lore/handoff_2026-07-19_paint-v0251-qwen-eval3.md` (stale, untracked)
+ this new file. Tags: v0.25.0, v0.25.1, v0.25.2. **origin/main @ `042003a` — 5 commits unpushed,
nothing pushed this session.** Factory disarmed.

## Next action
Owner-attended: M4 4b viewer wiring (SplatStudio panel onto the viewer) + rest of the tool belt
(#5/#6). Factory idle/disarmed — hold for the attended 4b block, or pick a filler slice if unattended.
Read order: CLAUDE.md + MEMORY.md → docs/decisions.md tail → tasks/QUEUE.md + DECISIONS.md → this handoff.
