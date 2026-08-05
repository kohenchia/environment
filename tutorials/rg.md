# rg — ripgrep quick tutorial

Here's a quick, practical `rg` (ripgrep) tutorial covering exactly what you asked.

## 1. Searching for a string — with and without regex

By default, `rg` treats the pattern as a **regex**:

```
rg "foo.*bar"        # regex: "foo" ... "bar" on the same line
rg "error\d+"        # regex: "error" followed by digits
```

To search for a **literal string** (no regex interpretation), use `-F` / `--fixed-strings`:

```
rg -F "config[env]"     # matches the literal "config[env]", brackets not special
rg -F "a.b.c"           # dots are literal, not "any char"
```

Other handy match modifiers:

```
rg -i "error"        # case-insensitive
rg -w "log"          # whole word only (won't match "login" or "catalog")
rg -v "debug"        # invert: lines that do NOT match
rg -x "pattern"      # whole line must match
```

## 2. Ignoring certain folders

`rg` already respects `.gitignore` automatically. To exclude more:

```
rg "foo" -g '!node_modules'        # exclude a folder (glob, note the !)
rg "foo" -g '!node_modules' -g '!dist'   # exclude multiple
rg "foo" -g '!**/tests/**'         # exclude tests anywhere in the tree
```

Related flags:

```
rg "foo" --no-ignore     # DON'T respect .gitignore (search everything)
rg "foo" -u              # relax ignore rules (-uu also searches hidden, -uuu binary)
rg "foo" --hidden        # include dotfiles/dot-directories
```

## 3. Restricting by file extension or filename

**By type** (fastest, uses built-in type definitions):

```
rg "foo" -t py           # only Python files
rg "foo" -t js -t ts     # JS and TS
rg "foo" -T py           # everything EXCEPT Python (capital T = exclude type)
rg --type-list           # see all predefined types
```

**By glob** (extension or name pattern):

```
rg "foo" -g '*.py'              # only .py files
rg "foo" -g '*.{js,ts}'        # .js or .ts
rg "foo" -g '*config*'         # filename contains "config"
rg "foo" -g 'test_*.py'        # name starts with test_ and ends .py
```

**Finding files by name** (no content search — like `find`):

```
rg --files -g '*config*'       # list files whose names match
rg --files | rg config         # equivalent, pipe file list through rg
```

## Bonus: everyday flags worth knowing

```
rg -l "foo"          # list only filenames with matches
rg -c "foo"          # count matches per file
rg -n "foo"          # show line numbers (on by default in a terminal)
rg -A 3 -B 2 "foo"   # 3 lines After, 2 Before (or -C 3 for both)
rg "foo" path/       # limit search to a directory
rg -o "\w+@\w+"      # print only the matched part, not the whole line
```

A quick mental model: **`-t`/`-g` filter which files, the pattern (or `-F`) controls what matches, and ignore flags control what's skipped.**
