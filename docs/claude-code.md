# Claude Code setup

How Claude Code is set up on this machine: one terminal, ordinary sessions, skills instead of teams, and
a personal assistant (Stella) who is just another session.

```
Alacritty ── tmux session `work`
              └─ window 1 `main`
                   ├─ left:  claude agents        every session, grouped by what it needs
                   └─ right: the session you work in (cy, or cw <name>)
```

## Pieces

| Piece | Lives in | Linked to |
|---|---|---|
| Global instructions (public half) | `claude/CLAUDE.md` | `~/.claude/CLAUDE.md` |
| Skills (`kc-*`, `stella*`) | `claude/skills/<name>/SKILL.md` | `~/.claude/skills/<name>` |
| The `stella` agent | `claude/agents/stella.md` | `~/.claude/agents/stella.md` |
| Hooks every session runs | `claude/plugin/hooks/hooks.json` → `claude/bin/kc-hook` | the `kc@kc-local` plugin |
| `stella` command | `claude/bin/stella` | `~/.local/bin/stella` |

`./setup.sh` links all of it and installs the plugin; re-run it after adding a skill or agent. After a
change to `hooks.json`, run `claude plugin update kc@kc-local` and start new sessions; a change to
`kc-hook` itself is live at once.

## Layering: public first, then the machine's own

The public half never names the machine's work. The machine adds its own on top, from
`~/.claude/kc-extensions/` (a link into the machine's own repo):

| Public | Machine's own, when present |
|---|---|
| `~/.claude/CLAUDE.md` | imports `~/.claude/kc-extensions/CLAUDE.md` at its end |
| skill `kc-review` | `~/.claude/kc-extensions/kc-review.md`, read as the skill's first step |
| (same for every skill) | `~/.claude/kc-extensions/<skill>.md` |

An extension only adds constraints; where it is stricter, it wins.

## Skills

| Skill | Does |
|---|---|
| `/kc-review <pr|branch|docs>` | Deep review: debates the best design, then UX, robustness, consistency, code quality; learns from corrections in `~/.local/share/kc-review/knowledge.md` |
| `/kc-debug <problem>` | Root cause with evidence; changes nothing unless asked |
| `/kc-plan <task>` | A plan in the vault; no code |
| `/kc-dev <plan or order>` | Builds straight away: worktree, tests, verify, commit, push |
| `/kc-tutorial <topic>` | A tutorial or explainer in the vault |
| `/kc-log [day]` | The daily log in the vault (`day`: every session of the day) |
| `/stella <message>` | Pass a message to Stella |
| `stella-agents`, `stella-audit`, `stella-priorities`, `stella-setup` | Stella's own skills |

Each skill decides for itself whether the task deserves subagents, and which.

## Hooks (`kc-hook`)

| Event | Does |
|---|---|
| Stop | The turn's final message must end with the status block (rule line, then NEXT FOR YOU (N) with N numbered items, ALL DONE or WORKING). Blocks once with the rule when it is missing or malformed. Skipped for `claude -p`. |
| UserPromptSubmit | A message starting "Stella" / "S," (or ending with her name, or "ask/tell Stella") is for Stella: the session is told to relay it with the `stella` skill. Not in her own session. |
| PreToolUse (Bash) | A `git push` into this repo or one of its worktrees runs the machine's `push_check` (named in the stella extension) over the commits and messages it would publish: no hits, allowed without a prompt; hits, denied with the list; no check configured, it asks. A session whose crew record lists `push` in `allow` is also not prompted for other pushes. |

## Stella

An ordinary background session named `stella`, started in `~/.local/share/stella` with the `stella`
agent. `stella` opens it (starting it if needed); `stella launch <name> <dir> <prompt>` starts a session
exactly like `cd <dir> && cy` would, in the agents view. Other sessions reach her with `SendMessage`.
Her store, `~/.local/share/stella/`: `priorities.md`, `canon.md` (the owner's judgment), `journal.md`.
Her recurring duties (daily log, agents tidy, weekly audit) are session crons she recreates when her
session starts.

## Commands

| Command | Does |
|---|---|
| `tw` | Attach the `work` session, building the main window the first time |
| `cy` | New session, permission prompts skipped |
| `cag` | The agents view |
| `cw [name]` | Open a background session here (no name: pick with fzf); Ctrl+Z drops back to the shell |
| `stella` | Open Stella's session |
