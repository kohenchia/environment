---
name: kc-review
description: Deep review of a PR, a branch, a worktree or a set of documents (design docs, RFCs, vault notes, gists, repo files) for Kohen, consistent with the reviews he has given before. Debates the best design among real alternatives, then checks UX simplicity, robustness, consistency with existing patterns and code quality to the target repo's standards. Writes a short report to the vault and stays in the session for questions. Never posts anything. Use when Kohen types /kc-review <pr|branch|path|doc url(s)> [focus], or asks for a review.
---

# kc-review

`/kc-review <subject> [focus]`. The subject is a PR (number or URL), a branch or worktree path, or one or
more documents reviewed as a set. The focus, if given, is where to spend the most care; it never shrinks
the review below the five questions.

## 0. Load what this machine adds

Read `~/.claude/kc-extensions/kc-review.md` if it exists and follow it on top of this skill: it adds
domain principles, knowledge sources, report conventions and verdict words for this machine's work. Where
it is stricter than this skill, it wins.

Then read Kohen's review knowledge, the record of how he reviews: `~/.local/share/kc-review/knowledge.md`
(create it from the template at the end of this skill if it is missing). Every principle there is a
correction he made once; a review that repeats a corrected mistake is a failed review.

## 1. Get the subject, read-only

- A PR or branch: check it out in a review worktree with the `wta` helper
  (`zsh -i -c 'wta <repo> review/pr-<N> <head>'`), never in the main checkout, and never edit it. Note the
  head sha: every claim in the report is about that sha.
- Documents: fetch each one and save a copy with its revision (or fetch time) next to the report, so the
  review stays true to what was read. Several linked docs are one subject: review them as a set, in the
  order they depend on each other.
- Read the target repo's `CLAUDE.md`, its contributing docs, and its lint and test config. Those are the
  coding standards the implementation is held to, not general taste.

## 2. Design the answer before reading the proposal

State the problem the subject solves in one or two sentences, without its solution. Then design what the
best solution would look like, from the problem, the codebase and the knowledge, before looking at the
subject's approach. This is the guard against anchoring on whatever the author chose.

Before naming alternatives, widen the field. Each of these has missed a better design before:

- **Same constraint, solved elsewhere.** List the hard constraints the research found ("the scheduler
  pairs steps by X", "a run holds one Y per Z"). For each, search every repo involved for the places that
  already work around it, in any feature or subsystem, not only the one under review. Every existing
  workaround is a candidate alternative.
- **Walk the layers before going upstream.** For a constraint, try in order: the user surface, our own
  code, the platform's configurable data (rows, rules, types and settings a client can already write),
  the platform's code, an upstream change. Rule out each layer with evidence before proposing the next.
- **Nothing is dropped unexamined.** An option dropped before the debate needs a one-line reason
  checked against the code, and an option dropped in an earlier round is re-tested, not inherited.
- **Principles are costs, not vetoes.** When a principle would eliminate an option, check whether the
  codebase already departs from it. If it does, report the drift and present the departure as a cost for
  Kohen to weigh.

Name two to four credible alternatives (the subject's approach is one of them). Debate them for real:
for anything bigger than a small fix, spawn one subagent per alternative to argue for it as strongly as
the code allows, plus one challenger whose only task is to find the strongest alternative the list omits or
dropped, then one judge subagent to try to disprove each case against the code and to answer the
challenger. You decide which
design wins and say why the others lost. A small fix gets the same reasoning inline. If the subject is
not the best design, the review says so first: everything else is secondary.

## 3. The five questions

Answer each for the chosen design and for what the subject actually does:

| # | Question | What a yes looks like |
|---|---|---|
| 1 | Is this the best design, rigorously debated? | It wins the debate in step 2, or the gap to the winner is named |
| 2 | Does the UX stay elegant, simple, effortless? | Walk every surface a user touches (CLI, config, output, docs) from their seat; count what they must learn; nothing new to learn without a reason |
| 3 | Is it robust enough? | Failure modes, edge inputs, concurrency, partial failure, rollback; tests that would catch a regression |
| 4 | Is it consistent with existing patterns? | Grep for two or three existing implementations of the same thing; same names, signatures, layering |
| 5 | Is the implementation clean, to this repo's standards? | Passes the repo's own linters and conventions; no dead code, duplication or needless abstraction |

Plus question 6: is the review itself consistent with the knowledge (step 0)?

## 4. Use agents when they earn it

You decide whether to spawn subagents and which ones; there is no fixed team. Typical splits: the design
debate (step 2), a cross-repo trace of callers and consumers, a correctness pass over the diff, and one
adversarial verifier. Set `model` on every subagent: Sonnet by default, Opus only for the deepest judgment
(designing the ideal answer, judging the debate, adversarial verification). Give each one the subject's
path and sha, the knowledge file, and the exact question; ask for findings with file:line evidence.

## 5. Verify every finding

Before anything reaches the report, check each finding against the code at the head sha (or the document
text). Drop what you cannot confirm; label what is plausible but unproven as such. A finding Kohen
disproves in one look costs more than the ten findings that were right.

## 6. Write the report

Into the vault's `Reviews/` folder (the vault's location is in the global instructions; the extension may
set the folder layout and a template), linked from `Reviews.md`. Short: a reader should get the verdict and
every ask in under a screen.

- The verdict first, in one line, then why in two or three sentences.
- One recommendation that picks one target. Every ask moves toward it; never "if you keep X, fix Y" when
  the verdict is to replace X.
- Asks as numbered imperatives, most important first, each with its evidence and, when it is not obvious,
  a worked example (before/after, a concrete input and the wrong output).
- What is good about it, briefly, so the author knows what to keep.
- A draft comment Kohen could post, if he wants one. Never post it.
- Facts as facts: name the sha, the PR number, the file. No bare symbols without saying what they are.

## 7. Stay for questions, and learn

The review is a conversation, not a delivery. Stay in the session. When Kohen corrects the review (a
missed issue, a wrong call, a comment he made on the PR that the review did not anticipate), add the
lesson to `~/.local/share/kc-review/knowledge.md` as a principle: a one-line claim, why, and the evidence
(date, subject, his words). Never delete or rewrite an existing principle unless he says so; add a
"Pending amendments" entry instead when one looks wrong. If the extension names a domain knowledge file,
domain lessons go there under its rules.

Never post to GitHub, Slack or anywhere else; never approve, merge or comment.

## Knowledge file template

```markdown
# Kohen's review knowledge

How Kohen reviews, as corrections he has made. Each principle: an ID, a claim, why, evidence.
Never delete or rewrite an accepted principle without his say-so.

## Principles

### R-01 · <claim>
Why: …
Evidence: <date> <subject>: "<his words>"

## Pending amendments
```
