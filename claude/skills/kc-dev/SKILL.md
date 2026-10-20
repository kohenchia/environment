---
name: kc-dev
description: Build a feature or fix for Kohen, end to end, straight away - from a plan in the vault or from the instructions given - without writing a plan first. Works in a worktree, follows the target repo's own standards, tests and verifies, commits and pushes. Use when Kohen types /kc-dev <plan path | instructions>, or asks for something to be built, changed or fixed in code.
---

# kc-dev

`/kc-dev <plan | instructions>`. A plan is a note in the vault's `Projects/` folder; otherwise the argument
is the order itself. Go straight to building: no plan document is written (that is `/kc-plan`).

## 0. Load what this machine adds

Read `~/.claude/kc-extensions/kc-dev.md` if it exists and follow it on top of this skill. Where it is
stricter, it wins.

## 1. Understand the order

- With a plan: read it in full, including inline `==**KC:** …==` comments. Execute every step, including
  integration steps against external systems; a step you cannot complete is reported as blocked, never
  skipped quietly.
- Check the plan is still true before building it. If code it touches changed since the sha in its
  Provenance (`git log <sha>..origin/main -- <paths>`), re-check the claims the work items rest on; if the
  change invalidates any, revise the plan with `/kc-plan` first instead of building a fix for a problem
  that no longer exists.
- Read the target repo's `CLAUDE.md` (or README) and follow it exactly. Check for a `justfile` before a
  `Makefile`; use the repo's task runner for format, lint and test. `uv run` for Python, `git --no-pager`
  for git.
- Grep for two or three existing implementations of the same pattern and match them. Before removing or
  renaming anything public, grep every caller.
- Ask only for decisions that are genuinely Kohen's: something the order, the plan, the code and sensible
  defaults cannot settle. Batch the questions; never ask what reading the code answers.

## 2. Decide the design, briefly

For anything beyond a small fix, settle the design in the session before writing code: the problem in one
sentence, the design, and why it beats the next-best alternative. When more than one design is credible,
debate them with subagents (one advocate each, one judge who tries to disprove them) and pick one. Say the
chosen design to Kohen in a few lines, then build; do not wait for approval unless the order says to.

## 3. Build

- Work in a worktree made with the `wta` helper (`zsh -i -c 'wta <repo> <branch>'`), never with raw
  `git worktree` or a native worktree tool. Personal tooling repos may be edited in place when the order
  is small and the tree is clean.
- Test-first where the repo has tests: write the failing test, make it pass.
- Delegate mechanical steps to subagents when it helps; set `model` on each (Sonnet by default, Opus only
  for the deepest judgment). You stay responsible for every line.

## 4. Verify before claiming done

Run the repo's gates (format, lint, type check, tests) and exercise the change for real as far as local
and dry runs allow. Evidence before assertions: quote the commands and their results. If anything fails,
say so with the output.

For a non-trivial change, run `/kc-review` on the committed branch and act on its report: apply each ask,
decline one only with code evidence, or bring a real judgment call to Kohen.

## 5. Commit and push

Commit with the repo's message conventions. Push the branch: a push to the public
`~/github/environment` is checked by the machine's leak check and goes through when it finds nothing (on a
hit it is denied: rewrite the hits generically, amend, push again); other pushes are not gated. Never put a
bypass on a push, and never open a PR unless asked.

## 6. Report

Lead with what changed for the user (a before/after picture when it helps), then what was verified and
how, then anything left open. End with the status block.
