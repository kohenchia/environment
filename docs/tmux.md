# tmux Workspace

A tmux setup where **tabs are projects** and **panes are tools**, driven entirely by single `Cmd`
chords instead of `C-b <key>` two-steps. Designed for Alacritty on macOS, aiming for the feel of
Ghostty or iTerm while keeping tmux's persistence: close the terminal, reopen it, everything is
exactly where you left it.

```
work                                                          14:32
┌─ 1 belle ─┬─ 2 benchmark ─┬─ 3 shamrock ────────────────────────┐
│ 1 zsh                     │ 2 claude                            │
│ ~/github/belle ❯          │ > run the eval suite                │
│                           │                                     │
└───────────────────────────┴─────────────────────────────────────┘
```

**Files:**
- `local/.tmux.conf` — the bindings, symlinked to `~/.tmux.conf`
- `local/alacritty.toml` — the Cmd translation layer, symlinked to
  `~/.config/alacritty/alacritty.toml` (macOS only)

---

## On Linux and WSL

`~/.tmux.conf` is linked on every platform and works on every platform — the status bar, the layout,
the pane labels, the `C-b` prefix and the `off` table are all plain tmux. What doesn't carry over is
the **chord layer**: `Cmd` is a macOS modifier, and `local/alacritty.toml` is only linked there.

Two ways to work on Linux or WSL:

- **Use the `C-b` prefix** for everything. Every chord below has a prefix equivalent
  (`C-b 1`, `C-b c`, `C-b %`, `C-b "` …), and the root-table chords simply never fire.
- **Send the same ESC sequences from your terminal.** The bindings key off `M-<key>` in the root
  table, so anything that emits `ESC 1`, `ESC d`, `CSI 1;3D` and friends drives the identical
  workspace — Alacritty on Linux (map `Alt`/`Super` instead of `Command`), or Windows Terminal's
  `sendInput` actions on WSL. `local/alacritty.toml` is the reference for what to send.

Two version notes, both handled automatically by `if-shell` guards in `.tmux.conf`:

- **`terminal-features` needs tmux 3.2.** Ubuntu 20.04 (3.0a) and Debian 11 (3.1c) ship older tmux,
  which would abort the config on an unknown option; those fall back to `terminal-overrides`.
  `./setup.sh --check` warns when your tmux is too old.
- **`tmux-256color` terminfo lives in `ncurses-term`**, which minimal Linux and WSL images omit.
  When it's missing, `default-terminal` falls back to `screen-256color`.

---

## Why Cmd chords need a translation layer

tmux understands only four key modifiers: `C-` (Ctrl), `S-` (Shift), `M-` (Alt/Meta), and the
function keys `F1`–`F12`. **There is no Super/Cmd modifier**, so `Cmd+1` can never be bound in tmux
directly — and terminal applications don't receive the Cmd modifier from macOS in the first place.

So Alacritty does the translating. Each chord is bound to write a specific ESC-prefixed byte
sequence, and `.tmux.conf` binds that sequence in tmux's **root key table** (`bind -n`), which fires
without any prefix:

```
Cmd+1         →  ESC 1      →  tmux sees M-1     →  select-window -t 1
Cmd+D         →  ESC d      →  tmux sees M-d     →  split-window -h
Cmd+Opt+Left  →  CSI 1;3D   →  tmux sees M-Left  →  select-pane -L
```

