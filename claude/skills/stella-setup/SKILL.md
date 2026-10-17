---
name: stella-setup
description: How Kohen's environment is built - Alacritty and tmux, the shell, Claude Code skills, extensions, hooks, agents, Stella, token handling - and how to change any of it safely. Use when Kohen asks to tweak, fix or explain his setup, or Stella needs to know where something lives.
---

# stella-setup

## The pieces

| Piece | Where | Notes |
|---|---|---|
| Terminal | Alacritty, one window, `~/github/environment/local/alacritty.toml` | Translates Cmd chords into ESC sequences the multiplexer binds |
| herdr | `local/herdr.toml` → `~/.config/herdr/config.toml`, docs in `docs/herdr.md` | The work window: `tw` starts the server, builds workspace `work` (a `stella` tab, a tab per crewmate) and attaches. The sidebar shows each agent's state. Update checks off |
| tmux | `local/.tmux.conf`, docs in `docs/tmux.md` | The fallback: `twt` builds the Work Env 2.0 window (agents view left, session right) |
| Shell | `local/.zshrc` (sources the machine's own extra rc file when present) | `cy` new session, `cag` agents view, `cw` attach to a session, `tw` / `twt` the work window, `wt*` worktrees |
| Global instructions | `~/.claude/CLAUDE.md` → `~/github/environment/claude/CLAUDE.md` | Public rules; it imports the machine's own instructions at the end |
| Skills | `~/github/environment/claude/skills/<name>/`, linked into `~/.claude/skills/` | Public. Each reads `~/.claude/kc-extensions/<name>.md` first when it exists |
| Extensions | `~/.claude/kc-extensions/` → the machine's own repo | Adds constraints to the public skills; never in the public repo |
| Agents | `~/github/environment/claude/agents/`, linked into `~/.claude/agents/` | `stella` is the main agent of her session |
| Hooks | the `kc` plugin (`~/github/environment/claude/plugin`, marketplace `kc-local`) running `claude/bin/kc-hook` | Status block (Stop), messages for Stella (UserPromptSubmit), the push prompt for `~/github/environment` (PreToolUse) |
| Stella | her session (`stella`, on Sonnet), her store `~/.local/share/stella/` (`crew/<name>/` records and briefs, `journal.md`, `canon.md`), `claude/bin/stella` linked to `~/.local/bin/stella` | The helper is the one command allowed outside the command sandbox; it validates every argument. After a change to her skill or setup, `stella restart` (not a plain re-attach, which skips her start-of-session steps). `stella --help` |
| Stella's watcher | `claude/bin/stella-watch` → `~/.local/bin/stella-watch` | A sandboxed background command in her session; exits (waking her) when the crew needs her |
| Tripwire | `claude/bin/live-check` (`stella live-check before|diff`) | Proves a change restarted, removed or re-tokened no running session |
| Calm mode | a function-hooks module in the `kc` plugin (`claude/plugin/hooks/`) | Only in Stella's session, only with `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1`; `/calm` toggles; the crew band above her prompt |
| Tests | `claude/tests/` | `python3 -m unittest discover -s claude/tests`; the kc-hook differential test must pass before any hook change merges |
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
4. herdr: `herdr server reload-config` (or `prefix+shift+r`). tmux: `tmux source-file ~/.tmux.conf`.
   Alacritty reloads its config on save.
5. Anything that runs in every session (kc-hook, the plugin, the helper) changes running sessions the
   moment it lands: build it in a worktree, run `python3 -m unittest discover -s claude/tests`, and run
   `stella live-check before` / `diff` around the merge.
6. Verify for real (the chord, the hook firing, the layout), then commit. Pushes to `~/github/environment`
   ask Kohen through Claude Code's prompt; other repos push freely.
7. Keep `docs/` and this skill true to what changed.
