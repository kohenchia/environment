#!/usr/bin/env bash
#
# Bootstraps this development environment on macOS, Linux, and WSL.
#
# Runs under bash (not zsh) so it can bootstrap a machine where zsh is not
# installed yet. Every step is idempotent — re-running is safe.

set -e

GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

info() { printf "${GREEN}✓${NC} %s\n" "$1"; }
warn() { printf "${YELLOW}⊘${NC} %s\n" "$1"; }
err()  { printf "${RED}✗${NC} %s\n" "$1"; }

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Platform detection ──────────────────────────────────────────────

case "$(uname -s)" in
    Darwin)
        OS=macos
        ;;
    Linux)
        # WSL kernels advertise "microsoft" in /proc/version
        if grep -qi microsoft /proc/version 2>/dev/null; then
            OS=wsl
        else
            OS=linux
        fi
        ;;
    *)
        err "Unsupported platform: $(uname -s)"
        exit 1
        ;;
esac
info "Detected platform: ${OS}"

# On Apple Silicon, Homebrew installs to /opt/homebrew and is only on PATH via
# `brew shellenv`. Because this repo owns ~/.zprofile, that line may not have
# been added yet — find brew directly so the installs below can use it.
if [[ "$OS" == macos ]] && ! command -v brew >/dev/null 2>&1; then
    for brew_bin in /opt/homebrew/bin/brew /usr/local/bin/brew; do
        if [[ -x "$brew_bin" ]]; then
            eval "$("$brew_bin" shellenv)"
            info "Found Homebrew at ${brew_bin}"
            break
        fi
    done
fi

# Package installs on Linux/WSL need root
SUDO=""
if [[ "$OS" != macos && "$(id -u)" -ne 0 ]] && command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
fi

PKG=""
case "$OS" in
    macos)
        command -v brew >/dev/null 2>&1 && PKG=brew
        ;;
    linux|wsl)
        for candidate in apt-get dnf yum pacman zypper; do
            if command -v "$candidate" >/dev/null 2>&1; then
                PKG="$candidate"
                break
            fi
        done
        ;;
esac

if [[ -z "$PKG" ]]; then
    warn "No supported package manager found — tools will use standalone installers"
fi

# ── Package installation ────────────────────────────────────────────

APT_UPDATED=0

# pkg_install <package-name> — returns non-zero if the install could not be done
pkg_install() {
    local pkg="$1"
    case "$PKG" in
        brew)
            brew install "$pkg"
            ;;
        apt-get)
            if [[ $APT_UPDATED -eq 0 ]]; then
                $SUDO apt-get update -qq
                APT_UPDATED=1
            fi
            $SUDO apt-get install -y "$pkg"
            ;;
        dnf|yum)
            $SUDO "$PKG" install -y "$pkg"
            ;;
        pacman)
            $SUDO pacman -S --noconfirm "$pkg"
            ;;
        zypper)
            $SUDO zypper --non-interactive install "$pkg"
            ;;
        *)
            return 1
            ;;
    esac
}

# ensure_tool <command> <package> [fallback-function] [note]
# Never aborts setup — a tool that cannot be installed is reported and skipped.
ensure_tool() {
    local cmd="$1" pkg="$2" fallback="${3:-}" note="${4:-}"

    if command -v "$cmd" >/dev/null 2>&1; then
        info "${cmd} already installed"
        return 0
    fi

    warn "Installing ${cmd}..."
    if pkg_install "$pkg"; then
        info "${cmd} installed via ${PKG}"
        return 0
    fi

    if [[ -n "$fallback" ]] && "$fallback"; then
        info "${cmd} installed"
        return 0
    fi

    warn "Could not install ${cmd} automatically.${note:+ }${note}"
    return 0
}

install_uv_standalone() {
    command -v curl >/dev/null 2>&1 || return 1
    curl -LsSf https://astral.sh/uv/install.sh | sh
}

