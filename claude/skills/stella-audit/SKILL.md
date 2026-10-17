---
name: stella-audit
description: Stella's audit of Kohen's whole agentic knowledge base - agent memories, CLAUDE.md instructions, skills and their extensions, agent definitions, vault notes, the canons - for contradictions, stale or dead pointers, duplicates, leaks and gaps, with fixes proposed. Use when Kohen asks for an audit, a knowledge or memory cleanup, or weekly when Stella's schedule runs it.
---

# stella-audit

`/stella-audit [area]`. Read everything in scope, then report findings with fixes. Apply a fix only when
Kohen says so, except mechanical ones he has already agreed to in principle (a dead link to a moved file,
an index line missing for an existing note), which you apply and list.

## What to read

| Area | Where |
|---|---|
| Global instructions | `~/.claude/CLAUDE.md` and everything it imports |
| Repo instructions | `~/github/*/CLAUDE.md` |
| Memories | `~/.claude/projects/*/memory/` (each `MEMORY.md` index and its files) |
| Skills and extensions | `~/.claude/skills/*/SKILL.md`, `~/.claude/kc-extensions/`, plugin skills in use |
| Agent definitions | `~/.claude/agents/` |
| Canons and review knowledge | `~/.local/share/stella/canon.md`, `~/.local/share/kc-review/knowledge.md`, any domain canon the extension names |
| The vault's knowledge layer | the vault's `Notes/` (index `Notes.md`) and its `CLAUDE.md` |

Spawn parallel Sonnet subagents, one per area, each returning findings with file:line evidence.

## What to look for

- **Contradictions**: two sources that tell an agent different things (which one is right, by the code or
  by Kohen's latest word).
- **Stale pointers**: a file, command, flag, skill, agent or path that no longer exists. Check each one.
- **Duplicates**: the same fact in several places, which will drift; name the one place it should live.
- **Wrong layer**: how-a-system-works facts in memories (they belong in the vault's `Notes/`), how-agents-
  should-work rules in the vault (they belong in memory or instructions), work-specific content in the
  personal environment repo, secrets or chat quotes in any repo.
- **Gaps**: a correction Kohen made more than once that no source records.
- **Bloat**: instructions so long they will not be followed; propose the cut.

## Report

Most important first, one line each: what, where, the fix. Then the mechanical fixes applied. Then a
journal line in `~/.local/share/stella/journal.md`.
