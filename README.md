# kohenchia/environment

A comprehensive development environment for macOS, Linux, and WSL. Includes shell configuration, Python virtual environment management, git worktree workflows, Vim/VS Code setup, and productivity aliases — all installed via a single setup script.

<p align="center">

| Feature | Description |
|---|---|
| [**Setup & Installation**](#setup--installation) | First-time setup and the `setup.sh` installer |
| [**Python Environments**](docs/python-environments.md) | Create, activate, list, and remove `uv`-based virtual environments |
| [**Git Worktrees**](docs/git-worktrees.md) | Work on multiple branches simultaneously with `wt*` commands |
| [**Git Aliases**](docs/git-aliases.md) | Shorthand commands for everyday git operations |
| [**Shell Aliases & Functions**](docs/shell-aliases.md) | Navigation, search, Docker, Kubernetes, system utilities, and more |
| [**Vim Configuration**](docs/vim.md) | Plugins, keybindings, and color scheme |
| [**VS Code Configuration**](docs/vscode.md) | Vim keybindings and editor settings for VS Code |

</p>

---

## Setup & Installation

```
git clone git@github.com:kohenchia/environment.git
cd environment
./setup.sh
```

### Supported platforms

| Platform | Notes |
|---|---|
| **macOS** | Intel and Apple Silicon. Uses Homebrew when available. |
| **Linux** | Package manager auto-detected: `apt-get`, `dnf`, `yum`, `pacman`, or `zypper`. |
| **WSL** | Treated as Linux, with two differences — see [WSL notes](#wsl-notes). |

`setup.sh` runs under **bash**, not zsh, so it can bootstrap a machine where zsh isn't installed yet. It detects the platform from `uname -s` (plus `/proc/version` to tell WSL from bare Linux) and exposes the result to your shell as `$ENV_OS` (`macos`, `linux`, or `wsl`).

### What `setup.sh` does

The setup script installs prerequisites and creates symlinks from this repo into your home directory. Anything already at a target path is backed up with a `.bak` extension before linking; re-running the script leaves existing correct symlinks untouched.

**Prerequisites installed automatically:**
- zsh, and sets it as your default shell (adding it to `/etc/shells` first on Linux/WSL)
- git
- [oh-my-zsh](https://ohmyz.sh)
- [Powerlevel10k](https://github.com/romkatv/powerlevel10k) prompt theme
- [uv](https://docs.astral.sh/uv/) Python package manager
- [fzf](https://github.com/junegunn/fzf) fuzzy finder (powers interactive `wt*` worktree pickers)
- [ripgrep](https://github.com/BurntSushi/ripgrep) (`rg`) fast recursive search

Each tool is installed via the platform's package manager, falling back to an upstream installer (uv, fzf) or, for ripgrep, `cargo install` when Rust is present and otherwise a prebuilt GitHub release binary in `~/.local/bin`. A tool that can't be installed is reported and skipped — it never aborts the rest of the setup.

**Symlinks created:**

```
environment/local/.zshrc     →  ~/.zshrc
environment/local/.zprofile  →  ~/.zprofile
environment/local/.p10k.zsh  →  ~/.p10k.zsh
environment/local/.tmux.conf →  ~/.tmux.conf
environment/vim/.vimrc       →  ~/.vimrc
environment/vim/.gvimrc      →  ~/.gvimrc
environment/vim/             →  ~/.vim
```

VS Code settings are also linked, to a platform-specific path — see [VS Code Configuration](docs/vscode.md).

After running `setup.sh`, open a new terminal to load the configuration. Run `p10k configure` to customize your Powerlevel10k prompt.

### WSL notes

- **VS Code settings are not linked.** VS Code runs on the Windows host, so its user settings live at `%APPDATA%\Code\User\settings.json`. `setup.sh` prints the copy command instead of linking.
- **Nerd Font required.** The prompt uses `POWERLEVEL9K_MODE=nerdfont-v3`. Install a [Nerd Font](https://www.nerdfonts.com) on Windows and select it in Windows Terminal's profile settings, or the prompt will show tofu boxes.
- `vsc` opens VS Code through the WSL shim; `open` maps to `wslview` (from `wslu`) if installed, otherwise `explorer.exe`.

### Work-specific configuration

If `~/.zshrc_work` exists, it is automatically sourced at the end of `.zshrc`. Use this file for employer-specific aliases, paths, or environment variables that shouldn't be committed to this repo. `$ENV_OS` is set before it is sourced, so it can branch on platform too.

---

## Documentation

See the **[docs/](docs/)** folder for detailed guides on each feature:

- **[Python Environments](docs/python-environments.md)** — `ve`, `vc`, `vd`, `vls`, `vrm`
- **[Git Worktrees](docs/git-worktrees.md)** — `wta`, `wtl`, `wtc`, `wtr`, `wts`, `wtu`
- **[Git Aliases](docs/git-aliases.md)** — `ga`, `gb`, `gc`, `gd`, `gs`, `gm`, `gpush`, `gup`, `ghist`, `gt`, `glc`
- **[Shell Aliases & Functions](docs/shell-aliases.md)** — Navigation, search (`rg`), Docker, Kubernetes, development tools, system utilities
- **[Vim Configuration](docs/vim.md)** — Plugins, keybindings, status line, color scheme
- **[VS Code Configuration](docs/vscode.md)** — Vim-style keybindings and editor theme settings
