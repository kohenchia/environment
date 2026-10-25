---
name: kc-review
description: Deep review of a PR, a branch, a worktree or a set of documents (design docs, RFCs, vault notes, gists, repo files) for Kohen, consistent with the reviews he has given before. Debates the best design among real alternatives, then checks UX simplicity, robustness, consistency with existing patterns and code quality to the target repo's standards. Every review is full depth: Opus judges, every step runs (a re-review that changes only documentation, comments or formatting is the one exception), and the report states what was done. A provisional first report of verified findings comes at 30 minutes when the model quota allows (the extension's check says when it does not), and the remaining steps follow as an addendum that rewrites it to the final state, so time changes when a finding arrives, never whether it is looked for. Writes a short, plain-language report to the vault (a before-and-after of what the user writes and runs, each ask a failure a user would hit, the code evidence at the end), and for code a companion page of every use case the change touches, each run before and after with its command, config, variables and exact warning, and stays in the session for questions. Never posts anything. Use when Kohen types /kc-review <pr|branch|path|doc url(s)> [focus], or asks for a review.
---

# kc-review

`/kc-review <subject> [focus]`. The subject is a PR (number or URL), a branch or worktree path, or one or
more documents reviewed as a set. The focus, if given, is where to spend the most care; it never shrinks
the review below the five questions.

## Depth contract (no shortcut is allowed)

Kohen wants every review to be the deepest one the code allows. Nothing below is waived by the focus, by an earlier
review or by a small diff (the one exception is tier 0 in rule 2). Kohen also wants the first answer within 30 minutes:
time and budget decide when a step's result reaches him, never whether the step runs (rule 7).

1. **Opus does the judging.** Look at the model you are running on (your system prompt names it). On Opus, you
   orchestrate and judge. On anything else you are only the orchestrator: the design, the diff pass, the caller
   trace and the verification are done by subagents with `model: "opus"` and `effort: "high"`, and you never
   substitute your own view for theirs. Every judging subagent gets both settings, set explicitly: without `effort` it
   runs at the default, which is not the depth Kohen wants. A review in which no Opus agent reasoned about the subject is not a review; the verdict line says so.
2. **Every step runs, every time.** Steps 1 to 5 run in full for every subject. An earlier review of the same subject,
   yours or anyone's, is something to compare against, never a substitute: re-derive the design, re-read the diff and
   re-trace the callers at the current head, then say what changed and which earlier findings still hold. The modes
   `rereview` and `delta` mean a complete review of the current head plus a "Since last review" section, not less work.
   One exception, **tier 0** (a code subject only; a document is never tier 0): since the last *complete* review the
   only changes are documentation prose, code comments or formatting that cannot change behavior, or a merge of the base branch that leaves the subject's own diff against the
   new base unchanged, changes no dependency or lock file, and brings no new consumer of any changed symbol (grep each at
   the new head). Not tier 0: whitespace in YAML or Python, documentation that is the product (skill instructions, a
   docs site, text that becomes CLI help), `noqa` or `type: ignore` comments, a deleted, skipped or weakened test, a
   changed test or CI configuration. Measure the interdiff from the last complete review, so successive tier-0 pushes
   cannot add up to a real change. Then you read the interdiff yourself, re-run the fact sheet's gates at the new head,
   refresh the subject's live state (CI, comments, tickets, the extension's checks), and have a verifier confirm the
   tier-0 label and your conclusion. "Since last review" and the `Depth:` line say it was a tier-0 re-review and why.
   Everything else is a complete review: a document is never carried forward on an earlier verdict, and neither is a
   change of behavior, a new feature surface, a changed design, or new context from Kohen or from a thread (an earlier
   pass has already missed defects in text that did not change).
3. **Small is not shallow.** A one-line change is traced to every consumer. Only the design debate (step 2) may be
   inline for a small fix; the diff pass, the caller trace and the verification still run on Opus.
4. **Say what was done.** The report carries a "How this was reviewed" table at its end (agents, models, steps done,
   steps not done and why), and one `Depth:` line under the verdict (a tier-0 re-review says so there). A step you could not do is a stated gap and the
   verdict line begins `INCOMPLETE:` (a first report is `IN PROGRESS:` instead, rule 7). "Not verified" is allowed; "assumed fine" is not.
