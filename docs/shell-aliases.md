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

## Python & Development

| Alias | Command | Description |
|---|---|---|
| `p` | `python` | Python shortcut |
| `p3` | `python3` | Python 3 shortcut |
| `ur` | `uv run` | Run a command with uv (no activation needed) |
| `mkdv` | `uv pip install -e ".[dev]"` | Install package in editable mode with dev extras |
| `pdt` | `pipdeptree` | Display Python dependency tree |
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

## Application Shortcuts (macOS only)

These aliases open files or directories in GUI applications:

| Alias | Application |
|---|---|
| `a` | Atom |
| `m` | MacVim |
| `vsc` | Visual Studio Code |

```bash
a .            # Open current directory in Atom
m file.txt     # Open file in MacVim
vsc .          # Open current directory in VS Code
```

---

## System Utilities

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

## Time Tracking

| Alias | Command | Description |
|---|---|---|
| `wt` | `watson` | [Watson](https://github.com/TailorDev/Watson) time tracker CLI |

---

## Environment Variables

| Variable | Value | Purpose |
|---|---|---|
| `POWERLEVEL9K_COMMAND_EXECUTION_TIME_THRESHOLD` | `0` | Always show command execution time in prompt |
| `NVM_DIR` | `$HOME/.nvm` | Node Version Manager directory (auto-loaded if present) |
| `PUSHDSILENT` | set | Suppress directory stack messages from `pushd`/`popd` |