This is collision-free because `window.option_as_alt = "None"` (Alacritty's macOS default): the
physical Option key never emits ESC-prefixed bytes, so an `M-<key>` arriving at tmux can only have
come from a binding in `alacritty.toml`. Nothing in zsh, vim, or Claude Code can compete for those
keys. **Turning `option_as_alt` on gives up that guarantee** — the chords would then be
indistinguishable from real Option presses.

`C-b` remains bound as the prefix, so every tmux command that isn't chorded here is still reachable
the normal way.

---

## Keymap

### Tabs = projects

| Chord | Action |
|---|---|
| `Cmd+1` … `Cmd+9` | Jump to tab 1–9 |
| `Cmd+0` | Last used tab (not "tab 10") |
| `Cmd+T` | New tab in the same directory, named after it |
| `Cmd+Shift+[` / `]` | Previous / next tab |
| `Cmd+Shift+←` / `→` | Previous / next tab (same thing, arrow form) |
| `Cmd+Ctrl+Shift+←` / `→` | Move the current tab left / right |
| `Cmd+Shift+R` | Rename the tab |
| `Cmd+Shift+W` | Close the tab (asks first) |

Tab names are stable by design — `allow-rename` and `automatic-rename` are both off, so a program
can never retitle your project tab. `renumber-windows` is on, so closing a tab reflows the rest and
`Cmd+1`…`Cmd+9` never develop gaps.

### Panes = tools

| Chord | Action |
|---|---|
| `Cmd+D` | Split right |
| `Cmd+Shift+D` | Split down |
| `Cmd+Shift+←↑↓→` | Move focus between panes |
| `Cmd+Opt+←↑↓→` | Move the pane itself in that direction |
| `Cmd+Ctrl+←↑↓→` | Resize the pane (hold to keep resizing) |
| `Cmd+Shift+Enter` | Zoom the pane in / out |
| `Cmd+Shift+Space` | Cycle pane layouts |
| `Cmd+R` | Rename the pane (sets the border label) |
| `Cmd+W` | Close the pane (asks first) |

Splits inherit the current directory, so `Cmd+D` in a project tab lands you in that project.

### Terminal

| Chord | Action |
|---|---|
| `Cmd+K` | Clear the pane and its scrollback |
| `Cmd+F` | Search the scrollback |
| `Cmd+C` / `Cmd+V` | Copy / paste (Alacritty native) |
| `Cmd+←` / `Cmd+→` | Jump to start / end of line |
| `Opt+←` / `Opt+→` | Move the cursor one word left / right |
| `Cmd+Backspace` | Delete to start of line |
| `Shift+Enter` | Newline without submitting (for Claude Code) |
| `Cmd+Enter` | Toggle fullscreen |
| `Cmd+Shift+B` | **Chord off-switch** — see below |
| `Cmd+N` / `Cmd+Q` / `Cmd+±` | New window / quit / font size (Alacritty defaults) |

Mouse works throughout: click a tab in the status bar to switch to it, click a pane to focus it,
drag a border to resize, scroll to enter copy mode. Copy-mode yanks reach the macOS clipboard
through OSC 52 (`set-clipboard on` in tmux, `osc52 = "OnlyCopy"` in Alacritty).

---

## The chord off-switch

Root-table chords are global — they never reach the program running in the pane. That's what makes
them feel native, but it breaks two cases: **a nested tmux** (ssh into a host that also runs tmux,
where the outer session eats every chord), and any app that genuinely wants `M-<key>`.

`Cmd+Shift+B` parks every binding in tmux's `off` table and turns the status bar red. Press it again
to restore. While off, everything passes straight through to the pane.

---

## Setting up a project tab

```
Cmd+T                       # new tab, named after the current directory
cd ~/github/belle           # or start there and Cmd+Shift+R to rename
Cmd+D                       # split right
claude                      # Claude Code in the right pane
```

Pane borders are labelled with whatever is running in them, and **`Cmd+R`** (or
`tmux select-pane -T logs`) names a pane explicitly when its command isn't descriptive enough. An
explicit name wins; otherwise the label falls back to the running command. tmux seeds `pane_title`
with the hostname rather than leaving it empty, so that's what `.tmux.conf` compares against to tell
"unnamed" from "named" — testing for an empty title would never work. It compares against `#{host}`
and *not* `#{host_short}`: the seed is the full name, so on this machine `host_short` yields
`Kohens-MacBook-Pro` against a `pane_title` of `Kohens-MacBook-Pro.local`, never matches, and every
unnamed pane ends up labelled with the machine instead of its command.

Anything that sets the terminal title (OSC 0/2) sets `pane_title` too, and tmux can't refuse it.
Claude Code puts its session name there, so a Claude pane self-labels rather than reading `node` —
and it will overwrite a name you set with `Cmd+R`.

Names survive shell activity: running commands and `cd`ing around don't clobber them.

The label sits on the border line rather than in a filled bar. The focused pane's label gets a block of
its window's mid shade behind it — near-black text on the hue, the same treatment as the current tab —
and the border line carries on either side of it. Unfocused panes get a dim grey label on a dim grey
line:

```
──▌1 · claude▐─────────────────────┬── 2 · zsh ──────────────────
 > implement the parser…           │ ~/github/belle ❯
   (▌▐ mark where the highlight starts and ends; it's a background, not glyphs)
```

The block is only as wide as the label because the format isn't padded. Padding it out to `#{pane_width}`
is what made this an edge-to-edge bar in an earlier revision — the status line already carries the
window's colour across a full row, so the pane only needs to say *which pane*, not *which window*.

One thing to know before you touch that format: **commas inside `#[…]` would break it.** The format is
one `#{?pane_active,…,…}` conditional, and a comma in a style tag (`#[fg=colour232,bold]`) reads as
that conditional's argument separator. Write each attribute as its own tag: `#[fg=colour232]#[bold]`.

Titles appear only once a window has more than one pane — a lone pane has no sibling to be
distinguished from, and the row is better spent on output. A `window-layout-changed` hook flips
`pane-border-status` between `off` and `top`.

Unfocused panes also sit on a lighter grey with muted text (`window-style`), so the focused pane reads
as the one hole you're working in rather than one panel among equals. Two things about that are easy
to get wrong:

- **The active pane must say `terminal`, not `default`.** In a tmux style `default` means *inherit*,
  and what the active pane inherits from is `window-style` — so `window-active-style "bg=default"`
  silently greys out the focused pane along with the rest. `terminal` is the terminal's own
  background, which leaves the focused pane looking untouched and keeps window opacity working. It
  needs tmux 3.2+, so it's gated on the same version check as `terminal-features` (recorded as
  `@tmux32`) with a pinned near-black as the fallback.