5. **Unexamined is not clean.** Anything the change can reach that you did not look at is a named risk, with the exact
   command that would settle it.
6. **A limit is a reason to wait, not to skip.** On a rate limit or a slow step, wait and continue; never drop a step to
   finish sooner.
7. **A first report at 30 minutes, the rest as an addendum, and nothing lower in quality.** At minute 30 of the review
   (or at the time the extension's check named before the team started) the report goes out with what the verifier
   has confirmed so far. Minutes count from the team's start; any wait before it (for another review, for Kohen's
   answer on the quota) is told to him with its expected end. In the first report:
   - an ask is only a finding a verifier has confirmed or labelled plausible. A finding no verifier has checked yet is
     one line under "Still being checked", tagged `could block merge` (`could block adoption` for a document) when its
     finder tagged it blocking. While any such line exists, the verdict line names it, e.g. `Provisional: merge with
     fixes, pending 2 findings that could block merge (being checked)`; no verdict reads as clean past an unchecked
     blocker;
   - the verdict is provisional: the Verdict line, the report's frontmatter verdict and its row in the reviews index
     begin `Provisional:`, and the `Depth:` line begins `IN PROGRESS:`, naming each agent still running and the clock
     time it should end;
   - an `Extension:` line of two sentences: what the running steps can still change (which asks, which kinds of user),
     and why this subject needs them. Kohen approves it; meanwhile nothing stops. If he says stop, the report is
     finished as `INCOMPLETE:`, naming the stopped agents and every finding never verified.

   Every step still runs to the end. The review is done only when the addendum is written (with, for code, the verified
   companion use-case page of step 7, which never delays the first report): rewrite the verdict, the
   asks, the summary lines, the user picture (every "dry run running" and "not yet checked" mark replaced), the draft
   comment, the frontmatter and the index row to the final state, remove the `Extension:` and "Still being checked"
   lines, and put a `**Since the first report:**` line under the `Depth:` and summary lines, saying which asks of the first report
   were added, reversed, downgraded or corrected (or "none"), so Kohen sees what the early answer cost. The `Depth:`
   line is then final, and the "How this was reviewed" table gives each agent's start and end minute. A skill that runs
   the review and acts on it (`kc-dev`, `kc-plan`) acts only on the final report, whose `Depth:` line does not begin
   `IN PROGRESS:`.

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
- **Check the subject against its originating ask before spending the team.** Find what it says it implements (the
  ticket, the thread, the plan, the order) and compare its premise with that ask in two or three sentences:
  is it still the problem, is it already solved or shelved, did the ask change since? A subject built on a wrong or
  stale premise is reported as that, first, with the evidence, and a verifier confirms it. You may then stop the team
  there: the verdict is that the direction is wrong, the `Depth:` line says which steps were not run and why, and Kohen
  decides whether to continue (an earlier design later shelved once consumed three quarters of a review's cost). If you
  cannot show the premise is wrong, the premise check changes nothing and the full review runs.

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

Name two to four credible alternatives (the subject's approach is one of them). Debate them for real. For
anything bigger than a small fix, spawn an advocate for the subject's approach and one for the design you chose
above (when they are the same, the second advocate argues the strongest named alternative), each arguing as strongly as the code allows, plus one challenger whose only
task is to find the strongest alternative the list omits or dropped. Each ends with the concrete fix for the problem
under its design (the command, the config lines, the before and after), so the asks can be written from it. There is
no separate judge agent: you decide which design wins and say why the others lost, and the verifier (step 5) checks
the debate's factual claims. Use the full debate instead (one advocate per credible alternative, and a judge agent
that tries to disprove each case against the code and answers the challenger) when the subject is a plan, an RFC or
another document whose design is the question, and whenever you are not running on Opus (depth contract 1). A small fix gets the
same reasoning inline. If the subject is not the best design, the review says so first: everything else is secondary.

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
with `model: "opus"` and `effort: "high"` (Sonnet only for mechanical work: listing files, fetching, formatting, and the
use-case capture of step 7). Give each the subject's
path and sha, the fact sheet (below), the knowledge file and the exact question, and ask for findings with `file:line`
evidence and, for each, the user-level case it causes: what a user does, what fails for them, and what would make it work.

| Agent | Its one task |
|---|---|
| Design debate (step 2) | The advocates and the challenger of step 2 (and a judge in the full debate); runs in the same wave as the finders |
| Diff pass | Read every changed line and every changed test; find bugs, edge inputs, partial failure, missing tests |
| Consumer trace | Find every caller and consumer of every changed or removed symbol, field, flag, default and name, across all repos involved and in open PRs; and what the change should have touched but did not (docs, registrations, migrations, tests). When the change reaches more than three kinds of consumer, one agent per kind, never per repo, so the slowest agent shortens the wait without a slice missing a consumer |
| Break-it pass | Given the design and the diff, find a realistic input, workflow or existing user that the change breaks or silently alters; name the case and the code, or list what was tried and found nothing |
| Verifier (step 5) | Try to disprove each finding, each "no problem here" claim on a risky area, and the debate's factual claims |
| Use-case capture (step 7, code only) | Sonnet, at most three: run every case of the companion page at the base and the head and record it; no judgment |
| Use-case verifier (step 7, code only) | Check the companion page against the captures, rerun a sample, and rewrite or label every statement that was inferred rather than observed |

Put this in every agent's brief: if it spawns helpers of its own, they too get `model: "opus"` and `effort: "high"`
(a helper spawned without a model runs on the session's default, which is how two Sonnet helpers once appeared under
Opus agents) and write what they find to the review's `assets/<sha10>/` folder. The extension may add more agents for its
domain; none removes one of these.

How the team runs (each rule below is a cost or a loss seen in 14 earlier reviews):

- **The user picture is a product of the team, not of memory.** The agent that runs the subject (dry runs, `--help`,
  config validation) at the base and at the head brings back the exact commands, config snippets and outputs for the
  surfaces the diff changes; ask for them in its brief. Its runs use step 7's case folders, so the companion page
  reuses them instead of running them again.
- **One fact sheet, built once.** Before the finders start, collect raw facts into the review's `assets/<sha10>/` folder (the head's first ten characters): the
  PR metadata, the diff and the changed symbols, the open PRs that overlap it, and the repo's tests, linters and type
  checks run once, in a fresh environment of the review worktree (a stale shared environment gave false failures).
  Facts are raw output, never conclusions, and are rebuilt for each head. A Sonnet agent may gather them. Every brief
  points to the sheet and says not to re-derive it; an agent still runs any query its own hypothesis needs.
