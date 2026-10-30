---
name: kc-debug
description: Debug or investigate a problem for Kohen - a failure, a bug, an incident, or a "why does X happen / how does X work" question - and come back with the root cause and evidence. Changes nothing unless Kohen asks for the fix. Use when Kohen types /kc-debug <problem>, or asks to debug, investigate, root-cause or explain a behaviour.
---

# kc-debug

`/kc-debug <problem>`. The deliverable is the root cause (or the answer), with evidence, and the fix
recommended. Do not change code, config or remote state while investigating; propose the fix and apply it
only when Kohen says so (or hand it to `/kc-dev`).

## 0. Load what this machine adds

Read `~/.claude/kc-extensions/kc-debug.md` if it exists and follow it on top of this skill: it names the
tools for this machine's jobs, logs and systems.

## 1. If Kohen is blocked, unblock him first

When something he relies on is broken, give him a working workaround right away (the exact commands), then
do the thorough investigation.

## 2. Reproduce and gather facts

- Restate the symptom precisely: what was expected, what happened, where, since when.
- Reproduce it, or find the logs, jobs or transcripts that show it. Never invent an identifier; every run
  ID, PR, commit and log line comes from a tool or a file.
- Read the code that produced the behaviour, at the version that ran, across every repo involved.

## 3. Find the root cause, systematically

Form hypotheses, then test each against evidence; do not stop at the first plausible story. Trace back
from the symptom to the first thing that went wrong. For a wide search, fan out parallel subagents (set
`model`: Sonnet by default, Opus for adversarially checking the conclusion) with one hypothesis or one
repo each.

## 4. Report

Lead with a picture of what happens (the sequence, the before/after, a table per scenario with a worked
example), then the root cause in one sentence, the evidence (file:line, log lines, commands and their
output), the fix you recommend, and how to confirm it. Say what you could not confirm.

A report or note written into the vault follows one more rule. **Angle brackets.** Obsidian reads a bare `<name>` as an HTML tag: the text vanishes and, alone on a line, it stops
markdown rendering until the next blank line. Write every placeholder or quoted argument as inline code (`` `<pr>` ``)
or as `&lt;pr&gt;`, never bare, and a `|` inside a table cell as `\|`. Before saving, run
`python3 ~/.claude/skills/kc-review/mdcheck.py <file>` on each file written to the vault; it must print nothing
(`--fix` wraps complete tags; the safe forms by context are in kc-review, "Text Obsidian can render").

If it cost real effort to find, offer to record it: a note in the vault's `Notes/` (via the vault's
investigation template, if it has one) for how a system works, or a memory for how agents should work.
