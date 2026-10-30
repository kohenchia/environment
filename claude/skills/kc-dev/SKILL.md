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
- Read the plan's Decision closure and Delivery sections: they settle names, the PR split, the merge order,
  tickets, reviewers, fallbacks and warn-or-refuse. Kohen's go to build accepts every default the plan records, so
  take each one without asking again.

## 2. Decide the design, briefly

For anything beyond a small fix, settle the design in the session before writing code: the problem in one
sentence, the design, and why it beats the next-best alternative. When more than one design is credible,
debate them with subagents (one advocate each, one judge who tries to disprove them) and pick one. Say the
chosen design to Kohen in a few lines, then build; do not wait for approval unless the order says to.

## 3. Keep going: decisions while building

Never end a turn on a decision while there is work it does not block. One build ended its turns on eight calls,
seven of them already carrying the builder's own recommendation. It worked 3.5 hours and waited 9.9.

- **A choice the plan settled** (or the order, the code, or the repo's conventions settle) is not a question: take
  it.
- **A choice nobody foresaw**: decide it the way the plan's decisions point, the reversible way, and write it down
  (in the plan's Decision closure with `taken while building`, or the PR description when there is no plan). Then
  keep going.
- **A call that is genuinely Kohen's** (anything outward-facing, a contract the order did not name, a scope change
  that adds or drops a deliverable, or a row the plan marks as his): take the default if one is reversible and keep
  building on it. If none is, park that part and build everything else.
- **Batch the calls into the end-of-turn list after the PR is up**, never one question per finding. Each call states
  the default taken and is marked `blocks merge` (the PR must not merge until he answers) or `can wait` (the
  default stands until he overrules it). A call that is not `blocks merge` is `can wait`.

**Caps per task.** The plan's Delivery table is the PR count (with no plan: one PR per order, plus a docs companion
the repo requires). A further PR, a split, or work outside the plan's work items is a `can wait` call; until Kohen
says yes, the work becomes a follow-up ticket. A defect found that predates the work is a follow-up ticket, never a
fix in this PR.

## 4. Build

- Work in a worktree made with the `wta` helper (`zsh -i -c 'wta <repo> <branch>'`), never with raw
  `git worktree` or a native worktree tool. Personal tooling repos may be edited in place when the order
  is small and the tree is clean.
- Test-first where the repo has tests: write the failing test, make it pass.
- Delegate mechanical steps to subagents when it helps; set `model` on each (Sonnet by default, Opus only
  for the deepest judgment). You stay responsible for every line.

## 5. Verify before claiming done

Run the repo's gates (format, lint, type check, tests) and exercise the change for real as far as local
and dry runs allow. Evidence before assertions: quote the commands and their results. If anything fails,
say so with the output.

For a non-trivial change, run `/kc-review` on the committed branch, **one round per PR**, and act on its final report
(not a provisional first report, whose `Depth:` line begins `IN PROGRESS:`):

- every `blocks merge` ask is fixed, with a test that fails without the fix, or declined with code evidence, or
  put to Kohen as a `blocks merge` call;
- a `can follow` ask goes into the one fix commit after the review only when it is small (a few lines in files the
  PR already changes, no new behaviour). That is the cap on fast-follow work in a PR. Every other one becomes a
  follow-up ticket, drafted where the plan's ticket rule says, and one `can wait` call lists them;
- the fixes are verified by the gates and the tests, not reviewed again: the report says "fixes verified, not
  re-reviewed". A second round runs only when Kohen asks for one.

## 6. Commit and push

Commit with the repo's message conventions. Push the branch: a push to the public
`~/github/environment` is checked by the machine's leak check and goes through when it finds nothing (on a
hit it is denied: rewrite the hits generically, amend, push again); other pushes are not gated. Never put a
bypass on a push, and never open a PR unless asked.

## 7. Report

Lead with what changed for the user (a before/after picture when it helps), then what was verified and
how, then anything left open. End with the status block: the calls of step 3, each marked `blocks merge` or
`can wait` with the default taken, `blocks merge` first.
