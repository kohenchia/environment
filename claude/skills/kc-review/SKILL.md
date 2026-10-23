---
name: kc-review
description: Deep review of a PR, a branch, a worktree or a set of documents (design docs, RFCs, vault notes, gists, repo files) for Kohen, consistent with the reviews he has given before. Debates the best design among real alternatives, then checks UX simplicity, robustness, consistency with existing patterns and code quality to the target repo's standards. Every review is full depth: Opus judges, every step runs, and the report states what was done. Writes a short, plain-language report to the vault (each ask a failure a user would hit, the code evidence at the end) and stays in the session for questions. Never posts anything. Use when Kohen types /kc-review <pr|branch|path|doc url(s)> [focus], or asks for a review.
---

# kc-review

`/kc-review <subject> [focus]`. The subject is a PR (number or URL), a branch or worktree path, or one or
more documents reviewed as a set. The focus, if given, is where to spend the most care; it never shrinks
the review below the five questions.

## Depth contract (no shortcut is allowed)

Kohen wants every review to be the deepest one the code allows. Nothing below is waived by the focus, by an earlier
review, by a small diff, or by time or budget.

1. **Opus does the judging.** Look at the model you are running on (your system prompt names it). On Opus, you
   orchestrate and judge. On anything else you are only the orchestrator: the design, the diff pass, the caller
   trace and the verification are done by subagents with `model: "opus"` and `effort: "high"`, and you never
   substitute your own view for theirs. Every judging subagent gets both settings, set explicitly: without `effort` it
   runs at the default, which is not the depth Kohen wants. A review in which no Opus agent reasoned about the subject is not a review; the verdict line says so.
2. **Every step runs, every time.** Steps 1 to 5 run in full for every subject. An earlier review of the same subject,
   yours or anyone's, is something to compare against, never a substitute: re-derive the design, re-read the diff and
   re-trace the callers at the current head, then say what changed and which earlier findings still hold. The modes
   `rereview` and `delta` mean a complete review of the current head plus a "Since last review" section, not less work.
3. **Small is not shallow.** A one-line change is traced to every consumer. Only the design debate (step 2) may be
   inline for a small fix; the diff pass, the caller trace and the verification still run on Opus.
4. **Say what was done.** The report carries a "How this was reviewed" table at its end (agents, models, steps done,
   steps not done and why), and one `Depth:` line under the verdict. A step you could not do is a stated gap and the
   verdict line begins `INCOMPLETE:`. "Not verified" is allowed; "assumed fine" is not.
5. **Unexamined is not clean.** Anything the change can reach that you did not look at is a named risk, with the exact
   command that would settle it.
6. **A limit is a reason to wait, not to skip.** On a rate limit or a slow step, wait and continue; never drop a step to
   finish sooner.

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

## 4. The review team (required)

For anything beyond a typo-level change to a document, spawn these, in parallel where they are independent, every one
with `model: "opus"` and `effort: "high"` (Sonnet only for mechanical work: listing files, fetching, formatting). Give each the subject's
path and sha, the knowledge file and the exact question, and ask for findings with `file:line` evidence and, for
each, the user-level case it causes: what a user does, what fails for them, and what would make it work.

| Agent | Its one task |
|---|---|
| Design debate (step 2) | One advocate per credible alternative, one challenger, one judge |
| Diff pass | Read every changed line and every changed test; find bugs, edge inputs, partial failure, missing tests |
| Consumer trace | Find every caller and consumer of every changed or removed symbol, field, flag, default and name, across all repos involved and in open PRs; and what the change should have touched but did not (docs, registrations, migrations, tests) |
| Break-it pass | Given the design and the diff, find a realistic input, workflow or existing user that the change breaks or silently alters; name the case and the code, or list what was tried and found nothing |
| Verifier (step 5) | Try to disprove each finding, and each "no problem here" claim on a risky area |

Put this in every agent's brief: if it spawns helpers of its own, they too get `model: "opus"` and `effort: "high"`
(a helper spawned without a model runs on the session's default, which is how two Sonnet helpers once appeared under
Opus agents). The extension may add more agents for its domain; none removes one of these.

## 5. Verify every finding

