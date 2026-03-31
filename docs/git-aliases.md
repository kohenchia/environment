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
