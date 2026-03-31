# Git Worktree Workflow

Work on multiple branches simultaneously without stashing or switching. Each branch gets its own directory with a full working copy, powered by [git worktrees](https://git-scm.com/docs/git-worktree).

## Commands at a Glance

| Command | Purpose |
|---|---|
| `wta <repo> <branch> [base]` | **Add** a worktree and cd into it |
| `wtl [repo]` | **List** all active worktrees |
| `wtc <repo> <branch>` | **Change** into an existing worktree |
| `wtr <repo> <branch>` | **Remove** a finished worktree |
| `wts <repo> <branch>` | **Symlink** a worktree into the current directory |
| `wtu <repo> <branch>` | **Unlink** a worktree symlink |

All six commands support **tab completion** for both `<repo>` and `<branch>` arguments.

---

## Directory Layout

Worktrees are created alongside the main checkout in a `-wt/` sibling directory:

```
~/github/
├── myproject/                    # main checkout (untouched)
├── myproject-wt/
│   ├── feature-a/                # worktree for feature-a branch
│   └── bugfix-123/               # worktree for bugfix-123 branch
├── otherproject/
└── otherproject-wt/
    └── refactor-api/
```

Your main checkout stays on its current branch. `git pull`, CI scripts, and other tooling that expects a clean main branch are unaffected.

---

## `wta` — Add a Worktree

```bash
# Create a new branch from HEAD
wta myproject add-login-page
# ✓ Worktree ready at ~/github/myproject-wt/add-login-page

# Branch off a specific base
wta myproject hotfix-99 origin/release-2.0

# Check out an existing remote branch
wta myproject someone-elses-branch
# If the branch already exists locally, the worktree uses it as-is
```

**What happens:**
1. Fetches latest from origin (quietly)
2. If the branch exists locally, checks it out in the worktree
3. If the branch is new, creates it from `[base]` (default: HEAD)
4. Automatically `cd`s into the new worktree

---

## `wtl` — List Worktrees

```bash
# List all active worktrees across all repos
wtl

# Filter to one repo
wtl myproject
```

**Example output:**

```
Active worktrees:

  myproject
    /Users/you/github/myproject              abc1234 [main]
    /Users/you/github/myproject-wt/add-login  def5678 [add-login-page]

  otherproject
    /Users/you/github/otherproject           111aaaa [main]
    /Users/you/github/otherproject-wt/fix    222bbbb [fix-api]
```

---

## `wtc` — Change to a Worktree

```bash
wtc myproject add-login-page
# Now in ~/github/myproject-wt/add-login-page (add-login-page)

wtc otherproject fix-api
# Now in ~/github/otherproject-wt/fix-api (fix-api)
```

---

## `wtr` — Remove a Worktree

```bash
wtr myproject add-login-page
# ✓ Removed worktree ~/github/myproject-wt/add-login-page
# Delete branch 'add-login-page' too? [y/N] y
# ✓ Branch 'add-login-page' deleted
```

**What happens:**
1. If you're inside the worktree, moves you to the main repo directory
2. Removes the worktree via `git worktree remove`
3. Cleans up the empty `-wt/` directory if no other worktrees remain
4. Offers to delete the branch as well

---

## `wts` — Symlink a Worktree

Create a local symlink pointing to a worktree. Useful for workspaces that aggregate repos via symlinks.

```bash
cd ~/github/ace
wts benchmark feature/launch-ifp
# ✓ benchmark@feature-launch-ifp -> ~/github/benchmark-wt/feature/launch-ifp

ls -l benchmark*
# benchmark -> ../benchmark
# benchmark@feature-launch-ifp -> ~/github/benchmark-wt/feature/launch-ifp
```

The symlink name is `<repo>@<branch>` with slashes replaced by hyphens.

---

## `wtu` — Unlink a Worktree Symlink

```bash
wtu benchmark feature/launch-ifp
# ✓ Removed benchmark@feature-launch-ifp
```

---

## Tab Completion

All commands offer intelligent tab completion:

| Argument position | Completes with |
|---|---|
| `<repo>` | Git repos under `~/github/` (or `WT_REPOS` if set) |
| `<branch>` for `wta` | All local and remote branches |
| `<branch>` for `wtc`, `wtr`, `wts`, `wtu` | Only existing worktree branches |

---

## Controlling the Repo List

By default, tab completion and `wtl` auto-discover all git repos under `~/github/`. To restrict to a specific set:

```bash
# In .zshrc or a sourced file (e.g. .zshrc_work):
WT_REPOS=(myproject otherproject webapp)
```

---

## Tips

- **Each worktree is independent.** You can have different virtual environments, run tests, and build in each one without interference.
- **Worktrees share the same `.git` data.** Commits, branches, stashes, and reflog are shared with the main checkout. There is no extra clone overhead.
- **Don't manually delete worktree directories.** Always use `wtr` (or `git worktree remove`) so git's internal bookkeeping stays clean. If you accidentally `rm -rf` a worktree directory, run `git worktree prune` in the main checkout to clean up.
- **You can't have the same branch checked out in two places.** Git enforces this. If you need the same code in two terminals, just `cd` into the same worktree from both.
