# kohenchia/environment

A comprehensive development environment for macOS. Includes shell configuration, Python virtual environment management, git worktree workflows, Vim/VS Code setup, and productivity aliases — all installed via a single setup script.

<p align="center">

| Feature | Description |
|---|---|
| [**Setup & Installation**](#setup--installation) | First-time setup and the `setup.sh` installer |
| [**Python Environments**](docs/python-environments.md) | Create, activate, list, and remove `uv`-based virtual environments |
| [**Git Worktrees**](docs/git-worktrees.md) | Work on multiple branches simultaneously with `wt*` commands |
| [**Git Aliases**](docs/git-aliases.md) | Shorthand commands for everyday git operations |
| [**Shell Aliases & Functions**](docs/shell-aliases.md) | Navigation, Docker, Kubernetes, system utilities, and more |
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

### What `setup.sh` does

The setup script installs prerequisites and creates symlinks from this repo into your home directory. Existing files are backed up with a `.bak` extension before linking.

**Prerequisites installed automatically:**
- Sets zsh as the default shell
- [oh-my-zsh](https://ohmyz.sh)
- [Powerlevel10k](https://github.com/romkatv/powerlevel10k) prompt theme
- [uv](https://docs.astral.sh/uv/) Python package manager (via Homebrew or standalone installer)

**Symlinks created:**

```
environment/local/.zshrc     →  ~/.zshrc
environment/local/.zprofile  →  ~/.zprofile
environment/local/.p10k.zsh  →  ~/.p10k.zsh
environment/vim/.vimrc       →  ~/.vimrc
environment/vim/.gvimrc      →  ~/.gvimrc
environment/vim/             →  ~/.vim
```

After running `setup.sh`, open a new terminal to load the configuration. Run `p10k configure` to customize your Powerlevel10k prompt.

### Work-specific configuration

If `~/.zshrc_work` exists, it is automatically sourced at the end of `.zshrc`. Use this file for employer-specific aliases, paths, or environment variables that shouldn't be committed to this repo.

---

## Documentation

See the **[docs/](docs/)** folder for detailed guides on each feature:

- **[Python Environments](docs/python-environments.md)** — `ve`, `vc`, `vd`, `vls`, `vrm`
- **[Git Worktrees](docs/git-worktrees.md)** — `wta`, `wtl`, `wtc`, `wtr`, `wts`, `wtu`
- **[Git Aliases](docs/git-aliases.md)** — `ga`, `gb`, `gc`, `gd`, `gs`, `gm`, `gpush`, `gup`, `ghist`, `gt`, `glc`
- **[Shell Aliases & Functions](docs/shell-aliases.md)** — Navigation, Docker, Kubernetes, development tools, system utilities
- **[Vim Configuration](docs/vim.md)** — Plugins, keybindings, status line, color scheme
- **[VS Code Configuration](docs/vscode.md)** — Vim-style keybindings and editor theme settings
