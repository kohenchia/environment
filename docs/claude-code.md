# Claude Code setup

How Claude Code is set up on this machine: ordinary sessions run by Claude's background daemon, skills instead of
teams, one gate on publishing, and a personal assistant (Stella) in a permanent session.

```
Alacritty ── herdr (tw)                                  Claude's background daemon
  space per project ── window per session ───────────►   every session; `cag` is the master list
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
| `stella`, `kc-env`, `herdr-space` | `bin/` | `~/.local/bin/` |

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
her manual. She automates routine operations and does not manage other sessions: a daily log of every project
worked on (`/kc-log day`), a weekly audit of memories, instructions and skills, Kohen's priorities from their Slack,
answering a waiting session when the canon settles it, and learning preferences into proposals for skills and
canon. Her manual, memory files and routines are in her agent file; no other session loads it. Her routines are
durable session crons she recreates at the start of her session.

## Commands

| Command | Does |
|---|---|
| `kc-env` | Every command, skill and background process of this environment |
| `kc-shot` | Types the screenshot you just took into the focused pane (`Cmd+Shift+V`) |
| `kc-keys` | Every key binding of the work window, read from the Alacritty and herdr configs |
| `tw` | The work window: herdr, one space per project |
| `cy` | New session, permission prompts skipped |
| `cag` | The agents view |
| `cw [name]` | Open a background session here (no name: pick with fzf) |
| `stella` | Open Stella's session |
