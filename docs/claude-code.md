# Claude Code setup

How Claude Code is set up on this machine: ordinary sessions run by Claude's background daemon, skills instead of
teams, one gate on publishing, and a personal assistant (Stella) in a permanent session.

```
Alacritty ── herdr (tw)                                  Claude's background daemon
  spaces you make  ── a window per session ──────────►   every session; `cag` is the master list
  space `stella`    ── her permanent session
```

## Pieces

| Piece | Lives in | Linked to |
|---|---|---|
| Global instructions (public half) | `claude/CLAUDE.md` | `~/.claude/CLAUDE.md` |
| Skills (`kc-*`) | `claude/skills/<name>/SKILL.md` | `~/.claude/skills/<name>` |
| The `stella` agent | `claude/agents/stella.md` | `~/.claude/agents/stella.md` |
| The leak gate | `githooks/pre-push` | `core.hooksPath` of this repo |
| The guard around it | `claude/plugin/hooks/hooks.json` → `claude/bin/kc-hook` | the `kc@kc-local` plugin |
| `stella`, `stella-check`, `kc-env`, `kc-keys`, `herdr-space`, `kc-new`, `kc-sessions` | `bin/` | `~/.local/bin/` |

`./setup.sh` links all of it and installs the plugin; re-run it after adding a skill or agent.

## Layering: public first, then the machine's own

