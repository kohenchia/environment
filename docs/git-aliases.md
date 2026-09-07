# Git Aliases

Shorthand commands for everyday git operations. These override some default oh-my-zsh git aliases with opinionated defaults.

## Quick Reference

| Alias | Expands to | Purpose |
|---|---|---|
| `ga` | `git add -A` | Stage all changes (new, modified, deleted) |
| `gb` | `git branch` | List local branches |
| `gc` | `git commit -v -m` | Commit with inline message (verbose diff shown) |
| `gd` | `git diff -w` | Diff ignoring whitespace changes |
| `gs` | `git status -s` | Short-format status |
| `gm` | `git merge --no-commit --no-ff` | Merge without auto-committing (allows review) |
| `gpush` | `git push -f --tags -u origin` | Force push with tags, setting upstream |
| `gup` | `git fetch --prune origin && git fetch --prune origin "+refs/tags/*:refs/tags/*" && git rebase -r` | Fetch, prune stale branches/tags, rebase |
| `ghist` | `git log --pretty=format:... --graph --date=short` | Pretty commit history with graph |

---

## Switching Branches — prefer `gsw`

**Use `gsw`, not `gco`.** `git switch` does one job — move between branches — where `git checkout` overloads
branch switching with restoring files, and will silently detach `HEAD` if you hand it a commit instead of a
branch. These come from the oh-my-zsh git plugin, not from this repo:

| Alias | Expands to | Purpose |
|---|---|---|
| `gsw` | `git switch` | Switch to an existing branch |
| `gswc` | `git switch --create` | Create a branch and switch to it |
| `gswm` | `git switch <main branch>` | Back to `main`/`master`, whichever the repo uses |
| `gswd` | `git switch <develop branch>` | Back to `develop`, if the repo has one |

```bash
gsw main               # switch to an existing branch
gswc feature/login     # create feature/login and switch to it
gswm                   # back to the repo's main branch, whatever it's named
gsw -                  # back to the previous branch
```

`gswm` and `gswd` resolve the branch name at runtime via the plugin's `git_main_branch` /
`git_develop_branch` helpers, so `gswm` works in a repo using `master` and one using `main`
without you having to remember which.

### What `gsw` deliberately won't do

`git switch` refuses the two jobs that made `git checkout` ambiguous, so reach for the purpose-built
command instead:

| Instead of | Use | Why |
|---|---|---|
| `gco -- file.txt` | `git restore file.txt` | Discarding working-tree changes is `restore`, not a branch operation |
| `gco <sha>` | `gsw --detach <sha>` | Detaching `HEAD` now has to be asked for explicitly |
| `gco -b x origin/x` | `gswc x --track origin/x` | Or just `gsw x` — git auto-creates a tracking branch from a unique remote name |

`gco` is left pointing at `git checkout` for exactly these cases. It isn't removed, just no longer the
habit.

**These four aliases come from the oh-my-zsh git plugin**, not from `local/.zshrc`, so unlike the table
above they aren't pinned by this repo — a plugin change could rename them, and they're absent entirely if
oh-my-zsh failed to install. `git switch` itself needs git 2.23 or newer.

For working on several branches at once without switching at all, see
[Git Worktrees](git-worktrees.md).

---

## Detailed Usage

### `ga` — Stage Everything

```bash
ga
# Equivalent to: git add -A
# Stages all changes: new files, modifications, and deletions
```

### `gc` — Commit with Message

```bash
gc "Add login page"
# Equivalent to: git commit -v -m "Add login page"
# The -v flag shows the diff in the commit editor for review
```

**Note:** A commit message is required. Running `gc` without a message will error.

### `gd` — Diff (Whitespace-Insensitive)

```bash
gd
# Shows unstaged changes, ignoring whitespace differences
```

### `gs` — Short Status

```bash
gs
# M  src/app.js        ← modified
# ?? new-file.txt      ← untracked
# A  added.txt         ← staged
```

### `gm` — Merge Without Committing

```bash
gm feature-branch
# Merges feature-branch but stops before committing
# Lets you review the merge result before finalizing
```

The `--no-ff` flag ensures a merge commit is always created (no fast-forward), making the branch history visible.

### `gpush` — Push with Tags

```bash
gpush main
# Force pushes current branch to origin with tags, setting upstream tracking
```

**Warning:** This uses `-f` (force push). Use with care on shared branches.

### `gup` — Update and Rebase

```bash
gup
# 1. Fetches from origin, pruning deleted remote branches
# 2. Fetches tags, pruning deleted remote tags
# 3. Rebases current branch (preserving merges with -r)
```

A single command to bring your branch up to date.

### `ghist` — Pretty History

```bash
ghist
# a1b2c3d 2024-01-15 | Add login page (HEAD -> main) [Alice]
# e4f5g6h 2024-01-14 | Fix auth bug [Bob]
# * i7j8k9l 2024-01-13 | Merge feature-x [Alice]
```

Shows a compact graph with commit hash, date, message, refs, and author.

---

## Git Functions

### `gt` — List Files in Branch

```bash
# List all tracked files in current branch
gt

# List all tracked files in a specific branch
gt main
```

Uses `git ls-tree` to show every file in the branch's tree.

### `glc` — Count Lines in Branch

```bash
# Count all lines in master branch
glc

# Count all lines in a specific branch
glc main
```

Outputs a line count for every file, plus a total.
