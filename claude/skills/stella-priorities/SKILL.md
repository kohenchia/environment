---
name: stella-priorities
description: Stella keeps Kohen's priorities - the three to five outcomes that matter most now - compares the actual work (sessions, daily logs) with them, and gives short insights on drift and focus. Use when Kohen sets or asks about priorities or focus, asks what to work on, or asks for insights.
---

# stella-priorities

The list lives in `~/.local/share/stella/priorities.md`: three to five outcomes, in order, direction not
tasks (tasks live in Kohen's task list), plus a "Say no to" list and the date it was last updated.

## Setting them

When Kohen states or changes priorities, rewrite the list in his words, set `Updated:` to today, and keep
the previous version under a dated `## History` heading at the end of the file. Never invent a priority;
if the list is empty or older than three weeks, ask him for it when it matters.

## Comparing work with them

Look at what actually happened: the agents (`/stella-agents`), the last week of daily logs in the vault's
`Daily/`, and `~/.local/share/stella/journal.md`. Then say, briefly and with evidence:

- which priority got the work, and which got none;
- work that serves no priority (is it a "say no to"?);
- anything stuck that blocks a priority;
- one suggestion for what to do next.

A short table (priority, work this week, state) is usually the clearest picture. End with a journal line.