install_fzf_upstream() {
    command -v git >/dev/null 2>&1 || return 1
    if [[ ! -d "$HOME/.fzf" ]]; then
        git clone --depth 1 https://github.com/junegunn/fzf.git "$HOME/.fzf"
    fi
    "$HOME/.fzf/install" --bin
    # Symlink into ~/.local/bin (already on PATH per local/.zprofile)
    mkdir -p "$HOME/.local/bin"
    ln -sf "$HOME/.fzf/bin/fzf" "$HOME/.local/bin/fzf"
}

# Prebuilt ripgrep from GitHub releases, for machines with no usable package
# manager. Bump RIPGREP_VERSION to pick up newer releases; asset names follow
# the pattern ripgrep-<version>-<target>.tar.gz.
RIPGREP_VERSION=15.2.0

install_ripgrep_cargo() {
    command -v cargo >/dev/null 2>&1 || return 1
    warn "Building ripgrep with cargo (this takes a few minutes)..."
    cargo install ripgrep
}

install_ripgrep_prebuilt() {
    command -v curl >/dev/null 2>&1 || return 1

    local target
    case "${OS}:$(uname -m)" in
        macos:arm64|macos:aarch64)                        target=aarch64-apple-darwin ;;
        macos:x86_64)                                     target=x86_64-apple-darwin ;;
        linux:x86_64|wsl:x86_64)                          target=x86_64-unknown-linux-musl ;;
        linux:aarch64|wsl:aarch64|linux:arm64|wsl:arm64)  target=aarch64-unknown-linux-gnu ;;
        *)
            warn "No prebuilt ripgrep for ${OS}/$(uname -m)"
            return 1
            ;;
    esac

    local name="ripgrep-${RIPGREP_VERSION}-${target}"
    local url="https://github.com/BurntSushi/ripgrep/releases/download/${RIPGREP_VERSION}/${name}.tar.gz"
    local tmp
    tmp="$(mktemp -d)"

    if ! curl -fsSL "$url" | tar xz -C "$tmp" --strip-components=1 2>/dev/null; then
        rm -rf "$tmp"
        return 1
    fi

    mkdir -p "$HOME/.local/bin"
    cp "$tmp/rg" "$HOME/.local/bin/rg"
    chmod 755 "$HOME/.local/bin/rg"

    # Man page and zsh completion ship in the tarball
    if [[ -f "$tmp/doc/rg.1" ]]; then
        mkdir -p "$HOME/.local/share/man/man1"
        cp "$tmp/doc/rg.1" "$HOME/.local/share/man/man1/rg.1"
    fi
    if [[ -f "$tmp/complete/_rg" ]]; then
        mkdir -p "$HOME/.local/share/zsh/site-functions"
        cp "$tmp/complete/_rg" "$HOME/.local/share/zsh/site-functions/_rg"
    fi

    rm -rf "$tmp"
    info "ripgrep ${RIPGREP_VERSION} installed to ~/.local/bin/rg"
}

install_ripgrep() {
    install_ripgrep_cargo || install_ripgrep_prebuilt
}

ensure_tool zsh zsh "" "Install zsh with your package manager, then re-run ./setup.sh."
ensure_tool git git "" "Install git with your package manager, then re-run ./setup.sh."
ensure_tool uv uv install_uv_standalone "See https://docs.astral.sh/uv/"
# fzf powers the wt* worktree pickers when called without args
ensure_tool fzf fzf install_fzf_upstream "See https://github.com/junegunn/fzf"
# ripgrep (rg) — fast recursive search, used directly and by fzf
ensure_tool rg ripgrep install_ripgrep "See https://github.com/BurntSushi/ripgrep"

# ── Default shell ───────────────────────────────────────────────────

ZSH_PATH="$(command -v zsh || true)"
if [[ -z "$ZSH_PATH" ]]; then
    err "zsh is not installed — shell configuration will not load. Install zsh and re-run."
elif [[ "$SHELL" == */zsh ]]; then
    info "Default shell is already zsh"
