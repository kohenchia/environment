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
| `stella`, `kc-env`, `kc-keys`, `herdr-space`, `kc-new` | `bin/` | `~/.local/bin/` |

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
certainty, learns Kohen's preferences into proposed canon, and in the background writes a daily log of every session
that worked (`/kc-log day`), keeps proposed priorities from their Slack, and audits memories, instructions and skills
weekly. Those results go into files in her store (`priorities.md`, `canon.md`, `audit.md`), which Kohen reads when
they want. Her manual, memory files and routines are in her agent file; no other session loads it. Her routines are
durable session crons she recreates at the start of her session.

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

It starts the session like `cy` would (`claude --bg … --dangerously-skip-permissions`, on the current default
token), opens a window in the space running `claude attach <id>`, and prints one line. The request is deleted as it
is read, so a refused one is never retried; the answer is also in `kc-new.result.json` next to it.

A request with `restart` instead of `space`/`dir`/`name`/`prompt` restarts a named session in bypass-permissions mode:
`{"restart": "<session name>", "prompt": "optional first message", "space": "optional herdr space"}`. It exists because a
session in any other mode holds a peer's messages for its user's approval, and they expire unread. It refuses `stella`,
a session already in bypass mode, and a session that is working (retry when idle); otherwise it stops the session
(`claude stop <job id>`) and resumes its conversation with `--dangerously-skip-permissions`. Without `space` it prints a
hint to run `tok reattach` for the window.

The allowlist entry is the machine owner's to add, never a session's. It must be an **exact** match of
`~/.local/bin/kc-new`: a `contains_match` entry, or an entry for `claude` or `herdr` themselves, would let any
command containing that word run outside the sandbox.
