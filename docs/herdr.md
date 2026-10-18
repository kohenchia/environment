# herdr: the work window

[herdr](https://github.com/herdrdev/herdr) is a terminal multiplexer built for coding agents: a background
server keeps everything running when the terminal closes, and a sidebar shows each agent's state. Install it with
the package manager (v0.8.0 or newer).

herdr's words and mine differ. This setup uses mine:

| I say | herdr says |
| --- | --- |
| **space** (a project) | workspace |
| **window** | tab |
| **pane** | pane |

```
Spaces (left)                window bar of the active space
  ● stella                   [ 2398-rebase ] [ pr-2398-kohen ] [ 2398-dev-priority-all ]
  ● 2398
  ○ docs-drift               Agents (sidebar): each session with its state dot
```

Each project is a space. You open a new one yourself (`Cmd+N`, a blank terminal) and delete it (`Cmd+Ctrl+W`)
when the project is done. A space's title is its own: it does not follow a session or window name. Rename a space whenever you like: `herdr-space sync` ties it to its project by herdr's workspace id
(recorded in `~/.local/state/herdr-space/spaces.json`, slug → id and the name it has now), never by its name, so
the project keeps its slug in Stella's `projects.md` and a rename costs nothing. A window
holds one Claude session (`claude attach <id>`), or whatever else you open there.

## `tw`

Starts the herdr server if needed and Stella's session if she is not running, runs `herdr-space sync`, and
attaches. `herdr-space sync` opens a space for every Claude session that needs you, is working, or finished in the
last 48 hours (`--hours N`), and one window per session. A session belongs to the project named by the first
number of three or more digits in its session name (every session about PR 2398 shares a space), else by its
repository (`~/github/<repo>-wt/<branch>` counts as `<repo>`). Spaces and windows that already exist are never
renamed or closed, so run it as often as you like; `--dry-run` prints what it would open. A window of a finished
session shows its log and attaches only when you press Enter (attaching starts a host process).

## Keys

`kc-keys` prints every binding, read from the config files. `local/herdr.toml`. Alacritty turns each Cmd chord into an ESC string (`local/alacritty.toml`) that herdr reads as
an `alt+…` chord, so the chords from the tmux days carry over unchanged.

| What | Chord |
| --- | --- |
| Focus a pane | `Cmd+Shift+←↑↓→` |
| Move a pane | `Cmd+Opt+←↑↓→` |
| Split right / down | `Cmd+D` / `Cmd+Shift+D` |
| Zoom, rename, clear, search a pane | `Cmd+Shift+Enter`, `Cmd+R`, `Cmd+K`, `Cmd+F` |
| Resize a pane | `C-b` then an arrow |
| New window / close a pane (a window goes with its last pane) / close the window | `Cmd+T` / `Cmd+W` / `Cmd+Shift+W` |
| Window 1–9 / previous / next | `Cmd+1…9` / `Cmd+Shift+{` / `Cmd+Shift+}` |
| Move a window left / right | `Cmd+Ctrl+Shift+←` / `→` |
| Rename the window | `Cmd+Shift+R` |
| **New space** | `Cmd+N` |
| **Go to the space above / below** | `Cmd+Ctrl+↑` / `↓` |
| **Move the space up / down** | `Cmd+Ctrl+Shift+↑` / `↓` |
| **Delete the space** (herdr asks first; its sessions keep running) | `Cmd+Ctrl+W` |
| **Rename the space** (a project's name; sync keeps it the same project) | `Cmd+Ctrl+R` (or `C-b` then `Shift+W`) |

The rule for the new ones: the Ctrl layer is for spaces, and Shift means "move", as it does for windows. herdr has
no action for moving a space, so `Cmd+Ctrl+Shift+↑↓` run `herdr-space move up|down` over its socket.
Missing in herdr: `Cmd+0` (last window), `Cmd+Shift+Space` (next layout), `Cmd+Shift+B` (the nested-tmux
off-switch). Detach with `C-b q` or `C-b d`: everything keeps running.

## Dots

The dot before a window and before a space is Claude's own state for the session, not herdr's guess from the
screen. herdr can only draw four fixed states, so the dots are drawn from tokens instead: `herdr-space follow` (one
detached process, started by `tw`) reads Claude's job files every 5 seconds and sets one `dot_*` token on the
window and on its space, and the sidebar rows in `local/herdr.toml` give each token its colour.

| Dot | Means | Claude's state |
| --- | --- | --- |
| red | A prompt waits for you (a question or approval on screen) | blocked, the transcript ends in an unanswered tool call |
| yellow | Finished, with next steps for you | blocked, the transcript ends in text |
| blue | Running | working |
| green, filled | Finished, nothing for you, not yet looked at | done; herdr has not shown it as seen |
| green, hollow | Finished and looked at | done; herdr has shown it as seen |

A space shows its most urgent window's dot (red, then yellow, blue, filled green, hollow green). The state is also
reported to herdr, which keeps the seen tracking that tells filled from hollow. `herdr-space probe` opens a space
with one window per dot to check the colours, and `herdr-space probe --clear` closes it.
