# Vim Configuration

Custom Vim and MacVim setup with Pathogen plugin management, the Obsidian2 color scheme, and keyboard shortcuts optimized for code navigation.

**Files:**
- `vim/.vimrc` — Main Vim configuration (symlinked to `~/.vimrc`)
- `vim/.gvimrc` — MacVim-specific settings (symlinked to `~/.gvimrc`)
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

Plugins are managed by [Pathogen](https://github.com/tpope/vim-pathogen) and stored in `vim/bundle/`.

### clang_complete

C/C++ autocompletion powered by Clang. Automatically detects the Clang library from Xcode Command Line Tools at `/Library/Developer/CommandLineTools/usr/lib`.

### vim-vividchalk

[VividChalk](https://github.com/tpope/vim-vividchalk) color scheme (installed but not active — Obsidian2 is the default).

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

## MacVim Settings (`.gvimrc`)

| Setting | Value |
|---|---|
| Font | Menlo, 12pt |
| Line spacing | 1 |
| Transparency | 8% |
| Color scheme | Obsidian2 |

The status line color-change behavior carries over from `.vimrc`.
