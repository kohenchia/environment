# Python Virtual Environment Management

Manage Python virtual environments using [uv](https://docs.astral.sh/uv/) with five short commands. Environments can be **local** (a `.venv` in the current directory) or **named** (stored centrally in `~/.uv/`).

## Commands at a Glance

| Command | Purpose |
|---|---|
| `vc [name] [-p version]` | **Create** a virtual environment |
| `ve [name]` | **Activate** a virtual environment |
| `vd` | **Deactivate** the current environment |
| `vls` | **List** all environments and show which is active |
| `vrm [name]` | **Remove** a virtual environment |

All commands require `uv` to be installed (`brew install uv`).

---

## Two types of environments

<!--
┌──────────────────────────────────────────────────────┐
│                  Environment Types                    │
├──────────────────────┬───────────────────────────────┤
│     Local (.venv)    │     Named (~/.uv/<name>)      │
├──────────────────────┼───────────────────────────────┤
│  Lives in project    │  Lives in ~/.uv/              │
│  directory as .venv  │  Shared across projects       │
│  Tied to one project │  Accessible from anywhere     │
│  No name argument    │  Requires a name argument     │
└──────────────────────┴───────────────────────────────┘
-->

<table>
<tr><th>Local (<code>.venv</code>)</th><th>Named (<code>~/.uv/&lt;name&gt;</code>)</th></tr>
<tr>
<td>

- Created in the **current directory** as `.venv`
- Tied to a single project
- **No name argument** needed

```
cd ~/github/myproject
vc              # creates ./myproject/.venv
ve              # activates it
```

</td>
<td>

- Stored centrally in **`~/.uv/<name>`**
- Accessible from any directory
- **Requires a name** argument

```
vc scratch      # creates ~/.uv/scratch
ve scratch      # activates from anywhere
```

</td>
</tr>
</table>

---

## `vc` — Create

```bash
# Local environment (in current directory)
vc

# Named environment
vc myenv

# With a specific Python version
vc myenv --python 3.11
vc --python 3.12           # local .venv with Python 3.12
vc myenv -p 3.11           # short flag
```

The new environment is **automatically activated** after creation.

**Safeguards:**
- Refuses to overwrite an existing environment. Delete first with `vrm`, or use a different name.
- Deactivates any currently active environment before creating a new one.

---

## `ve` — Activate

```bash
# Activate local .venv
ve

# Activate a named environment
ve myenv
```

**Behavior:**
- If another environment is active, it is deactivated first.
- Warns (without error) if you're already in the requested environment.
- Shows helpful error messages if the environment doesn't exist.

---

## `vd` — Deactivate

```bash
vd
```

Deactivates the current virtual environment. Errors if no environment is active.

---

## `vls` — List

```bash
vls
```

Displays all environments with their Python versions and active status:

```
Named environments in ~/.uv/:
  * myenv    (Python 3.11.6)      ← green * = active
    scratch  (Python 3.12.1)      ← yellow  = inactive

Local environment in current directory:
    .venv    (Python 3.11.6)
```

**Active indicator:** A green `*` marks the currently active environment. Inactive environments are shown in yellow. Python versions are displayed in gray.

If the active environment is not managed by these tools (e.g., a conda environment), it is shown separately under "Active environment (not managed by uv)".

---

## `vrm` — Remove

```bash
# Remove a named environment
vrm myenv

# Remove local .venv
vrm
```

**Behavior:**
- Deactivates the environment first if it's currently active.
- Permanently deletes the environment directory.

---

## Typical Workflow

```bash
# Start a new project
cd ~/github/new-project
vc                          # create local .venv
uv pip install -r requirements.txt

# ... work on the project ...
vd                          # deactivate when done

# Come back later
cd ~/github/new-project
ve                          # reactivate

# Create a shared scratch environment
vc playground -p 3.12
ve playground               # activate from any directory
vrm playground              # clean up when done
```

## Related aliases

| Alias | Command | Purpose |
|---|---|---|
| `ur` | `uv run` | Run a command inside the environment without activating |
| `mkdv` | `uv pip install -e ".[dev]"` | Install current package in editable mode with dev extras |
| `p` | `uv run python` | Short alias for python (runs via uv) |
| `p3` | `uv run python3` | Short alias for python3 (runs via uv) |
| `pdt` | `uvx pipdeptree` | Show dependency tree (runs without install) |