- **At most eight Opus agents at a time, helpers included.** The model's request limit is shared by every agent, and
  parallel agents trip it (the extension names the number); stage the rest rather than let agents die. Rate limits, not
  agent count, set the speed. One review per quota at a time: a second review on the same quota slows both, and a
  quota that runs out mid-review loses a whole wave (two reviews started 15 minutes apart lost theirs at minutes 7
  to 25). The companion page (step 7) is part of the review, not a second one, and runs under this rule.
- **An agent starts on its inputs, not on the slowest finder.** An agent that needs another agent's file (a ledger, a
  table) starts when that file is written, an interim one included, in the first slot a finished agent frees (the
  design advocates finish first; the extension orders who takes the freed slots). Every report file begins
  `Status: interim HH:MM` or `Status: final HH:MM`. An agent that starts on an interim file copies it to
  `assets/<sha10>/<its role>.input-<HHMM>.md`. Before it finishes it waits, checking every two minutes (`sleep 120`),
  until the file says `final` or the roster marks its producer `stopped`; then it diffs the file against its copy and
  audits every new or changed row, and names the versions it audited. If the producer stopped, it lists the rows it
  could not audit, and the report counts them as never verified. So an early start never audits half a table.
- **Report by minute 25, then keep going.** Each finder's brief gives the clock time to write its report so far by
  (minute 25 of the review, or five minutes before a later first-report time the extension's check set), with an
  `## Unfinished` list of what it has not reached, and then it carries on to the end of its task. It never cuts its work
  to make the minute; what it finds later is verified for the addendum (depth contract 7).
- **A roster of agents.** Keep `assets/<sha10>/roster.md`: each agent, its task, and running, done, respawned or
  stopped (died and not respawned, or stopped by Kohen). The verifier and the addendum work from it.
- **No report is ever lost.** Each agent writes its full report to `assets/<sha10>/<role>.md` before its final message, and
  an interim report after about 40 tool calls. If the harness refuses file writes in a subagent, the agent returns the
  report as its final message and you save it at once, with `Status: final HH:MM` at its top. An agent that died (rate limit, quota reset) is respawned
  alone, with its brief and its interim report; a finished agent is never re-run, and a wave is never repeated.
- **A moving head does not restart the team.** Record the head sha when the team starts. If the head moves, let the
  running agents, and any agent not yet started, finish at the old sha (the wave, the verifier and the report all
  describe that sha; new files go under the new sha's folder, never over the old); then the new head is a re-review
  (depth contract 2).

## 5. Verify every finding

Before anything reaches the report, an Opus verifier that did not produce the finding checks it against the code at the
head sha (or the document text). Drop what cannot be confirmed; label what is plausible but unproven as such. A finding Kohen
disproves in one look costs more than the ten findings that were right.

The verifier also checks the user picture: each After snippet is accepted at the head, each Before snippet at the base,
and the outputs shown are the ones those commands print. The verifier works as the findings arrive: it starts with
the first finder's report and takes each later report as it lands, blocking findings first, so a finding is checked
minutes after it exists. It ends only when every other agent on the roster (a respawned one and the extension's
silent-failure agent included) is done and checked; it never finishes beside a running finder. Its last pass re-checks
every claim that a later report contradicts or depends on. A report that lands after the verifier ended, or after it
died, gets its own verifier pass before it reaches the report.
Nothing reaches the report as verified that no verifier saw; a finding that was not verified is written as such. A verifier's report is saved to
`assets/<sha10>/` like any other.

## 6. Write the report

Into the vault's `Reviews/` folder (the vault's location is in the global instructions; the extension may
set the folder layout and a template), linked from `Reviews.md`. For code, the companion use-case page (step 7) sits
beside it.

The depth contract decides what the review finds; this step decides only how it is written. Kohen reads a report to
decide, not to audit: he must be able to act on every ask without opening the code. Start from what a user does and
what the system does; code appears only as a pointer to the key piece of logic. Plain writing never drops a
finding, a gap or a check. It moves the detail to the Evidence section at the end.

### The readability contract

| Part | Rule |
|---|---|
| Verdict | Two sentences at most: the call, then the deciding reason told as what happens to a user. Then the `Depth:` line (how many Opus agents, which steps ran; `IN PROGRESS:` and what is still running in a first report, with the `Extension:` line under it; or `INCOMPLETE:` and what did not). A first report's verdict begins `Provisional:` (depth contract 7). |
| Target | One recommendation that picks one target. Every ask moves toward it; never "if you keep X, fix Y" when the verdict is to replace X. |
| Who and what | Name the features, targets, teams or commands an ask affects, with a count when there is one ("the checkout service in eu-west", "37 of 64 batches"). Never "everyone else", "other users" or "some cases". Call the author's code "the PR" and the asked-for change "the fix"; never "this change", "this way" or "the new behavior", which can mean either. |
| Terms | Each term an ask needs that a user of the system would not know, defined once in plain words, before the asks. Coin none: use the names the code and its users already use. |
| User picture | Right after the terms and before the asks, a **before and after of the user's experience**, so the impact is clear at a glance. Show every surface the subject changes: each config file the user edits (every file, not only the main one), each command line they type, and the output they see when it changes (a new refusal, a new line, a renamed object). Two labelled blocks per surface, **Before** (on the base) and **After** (on the subject's head), on the same running example with real names and values; changed lines only, plus the line or two that place them. About 25 lines in all; a longer picture goes to Evidence with a pointer. If the user's experience does not change, say so in one line with the reason ("internal refactor: the same command and config give the same output") and show one unchanged command with its output. For a document, show what the user writes if it is adopted, next to what they write today. The picture is real, not invented: produce each snippet by running or validating it on the base and on the head (a dry run, `--help`, the config validator) and say how; one you could not run is labelled "not run". These snippets are what the user types and sees, so they are not code in the sense of the next row. In a first report, a surface whose dry run is still running says "dry run running, ends about HH:MM", and each snippet says whether a verifier has checked it yet. For code, the picture ends with one line linking the companion use-case page (step 7) and its number of cases; the picture is the one running example and never repeats the page's cases. In a first report that line says the page comes with the final report. |
| Asks | Numbered, most important first, at most six. A finding that blocks merge is always an ask, whatever the cap or the length; lower-ranked ones go to Evidence, each with a one-line plain case, and the body says "N smaller findings in Evidence". |
| One ask | A heading that says what the change should do, tagged `blocks merge` or `can follow` (`blocks adoption` for a document; the extension may name the tags). Then one short paragraph, starting from what a user does and what the system then does, never from the code: **if** the user does X, **then** Y fails, **and doing Z** (the fix asked for) **makes it work**. X is a real action with real names and numbers: the command they run, the input, the config they write. Y is what they see, or what goes wrong silently and how they would notice. Then the fix as an example: the exact command to run, the config lines to add, or the before and after of the name or output that changes (for instance `nightly.cfg` gains the line `retries = 3`; a saved job named `export` becomes `export-eu` and `export-us`). For two or three cases, use a table instead (*If the user… · then… · this makes it work*, one row per case) and still show the fix as an example. End with the ask's evidence numbers, e.g. `(E2, E5)`. Something not verified is written the same way: "if the user does X, we have not checked whether Y; running `<command>` settles it". |
| Code is a footnote | The explanation never starts from code, and it must make sense with every code reference removed. The verdict, terms, draft comment and every section other than the asks hold none. An ask may add, after its paragraph and example, one short line `Key logic: <what it does in plain words> (path:line)`, at most two per ask, only where seeing that piece of logic makes the failure obvious; everything else goes in Evidence. A name the user types or sees (a command, a flag, a config key, an error message) is not code: use it anywhere. Internal shorthand and principle IDs stay in Evidence. Commit shas, PR and ticket numbers are facts. |
| Unproven | A plausible finding says "(plausible, not proven)" in its ask. |
| Draft comment | One Kohen could post if he wants to; never post it. At most 12 lines, written the same plain way: a bold imperative per ask that goes to the author, then at most two sentences (the change, and the exact command or ticket number). Numbers match the asks. No rationale, no riders ("check that…"), no placeholders. |
| Symbols | A symbol (✅ ❌ ⚠️ 🔴) is never bare: say once, in the legend or the cell, what goes wrong and give an example. "Accepted" is a problem only when the result is silently wrong, so say "accepted, then X happens". No ASCII art. |
| Length | From the title to the end of the draft comment (the `Depth:` and any summary lines count): about 40 lines, plus the user picture (which has its own budget), so about one and a half screens. Everything else comes after. When the blocking asks cannot fit, the budget gives way, never an ask. In a first report, "Still being checked" is one line (`N findings still being checked, M could block merge:`, `adoption` for a document) plus one line for each of the M, and none of it counts against the budget. |
| End matter | After the draft comment, in this order: what is good about it, briefly, so the author knows what to keep; the sections the extension adds; `## Evidence`, numbered `E1`, `E2`, …, each naming the ask it supports, with the code (`file:line` at the head sha), how it was verified and by which agent; last, the "How this was reviewed" table (each agent, its model, its task, its start and end minute, every step not done and why). |

