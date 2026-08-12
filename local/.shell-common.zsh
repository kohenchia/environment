# Environment shared by login (.zprofile) and interactive (.zshrc) shells.
#
# Sourced by both because zsh reads .zprofile for login shells only: macOS
# terminals start login shells, but most Linux emulators start non-login
# interactive ones, which would otherwise never see Homebrew or ~/.local/bin.
# Everything here is idempotent, so being sourced twice is harmless.

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

# Tools installed by setup.sh's fallback installers land here (uv, fzf, rg, h).
case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) export PATH="$HOME/.local/bin:$PATH" ;;
esac
