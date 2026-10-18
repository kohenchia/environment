# herdr: the work window

[herdr](https://github.com/herdrdev/herdr) is a terminal multiplexer built for coding agents: workspaces
hold tabs, tabs hold panes, a background server keeps them running when the terminal closes, and a sidebar
shows each agent's state (blocked, working, done, idle) by reading its screen. Apache-2.0 from v0.8.0;
install it with the package manager, never a release older than v0.8.0.

## The layout

| Where | What |
| --- | --- |
| Workspace `stella`, its one tab | Stella's session: talk to her here. Nothing else is a tab of this window |
| The sidebar, top (Spaces) | `stella`, then one workspace "└ <project> · <crewmate>" per live crewmate, grouped by project (priorities.md order, then alphabetical; no project last) |
| The sidebar, bottom (Agents) | herdr's own panel: one row per agent with its state dot, workspace, tab and harness. It is herdr's default, the same as firstmate's |
| A crewmate's workspace | one tab, `fm-<crewmate>`, whose shell runs `while stella listed <id>; do claude attach <id>; sleep 2; done`: `claude attach` itself is the foreground process (herdr detects an agent from that, so a wrapper process in front of it would hide it), and the loop attaches again after a restart, of a session that lives in the Claude daemon. If herdr still lists no agent in the pane, `stella crew sync` registers it with `herdr pane report-agent` (source `stella`) and releases that when herdr sees it itself. Closing it does not stop the session |

`tw` starts the server if needed, builds `stella` the first time (it renames an older `work` workspace) (`stella`) and runs `stella crew sync`, which creates the workspace of each live crewmate that has none (`--no-focus`, then moved right after the last crew workspace, or after `work`, over the control socket as firstmate does), attaches again in a tab showing "session exited", and closes the workspace of a session that has gone for good. You stay in Stella's tab and click a row to visit a crewmate (`stella view <name>` does the same). `stella crew doctor [--json]` prints what herdr holds (workspaces in order, tabs, panes, agents) next to what the records expect; it is how the sidebar is debugged. `stella launch`, `adopt`, `rm` and `tok` keep the sidebar in step, and Stella runs it after each wake. `stella hide` only closes crew tabs of the earlier layout (opened in the `work` window). Detach with `C-b q` or `C-b d`, or close the window: everything keeps running. `twt` is the
tmux window from before, kept as the fallback.

## Keys

`local/herdr.toml`. Alacritty's Cmd chords arrive as `alt+…` chords, so the tmux keys carry over (see
`docs/tmux.md` for the table). Missing in herdr: Cmd+0 (last tab), Cmd+Shift+Space (next layout),
Cmd+Shift+B (the chord off-switch). Search is copy mode (`Cmd+F`) then `/`.

## What is not used

- herdr's Claude integration hook (`herdr integration install claude`): the Claude daemon already resumes
  background sessions, and the hook writes to herdr's socket from every session.
- Driving herdr from inside an agent's shell: only the `stella` helper calls herdr, with a validated name.
