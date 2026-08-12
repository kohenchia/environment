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
| [**Command Tutorials**](docs/command-tutorials.md) | `h <command>` — color-coded, copy-pasteable cheat sheets in your terminal |
| [**tmux Workspace**](docs/tmux.md) | Projects as tabs, tools as panes, single-chord `Cmd` navigation |
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

To audit an existing machine without changing anything, run `./setup.sh --check`. It reports which tools are installed, whether every dotfile points at this repo, and whether an interactive zsh starts without errors, exiting non-zero if anything is missing.

### Supported platforms

| Platform | Notes |
|---|---|
| **macOS** | Intel and Apple Silicon. Uses Homebrew when available. |
| **Linux** | Package manager auto-detected: `apt-get`, `dnf`, `yum`, `pacman`, or `zypper`. |
| **WSL** | Treated as Linux, with a few differences — see [WSL notes](#wsl-notes). |

`setup.sh` runs under **bash**, not zsh, so it can bootstrap a machine where zsh isn't installed yet. It detects the platform from `uname -s` (plus `/proc/version` to tell WSL from bare Linux) and exposes the result to your shell as `$ENV_OS` (`macos`, `linux`, or `wsl`).

**A Nerd Font is required on every platform.** The prompt uses `POWERLEVEL9K_MODE=nerdfont-v3`, so install a [Nerd Font](https://www.nerdfonts.com) and select it in your terminal, or the prompt will show tofu boxes.

### What `setup.sh` does

The setup script installs prerequisites and creates symlinks from this repo into your home directory. Anything already at a target path is backed up with a `.bak` extension before linking; re-running the script leaves existing correct symlinks untouched.

**Prerequisites installed automatically:**
- curl (needed by the installers below; minimal Linux and WSL images ship without it)
- zsh, and sets it as your default shell (adding it to `/etc/shells` first on Linux/WSL)
- git
- [oh-my-zsh](https://ohmyz.sh)
- [Powerlevel10k](https://github.com/romkatv/powerlevel10k) prompt theme
- [uv](https://docs.astral.sh/uv/) Python package manager
- [fzf](https://github.com/junegunn/fzf) fuzzy finder (powers the interactive `wt*` worktree pickers and the `Ctrl-T`/`Ctrl-R`/`Alt-C` key bindings)
- [ripgrep](https://github.com/BurntSushi/ripgrep) (`rg`) fast recursive search
- vim and tmux, both of which this repo configures

Each tool is installed via the platform's package manager, falling back to an upstream installer (uv, fzf) or, for ripgrep, `cargo install` when Rust is present and otherwise a prebuilt GitHub release binary in `~/.local/bin`. A tool that can't be installed is reported and skipped — it never aborts the rest of the setup.

`.tmux.conf` wants **tmux 3.2 or newer**. On older versions it still loads, falling back to `terminal-overrides` for RGB colour; `--check` warns when your tmux is too old.

**Symlinks created:**

```
environment/local/.zshrc     →  ~/.zshrc
environment/local/.zprofile  →  ~/.zprofile
environment/local/.p10k.zsh  →  ~/.p10k.zsh
environment/local/.tmux.conf →  ~/.tmux.conf
environment/vim/.vimrc       →  ~/.vimrc
environment/vim/.gvimrc      →  ~/.gvimrc
environment/vim/             →  ~/.vim
environment/bin/h            →  ~/.local/bin/h
```

`local/.shell-common.zsh` is not linked: it holds the Homebrew prefix and `~/.local/bin` setup, and both `.zshrc` and `.zprofile` source it from the repo. Both do so because zsh reads `.zprofile` for login shells only — macOS terminals start login shells, but most Linux ones don't, which would otherwise leave Linuxbrew off `PATH` there.

On macOS only, `local/alacritty.toml` is linked to `~/.config/alacritty/alacritty.toml` — see [tmux Workspace](docs/tmux.md). `iterm/com.googlecode.iterm2.plist` is an optional macOS extra that is never linked; load it from iTerm2 via *Settings → General → Preferences → Load preferences from a custom folder*.

VS Code settings are also linked, to a platform-specific path — see [VS Code Configuration](docs/vscode.md).

After running `setup.sh`, open a new terminal to load the configuration. Run `p10k configure` to customize your Powerlevel10k prompt.

### WSL notes

- **VS Code settings are not linked.** VS Code runs on the Windows host, so its user settings live at `%APPDATA%\Code\User\settings.json`. `setup.sh` prints the copy command instead of linking.
- **Install the Nerd Font on Windows**, not inside the distro, and select it in your Windows Terminal profile.
- **`chsh` usually fails** because the default WSL user has no Unix password. Run `sudo passwd $USER` and re-run `setup.sh`, or set the shell as root: `sudo chsh -s "$(command -v zsh)" "$USER"`.
- **The `Cmd`-chord tmux layer is macOS-only.** `~/.tmux.conf` itself works everywhere, but the chords depend on Alacritty translating `Cmd` — a modifier Windows and Linux don't have. Use the `C-b` prefix, or bind the same ESC sequences in your terminal (see [tmux Workspace](docs/tmux.md)).
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
- **[Command Tutorials](docs/command-tutorials.md)** — `h` prints color-coded command cheat sheets in your terminal
- **[tmux Workspace](docs/tmux.md)** — Projects as tabs, tools as panes, `Cmd`-chord navigation in Alacritty
- **[Vim Configuration](docs/vim.md)** — Plugins, keybindings, status line, color scheme
- **[VS Code Configuration](docs/vscode.md)** — Vim-style keybindings and editor theme settings
