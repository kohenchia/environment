# Global Claude Code Instructions

These instructions apply to every Claude Code session on this machine. They are the public, portable
half; the machine's own instructions are imported at the end and add to them (where they are stricter,
they win).

## How I work

- **One terminal, one tmux server.** The main window has the Claude agents view on the left and the
  session I am working in on the right. Every session is an ordinary interactive session: I start it
  (`cy`), it can go to the background and come back, and the agents view is where I see which ones need
  me.
- **Skills, not teams.** Work starts from a skill, and the skill decides whether a task deserves
  subagents and which ones:

| Skill | For |
|---|---|
| `/kc-review` | A deep review of a PR or documents |
| `/kc-debug` | Debugging or investigating a problem |
| `/kc-plan` | A plan in the vault; no code |
| `/kc-dev` | Building from a plan or instructions, straight away |
| `/kc-tutorial` | A tutorial or explainer in the vault |
| `/kc-log` | The daily log in the vault |
| `/stella` | A message for Stella (also: start a message with "Stella" or "S,") |

- **Stella** is my personal assistant: a session of her own (`stella` in a terminal), with her skills
  (`stella-agents`, `stella-audit`, `stella-priorities`, `stella-setup`). She keeps track of my priorities
  and all ongoing work, tidies finished sessions, audits the knowledge base and writes the daily log. She
  is not a gateway: anything she launches is a normal session I can attach to.
- **Every skill reads its extension first**: `~/.claude/kc-extensions/<skill>.md`, when it exists, adds
  this machine's constraints.

## The vault

My second brain is an Obsidian vault. Its location is in the machine's own instructions. Plans, reviews,
tutorials, notes and daily logs go there, never in a repo. Read the vault's own `CLAUDE.md` before writing
to it; it is authoritative on folders, names and frontmatter. `Notes/` is the knowledge layer, `Projects/`
is work in progress, `Daily/` the daily logs, `Reviews/` the reviews.

## Every turn ends with the status block

The last block of your final message each turn, nothing after it, plain markdown (not in a code fence):
a line of 40 `━` characters on its own line, then exactly one of:

- `🟧 **NEXT FOR YOU** (N)` followed by N numbered items `1.` `2.` …: each one thing only I can do or
  decide, short and imperative (a question, a decision, a review to post).
- `🟩 **ALL DONE** — nothing left for you.`: only when nothing is uncommitted, unpushed or open for me.
- `🟦 **WORKING** — <what is still running>`: only when background work continues after the turn.

The Stop hook checks the form. When I answer with just a number, or "do 2" / "approve 1 and 3", I mean the
items of your last NEXT FOR YOU block.

## Access

Sessions have all the read and write access I have. Writes and pushes are not gated, with one exception:
a push to `~/github/environment` (this public repo) asks me first through Claude Code's prompt. Put
`KC_OWNER_SAID_PUSH=1 ` in front of that push only when my instructions in this session explicitly say to
push there. If I want no writes, I use plan mode.

Still ask before anything outward-facing that cannot be taken back: posting or reacting anywhere, a review,
approval, merge or comment on someone else's work, triggering remote jobs, deleting anything of mine.

## Explaining things to me: show it, don't just say it

I'm a visual learner. When explaining how something behaves — a file layout, a data flow, why one
approach works and another doesn't — **show a concrete example**, don't only describe it in the abstract.

- **Before/after pictures** of the actual thing (a directory tree, a request sequence, a table of rows),
  using real names from the case at hand, not `foo`/`bar`.
- **One small table per scenario** with the same columns each time ("who reads it", "what it finds",
  "result" with ✅/❌), so the scenarios can be compared side by side.
- **A worked example with numbers** showing the failure ("the score counted twice: 0.80 + 0.80").
- **Name the players first** ("there are two readers, and they look differently") before the scenarios,
  then end with a one-line takeaway of *why* it works.

Lead with the picture, keep prose short, and save `file:line` evidence for after the explanation.

## Secrets

Secrets live in `~/.secrets`, one file per environment variable, named for that variable.

- **Never write a secret into a repo.** **Never print a secret's value**: not into a log, a commit, a plan,
  a PR description or the transcript. Refer to it by variable name or path.
- If a secret appears to be missing, say so and point at the setup script rather than asking for the value
  to be pasted into the conversation.

## Working in repositories

- Every repo under `~/github/` is its own project with its own environment. `cd` into it first, read its
  `CLAUDE.md` (or `README.md`) and follow its conventions exactly.
- Use `uv run` for Python, never bare `python`. Use the repo's own task runner: check for a `justfile`
  before a `Makefile`.
- Use `git --no-pager` for git. `--no-color` is not a top-level git flag; pass it only to subcommands
  that accept it (`git --no-pager diff --no-color --stat`).
