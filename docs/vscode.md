# VS Code Configuration

Vim-style keybindings and editor theme settings for Visual Studio Code. These settings are designed to match the [Vim configuration](vim.md) in this repo, so muscle memory carries over between editors.

**File:** `vscode-user-settings.json`

`setup.sh` symlinks this file into your VS Code user settings directory, which differs by platform:

| Platform | Target |
|---|---|
| macOS | `~/Library/Application Support/Code/User/settings.json` |
| Linux | `~/.config/Code/User/settings.json` |
| WSL | Not linked — see below |

Any existing `settings.json` is moved to `settings.json.bak` first, so merge your own settings back in afterwards if you had them.

### WSL

On WSL, VS Code runs on the Windows host and reads its user settings from the Windows filesystem, so there is nothing useful to link inside the Linux environment. (`~/.vscode-server/data/Machine/settings.json` only accepts machine-scoped settings, which excludes editor and extension settings like these.) `setup.sh` prints the path and skips the link. Copy it manually:

```bash
cp vscode-user-settings.json "$(wslpath "$(cmd.exe /c 'echo %APPDATA%' 2>/dev/null | tr -d '\r')")/Code/User/settings.json"

# Or just open the folder and copy it by hand:
explorer.exe "$(wslpath -w ~)"
```

**Requires:** The [Vim extension for VS Code](https://marketplace.visualstudio.com/items?itemName=vscodevim.vim) (`vscodevim.vim`).

---

## Keybindings

These match the custom Vim keybindings from `.vimrc`:

| Key | Modes | Action |
|---|---|---|
| `Space` | Normal, Visual | Center current line on screen (`zz`) |
| `Ctrl-j` | Normal, Visual | Scroll down 2 lines + move cursor down 2 lines |
| `Ctrl-k` | Normal, Visual | Scroll up 2 lines + move cursor up 2 lines |

All bindings are non-recursive to avoid conflicts with other mappings.

---

## Editor Settings

| Setting | Value | Description |
|---|---|---|
| `editor.renderLineHighlight` | `"all"` | Highlights the entire current line (full width, not just gutter) |
| `editor.lineHighlightBackground` | `#333333` | Dark gray line highlight matching the Obsidian2 theme feel |

---

## Full Settings File

```json
{
    "vim.normalModeKeyBindingsNonRecursive": [
        { "before": ["<space>"], "after": ["z", "z"] },
        { "before": ["<C-j>"],  "after": ["2", "<C-e>", "2", "j"] },
        { "before": ["<C-k>"],  "after": ["2", "<C-y>", "2", "k"] }
    ],
    "vim.visualModeKeyBindingsNonRecursive": [
        { "before": ["<space>"], "after": ["z", "z"] },
        { "before": ["<C-j>"],  "after": ["2", "<C-e>", "2", "j"] },
        { "before": ["<C-k>"],  "after": ["2", "<C-y>", "2", "k"] }
    ],
    "editor.renderLineHighlight": "all",
    "workbench.colorCustomizations": {
        "editor.lineHighlightBackground": "#333333"
    }
}
```
