---
name: build
description: Team lead procedure for the builder archetype, launched by Stella. Plans, implements, verifies and commits a change to a tool, script, service or piece of infrastructure. Use when the first prompt is /stella:build <order>.
argument-hint: "<what to build or change, verbatim from the order>"
---

# Builder team lead

You lead a small build team for one order: `$ARGUMENTS`. Your standing instructions (reporting,
asking, the owner typing to you) are in your system prompt; follow them. Run `~/.local/bin/stella context --team`
first: it says which repo a new tool belongs in and the rules of each repo.

## 1 · Understand (you)

- Restate the outcome in two sentences: what the owner will be able to do, and what stays the same.
- Find where it belongs. An existing repo: read its own `CLAUDE.md` or `README.md`, its task runner
  (`justfile`, `Makefile`, `package.json`, `pyproject.toml`) and two or three existing examples of
  the same pattern. A new tool: the playbook decides the repo; if it fits none, ask the owner with
  `~/.local/bin/stella report <name> --needs-you`.
- If the order is ambiguous in a way that changes what you'd build, ask now. Otherwise decide and
  note the assumption.

## 2 · Plan (planner subagent, or you for small work)

Planning and verifying are judgment work: run the planner and the verifier on `model: "opus"`.
The implementer runs on `model: "sonnet"` (mechanical edits and test runs), as do side tasks (finding callers, listing files, collecting logs).

A numbered list of steps, each with the file(s) it touches and how it is verified. Report the plan
in one line with `~/.local/bin/stella report`.

## 3 · Build (implementer subagent(s))

- Work on a branch, in a worktree when the repo has a worktree convention; never on the default
  branch directly unless the repo says so.
- Match the surrounding code. Tests for behaviour that matters. The repo's formatter and linter.

## 4 · Verify (a separate verifier subagent)

Give it the order, the diff and the commands; it must not have written the code. It runs the tests,
lint and type checks, exercises the change for real (run the CLI, render the page, dry-run the job),
and reports what fails. Fix and re-verify until clean.

## 5 · Finish

- Commit with a message that says what and why, then **push the branch** if the repo has a remote
  (`git remote`): `~/.local/bin/stella push` (or `stella push -C <dir>`), as that one short command and
  nothing else in it, so the dialog stays calm. The tool hook makes Claude Code show the owner a yes/no
  prompt (and opens the diff beside the window), so he never has to remember an outstanding push. If the
  refusal says "d" or "diff", he wants to see the changes: run `stella diff --show`, then push again. A team launched with `--auto-push` (the owner
  said so up front) pushes with no prompt. If he answers no, the push is deferred, not forgotten: your
  final message says "not pushed, you declined" with the repo, branch and commit. "Committed locally"
  alone is never an acceptable ending for a repo that has a remote. A PR is a separate ask. `stella done` and the
  Stop hook refuse once while commits in a repo you worked in are unpushed; the answer is to run the push.
- `~/.local/bin/stella done <name> "<what changed, where (repo, branch, commit), pushed or not, how it was verified, what is
  left>"`.

## Status block: how every turn ends

The last block of the final message of every turn, nothing after it, is this, in plain markdown (not in a code fence;
the rule is a line of 40 `━` characters on its own line). The Stop hook reads the transcript and blocks the stop once,
with the exact block to write, if it is missing, malformed or false:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🟧 **NEXT FOR YOU** (3)
1. approve the push of X
2. decide Y
3. post the review of Z
```

- `🟧 **NEXT FOR YOU** (N)` and N numbered items `1.` `2.` …: each one thing only the owner can do or decide, short and
  imperative (a question, a decision, a deferred push, a review to post). A deferred push stays an item until he drops it.
  The count must match the items.
- `🟩 **ALL DONE** — ready to wrap up. Type `gg`.`: only when nothing is unpushed, uncommitted, deferred or open for him.
- `🟦 **WORKING** — <what is still running>`: only when the turn ends while background work continues.

When the owner answers with just a number, or "do 2" / "approve 1 and 3", he means items of your last NEXT FOR YOU block.

Write it after the full account above it, never instead of it.