- Before writing new code, grep for two or three existing implementations of the same pattern and match
  them. Before removing or renaming anything public, grep every caller.
- Run the repo's formatter, linter and relevant tests after a change.
- When working from a plan, execute every step, including integration steps against external systems. A
  step that cannot be completed is reported as blocked, never skipped quietly.
- The dotfiles (`~/.zshrc`, `~/.claude/CLAUDE.md`, …) are symlinks into repos. The Edit tool refuses to
  write through a symlink: edit the real file in the repo.

## Deep code exploration

When analyzing code, be exhaustive. Trace every relevant code path across every codebase involved, to the
implementations. Cross-reference both sides of cross-repo calls. Resolve ambiguity by reading code, not by
asking: only surface questions that need human judgment. Spawn parallel subagents for multi-repo
analysis. Cite specific references (paths, line numbers, functions).

## Writing project plans

Plans live in the vault's `Projects/<Topic>/`, never in a repo.

**Describe what the change does, not how it does it.** Lead with one or two sentences naming what ships
and what stays the same. A plan is read to decide whether the work is right, not to review its internals.

**Define every term, and invent none.** Assume the reader knows the domain but not this project's private
shorthand. Where two nearby things are easy to confuse, say both and which is which. More than about three
terms: a short vocabulary section up front. Never coin a phrase for a concept the codebase does not name.

**Be precise about facts and honest about state.** "440 lines", not "large"; name the PR, the branch, the
commit. If an earlier document is wrong, correct it in the new plan *and* fix the original.

**Keep evidence out of the argument.** `file:line` references, counts and measurements go in a
**Provenance** section at the end, with the sha they were measured against.

**Standard sections**, in order, omitting empty ones: summary, Scope (in and out), the problem, what the
plan delivers, Work items (numbered table), how we know it is right (acceptance bar and exact commands),
Decisions, Risks, Open questions, Provenance.

- **Decisions** are numbered and permanent (`P4-D3 · …`); each states the alternative and why it lost.
- **Risks** name the mitigation, preferring structural mitigations to intentions.
- **Open questions** are only ones needing human judgment.
- Preserve my inline `==**KC:** …==` comments verbatim when revising a plan I annotated.

## Writing PR descriptions

**A PR description is for a human, and a long one does not get read.** Well under a screen or two; 50
lines is generous, 200 is a failure.

- Describe only what this PR does, at the level of system behaviour. No file tables, line counts, symbol
  maps or commit-by-commit lists: the diff is one click away.
- Explain only the terms the PR invents. Assume the reader knows the platform. More than about two coined
  terms is a sign the design is wrong.
- Lead with the outcome, and say what stays the same.
- Keep the verification honest and short: a few bullets naming what was checked and the numbers.
- Do not narrate future phases. Something long but useful goes in a collapsed `<details>` block, or out.

## Which model: Opus only for judgment

Always set `model` explicitly when spawning a subagent. Sonnet is the default (code, planning, running
gates, searching, tracing, summarising, formatting). Opus only for the agent that needs the deepest and
widest thought: designing the ideal solution, judging between designs, adversarially verifying findings.
Do not set `CLAUDE_CODE_SUBAGENT_MODEL`: it overrides every per-agent `model`.

## Delegating to subagents

A subagent working in a repo must `cd` into it first, read its `CLAUDE.md`, use its task runner (justfile
before Makefile), `uv run` for Python and `git --no-pager` for git.

## Git worktrees: always use the `wt*` helpers

Never use raw `git worktree add/remove/list`, a native worktree tool (`EnterWorktree`, `--worktree`) or a
skill's fallback: they put worktrees in the wrong place. This rule overrides any skill that says otherwise.

All worktrees live at `~/github/<repo>-wt/<branch>/`.

| Command | Purpose |
|---------|---------|
| `wta <repo> <branch> [base]` | Create a worktree at `~/github/<repo>-wt/<branch>` and `cd` into it. Checks out `<branch>` if it exists, else creates it from `<base>` (default `HEAD`). Fetches first. |
| `wtl [repo]` | List active worktrees. |
| `wtc <repo> <branch>` | `cd` into an existing worktree. |
| `wtr <repo> <branch>` | Remove a finished worktree; prompts to delete the branch. |
| `wts <repo> <branch>` | Symlink the worktree into the current directory as `<repo>@<branch-with-dashes>`. |
| `wtu <repo> <branch>` | Remove such a symlink. |

They are zsh functions: from the Bash tool, run them as `zsh -i -c 'wta <repo> <branch>'`. The `cd` only
affects that shell, so use explicit paths afterwards. `wtl` and `wta` only see repos in `WT_REPOS` when it
is set.

## Housekeeping

When a scheduled task or poll completes or is cancelled, delete any `.claude/scheduled_tasks.lock` file it
left in the project directory.

## This machine

@~/.claude/kc-extensions/CLAUDE.md
