---
name: kc-log
user-invocable: true
description: Append today's work to the daily log in Kohen's Obsidian vault (Daily/YYYY-MM-DD.md). Use when asked to log the day, write up what was done, update the daily note, or at the end of a working session — e.g. "/kc-log" or "/kc-log just the parser debugging". Also handles Stella's nightly log of every session that day, and the weekly grooming pass.
---

# kc-log

Append what actually happened to the daily log at `Daily/YYYY-MM-DD.md` in the vault (its
location is in the global instructions).

Before anything else, read `~/.claude/kc-extensions/kc-log.md` if it exists and follow it on
top of this skill: it names this machine's tools for sourcing identifiers and where tasks live.

Invoked as `/kc-log [what to log]`. With no argument, summarize the current session's
work. With an argument, log only what it describes. `/kc-log day [YYYY-MM-DD]` logs the
whole day across every session (see "The whole day", below); Stella runs it nightly.

## Get the date from the system

```bash
date +%Y-%m-%d          # filename
date "+%A, %-d %B %Y"   # H1, e.g. "Thursday, 13 August 2026"
```

Never infer today's date from context or from the newest file in `Daily/`.

## Find or create today's note

1. If `Daily/<date>.md` exists, **append to it** — Obsidian's
   daily-notes plugin may have created it, or an earlier `/kc-log` run.
2. If not, create it from the vault's `Templates/Daily note.md`, substituting
   `{{date:YYYY-MM-DD}}` and `{{date:dddd, D MMMM YYYY}}`.

Never overwrite the file, and never rewrite lines that are already there — Kohen edits
these by hand and may have ticked things off. Append under the existing headings.

## What goes where

**`## Touched`** — one line per thing worked on, with the real link:

- PRs, jobs, pipelines, tickets, chat threads.
- What changed, not how you felt about it. `Fixed the cache key in the CI image build
  (infra#466)`, not `worked on some CI issues`.

**`## Learned`** — anything that cost more than ten minutes to figure out.

- These are the candidates for `Notes/`. A line here means "this was expensive to
  discover once".

Some daily notes still have a legacy `## Open` section. Leave it alone; don't add one to
new notes.

## Rules

1. **Never fabricate an identifier.** Every run ID, PR number, pipeline version, task
   ID, and ticket must come from the session or from a tool (the extension names them).
   If you can't source it, describe the thing without the ID.
2. **No task tracking.** Work tracking lives in Kohen's task list (the extension says
   where). Never add TODO items or checklists to the log. If something needs tracking, say so in
   your reply and let Kohen put it on the list.
3. **Don't pad.** If the session produced nothing worth logging, say that instead of
   inventing entries. A short log is fine; a fictional one is not.
4. **Deduplicate.** Check the existing content before appending. Extend a line rather
   than adding a near-duplicate.
5. **Obsidian Sync is usually running**, and today's note is the file most likely to be
   open. Mention in your reply that you edited it.

## Promote what's durable

After appending, look at what landed under `## Learned` and offer the next step — don't
do it unprompted:

- A root-caused bug across repos → a note from the vault's
  `Templates/Investigation.md` in `Notes/`.
- A standalone fact worth recalling → a note from `Templates/Note.md` in `Notes/`.
- A whole mechanism worth explaining → `/kc-tutorial`.
- Something that changes how an agent should work → a memory in
  `~/.claude/projects/<project>/memory/`, not the vault.

## Weekly pass

When asked to groom (`/kc-log groom`, "clean up my daily notes"):

1. Read the last 7–10 notes in `Daily/`.
2. Pull out anything durable still sitting only in a daily note and propose specific
   `Notes/` entries for it.
3. Check whether any project note's state is now out of date — verify its links with the
   tools the extension names, and report drift.
4. Report a summary of the week. Don't delete or rewrite the daily notes; they're the
   raw record.

## The whole day

`/kc-log day [YYYY-MM-DD]` (default: yesterday when run before 06:00, else today) logs every
session's work for that day, not just this one:

1. List the day's transcripts: `~/.claude/projects/*/*.jsonl` modified that day.
2. For each, read what was done (subagents may summarize transcripts in parallel; Sonnet).
   Skip sessions that only chatted.
3. **Log only work COMPLETED that day**: merged, pushed, sent, finished, decided, learned.
   Work only started or discussed waits for the day it finishes.
4. Follow every rule above; this run is unattended, so ask nothing. Derived content from
   chat tools keeps its data-policy tags.

## Finish

Report the file path, which sections you appended to, how many lines, and anything you
deliberately left out (unsourced identifiers, work that belongs on the task list).
