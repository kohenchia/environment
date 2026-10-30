---
name: kc-plan
description: Write a plan for a development task or a project into the vault - researched against the real code, in Kohen's plan style, and not done until every choice a builder will face is answered by Kohen or has a default he accepted (the decision closure). No code is written and nothing outside the vault changes. Use when Kohen types /kc-plan <task or project>, or asks for a plan, design doc or implementation plan.
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
- Resolve ambiguity by reading code. A question that needs Kohen's judgment is a Decision closure row (step 5),
  put to him in the one batch; the plan's Open questions are only what step 5 allows there.
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
- **Check what a decision assumes exists.** A decision that relies on something outside the plan's own code (a
  value another library records, a field a system stores, a rule another team must approve, the inputs of the
  acceptance case) is checked at its source before the plan rests on it. One plan's check read a failed-call count
  that the library never records; the builder found out mid-build and had to stop and ask.

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
Work items (numbered table), Delivery (below), how we know it is right (acceptance bar and exact commands),
Decisions (numbered, each with the alternative and why it lost), Decision closure (step 5), Risks (with
structural mitigations), Open questions, Provenance.

Every command in "how we know it is right" is real: run it, or at least parse it (`--help`, `--dry-run`),
against `origin/main`. A command naming a path or option that does not exist is a defect in the plan.

A plan for code always has a **Delivery** section after the Work items: one row per PR (what it holds, the PR it
stacks on, its reviewer, its ticket with priority, milestone and due date, who files the ticket and when), then
the merge order. The merge order also says, for each open PR by someone else that touches the same code, which one
lands first and who ports the other's changes.

## 5. Close every decision before calling it done

A plan is not done until a builder could build all of it without ending a turn on a question. Kohen's time is
the scarce part: one plan's build worked 3.5 hours and sat 9.9 hours waiting on eight choices the plan had never
put to him (a module name, a merge order, whether to file a ticket, warn or refuse), each with a recommended answer
attached.

**Enumerate every choice the builder will face**, against the plan as written, and give each one a row in a
`## Decision closure` table (`Choice · Answer · Settled by`). "None" is an answer; a missing row is not.

| Choice | The plan states |
|---|---|
| Names and placement | every new public name (module, file, class or function another module imports, CLI flag, config key, pipeline or environment variable, the term the user docs use) and where each lives |
| PR split and stacking | each PR and what it holds, split by dependency: a part that needs nothing else in the plan is its own PR, never bundled into one that waits |
| Merge order | the order, and the rule for every open PR by someone else on the same code (who lands first, who ports) |
| Tickets | one ticket per PR with its priority, milestone and due date; who files each and when; what happens to a defect found while building that predates the work (default: a follow-up ticket, never this plan's PRs) |
| Reviewers | who reviews each PR and who requests them |
| Fallbacks | for every decision resting on something not yet built, verified or approved by someone else: what the builder does if it is false or late |
| Warn or refuse | each new check and each edge it meets: refuse, warn or allow, with the message, and the exit code of a dry run that would be refused for real |
| Edge-case scope | which inputs are in and which are deferred, checked against the real inputs of every acceptance case |
| Docs | which PR changes which docs, and what they say while a dependency is still pending |
| Out of scope | what the builder must not take on even when it finds it: neighbouring fixes, more PRs than the Delivery table, design changes. These become follow-up tickets |
| Acceptance | every real run or registration the proof needs, and who triggers it |

**Settle each row one of these ways**, and say which in the `Settled by` column:

- `Kohen, <date>`: his answer, verbatim.
- `default, accepted` or `default, delegated`: a recommended default he accepted, or a kind of choice he gave to the
  builder ("you own the merge order and registration"). Record his words and the date.
- `default, pending`: your recommendation, which needs his yes. His go to build (`/kc-dev <plan>`, "start building")
  accepts every pending default that he has not overruled, and the plan says so in one line above the table.
- `needs his yes`: a row whose answer authorises an outward-facing act (a ticket filed with its fields, a reviewer
  requested, a registration or real run, a merge order that makes someone else port their work) or changes a contract
  (anything the extension reserves for him). His go does not accept these: each needs `Kohen, <date>` or `default,
  accepted`. Until then the builder builds on the recommendation, and only the step the row authorises waits.
- `taken while building`: a choice nobody foresaw, decided by the builder (`kc-dev` step 3). A revision keeps it unless
  Kohen overrules it.

An answer Stella relays at night is never Kohen's: it does not settle a row.

**Ask once, never in waves.** Put every row that is not yet `Kohen` or `accepted` to him in one numbered batch, each
with your recommendation and its cost, in the end-of-turn list of step 7, after the review (step 6) has added its rows.
Do not stop at this step to ask. When step 6 must stop for him, the whole batch goes with that stop. When an answer
reverses an earlier one, re-run the whole table: a reversal reopens every row it touches, and those go back to him in
the next single batch.

**Open questions are only the rows that cannot be settled before building**: they need a result the build produces,
or an answer from someone other than Kohen. Each names the default the builder takes meanwhile, what it changes if
the answer differs, and whether it blocks merge. A question with no default is a defect in the plan.

The review (next step) is handed the closure table as part of its focus: a choice missing from the table, or an open
question with no default, is an ask tagged `blocks adoption`.

## 6. Review it before handing it over

Run `/kc-review <plan path>` on the finished plan (it reviews documents at full depth) and treat its asks
as the next revision: apply each one, or answer it in the plan, then review again. Act only on the final report
(its `Depth:` line does not begin `IN PROGRESS:`), never on a provisional first report. Stop when the verdict is
`Adopt as written`, or `Adopt after changes` with no ask tagged `blocks adoption` left. If a decision only
Kohen can make blocks the verdict, stop and put it to him rather than choosing for him, with the whole closure batch
(step 5).

Two more places to stop and ask Kohen, because every further round is a full-team review that costs as much as the
first (one plan used three rounds on a design he then shelved): a verdict of `Rework` or `Do not adopt` (the direction
is in question: report the verdict and the reviewer's target, and review a revision only after he confirms the
direction), and a review of the plan's second revision (the third review, counting the first) that still has an ask tagged
`blocks adoption` (put what blocks to him).

## 7. Finish

Link the plan from the project's index note and `Projects.md` if the vault keeps one. Report the path,
the review verdict and its report, the decisions taken, and the closure count (`14 choices: 6 answered by Kohen,
5 defaults accepted or delegated, 2 pending his go, 1 open with a default`). The end-of-turn list holds the one batch
of pending rows, each with its default. `/kc-dev <plan path>` builds it and takes every default his go accepts. When
Kohen says to build in this session ("start building"), run `/kc-dev <plan path>` here before writing any code, so its
rules govern the build.
