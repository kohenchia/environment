# herdr: the work window

[herdr](https://github.com/herdrdev/herdr) is a terminal multiplexer built for coding agents: a background
server keeps everything running when the terminal closes, and a sidebar shows each agent's state. Install it with
the package manager (v0.8.0 or newer).

herdr's words and mine differ. This setup uses mine:

| I say | herdr says |
| --- | --- |
| **space** | workspace |
| **window** | tab |
| **pane** | pane |

The left column (the Spaces and Agents lists, their dots and rows) is herdr's own, unconfigured. You make a space
yourself (`Cmd+N`, a blank terminal), name it (`Cmd+Ctrl+R`) and delete it (`Cmd+Ctrl+W`). A window holds one
Claude session (`claude attach <id>`, or `cw` to pick one) or whatever else you open there.

## `tw`

Starts the herdr server if needed and Stella's session if she is not running, then attaches.

## Keys

`kc-keys` prints every binding, read from the config files (`local/herdr.toml`). Alacritty turns each Cmd chord into an ESC string (`local/alacritty.toml`) that herdr reads as
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
| **Rename the space** | `Cmd+Ctrl+R` (or `C-b` then `Shift+W`) |

The rule for the new ones: the Ctrl layer is for spaces, and Shift means "move", as it does for windows. herdr has
no action for moving a space, so `Cmd+Ctrl+Shift+↑↓` run `herdr-space move up|down` over its socket.
Missing in herdr: `Cmd+0` (last window), `Cmd+Shift+Space` (next layout), `Cmd+Shift+B` (the nested-tmux
off-switch). Detach with `C-b q` or `C-b d`: everything keeps running.
