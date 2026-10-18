---
name: stella-agents
description: Stella's report on every session (what runs, what waits on Kohen, what is stuck) and, with "tidy", the cleanup of finished ones. Stella's own session runs it; other sessions do not need it.
---

# stella-agents

`/stella-agents` reports; `/stella-agents tidy` reports, then cleans up.

## Look

1. `~/.local/bin/stella projects` first (the crew grouped by project, with the decisions waiting in each),
   then `~/.local/bin/stella agents --all`, which lists every session (the same JSON as `claude agents --json --all`,
   through the one command allowed outside the sandbox): `id`, `name`, `cwd`, `kind`, `status`
   (busy/idle) and `state` (working/blocked/done/…). Her crew are the sessions with a record in
   `~/.local/share/stella/crew/`; adopted ones carry `"adopted": true`.
2. For each background session, `~/.claude/jobs/<id>/state.json` holds what it was asked (`intent`), its
   state and what it needs (`needs`, `detail`). For more, read the tail of its transcript
   (`~/.claude/projects/*/<sessionId>.jsonl`), or `claude logs <id>`.
3. Sort them:

| Group | Means |
|---|---|
| Waiting on Kohen | Its last turn ended with a NEXT FOR YOU block, or its state is blocked on a question |
| Working | Busy, or a turn with WORKING |
| Stuck | Blocked on an error (rate limit, budget, crash) or no progress for hours |
| Finished | Done, last turn ALL DONE |

Report as four sections: **Needs you** (waiting on Kohen, most important first as Stella's manual ranks them, with what he needs to do in the session's own
words), **Landed** (finished since the last digest, with the PR or report), **Underway** (working; a team
as one line, `team · D/N done · W working`), **Queued** (over a cap, with why). Keep it to a screen.

## Tidy

Crewmates Stella launched: `~/.local/bin/stella rm <name>` for each finished one; it removes the session
and its worktree (and closes its tab, if one is open) only when the work has landed, and says what is missing otherwise.
An open PR counts as not landed, whatever the mode: `stella rm` refuses a session whose record `pr`, or
whose branch's PR, is still OPEN, and says so. Leave that session in place: removing it would leave the PR
unwatched. If its PR should be watched without the session, `stella track-pr <url>` first. Track records
(`mode: track`) follow the same rule: `stella rm` removes one once its PR is merged or closed. Never adopted
ones.

Other sessions: only **Finished** ones, and only when nothing is left open from them: their repo
(`git -C <cwd> status --short` and `git -C <cwd> log @{u}..` when there is an upstream) has nothing the
session left uncommitted or unpushed, their branch has no open PR (`gh pr view` in its `cwd`), and their last
message asks nothing of Kohen. For each:
`claude rm <id>` (the transcript stays, so `claude --resume` still finds it). Never remove a session that
is busy, waiting on Kohen or stuck; list those for him instead, with what to do about each. A stuck session
on a rate limit or budget usually only needs `claude respawn <id>` later, or a token switch.

Also report stale worktrees under `~/github/*-wt/` whose branch is merged and clean (`wtl`), for Kohen to
remove with `wtr`; never remove them yourself.

Finish with what was removed, what was left and why, as one journal line in
`~/.local/share/stella/journal.md`.
