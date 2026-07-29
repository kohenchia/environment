# Homebrew is not on PATH by default on Apple Silicon (/opt/homebrew) or
# Linuxbrew. Load whichever prefix exists — brew shellenv sets PATH, MANPATH,
# INFOPATH and HOMEBREW_* for us.
for brew_bin in /opt/homebrew/bin/brew /usr/local/bin/brew /home/linuxbrew/.linuxbrew/bin/brew; do
    if [[ -x "$brew_bin" ]]; then
        eval "$("$brew_bin" shellenv)"
        break
    fi
done
unset brew_bin

export PATH="$HOME/.local/bin:$PATH"