One ask, before and after:

| | The ask |
|---|---|
| ❌ Before: Kohen cannot act on it without the code | 🔴 2. Fix `ready_inputs()` in `sched/plan.py:212`: it counts sibling nodes as producers, so `check_inputs` only warns. |
| ✅ After | **2 · Count only the jobs that run before a report as the source of its table** · blocks merge. If a user submits one report that reads a misspelled table, `sales_dayly`, it is refused, as it should be. If they submit it beside a second report (37 of 64 batches have one), it only warns, because "the other report might create it". Neither does, so the report runs on an empty table and finishes green. With the fix, `report submit nightly sales_dayly` is refused in both cases: `no earlier job creates sales_dayly`. *Key logic: every job in the batch counts as a possible source (`plan.py:212`).* (E2) |

### Before saving: the self-check

Read the report from the top as Kohen would, and revise it until every answer is yes:

1. Could Kohen act on every ask without opening the code?
2. Is the user picture there, with a Before and an After for every changed config file, command and output, and does
   each snippet say how it was produced (run, validated, or "not run")?
3. Does every ask name a real user action, what fails for them, and the fix that makes it work, with real names and
   numbers, and show the fix as an example (the command, the config lines, the before and after)?
4. Is every term either common or defined once above the asks?
5. Cover every code reference and re-read: does each ask still make sense? Search outside the asks for paths,
   `name:line`, `()` and principle IDs, and inside them for more than two per ask: is every other hit a name a user
   types or sees? Move the rest to Evidence.
