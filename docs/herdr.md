# herdr: the work window

[herdr](https://github.com/herdrdev/herdr) is a terminal multiplexer built for coding agents: workspaces
hold tabs, tabs hold panes, a background server keeps them running when the terminal closes, and a sidebar
shows each agent's state (blocked, working, done, idle) by reading its screen. Apache-2.0 from v0.8.0;
install it with the package manager, never a release older than v0.8.0.

## The layout

| Where | What |
| --- | --- |
| Workspace `work`, first tab | Stella's session: talk to her here |
| Left of Stella's tab | the crew list: `stella crew --watch`, one line per crewmate under its project, with its state and need |
| A crewmate's tab, only when asked | `claude attach <id>`: a view of a session that lives in the Claude daemon. Closing the tab does not stop it |
| The sidebar | every agent herdr sees in a pane and its state (a crewmate without a tab is not in it: the crew list is) |

`tw` starts the server if needed, builds `work` the first time (`stella`), puts the crew list in a pane on the left of Stella's tab (`stella crew --pane`, once), re-attaches any open tab whose session restarted (`stella view --repair`; it opens nothing) and attaches. Crewmates get a tab only when Kohen asks to talk to one (`stella view <name>`); `stella hide` closes crew tabs (never any other) and `stella rm` closes the tab of the crewmate it removes. Detach with `C-b q` or `C-b d`, or close the window: everything keeps running. `twt` is the
tmux window from before, kept as the fallback.

## Keys

`local/herdr.toml`. Alacritty's Cmd chords arrive as `alt+…` chords, so the tmux keys carry over (see
`docs/tmux.md` for the table). Missing in herdr: Cmd+0 (last tab), Cmd+Shift+Space (next layout),
Cmd+Shift+B (the chord off-switch). Search is copy mode (`Cmd+F`) then `/`.

## What is not used

- herdr's Claude integration hook (`herdr integration install claude`): the Claude daemon already resumes
  background sessions, and the hook writes to herdr's socket from every session.
- Driving herdr from inside an agent's shell: only the `stella` helper calls herdr, with a validated name.