- **The grey has to clear the terminal's own background.** Alacritty's default is `#1d1f21`, so
  `colour235` (`#262626`) is close enough that every pane just looks uniformly grey. `colour237`
  (`#3a3a3a`) registers at a glance.

The grey paints only where a program hasn't painted its own background — anything that fills its
screen, vim with a colorscheme for instance, covers its whole pane and the grey won't show there.

---

## A hue per window

Every window owns a hue. The whole status bar wears it, and the panes inside that window carry it on
their border lines, so a glance anywhere on screen says which project you're in and the tab strip
doubles as the legend. Sixteen sets; a seventeenth window falls back to grey.

| # | Hue | Bar | Tab | | # | Hue | Bar | Tab |
|---|---|---|---|---|---|---|---|---|
| 1 | red | `167` | `217` | | 9 | lime | `149` | `193` |
| 2 | blue | `68` | `153` | | 10 | pink | `168` | `218` |
| 3 | green | `71` | `157` | | 11 | teal | `79` | `158` |
| 4 | yellow | `179` | `229` | | 12 | gold | `185` | `228` |
| 5 | magenta | `176` | `219` | | 13 | sky | `110` | `195` |
| 6 | cyan | `80` | `159` | | 14 | violet | `140` | `183` |
| 7 | orange | `173` | `223` | | 15 | salmon | `174` | `224` |
| 8 | purple | `104` | `189` | | 16 | mint | `114` | `194` |

The mid shade fills the status bar and draws the focused pane's label and border line. The current tab
is a pale, much lighter block of that same hue, capped either side with a half-block glyph in its own
colour on the bar's:

```
 belle   1 belle ▐ 2 benchmark ▌ 3 shamrock      Thu Aug 13 10:31:05 AM
```

The right side is the date and time in the macOS menu-bar layout. tmux hands `status-right` through
strftime(3), so it's plain specifiers — `%a %b %d %I:%M:%S %p`. `%d` is zero-padded to match the
`DDD MMM dd` shape; `%e` instead would render single-digit days as `Aug  3`.

**Seconds are possible, and they cost a redraw a second.** `status-interval` is how often tmux repaints
the status line, and it's the *only* thing that advances the clock — at the 5s default the seconds would
jump in fives. So it's set to `1`. Drop the `:%S` and it can go back to `5`. The `✳` marker is unaffected
either way: that redraw is event-driven, not on the interval.

Below the bar is a blank row, so the coloured strip doesn't sit flush against the pane under it. That's
`status 2` to buy the row plus `status-format[1]` to paint it — and it *has* to be painted: an empty
format leaves the row on `status-style`, which makes the bar look two rows thick instead of leaving a
gap. `#[fill=terminal]` follows Alacritty's own background rather than pinning a grey that would show
as a band if you ever set a theme, which puts it behind the same tmux 3.2+ gate as
`window-active-style`. It costs one row of window height.

There is no equivalent for panes. Pane chrome is exactly one row — the border — and everything below it
is the program's own screen; nothing in tmux's 139 options pads or insets a pane's interior. `status 2`
works only because the status line is tmux's own real estate.

