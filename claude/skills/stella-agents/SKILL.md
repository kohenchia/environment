---
name: stella-agents
description: Stella's view of every Claude Code session on the machine - what each is doing, which are waiting on Kohen, which are stuck - and, with "tidy", the cleanup of finished sessions. Use when Kohen asks what is running, what needs him, to clean up dead or finished agents, or when Stella runs her morning check.
---

# stella-agents

`/stella-agents` reports; `/stella-agents tidy` reports, then cleans up.

## Look

1. `claude agents --json --all` lists every session: interactive and background, with `id`, `name`,
   `cwd`, `kind`, `status` (busy/idle) and `state` (working/blocked/done/…). Run it through
   `bash -c '…'` if the shell sandbox refuses it.
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

Report one line per session, grouped, waiting-on-Kohen first: name, folder, and what it needs from him in
his words (the NEXT FOR YOU items). Keep it to a screen.

## Tidy

Only for **Finished** sessions, and only when nothing is left open from them: their repo
(`git -C <cwd> status --short` and `git -C <cwd> log @{u}..` when there is an upstream) has nothing the
session left uncommitted or unpushed, and their last message asks nothing of Kohen. For each:
`claude rm <id>` (the transcript stays, so `claude --resume` still finds it). Never remove a session that
is busy, waiting on Kohen or stuck; list those for him instead, with what to do about each. A stuck session
on a rate limit or budget usually only needs `claude respawn <id>` later, or a token switch.

Also report stale worktrees under `~/github/*-wt/` whose branch is merged and clean (`wtl`), for Kohen to
remove with `wtr`; never remove them yourself.

Finish with what was removed, what was left and why, as one journal line in
`~/.local/share/stella/journal.md`.