Before anything reaches the report, an Opus verifier that did not produce the finding checks it against the code at the
head sha (or the document text). Drop what cannot be confirmed; label what is plausible but unproven as such. A finding Kohen
disproves in one look costs more than the ten findings that were right.

## 6. Write the report

Into the vault's `Reviews/` folder (the vault's location is in the global instructions; the extension may
set the folder layout and a template), linked from `Reviews.md`.

The depth contract decides what the review finds; this step decides only how it is written. Kohen reads a report to
decide, not to audit: he must be able to act on every ask without opening the code. Plain writing never drops a
finding, a gap or a check. It moves the detail to the Evidence section at the end.

### The readability contract

| Part | Rule |
|---|---|
| Verdict | Two sentences at most: the call, then the deciding reason told as what happens to a user. Then the `Depth:` line (how many Opus agents, which steps ran; or `INCOMPLETE:` and what did not). |
| Target | One recommendation that picks one target. Every ask moves toward it; never "if you keep X, fix Y" when the verdict is to replace X. |
| Terms | Each term an ask needs that a user of the system would not know, defined once in plain words, before the asks. Coin none: use the names the code and its users already use. |
| Asks | Numbered, most important first, at most six. A finding that blocks merge is always an ask, whatever the cap or the length; lower-ranked ones go to Evidence, each with a one-line plain case, and the body says "N smaller findings in Evidence". |
| One ask | A heading that says what the change should do, tagged `blocks merge` or `can follow` (`blocks adoption` for a document; the extension may name the tags). Then one paragraph of at most four sentences: **if** the user does X, **then** Y fails, **and doing Z** (the change asked for) **makes it work**. X is a real action with real names and numbers: the command they run, the input, the config they write. Y is what they see, or what goes wrong silently and how they would notice. For two or three cases, use a table instead (*If the user… · then… · this makes it work*, one row per case). End with the ask's evidence numbers, e.g. `(E2, E5)`. Something not verified is written the same way: "if the user does X, we have not checked whether Y; running `<command>` settles it". |
| No code above Evidence | Nothing above `## Evidence` (the verdict, terms, asks, draft comment and every other section) holds a `file:line`, a function, class or variable name, internal shorthand or a principle ID. A name the user types or sees (a command, a flag, a config key, an error message) is not code: use it. Commit shas, PR and ticket numbers are facts, not code. |
| Unproven | A plausible finding says "(plausible, not proven)" in its ask. |
| Draft comment | One Kohen could post if he wants to; never post it. Written the same plain way: a bold imperative per ask, then at most two sentences. |
| Length | The verdict, terms and asks fit on one screen, about 40 lines. Everything else comes after the draft comment. When the blocking asks cannot fit, the budget gives way, never an ask. |
| End matter | After the draft comment, in this order: what is good about it, briefly, so the author knows what to keep; the sections the extension adds; `## Evidence`, numbered `E1`, `E2`, …, each naming the ask it supports, with the code (`file:line` at the head sha), how it was verified and by which agent; last, the "How this was reviewed" table (each agent, its model, its task, every step not done and why). |

One ask, before and after:

| | The ask |
|---|---|
| ❌ Before: Kohen cannot act on it without the code | 🔴 2. Fix `ready_inputs()` in `sched/plan.py:212`: it counts sibling nodes as producers, so `check_inputs` only warns. |
| ✅ After | **2 · Count only the jobs that run before a report as the source of its table** · blocks merge. If a user submits one report that reads a misspelled table, `sales_dayly`, it is refused, as it should be. If they submit it beside a second report, it only warns, because "the other report might create it". Neither does, so the report runs on an empty table and finishes green. Counting only the jobs that run before a report, and feed it, refuses the typo however many reports are in the batch. (E2) |

### Before saving: the self-check

Read the report from the top as Kohen would, and revise it until every answer is yes:

1. Could Kohen act on every ask without opening the code?
2. Does every ask name a real user action, what fails for them, and the change that makes it work, with real names
   and numbers?
3. Is every term either common or defined once above the asks?
4. Search the text above `## Evidence` for paths, `name:line`, `()` and principle IDs: is every hit a name a user
   types or sees? Move the rest to Evidence.
5. Do the verdict, terms and asks fit on one screen?
6. Did the writing lose nothing? Every confirmed finding is an ask, a lower-ranked item in Evidence, or a stated gap.

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
