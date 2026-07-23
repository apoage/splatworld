# Handoff #13 — Paint cross-dab v0.25.1 verified + Splat Studio hygiene eval #3 (Qwen) in flight (2026-07-19)

Previous: `lore/handoff_2026-07-19_splat-studio-multiline.md`
(chain: … #11 d8-readme-run13-arm → #12 splat-studio-multiline → **#13 this**)

- **Branch:** main · **Working dir:** /home/lukas/splatworld
- **Session focus:** independently reconciled + verified the Kimi K3 paint cross-dab run (**v0.25.1
  CONFIRMED GREEN**, mutation-proven) → answered the two unblock questions (batch #2+#3+#4 + fold `%g`)
  → wrote + **armed** the Splat Studio hygiene batch as **alt-model eval #3 (Qwen local)** → committed a
  clean **planner rollback boundary `e2a7e01`** (disarm→commit→re-arm around the dark-factory commit
  gate). Eval #3 was **IN FLIGHT** at chandoff (Qwen worker running; untracked scratch already in
  `tasks/`). Splatworld-only session; dark-factory multiline stays a separate repo/research track.

## Confirmed compaction rubric (chandoff 2026-07-19)

```
KEEP IN FULL:
- v0.25.1 (Paint cross-dab #1) SHIPPED + INDEPENDENTLY planner-verified (mutation-proven: new
  _check_paint_poisson gate RED 28/32 on buggy scatter_core, GREEN on fix; pytest 141; diff trace).
  Kimi K3 implemented (alt-model eval #2) — result STRONG (one-shot clean, honest self-evidence,
  correct scope discipline). NOT graded-its-own-homework (planner re-verified independently).
- eval #3 IN FLIGHT NOW: Qwen LOCAL worker running tasks/2026-07-19-splat-studio-hygiene.md
  (followups #2 op-key id/target alias + #3 resync is_queued_for_deletion guard + #4 smoke
  log/test honesty + the %g latent). One-task-then-stop. Untracked worker scratch already in
  tasks/ (nudge_delete_test.py, splat_studio_hygiene_plan.md) — lane-hygiene flag; don't touch.
- Rollback boundary = e2a7e01 (planner commit). ALL LOCAL/unpushed (HEAD 3 ahead of origin/main
  @ 042003a). Rollback: git reset --hard e2a7e01 (keep prep, drop Qwen) or v0.25.1/35a3220 (green
  code); git tag -d any bad tag Qwen cuts.
- GOTCHA (reusable): mutation/red-tests MUST run in the MAIN tree, not a git worktree — a fresh
  worktree lacks the gitignored .godot/ class cache so GDGS class_name GaussianSplatNode fails to
  parse. Use git checkout <ref> -- <file> + a restore trap. (Serialize red-tests in the live tree.)
- dark-factory COMMIT GATE: planner CANNOT commit while armed. For a planner rollback boundary:
  disarm → commit → re-arm (safe only when the factory is idle between runs).
- Process → multiline (SEPARATE repo, NOT this session): worker-cap death now 2-for-2 (GLM
  impl-side v0.25.0, Kimi verify-side v0.25.1) = D10 B-route evidence.
- NEXT: reconcile Qwen's hygiene run when it STOPS — independent verify (mutation-proof #2 both-keys
  + #4c middle-erase gates; load_carpet/resync byte-identity; scope+lane hygiene incl. the tasks/
  scratch) → ship or rollback. Then followups #5/#6 (owner-attended 4b), M4 tasks 5/6, owner-gated
  M3 acceptance.

COMPRESS + POINT:
- v0.25.1 reconcile/verify + eval notes + process findings → docs/2026-07-19-handoff-paint-cross-dab-v0.25.1.md
- Hygiene batch spec (#2+#3+#4+%g) → tasks/2026-07-19-splat-studio-hygiene.md
- Paint fix #1 mechanics → collapse to "shipped v0.25.1" (spec: tasks/2026-07-19-paint-cross-dab-spacing.md, STATUS banner)

DROP:
- The over-engineered "weak-model" first draft of the paint task + the abandoned spec-review workflow
  (wf_4f105c35-99d). Keep only: owner corrected "K3 not weak → prepare tasks at normal register."
- The invalid first mutation attempts (worktree parse errors) blow-by-blow — keep the distilled GOTCHA.
- AskUserQuestion mechanics — keep the answers (batch #2-#4; fold %g into #4).

UNCERTAIN:
- Whether the mutation-in-main-tree / .godot-cache gotcha should become a memory (reference) entry
  vs living only in the handoff (reusable across sessions).
- Whether Qwen's untracked tasks/ scratch is benign worker-workspace or a real lane violation —
  resolve at reconcile.
```

## Git state (safety net — snapshot at chandoff, Qwen run in flight)
```
e2a7e01 Planner: verify v0.25.1 (mutation-proven green) + arm eval #3 hygiene batch
35a3220 Reconcile paint cross-dab run: banner v0.25.1 SHIPPED, task spec, handoff
663a562 Splat Studio follow-up #1 (v0.25.1): Paint cross-dab Poisson spacing + gate gap
042003a docs: handoff #12 — Splat Studio v0.25.0 (GLM worker) + multiline design/scaffold
b06003c Design: dark-factory multiline (B route) + DECISIONS D10
```
`git status --short` at chandoff (Qwen worker scratch — will change as it runs):
```
?? tasks/nudge_delete_test.py
?? tasks/splat_studio_hygiene_plan.md
```
Tags … v0.25.0, **v0.25.1** (`663a562`). Rollback boundary **`e2a7e01`**. Nothing pushed (origin/main @
`042003a`, HEAD 3 ahead). Factory **ARMED** (`state.json`, gitignored → hygiene batch, boundary noted).

## Next action
**Reconcile Qwen's eval #3 hygiene run once it STOPS** (single-task protocol): check `git log`/tree for
its commit; independently verify (mutation-proof the new #2 both-keys + #4c middle-erase gates in the main
tree with a restore trap; confirm `load_carpet`/resync byte-identity, pytest 141, sibling smokes; assess
scope + lane hygiene incl. the `tasks/` scratch files) → ship (banner/tag) or `git reset --hard e2a7e01`.
Then: followups #5/#6 (owner-attended 4b), M4 tasks 5/6, owner-gated M3 acceptance. Read order:
CLAUDE.md + MEMORY.md → docs/decisions.md tail → tasks/QUEUE.md + DECISIONS.md → this handoff →
docs/2026-07-19-handoff-paint-cross-dab-v0.25.1.md + tasks/2026-07-19-splat-studio-hygiene.md.

Sequence: **#13**.