Going lighter rather than more saturated is what makes it read as selected — the jump in brightness
against the mid bar is the signal, and a near-white background is where near-black bold text is most
legible. The caps extend the block half a cell each way and give it a defined edge without needing a
Nerd Font (`▐` and `▌` are plain Block Elements, which Menlo and SF Mono both have). Every other
character on the bar is near-black `colour232`, the one text colour that stays legible across all
sixteen hues; the unselected tabs are that same text at normal weight. The unfocused-pane grey is the
only thing left greyscale, since "not focused" shouldn't be a hue at all.

Two tmux details make this work without a single hook, both verified against 3.5a:

- **Style options expand formats at draw time.** Both `status-style "bg=#{E:@hue_pane}"` and
  `pane-active-border-style "fg=#{E:@hue_pane}"` render identically to a literal colour, so the bar and
  the border can follow `#{window_index}` directly. The option stores the unexpanded text, so
  `show -gv` looks wrong while the rendering is right — check these by rendering, not by reading the
  option back. The `off`-table half of `Cmd+Shift+B` has to restore that format rather than a literal,
  or the bar comes back grey and stops following the window.
- **`#{s/…/…/;s/…/…/:var}` chains substitutions left to right**, which makes the index → colour map one
  flat list instead of sixteen nested conditionals. The `^N$` anchors stop `^1$` swallowing 10-16, and
  each replacement carries its own `colour` prefix so no later rule can match a value an earlier one
  produced.

The out-of-range fallback is a trailing `s/^[0-9]+$/colour245/` — anything still a bare number after
sixteen misses was never in the table. It is *not* written as a numeric guard because **`#{>:}` compares
as strings**: `#{>:2,16}` is true, so `#{?#{>:#{window_index},16},…}` sends windows 2 through 9 to the
fallback and only 1 and 10-16 come out right. (tmux does have numeric comparison — it's the `e` family,
`#{e|>:2,16}` — but the substitution chain needs no arithmetic at all.)

Activity on an unfocused tab is `underscore`, carrying no colour of its own — repainting the tab would
make it read as a second, lit selection.

---

## Claude Code's ✳ on the tab

Claude Code prefixes its **pane** title with `✳` when it's waiting on you (verified: idle at its prompt,
`pane_title` is `✳ Claude Code`). That's no use when you're in a different window, so the tab strip
rolls it up, in the same position Claude uses — in front of the name:

```
 belle  ▐ 1 belle ▌ 2 ✳ benchmark  3 shamrock                  09:53
```

```tmux
set -g @pane_ready "#{?#{P:#{?#{m:*✳*,#{pane_title}},x,}},✳ ,}"
set -g window-status-format " #I #{E:@pane_ready}#W "
```

`#{P:…}` loops the panes of the window being formatted — not the current window — and emits a token for
each pane whose title carries the glyph; the outer conditional collapses "any of them" into one marker,
so a window with three waiting Claudes still shows a single `✳`. `#{m:*✳*,…}` is an fnmatch against the
title and matches the multibyte glyph without special handling.

It works at all only because `pane_title` is whatever the program set via OSC 0/2 and tmux cannot refuse
it — the same behaviour that makes a Claude pane self-label in its border. Updates are event-driven, not
tied to `status-interval`: the marker appears within a second of the title changing and clears the same
way.

Claude decides when to set that marker partly from focus events, so `set -g focus-events on` (already in
the config) is what lets it know you're looking elsewhere. Run Claude under a tmux without it and it
says so on startup.

---

## Rearranging panes

`Cmd+Opt+←↑↓→` swaps the current pane with its neighbour in that direction, and the focus travels
with it, so you can walk a pane across the layout by holding the chord's direction. It's built on
tmux's positional pane targets (`swap-pane -t '{left-of}'`), not the older `swap-pane -U`/`-D`, which
only step through pane *index* order and so don't match what you see on screen.

For the rarer rearrangements there's no chord — use the `C-b` prefix:

| Command | Action |
|---|---|
| `C-b Space` | Cycle to the next layout (also `Cmd+Shift+Space`) |
| `C-b C-o` | Rotate every pane through the layout |
| `C-b !` | Break the pane out into its own tab |
| `C-b :join-pane -t :N` | Pull this pane into tab N |
| `C-b :join-pane -s :N` | Pull tab N's pane in here |
| `C-b :move-pane -t :N.M` | Move this pane next to a specific pane |

`join-pane` and `break-pane` are how you move a tool *between* projects — e.g. breaking a long-running
process out of a project tab so it stops competing for space, or pulling a shell into the tab you're
working in. Add `-h`/`-v` to control which way the target splits, and `-d` to leave the focus where
it is instead of following the pane.

