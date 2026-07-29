# Shell Aliases & Functions

Productivity shortcuts for navigation, development tools, Docker, Kubernetes, and system utilities.

---

## Directory Navigation

Jump to frequently used directories with a single command:

| Alias | Destination | Description |
|---|---|---|
| `cg` | `~/github` | GitHub repositories |
| `bb` | `~/bitbucket` | Bitbucket repositories |
| `dev` | `~/development` | Development directory |
| `home` | `~` | Home directory |
| `tmp` | `/tmp` | Temporary files |

---

## File Listing

| Alias | Command | Description |
|---|---|---|
| `l` | `ls -lFh` | Long listing with file type indicators and human-readable sizes |
| `ll` | `ls -alFh` | Same as `l` but includes hidden files |

---

## File Search Functions

### `ff` — Find Files

```bash
ff "*.py"
# Recursively finds all files matching the pattern from current directory
```

### `fd` — Find Directories

```bash
fd "node_modules"
# Recursively finds all directories matching the pattern from current directory
```

### `drawline` — Draw a Separator

```bash
drawline
# Prints a line of dashes spanning the full terminal width
# Useful for visually separating output
```

---

## Content Search — ripgrep

[ripgrep](https://github.com/BurntSushi/ripgrep) (`rg`) is installed by `setup.sh`. It searches file *contents* recursively and respects `.gitignore` by default, which makes it much faster than `grep -r` in a repo.

```bash
rg "def main"              # Search all tracked files from the current directory
rg -i todo                 # Case-insensitive
rg -t py "import belle"    # Only Python files
rg -l "TODO"               # Just list matching file names
rg -C 3 "raise ValueError" # 3 lines of context around each match
```

These aliases are defined only when `rg` is on `PATH`:

| Alias | Command | Description |
|---|---|---|
| `rgh` | `rg --hidden` | Include hidden files, still honouring `.gitignore` |
| `rga` | `rg --hidden --no-ignore` | Search everything, including ignored files |
| `rgf` | `rg --files` | List the files `rg` would search (no pattern) |

When `rg` is present it also becomes fzf's file-listing command via `FZF_DEFAULT_COMMAND`, so `Ctrl-T` and bare `fzf` skip anything in `.gitignore`. The `wt*` worktree pickers feed fzf on stdin and are unaffected.

Use `rg` for searching inside files and `ff`/`fd` for finding files and directories by *name*.

---

## Python & Development

| Alias | Command | Description |
|---|---|---|
| `p` | `uv run python` | Python shortcut (runs via uv) |
| `p3` | `uv run python3` | Python 3 shortcut (runs via uv) |
| `ur` | `uv run` | Run a command with uv (no activation needed) |
| `mkdv` | `uv pip install -e ".[dev]"` | Install package in editable mode with dev extras |
| `pdt` | `uvx pipdeptree` | Display Python dependency tree (runs without install) |
| `rn` | `npx react-native` | React Native CLI via npx |

### `pvd` — Python Visual Debugger

```bash
pvd
# Starts an interactive Python session with debugpy listening on port 17778
# Waits for a client (e.g., VS Code) to attach before proceeding
```

Use this to attach VS Code's debugger to a running Python session. Configure VS Code with a "Remote Attach" debug configuration targeting `localhost:17778`.

See also: [Python Environment commands](python-environments.md) (`ve`, `vc`, `vd`, `vls`, `vrm`)

---

## Docker

| Alias | Command | Description |
|---|---|---|
| `d` | `docker` | Docker shortcut |
| `dcp` | `docker-compose` | Docker Compose shortcut |

### `ssd` — Shell into Docker Container

```bash
ssd my-container
# Opens an interactive shell in the container
# Passes your current terminal dimensions so output formats correctly
```

Equivalent to `docker exec -it <container> sh -l` with `COLUMNS` and `LINES` set to your terminal size.

---

## Kubernetes

| Alias | Command | Description |
|---|---|---|
| `k` | `kubectl` | kubectl shortcut |

---

## Conda

| Alias | Command | Description |
|---|---|---|
| `ca` | `conda activate` | Activate a conda environment |
| `cda` | `conda deactivate` | Deactivate current conda environment |

### `c` — Initialize Conda

```bash
c
# Loads the conda shell hook into the current session
# Run this once per session before using conda commands
```

This lazily initializes conda so it doesn't slow down shell startup.

---

## Application Shortcuts (platform-specific)

These aliases open files or directories in GUI applications. Which ones exist depends on `$ENV_OS` (see [platform detection](../README.md#supported-platforms)):

| Alias | macOS | Linux | WSL |
|---|---|---|---|
| `m` | MacVim | — | — |
| `vsc` | `open -a "Visual Studio Code"` | `code` | `code` (via the WSL shim) |
| `open` | built in | `xdg-open` (if installed) | `wslview`, else `explorer.exe` |

```bash
m file.txt     # Open file in MacVim (macOS)
vsc .          # Open current directory in VS Code
open .         # Open current directory in the file manager
```

---

## System Utilities (macOS only)

These are defined only when `$ENV_OS` is `macos`:

| Alias | Purpose |
|---|---|
| `cf` | `caffeinate` — Prevent macOS from sleeping |
| `cputemp` | Show CPU die temperature (requires sudo) |
| `resetaudio` | Kill and restart macOS Core Audio (fixes audio glitches) |

### `cputemp`

```bash
cputemp
# CPU die temperature: 45.3 C
# (Requires sudo — uses PowerMetrics)
```

### `resetaudio`

```bash
resetaudio
# Kills the coreaudiod process; macOS restarts it automatically
# Use when audio output is glitchy or not working
```

---

## Environment Variables

| Variable | Value | Purpose |
|---|---|---|
| `ENV_OS` | `macos`, `linux`, `wsl`, or `unknown` | Detected platform; set before `~/.zshrc_work` is sourced |
| `POWERLEVEL9K_COMMAND_EXECUTION_TIME_THRESHOLD` | `0` | Always show command execution time in prompt |
| `FZF_DEFAULT_COMMAND` | `rg --files --hidden --glob "!.git/*"` | fzf file listing via ripgrep (only when `rg` is installed) |
| `NVM_DIR` | `$HOME/.nvm` | Node Version Manager directory (auto-loaded if present) |
| `PUSHDSILENT` | set | Suppress directory stack messages from `pushd`/`popd` |