The public half never names the machine's work. The machine adds its own on top, from
`~/.claude/kc-extensions/` (a link into the machine's own repo): `CLAUDE.md` is imported at the end of
`~/.claude/CLAUDE.md`, and each skill reads `~/.claude/kc-extensions/<skill>.md` as its first step. An extension
only adds constraints; where it is stricter, it wins.

## The leak gate

A push from this public repo runs `githooks/pre-push`, which runs `~/.local/bin/leakcheck` (the machine's own
check; a link to its denylist scanner) over exactly what the push adds: every commit message and every file it
adds or changes. A hit refuses the push and prints it; the session rewrites it generically, amends and pushes
again. A machine without the check cannot push (the hook fails closed). `kc-hook` (a PreToolUse hook) denies the
ways around the hook: `git push --no-verify` and changing `core.hooksPath`. Tests: `python3 -m unittest discover tests`.

## Sessions

Every session is a background session of Claude's daemon, so `cag` (the agents view) lists all of them and which
ones need you. `cw [name]` attaches one here (Ctrl+Z drops back to the shell; it keeps running). `tw` shows them in
herdr (see `herdr.md`).

## Stella

A personal assistant in a permanent background session named `stella`, started in `~/.local/share/stella` with the
`stella` agent. `stella` opens it (starting it if needed), `stella start` only starts it, `stella restart` reloads
her manual. She automates routine operations, starts a session in a space (through `kc-new`) for a task Kohen gives
her, and does not otherwise manage other sessions. Kohen watches their sessions themselves, so the only thing she
reports is how many are waiting for them. She answers a waiting session herself when the canon settles it with
certainty and, in the overnight window her manual sets in one line (23:00-07:00 Pacific), with the session's own
default when that is reversible, not outward-facing and no change of scope, logging each in `overnight.md` for the
first status of the morning. She learns Kohen's preferences into proposed canon, and in the background writes a daily log of every session
that worked (`/kc-log day`), keeps proposed priorities from their Slack, and audits memories, instructions and skills
weekly. Those results go into files in her store (`priorities.md`, `canon.md`, `audit.md`), which Kohen reads when
they want. Her manual, memory files and routines are in her agent file; no other session loads it. Her daily and
weekly routines are durable session crons she recreates at the start of her session.

Nothing runs a model on a timer to watch the other sessions. `stella-check` (`bin/`) does that without one: it reads
the job records every minute and runs her PR helper every 10 minutes, and wakes her only for what she can act on:
a blocked session whose last message asks a bare question (a "Needs you" table means the session marked the ask as
Kohen's, so no wake; once per blocked episode, not per rewording), an API-error stop (hourly, up to 3 hours), a PR item
that is new or whose signature changed (a conflict counts once it has held for two runs; an item she marked `noted`
for that signature is silent and listed under `noted` in `pr-tasks.json`), a merged set whose session is not working,
a due reminder, and the check's own errors. A session in a mode that holds her messages is no wake: it matters only
when an item for it says `would_be_held`. Hooks in her project settings start the watcher at session start and at the
end of every turn (`asyncRewake`: its exit code 2 starts her turn), and `stella` writes those settings on every
start and restart, with recaps off, a one-hour prompt cache and, after a day of PR lists in files, a 200k-token
compaction window. A quiet hour draws nothing and spends nothing, except one hourly judgment check (a self-paced
`/loop` whose quiet ticks Claude Code folds into one row). Each wake and each action she takes is a line in
`~/.local/share/stella/events.log`; her lasting PR tasks are in `pr-tasks.json`.

In her session, `/calm` (the `kc` plugin's `stella-calm.tsx`) hides tool rows, turn timings, the wake row
("stella-check wake") and her bare "Quiet." reply, so a wake that needed nothing leaves nothing on screen (on by default;
`/calm` again shows everything; failed tool calls always show). **It only works if the module loads, and Claude Code
loads a hooks module only if its static check passes**: a helper that takes `$` must be declared at the top level of the
file, and a name that is passed `$` must not be assigned anywhere else. A module that fails the check does not load, silently
(the error is a line in the transcript only when it reloads while running). To see whether it loaded, read
`~/.local/share/stella/calm.status` (one line per session start; `kc-env` shows it). To test a change without restarting
her: copy the module into a throwaway session's user-level plugin folder and read the "reloaded" or "reload failed" line it
leaves in that session's transcript. It needs `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1` in the `env` of
`~/.claude/settings.json` (the hooks do not), and `./setup.sh` (which links `stella-check`) before `stella restart`
switches her over.

## Commands

| Command | Does |
|---|---|
| `kc-env` | Every command, skill and background process of this environment |
| `kc-keys` | Every key binding of the work window, read from the Alacritty and herdr configs |
| `tw` | The work window: herdr, with the spaces you make |
| `cy` | New session, permission prompts skipped |
| `cag` | The agents view |
| `cw [name]` | Open a background session here (no name: pick with fzf) |
| `stella` | Open Stella's session |

## Sessions starting sessions: `kc-new`

A session's shell runs in Claude Code's command sandbox, where `claude` cannot start (it cannot nest a sandbox) and
herdr's socket cannot be reached. `kc-new` does both on the session's behalf, and it is the only thing that has to
run outside the sandbox. It takes **no arguments** and trusts nothing it reads, so the sandbox's command allowlist
can allow it by an exact match.

The session writes a request and then runs `~/.local/bin/kc-new` as the only command:

```
$CLAUDE_JOB_DIR/tmp/kc-new.json   {"space": "reports", "dir": "~/github/project", "name": "reports-docs",
                                   "prompt": "the new session's first message"}
```

| Field | Rule |
|---|---|
| `space` | the herdr space for the session's window; made when no space has that name. Letters, digits, space, `.`, `-`, `_`, `#` |
| `dir` | an existing directory under `~/github` or a directory listed in `~/.config/kc-new/roots` (symlinks resolved first) |
| `name` | the session's name: lower-case letters, digits, dashes. Default: the space's name |
| `prompt` | its first message, up to 20,000 characters, passed as one argument, never through a shell |
| `model` | optional: `opus`, `sonnet` or `haiku`; default is the machine's default model. Use `opus` for a review or any task that needs deep judgment |
| `effort` | optional: `low`, `medium`, `high`, `xhigh` or `max`. Use `high` with `opus` for a review, a plan or a debug |

It starts the session like `cy` would (`claude --bg … --dangerously-skip-permissions`, on the current default
token), opens a window in the space running `claude attach <id>`, and prints one line. The request is deleted as it
is read, so a refused one is never retried; the answer is also in `kc-new.result.json` next to it.

A request with `restart` instead of `space`/`dir`/`name`/`prompt` restarts a named session:
`{"restart": "<session name>", "prompt": "optional first message", "space": "optional herdr space"}`. A session in any
other permission mode holds a peer's messages for its user's approval, and they expire unread, so it is continued in
bypass-permissions mode: the one restart that has to change the job id (the mode is fixed when a job is created). A
session already in bypass mode is refused unless `"force": true`, which restarts it **in place**: same job id, flags and
crons, the instruction files reloaded. Both go through `kc-sessions` (below). The request is refused for `stella`
(`stella restart` does hers), for a busy session (retry when idle), and for a name that more than one session holds.
A new session may not take a name that a live session already has.

Two more requests change a session without restarting it, and take no other fields:

```
$CLAUDE_JOB_DIR/tmp/kc-new.json   {"move": "<session name>", "space": "<herdr space>"}
                                   {"rename": "<session name>", "to": "<new name>"}
```

| Request | Does | Refused for |
|---|---|---|
| `move` | moves the window that runs `claude attach <id>` into the space as a new tab (`herdr pane move --new-tab`, or `--new-workspace` when no space has that name); the pane keeps its process | a name more than one session holds; a session with no window, or with more than one; a request for the space it is already in answers `ok` and changes nothing |
| `rename` | writes the new `name` (with `nameSource: "user"`) into the job's `state.json`, as the agents view does, reads it back, and renames the window's tab when its title is the old name. `new` is lower-case letters, digits, dashes | `stella`; a busy session (retry when idle); a name more than one session holds; a name a live session already has |

A rename may leave `-n <old name>` in the job's saved flags, as a rename made in the agents view does: the name in
`state.json` wins, and it survives a restart in place (checked on a throwaway session). If herdr is unreachable the session is still renamed and the printed line says `WARNING`.

A third, `{"retire": "<session name>"}`, stops a session and removes its record (`kc-sessions retire --rm`; a session
in a git worktree is stopped but kept). It exists because a sandboxed session cannot run `claude stop`: **only the session that
started the session through `kc-new` may ask** (`kc-new` records who started whom in `~/.local/state/kc-sessions/started.json`),
and Stella for any. It refuses `stella`, the asker itself, a busy session, and a name more than one session holds. The
window falls back to its shell and stays open.

After starting a session, `kc-new` runs the machine's hook `~/.config/kc-new/after-start <new job id>` when it exists
(`KC_CALLER_JOB` is the asking job). The work setup uses it so that a session started by another one bills the token the
asker bills, not the default; if the hook fails the session stays and the printed line says `WARNING`.

A request `{"doctor": "report"}` returns drift in sessions and windows in `kc-new.result.json` (any session may ask);
`{"doctor": "repair"}` is Stella's alone, takes no other field, and runs at most once in 10 minutes. Both run the
machine's hooks `~/.config/kc-sessions/doctor` and `~/.config/kc-sessions/repair` when they exist, else
`kc-sessions check` / `kc-sessions repair`. Run `kc-new` as the only command of its Bash call: combined with another command it runs in the sandbox, where
`claude stop` and `claude --bg --resume` fail with `sandbox_apply: Operation not permitted`.

## Restarting sessions without disturbing anything: `kc-sessions`

Two restarts exist and they differ:

| | `claude respawn <id>` | `claude --bg --resume <session id> <any flag>` |
|---|---|---|
| Job id, session id, name | kept | **new**; the old record stays under the same name |
| Flags (mode, model, effort, agent), crons | kept | only what is repeated on the new command line |
| Herdr window running `claude attach <id>` | its attach ends, the pane falls back to its shell | still points at the old id (grey) |

`kc-sessions` is the one tool that restarts sessions: `respawn` (in place; windows get their attach back, a busy session
is waited for with `--wait-idle SECONDS`), `restart TARGET --prompt TEXT` (in place with a first message), `fork`
(continue in bypass mode: new job first, windows moved, the old one stopped and removed unless it did work since or runs
in a git worktree), `retire`, `check` (duplicate names, windows that attach a stopped job, grey dots, sessions not in
bypass mode; `--files-only` needs neither `claude` nor herdr, so a sandboxed session can run it), `repair` and `list`.
It types into a pane only when every process there is a shell and the screen has stopped changing, and only for a pane
it saw attached to the job it restarted (recorded in `~/.local/state/kc-sessions/detached.json` until the attach is
back), never into a Claude, a pager or a shell somebody is typing in.

The allowlist entry is the machine owner's to add, never a session's. It must be an **exact** match of
`~/.local/bin/kc-new`: a `contains_match` entry, or an entry for `claude` or `herdr` themselves, would let any
command containing that word run outside the sandbox.