6. Do the title to the end of the draft comment fit about 40 lines (the user picture has its own budget)?
7. Is every "everyone", "others", "this change" or "this way" replaced by the named features, targets or commands, the
   PR or the fix?
8. Did the writing lose nothing? Every confirmed finding is an ask, a lower-ranked item in Evidence, or a stated gap.
9. In a first report: is every ask verified, every unchecked finding under "Still being checked" (blocking ones tagged),
   the verdict marked `Provisional:` everywhere it appears, every running agent named with its end time, and the
   `Extension:` line there? After the addendum: are the verdict, asks, user picture, draft comment, frontmatter and
   index row rewritten to the final state, the `Extension:` and "Still being checked" lines gone, and does the
   `**Since the first report:**` line say which asks of the first report changed?
10. For code, in the final report: is the companion page there (or its one paragraph when nothing a user sees
    changes), linked from the user picture and the reviews index, opened by its index table, and does every case show
    the command, the config, the variables as printed, before, after, the exact warning or refusal and its "if the
    user does X" line? Does `usecases.py check` pass on it, has its verifier rerun the sample, is every inferred
    statement rewritten or labelled, and are the cases reasoned from code named?

## 7. The companion use-case page (code only)

Every review of code (a PR, a branch, a worktree) also writes a companion page beside the report: every situation the
change touches, each run at the base and at the head, so Kohen sees its impact case by case. The report's user picture
(step 6) shows one running example; the page is its exhaustive version, and the picture links to it instead of
repeating it. A document review has no page: there is nothing to run before and after.