Dragging a pane border with the mouse resizes it; that works out of the box with `mouse on`.

---

## Notes and trade-offs

- **Word movement is wired explicitly.** `Opt+←` / `Opt+→` send `ESC b` / `ESC f`, which zsh binds to
  `backward-word` / `forward-word` and which readline-style TUIs (including Claude Code) understand.
  Alacritty's native Alt+arrow encoding, `CSI 1;3D` / `CSI 1;3C`, is *not* usable here: zsh reports
  both as `undefined-key`. Because of this, `.tmux.conf` must leave `M-b` and `M-f` unbound — that's
  why scrollback search sits on `M-/` (`Cmd+F`) rather than the more obvious `M-f`.
- **Arrow chords are layered by modifier**, which is worth internalising: bare `Cmd` edits the line,
  `Opt` moves by word, `Cmd+Shift` moves pane focus, `Cmd+Opt` moves the pane, `Cmd+Ctrl` resizes it,
  and `Cmd+Ctrl+Shift` reorders tabs.
- **Alacritty does not start tmux for you.** `terminal.shell` is deliberately unset, so a window opens
  on a plain login shell. Attach when you want the workspace:

  ```sh
  tmux new-session -A -s work
  ```

  Two things follow from that. A raw terminal is a first-class thing — open a window and you're in a
  shell, with none of the `Cmd` chords intercepted, which is what you want for a nested tmux over ssh
  or anything that needs `M-<key>` for itself. And **detaching (`C-b d`) returns you to that shell
  instead of closing the window**, which is not true when tmux *is* the shell: there, ending the tmux
  client ends the process Alacritty launched, and the window goes with it.

  If you attach the same session from a *second* Alacritty window, the two **mirror** each other —
  switch tabs in one and the other follows. That's tmux behaving correctly, not a bug, and it's
  invisible if you work in a single window (which is the point of tabs). For independent windows over
  the same set of project tabs, join a session *group* instead:

  ```sh
  tmux new-session -t work \; set-option destroy-unattached on
  ```
- **`escape-time` is 10ms**, down from tmux's 500ms default. This matters: every chord arrives as
  ESC + key, and a long escape-time makes them feel laggy and ambiguous with a real Escape press.
- **Chords are stolen from pane apps** — that's the point of the root table, but it means `M-1`,
  `M-d`, `M-k`, `M-f`, `M-w`, `M-t`, `M-z` and `M-arrows` are unavailable to programs inside tmux.
  The set avoids everything zsh, vim, and Claude Code rely on (`Shift+Tab`, `Esc`, `C-c`, `C-r`,
  `C-l` all pass through untouched).
- **`Cmd+Shift+[` / `]`** are bound as the key names `{` and `}`, because macOS reports the *shifted*
  character when Shift is held — the same way a letter binding uses `"D"` rather than `"d"`. The
  arrow forms (`Cmd+Shift+←` / `→`) emit identical bytes, so both chords share one tmux binding.
- **Nerd Font.** `alacritty.toml` sets no font family — naming a font that isn't installed is a hard
  config error. Powerlevel10k's glyphs need a Nerd Font; install one and set `font.normal.family`.

### Debugging a chord that doesn't work

Run `cat -v` in a pane and press the chord. If nothing prints, the problem is on the Alacritty side
(usually a key name — arrows are `ArrowLeft`, not `Left`). If the right bytes print but nothing
happens, the problem is the tmux binding:

```bash
tmux list-keys -T root | grep -E ' M-| C-M-'     # what tmux actually registered
tmux source-file ~/.tmux.conf                   # reload, reporting any parse error
```

Note that `cat -v` only sees a chord that tmux *doesn't* have bound — the root table swallows the
rest before they reach the pane.

Two things that cause most of the confusion:

- **Alacritty reloads its config live; tmux does not.** After editing `.tmux.conf` you must run
  `tmux source-file ~/.tmux.conf`, and a *running* tmux server keeps its old bindings until you do.
  Attaching a new session to an existing server does not re-read the file.
- **Alacritty folds letter case when matching.** `key = "R"` matches an unshifted `Cmd+R`, so letter
  chords can be written either way — but two bindings differing only in case will both fire on one
  press. Bracket and symbol keys are *not* folded: with Shift held they must be spelled as the
  shifted character (`{`, `}`).
