---
name: kc-plan
description: Write a plan for a development task or a project into the vault - researched against the real code, in Kohen's plan style. No code is written and nothing outside the vault changes. Use when Kohen types /kc-plan <task or project>, or asks for a plan, design doc or implementation plan.
---

# kc-plan

`/kc-plan <task or project>`. The output is one plan note in the vault. **Write no code, change no repo,
run nothing that writes outside the vault.** Reading, tracing and dry runs are fine.

## 0. Load what this machine adds

Read `~/.claude/kc-extensions/kc-plan.md` if it exists and follow it on top of this skill. Where it is
stricter, it wins.

## 1. Where the plan goes

`Projects/<Topic>/<Plan title>.md` in the vault (the vault's location is in the global instructions; read
the vault's own `CLAUDE.md` first, it is authoritative on folders, names and frontmatter). If a plan for
this already exists, revise it rather than starting another, and preserve Kohen's inline
`==**KC:** …==` comments verbatim.

## 2. Research until no question is left that the code can answer

- Trace every relevant code path across every repo involved, to the implementations, not the
  abstractions. Read both sides of each cross-repo call.
- Use parallel subagents for multi-repo research (set `model`: Sonnet by default), then synthesize.
- Resolve ambiguity by reading code. The only open questions a plan may carry are ones that need Kohen's
  judgment.

## 3. Debate the approach

For anything with more than one credible approach, name the alternatives and argue them (subagents as
advocates and a judge, for a large decision). The plan records the choice and why each alternative lost.

## 4. Write it in Kohen's plan style

The global instructions' "Writing project plans" section is the style; follow it exactly. In short: lead
with what ships and what stays the same; describe what the change does, not how; define every term and
invent none; precise facts; evidence in a Provenance section at the end, with the sha it was measured
against. Standard sections in order, omitting empty ones: summary, Scope, the problem, what it delivers,
Work items (numbered table), how we know it is right (acceptance bar and exact commands), Decisions
(numbered, each with the alternative and why it lost), Risks (with structural mitigations), Open
questions, Provenance.

## 5. Finish

Link the plan from the project's index note and `Projects.md` if the vault keeps one. Report the path,
the decisions taken, and the open questions for Kohen. `/kc-dev <plan path>` builds it.
