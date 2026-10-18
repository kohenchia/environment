# herdr: the work window

[herdr](https://github.com/herdrdev/herdr) is a terminal multiplexer built for coding agents: a background
server keeps everything running when the terminal closes, and a sidebar shows each agent's state. Apache-2.0
from v0.8.0; install it with the package manager, never a release older than v0.8.0.

herdr's words and mine differ. This setup uses mine:

| I say | herdr says | Here |
| --- | --- | --- |
| **space** (= a project) | workspace | a row in the Spaces list, top of the left column |
| **window** | tab | an entry in the window bar at the top of a space |
| **pane** | pane | a split inside a window |
| **dot** | state icon | the glyph before a row in either panel |

## The layout

```
Spaces                       window bar of the active space
  ● stella                   [ bolt-priority ] [ 2398-rebase ] [ pr-2398-kohen ] [ 2398-dev-priority-all ]
  ● bolt-priority  2 waiting  
  ○ docs-drift                Agents (the active space only)
  ● tracker                     ● 2398-rebase        <- one line of what it needs
                                ● pr-2398-kohen
```

| Where | What |
| --- | --- |
| Space `stella`, first | Stella's window, then one window for every session that has no project, including sessions started by hand that nobody adopted: the herdr view lists everything Claude's agent view lists |
| One space per project, labelled with its slug | Ordered like `priorities.md` (then alphabetically). The first window carries the project's name and IS the project's main session: its `claude attach` loop (the session named like the project, else a blocked or working one, else the most recently started; a stopped one never), so that session has no second window. A project with no session has a plain shell in its directory; Claude is never started for you. Then one window per other session of the project, named after the session (no prefix), each running `while stella listed <id>; do claude attach <id>; sleep 2; done` (`claude attach` is itself the foreground process, and the loop attaches again after a restart). Completed sessions keep their window until Stella's tidy removes them once landed; the window of a finished session shows its log and attaches only when the session works again (attaching a viewer to a finished session makes the daemon start a host process for it); a session that is *stopped* gets none (attaching may resume it) |
| The Agents panel | only the active space's agents, awaiting-input first, each with the one line it needs under its name. Set by `stella crew follow` (`agent.view.set`, a transient view it sets again every minute) |

A window and a space you close stay closed until a session in them awaits input again or a new session joins the
space. A window you rename keeps your name. A new window of your own in a project (`Cmd+T`) is yours: sync never
touches it.

## The dots

Each window's dot shows **Claude's own state** for its session, copied from the job file Claude's agent view reads
by `stella crew follow` (one detached process, started by `tw` and `stella crew sync`, never a child of Stella:
`stella restart` leaves it running). herdr alone would show a session waiting at its `❯` prompt as idle.

| Claude's agent view | Dot |
| --- | --- |
| Awaiting input (job state `blocked`) | ● yellow |
| Working | ● blue (static) |
| Completed, not yet seen | ● green |
| Completed and seen | ○ hollow |

A space's dot is its most urgent window, and `N waiting` beside its name counts its yellow windows. The colours are
`[theme.custom]` in `local/herdr.toml` (herdr draws its `blocked` with `red` and `working` with `yellow`, so the
override swaps those two; green is herdr's own). herdr has no animation: a pulsing blue is not built.
`stella crew doctor` ends with a parity line, `Claude 8 awaiting · 0 working · 17 completed = herdr 8 yellow · 0 blue
· 17 green/hollow`, and any mismatch is BAD.

## Keys

`local/herdr.toml`. Alacritty's Cmd chords arrive as `alt+…` chords, so the tmux keys carry over (see
`docs/tmux.md`). Here they mean:

| Chord | Does |
| --- | --- |
| `Cmd+Shift+N` | A popup asks for a name and opens a new project (`stella project new --ask`: registers it with Stella and opens its space with the first window) |
| `Cmd+Shift+W` | Closes the space (herdr asks first; its sessions keep running) |
| `Cmd+Shift+↑` / `↓` | Previous / next space, in the list's order |
| `Cmd+Shift+R` | Renames the window in place; on a project's first window it renames the project (the space, the records, the title in `projects.md`; Stella is woken to update her priorities) |
| `Cmd+R` | Renames the pane |
| `Cmd+T`, `Cmd+W` | A new window of yours; close a pane (a window goes with its last pane) |
| `C-b k` / `C-b j` | Focus the pane above / below (the arrow chords went to the spaces) |

Each has a plain-words equivalent Stella runs: `stella project new|rename|close`, `stella window new|rename|close`,
`stella pane rename`, `stella assign <crewmate> <project>`. Missing in herdr: Cmd+0 (last tab), Cmd+Shift+Space
(next layout), Cmd+Shift+B (the chord off-switch). Search is copy mode (`Cmd+F`) then `/`.

## Commands

`tw` starts the server if needed, builds the `stella` space the first time, runs `stella crew sync`, starts the
reporter (`stella crew follow --ensure`) and attaches. `stella crew sync` opens what is missing, moves the live
pane of an earlier layout's `└ project · name` space into its project's space (nothing restarts: it is a `pane move`
of the running `claude attach`; if herdr refuses, a fresh window with the same loop opens and the old space
closes, the session untouched), closes the window of a session that is gone or landed, orders the spaces, and
never touches your own windows. `stella crew doctor [--json]` prints the spaces, the windows, each window's herdr
state against Claude's, the reporter, the agent view and the parity line; it is how the layout is debugged.
`stella crew empties [<since>]` lists, read-only, sessions started by hand in a project's directory that hold no work (the old auto-started `cy` sessions). `stella crew doctor --spike` runs the throwaway-session probes (`ws4-spike`) used when herdr changes. Detach with
`C-b q` or `C-b d`, or close the window: everything keeps running. `twt` is the tmux window from before, kept as
the fallback.

Text is typed into a pane only when `herdr pane process-info` shows a shell in the foreground (a new window's own
shell, or a window showing 'session exited' at a prompt): never into a Claude that is attached there, and never
into a pane whose processes cannot be read. A finished session's attached window is closed and a dormant one
opened instead of changing the command in place. `stella crew doctor` flags a window whose foreground Claude is
attached to another session than the window's.

## What is not used

- herdr's Claude integration hook (`herdr integration install claude`): the Claude daemon already resumes
  background sessions, the hook writes to herdr's socket from every session, and it does not report awaiting
  input.
- Driving herdr from inside an agent's shell: only the `stella` helper calls herdr, with a validated name.
- A pulsing working dot (herdr removed animated indicators on purpose).
