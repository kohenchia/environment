---
name: stella-setup
description: How Kohen's environment is built - Alacritty and tmux, the shell, Claude Code skills, extensions, hooks, agents, Stella, token handling - and how to change any of it safely. Use when Kohen asks to tweak, fix or explain his setup, or Stella needs to know where something lives.
---

# stella-setup

## The pieces

| Piece | Where | Notes |
|---|---|---|
| Terminal | Alacritty, one window, `~/github/environment/local/alacritty.toml` | Translates Cmd chords into ESC sequences tmux binds |
| tmux | `local/.tmux.conf`, docs in `docs/tmux.md` | One server, session `work`; the window list on top. `tw` attaches and builds the main window: left pane the agents view (`cag`), right pane the session Kohen works in |
| Shell | `local/.zshrc` (sources the machine's own extra rc file when present) | `cy` new session, `cag` agents view, `cw` attach to a session, `tw` the workspace, `wt*` worktrees |
| Global instructions | `~/.claude/CLAUDE.md` → `~/github/environment/claude/CLAUDE.md` | Public rules; it imports the machine's own instructions at the end |
| Skills | `~/github/environment/claude/skills/<name>/`, linked into `~/.claude/skills/` | Public. Each reads `~/.claude/kc-extensions/<name>.md` first when it exists |
| Extensions | `~/.claude/kc-extensions/` → the machine's own repo | Adds constraints to the public skills; never in the public repo |
| Agents | `~/github/environment/claude/agents/`, linked into `~/.claude/agents/` | `stella` is the main agent of her session |
| Hooks | the `kc` plugin (`~/github/environment/claude/plugin`, marketplace `kc-local`) running `claude/bin/kc-hook` | Status block (Stop), messages for Stella (UserPromptSubmit), the push prompt for `~/github/environment` (PreToolUse) |
| Stella | her session (`stella`), her store `~/.local/share/stella/`, `claude/bin/stella` linked to `~/.local/bin/stella` | |
| Setup | `~/github/environment/setup.sh` (`--check` to verify) | Links everything; re-run after adding a skill or agent |

The machine's own repo (named in the extension) adds its rc file, instructions, extensions, plugin and
tools on top; its own setup script links them.

## Changing it

1. **Pick the repo by content, not convenience.** Anything not specific to Kohen's employer goes in
   `~/github/environment` (public: no employer names, hosts, people, paths or examples, ever; the leak
   check refuses a commit that has them). Anything specific to his work goes in the machine's own repo.
   When unsure, ask.
2. Edit the real file in the repo; the dotfiles are symlinks and the Edit tool refuses to write through a
   symlink.
3. Re-run the repo's `setup.sh` when a link is added (new skill, agent, binary). A changed `hooks.json`
   needs `claude plugin update kc@kc-local` (or the machine's plugin) and new sessions; a changed hook
   script is live at once.
4. tmux: `tmux source-file ~/.tmux.conf`. Alacritty reloads its config on save.
5. Verify for real (the chord, the hook firing, the layout), then commit. Pushes to `~/github/environment`
   ask Kohen through Claude Code's prompt; other repos push freely.
6. Keep `docs/` and this skill true to what changed.
