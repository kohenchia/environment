# Vim Configuration

Custom Vim and MacVim setup with Pathogen plugin management, the Obsidian2 color scheme, and keyboard shortcuts optimized for code navigation.

**Files:**
- `vim/.vimrc` — Main Vim configuration (symlinked to `~/.vimrc`)
- `vim/.gvimrc` — GUI settings for MacVim and GTK gvim (symlinked to `~/.gvimrc`)
- `vim/` — Plugin directory (symlinked to `~/.vim`)

---

## Keybindings

### Navigation

| Key | Mode | Action |
|---|---|---|
| `Space` | Normal | Center current line on screen (`zz`) |
| `Ctrl-j` | Normal | Scroll down 2 lines + move cursor down 2 lines |
| `Ctrl-k` | Normal | Scroll up 2 lines + move cursor up 2 lines |
| `Cmd-h` | Normal | Move to left window split |
| `Cmd-j` | Normal | Move to below window split |
| `Cmd-k` | Normal | Move to above window split |
| `Cmd-l` | Normal | Move to right window split |

`Ctrl-j`/`Ctrl-k` provide smooth scrolling — they move the viewport and cursor together, keeping context visible.

The `Cmd-hjkl` mappings work in MacVim for window navigation (in terminal Vim, use the default `Ctrl-w hjkl`).

---

## Editor Settings

| Setting | Value | Description |
|---|---|---|
| Encoding | UTF-8 | Set explicitly — the list characters below are multibyte, and a shell with no `LANG` set would otherwise leave Vim in `latin1` and reject them |
| Tab width | 4 spaces | `ts=4 sw=4 sts=4` |
| Expand tabs | Yes | Spaces instead of tabs |
| Auto-indent | Yes | Preserves indentation on new lines |
| Line numbers | Yes | Absolute line numbers |
| Cursor line | Highlighted | Visual indicator of current line |
| List characters | `▸` for tabs, `¬` for EOL | Makes whitespace visible |
| Backup files | Disabled | No `.swp` clutter |

### Status Line

The status line shows detailed file and position information:

```
[+] 3: ~/github/project/src/app.py (45%) l:120 c:15 b:97 (0x61)
 │   │  │                            │     │     │    │     │
 │   │  │                            │     │     │    │     └── hex byte value
 │   │  │                            │     │     │    └── byte value at cursor
 │   │  │                            │     │     └── column number
 │   │  │                            │     └── line number
 │   │  │                            └── percentage through file
 │   │  └── file path
 │   └── buffer number
 └── modified flag
```

The status line changes color based on mode:
- **Normal mode:** Dark red background
- **Insert mode:** Green background
- **Replace mode:** Purple background

---

## Color Scheme — Obsidian2

A dark color scheme with a deep blue-gray background:

| Element | Color |
|---|---|
| Background | Dark blue-gray (`#1A252A`) |
| Foreground | Light gray (`#E0E2E4`) |
| Keywords | Light green (`#93C763`) |
| Strings | Orange (`#EC7600`) |
| Numbers | Yellow (`#FFCD22`) |
| Comments | Gray, italic (`#66747B`) |
| Functions | Light beige (`#E8E2B7`) |

---

## Plugins (via Pathogen)

[Pathogen](https://github.com/tpope/vim-pathogen) is vendored at `vim/autoload/pathogen.vim` and loads anything dropped into `vim/bundle/`, which is empty by default. The two plugins below ship directly in `vim/plugin/` and load without pathogen's help.

### cscope.vim

Code navigation plugin for C/C++ projects. Requires [cscope](http://cscope.sourceforge.net/) to be installed.

**Key bindings** (all prefixed with `Ctrl-\`):

| Key | Action |
|---|---|
| `Ctrl-\ s` | Find all references to symbol under cursor |
| `Ctrl-\ g` | Find global definition |
| `Ctrl-\ c` | Find all calls to function under cursor |
| `Ctrl-\ t` | Find all instances of text |
| `Ctrl-\ e` | Egrep search |
| `Ctrl-\ f` | Open file under cursor |
| `Ctrl-\ i` | Find files that include this file |
| `Ctrl-\ d` | Find functions called by this function |

**Split variants:**
- `Ctrl-@ <key>` — Open result in a horizontal split
- `Ctrl-@ Ctrl-@ <key>` — Open result in a vertical split

### BufOnly.vim

Delete all buffers except the current one:

```vim
:BOnly          " Close all other buffers
:BOnly 5        " Close all buffers except buffer 5
:BOnly!         " Force close (even modified buffers)
```

---

## Machine-specific overrides

`.vimrc` sources `~/.vimrc.local` last if it exists. That file is not tracked by this repo — use it for any per-machine Vim settings.

---

## GUI Settings (`.gvimrc`)

| Setting | MacVim | GTK gvim |
|---|---|---|
| Font | Menlo, 12pt | Monospace, 12pt |
| Transparency | 8% | — (MacVim-only option) |
| Line spacing | 1 | 1 |
| Color scheme | Obsidian2 | Obsidian2 |

The font and transparency lines are gated on `has('gui_macvim')`: `transparency` does not exist outside MacVim (`E518`), and MacVim's `Font:h<size>` syntax is rejected by GTK gvim (`E596`), so loading them unconditionally would error on Linux and WSLg.

The status line color-change behavior carries over from `.vimrc`.
