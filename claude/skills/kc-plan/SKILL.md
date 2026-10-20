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

**Revising a plan is re-planning, not editing.** Its Provenance names the sha it was measured against: list
everything that merged since then in the code the plan touches (`git log <sha>..origin/main -- <paths>`), and
re-check every claim in it against today's `main`. A plan measured two weeks ago may describe a problem that
is already fixed. A review of the plan (its findings are asks, not suggestions) is an input to the revision:
each ask is applied or answered in the plan.

## 2. Research until no question is left that the code can answer

- Trace every relevant code path across every repo involved, to the implementations, not the
  abstractions. Read both sides of each cross-repo call.
- Use parallel subagents for multi-repo research (set `model`: Sonnet by default), then synthesize.
- Resolve ambiguity by reading code. The only open questions a plan may carry are ones that need Kohen's
  judgment.
- **Check it is not already solved.** Before designing, search merged and open PRs, and the tickets, for the
  same symptom and the same code (`gh pr list --state all --search …`, `git log origin/main -- <paths>`).
  Work already landed or in flight changes the problem; a plan that duplicates it is the wrong plan.
- **A subagent's claim is a lead, not a fact.** Every fact the plan's argument rests on (what broke, which
  run, what a system does today, what another repo pins) is checked against its primary source by someone
  other than the agent that reported it: the code at `origin/main`, the live record (a run's status, an
  object's fields), a grep across every repo named. Drop what cannot be confirmed, or label it unverified.
- **Evidence is durable.** Data the plan relies on (queries, exports, sampled outputs) is saved next to the
  plan in the vault, never only in `/tmp` or a session directory, so a reviewer can check it later.
- **Test a rule before proposing it.** Any rule, threshold or heuristic the plan introduces (a check that
  fails a step, a limit, a classifier) is run offline against real known-good and known-bad cases, and the
  plan records the numbers. A rule that fails a healthy case is not proposed.

## 3. Debate the approach

For anything with more than one credible approach, name the alternatives and argue them (subagents as
advocates, a challenger and a judge, for a large decision). The plan records the choice and why each
alternative lost.

Widen the field first, as `kc-review` step 2 says: for every hard constraint the research found, search
all the repos for where it is already worked around; walk the layers (user surface, our code, the
platform's configurable data, the platform's code, upstream) before going upstream; test every option
dropped before the debate, including those dropped in an earlier round; treat principles as costs, and
check the codebase for precedents that already depart from them. The challenger's only task is to find
the strongest alternative the list omits or dropped, and the judge must answer it.

## 4. Write it in Kohen's plan style

The global instructions' "Writing project plans" section is the style; follow it exactly. In short: lead
with what ships and what stays the same; describe what the change does, not how; define every term and
invent none; precise facts; evidence in a Provenance section at the end, with the sha it was measured
against. Standard sections in order, omitting empty ones: summary, Scope, the problem, what it delivers,
Work items (numbered table), how we know it is right (acceptance bar and exact commands), Decisions
(numbered, each with the alternative and why it lost), Risks (with structural mitigations), Open
questions, Provenance.

Every command in "how we know it is right" is real: run it, or at least parse it (`--help`, `--dry-run`),
against `origin/main`. A command naming a path or option that does not exist is a defect in the plan.

## 5. Review it before handing it over

Run `/kc-review <plan path>` on the finished plan (it reviews documents at full depth) and treat its asks
as the next revision: apply each one, or answer it in the plan, then review again. Stop when the verdict is
`Adopt as written`, or `Adopt after changes` with no ask tagged `blocks adoption` left. If a decision only
Kohen can make blocks the verdict, stop and put it to him rather than choosing for him.

## 6. Finish

Link the plan from the project's index note and `Projects.md` if the vault keeps one. Report the path,
the review verdict and its report, the decisions taken, and the open questions for Kohen.
`/kc-dev <plan path>` builds it.