**When.** The page is built once the findings are verified and belongs to the final report (to the addendum when there
was a first report): it never delays the first report and never replaces a finding. A situation on the page that no
finding covers is a new finding: it goes to the verifier (step 5) and into the report, not only onto the page. If
nothing a user types, writes or sees changes, the page is one paragraph saying so, with the unchanged command run at
base and head and its identical output; no padding. A review stopped on a wrong premise (step 1) has no page; a tier-0
re-review keeps it with one line saying why it still holds at the new head; any other re-review reruns every case at
the new head and adds the cases the new changes need.

**Which cases.** Write the list before capturing anything, from the diff, the consumer trace and the verified findings:

- the default path, where the user declares nothing new: one case per kind of user the consumer trace found;
- each new option, flag, key or input: its happy path, then each way it fails (missing; misspelled, on each side of a
  name and value; a value the system supplies itself; one that clashes with what the system sets; written in the wrong
  place), alone and beside what it is usually run with;
- the combinations the change alters: two features in one run, a multi-step flow, an existing option meeting the new one;
- every verified finding a user can hit, so each ask has its case.

**Each case shows**, in this order: the command the user runs, exactly; the config excerpt they write (every file the
case needs, with its path, "same before and after" when it is), as it stands in the file; the variables or inputs the
system resolves, as it prints them; **Before**, what the base prints for that input, with its exit code (for a new
option, the base's own refusal or load error, as captured); **After**, what the head prints, with its exit code; the
exact warning or refusal text, in full; and one line: **if** the user does X, **then** Y happens (fails, warns, or
silently does Z), **and doing** W **makes it work** (or "nothing changes for you").

**Layout.** Frontmatter; one paragraph (the base and head shas, how the cases were run, that nothing was created,
submitted or posted, and which cases were reasoned from code); what the change does, in a few plain rows; the terms the
cases need and the legend of marks, each saying what goes wrong; an **index table** (Case · Situation · Before ·
After); the cases, in parts by kind of user, the default path first; a summary table (kind of user · before · after)
and one line mapping the cases to the report's asks. Similar cases may share a table, one row each, with the verbatim
text of at least one. The report's length budget does not apply to the page.

**How it is built.**

- **Capture agents** (Sonnet, at most three, one slice of the parts each): running and recording is mechanical. Each
  runs its cases with `uv run --no-project python ~/.claude/skills/kc-review/usecases.py capture` (the helper beside
  this skill) in the base and head review worktrees, into one folder per case under the review's `assets/usecases/`:
  `cmd.txt`, the config as it was loaded, `base.log` and `head.log` (each ending `EXIT <n>`), and `notes.md` quoting
  lines with their file and line. A config is changed in memory or in a scratch copy, never in a worktree, and both
  worktrees are clean at the end. Nothing is submitted, set, registered or posted, on the PR or anywhere else; a case
  that only a write could show is reasoned from code instead.
- **A generator script** in `assets/usecases/` writes the page from the case folders. Every excerpt is pulled from a
  captured file by pattern (the helper's `pull`, `block`, `exit_code` and `fence`), never typed, and a pattern that
  matches nothing stops the script. Its prose is the only hand-written text. A correction goes into the generator and
  the page is generated again, never edited by hand.
- **Before the verifier**, `usecases.py check <page> assets/usecases` passes: every line of every fenced excerpt is in
  a captured file (scripts and notes do not count). A block that cannot be, such as a template, carries a
  `<!-- not captured: why -->` line, and the check lists it for the verifier.
- **One Opus verifier** that wrote none of the page checks every fenced excerpt against its log; reruns a sample byte
  for byte from the clean worktrees (one case per part at least, and every refusal an ask rests on), after normalising
  shas and times; marks every statement observed (which log), inferred (which code or reproduction) or unsupported;
  confirms the head has not moved; and lists the situations the page misses. Every inferred statement is rewritten to
  what was observed or labelled `(inferred from <code or reproduction>, not observed)`; every unsupported one goes.
  Nobody edits the page while it reads.

The first such page needed 21 statements changed (three wrong outright) and six situations added. Write to avoid them:

- **Before is what the base printed for that input**, never a history of the PR ("it was accepted at the previous
  push") that no capture shows.
- **A runtime outcome a dry run cannot show is "would"**, with what it rests on ("the job would run at priority 5:
  overrides are applied before mappings"); a local reproduction is called one, with what it ran on.
- **Like for like**: a comparison changes one thing on the same input; a different subject is not "the same case beside
  others".
- **Every count is recomputed at the head, with its denominator** ("37 of the 63 config files that have evals").
- **What was not run is not claimed**: a target, feature or environment is run or dropped.
- **"Works" means the intended effect was seen**; "accepted" means the input was taken and the effect not seen (a
  misspelled variable is accepted and does nothing).
- **The page describes the report's sha**: a newer head is a re-review (step 4), not a quiet recapture.

**Where it lives.** Beside the report, named `<report name> — use cases and impact` unless the extension names it, with
its evidence in `assets/usecases/`. The report's user picture and the reviews index row link to it. When the change
cannot be run at all (no entry point, an environment this machine lacks), the page says so at the top and labels each
case "reasoned from code, not run"; such a case shows no output block.

**Quota.** The page is part of the review: its agents run in the review's session, under step 4's one-review-per-quota
rule. A page added to a finished review is review work, and waits for another review running on the same quota as a
review would.

## 8. Stay for questions, and learn

The review is a conversation, not a delivery. Stay in the session. When Kohen corrects the review (a
missed issue, a wrong call, a comment he made on the PR that the review did not anticipate), add the
lesson to `~/.local/share/kc-review/knowledge.md` as a principle: a one-line claim, why, and the evidence
(date, subject, his words). Never delete or rewrite an existing principle unless he says so; add a
"Pending amendments" entry instead when one looks wrong. If the extension names a domain knowledge file,
domain lessons go there under its rules.

A review that ends with a verdict that the direction is wrong (`right goal, wrong shape`, `don't do this`, `Rework`,
`Do not adopt`) is where the loop stops: do not review a revision, or let a caller review one, until Kohen has
confirmed the direction. A caller that rebuilds from the review's own target (`kc-dev`, when the target fits the order
it was given) is the one exception, because the direction is then already his.

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
