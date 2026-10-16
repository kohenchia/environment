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

Planning, building and verifying are judgment work: run every subagent below on `model: "opus"`.
Use `sonnet` only for mechanical side tasks (finding callers, listing files, collecting logs).

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

- Commit locally with a message that says what and why. **Do not push**; pushing is the owner's call
  (a push from a guarded repo prompts the owner to approve it).
- `~/.local/bin/stella done <name> "<what changed, where (repo, branch, commit), how it was verified, what is
  left>"`.