else
    warn "Changing default shell to ${ZSH_PATH}..."
    # chsh refuses shells that are not listed in /etc/shells
    if [[ "$OS" != macos ]] && ! grep -qxF "$ZSH_PATH" /etc/shells 2>/dev/null; then
        printf '%s\n' "$ZSH_PATH" | $SUDO tee -a /etc/shells >/dev/null \
            || warn "Could not add ${ZSH_PATH} to /etc/shells"
    fi
    if chsh -s "$ZSH_PATH"; then
        info "Default shell set to ${ZSH_PATH}"
    else
        warn "chsh failed — run 'chsh -s ${ZSH_PATH}' manually"
    fi
fi

# ── zsh framework ───────────────────────────────────────────────────

# Install oh-my-zsh (idempotent — skips if already present)
if [[ -d "$HOME/.oh-my-zsh" ]]; then
    info "oh-my-zsh already installed"
elif command -v curl >/dev/null 2>&1 && command -v git >/dev/null 2>&1; then
    warn "Installing oh-my-zsh..."
    RUNZSH=no KEEP_ZSHRC=yes sh -c "$(curl -fsSL https://raw.github.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"
    info "oh-my-zsh installed"
else
    warn "Skipped oh-my-zsh (needs curl and git)"
fi

# Install powerlevel10k theme (idempotent)
P10K_DIR="${ZSH_CUSTOM:-$HOME/.oh-my-zsh/custom}/themes/powerlevel10k"
if [[ -d "$P10K_DIR" ]]; then
    info "powerlevel10k already installed"
elif command -v git >/dev/null 2>&1 && [[ -d "$HOME/.oh-my-zsh" ]]; then
    warn "Installing powerlevel10k..."
    git clone --depth=1 https://github.com/romkatv/powerlevel10k.git "$P10K_DIR"
    info "powerlevel10k installed"
else
    warn "Skipped powerlevel10k (needs git and oh-my-zsh)"
fi

# ── Symlinks ────────────────────────────────────────────────────────

# link <repo-relative-source> <target>
# Backs up anything already at <target> to <target>.bak, then symlinks.
# Handles files and directories alike, and creates missing parent directories.
link() {
    local src="${REPO_DIR}/$1" target="$2"

    if [[ ! -e "$src" ]]; then
        warn "Skipped ${target} (missing ${1})"
        return 0
    fi

    mkdir -p "$(dirname "$target")"

    # Already pointing where we want — leave it alone so re-runs don't churn .bak
    if [[ -L "$target" && "$(readlink "$target")" == "$src" ]]; then
        info "${1} → ${target} (already linked)"
        return 0
    fi

    if [[ -e "$target" || -L "$target" ]]; then
        # rm -rf, not unlink: the stale backup may be a real directory
        rm -rf "${target}.bak"
        mv "$target" "${target}.bak"
        warn "Backed up ${target} → ${target}.bak"
    fi

    ln -s "$src" "$target"
    info "Linked ${1} → ${target}"
}

link local/.zshrc "$HOME/.zshrc"
link local/.zprofile "$HOME/.zprofile"
link local/.p10k.zsh "$HOME/.p10k.zsh"
link local/.tmux.conf "$HOME/.tmux.conf"
link vim/.vimrc "$HOME/.vimrc"
link vim/.gvimrc "$HOME/.gvimrc"
link vim "$HOME/.vim"

# `h` — color-coded command tutorials. Linked into ~/.local/bin (on PATH per
# local/.zprofile) so it's runnable as `h <command>`.
link bin/h "$HOME/.local/bin/h"

# VS Code stores user settings in a different place on every platform
case "$OS" in
    macos)
        link vscode-user-settings.json "$HOME/Library/Application Support/Code/User/settings.json"
        ;;
    linux)
        link vscode-user-settings.json "$HOME/.config/Code/User/settings.json"
        ;;
    wsl)
        # VS Code runs on the Windows host; only the server's machine settings
        # live inside WSL, and they can't hold editor/extension settings.
        warn "Skipped VS Code settings: on WSL they live on the Windows host."
        printf '  Copy %s\n  to   %%APPDATA%%\\Code\\User\\settings.json\n' \
            "${REPO_DIR}/vscode-user-settings.json"
        ;;
esac

printf "\n${GREEN}Setup complete.${NC} Open a new terminal to load the configuration.\n"
