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

## 5. Keep the write-up in the vault's `Issues/` folder

Whenever Kohen asks you to debug or investigate an issue, the deliverable is also an issue report in the vault's
`Issues/` folder (a plain-language correction-of-errors report). Never skip it, and never write the
same issue twice:

1. Look first: grep `Issues/` for the error text, the feature and the Slack link. If a report for this issue exists,
   add to it or edit it (update the facts, add a dated line under `Timeline`, set `updated:`); otherwise create one
   from the vault's `Templates/Issue.md`.
2. Name: `YYYY-MM-DD First Last - Issue title`: the date the issue was raised and the full name of the person who
   raised it (the author of the original message; Kohen Chia when he found it himself). No `/` or `:` in a file name.
   The title is a claim: what is wrong and why.
3. Front-matter: `reporter` and `slack` (the link to the original message, or `unknown`), plus the vault's usual fields.
   Slack-derived text keeps its data-policy tags and never goes into a repo.
4. Body, in simple and explicit language that assumes no knowledge of the feature: **What happened** (what the person saw,
   as a concrete example with real values), **Why it happens** (the root cause, a worked example, every term defined where
   it first appears), **The fix**, **How to recognise it next time**, **What we could not confirm**, **Timeline**,
   **Evidence**. Show it, don't only say it: a before/after or a small table per scenario.
5. Add it to the `Issues` index note, and apply the angle-bracket rule above.

Offer a memory (not a vault note) only for how agents should work.
