#!/usr/bin/env bash
#
# Bootstraps this development environment on macOS, Linux, and WSL.
#
# Runs under bash (not zsh) so it can bootstrap a machine where zsh is not
# installed yet. Every step is idempotent — re-running is safe.
#
#   ./setup.sh           install tools and link dotfiles
#   ./setup.sh --check   report what is installed and linked; change nothing

set -e

GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

info() { printf "${GREEN}✓${NC} %s\n" "$1"; }
warn() { printf "${YELLOW}⊘${NC} %s\n" "$1"; }
err()  { printf "${RED}✗${NC} %s\n" "$1"; }

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Arguments ───────────────────────────────────────────────────────

CHECK_ONLY=0
case "${1:-}" in
    "")
        ;;
    --check)
        CHECK_ONLY=1
        ;;
    -h|--help)
        printf 'Usage: %s [--check]\n\n' "$(basename "$0")"
        printf '  (no args)  Install prerequisites and link dotfiles into $HOME.\n'
        printf '  --check    Report installed tools and dotfile links. Read-only;\n'
        printf '             exits non-zero if anything is missing.\n'
        exit 0
        ;;
    *)
        err "Unknown argument: $1 (try --help)"
        exit 1
        ;;
esac

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
    # Not --bin: local/.zshrc falls back to sourcing ~/.fzf/shell/*.zsh when the
    # installed fzf is too old for `fzf --zsh`, so those scripts must be there.
    "$HOME/.fzf/install" --key-bindings --completion --no-update-rc --no-bash --no-fish
    # Symlink into ~/.local/bin (already on PATH per local/.shell-common.zsh)
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

# Tools this environment expects, as "command|package|fallback-fn|note".
# Iterated to install below, and again by --check to report what is missing, so
# the two can't drift apart. curl comes first: the fallback installers for uv
# and ripgrep, plus the oh-my-zsh installer, all need it, and minimal
# Debian/Ubuntu and WSL images ship without it.
TOOLS=(
    "curl|curl||Install curl with your package manager, then re-run ./setup.sh."
    "zsh|zsh||Install zsh with your package manager, then re-run ./setup.sh."
    "git|git||Install git with your package manager, then re-run ./setup.sh."
    "uv|uv|install_uv_standalone|See https://docs.astral.sh/uv/"
    # fzf powers the wt* worktree pickers and the Ctrl-T/Ctrl-R key bindings
    "fzf|fzf|install_fzf_upstream|See https://github.com/junegunn/fzf"
    # ripgrep (rg) — fast recursive search, used directly and by fzf
    "rg|ripgrep|install_ripgrep|See https://github.com/BurntSushi/ripgrep"
    # vim and tmux are configured by this repo, so make sure they exist
    "vim|vim||Install vim with your package manager, then re-run ./setup.sh."
    "tmux|tmux||Install tmux with your package manager, then re-run ./setup.sh."
)

if [[ $CHECK_ONLY -eq 0 ]]; then
    # https:// downloads need a CA bundle; minimal Debian/Ubuntu images omit it
    if [[ "$PKG" == apt-get && ! -e /etc/ssl/certs/ca-certificates.crt ]]; then
        pkg_install ca-certificates || warn "Could not install ca-certificates"
    fi

    for tool in "${TOOLS[@]}"; do
        IFS='|' read -r t_cmd t_pkg t_fallback t_note <<< "$tool"
        ensure_tool "$t_cmd" "$t_pkg" "$t_fallback" "$t_note"
    done

    # ── Default shell ───────────────────────────────────────────────

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
            # Common on WSL, where the default user has no Unix password set
            warn "chsh failed — run 'chsh -s ${ZSH_PATH}' manually (on WSL, 'sudo passwd \$USER' first)"
        fi
    fi

    # ── zsh framework ───────────────────────────────────────────────

    # Install oh-my-zsh (idempotent — skips if already present)
    if [[ -d "$HOME/.oh-my-zsh" ]]; then
        info "oh-my-zsh already installed"
    elif command -v curl >/dev/null 2>&1 && command -v git >/dev/null 2>&1; then
        warn "Installing oh-my-zsh..."
        RUNZSH=no KEEP_ZSHRC=yes sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"
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

# copy_file <repo-relative-source> <target>
# Like link(), but copies content instead of symlinking. For a target that a
# native Windows process must read directly, a WSL-created symlink pointing
# into the Linux filesystem is not resolvable there — it shows up as an
# opaque junction Windows apps can't open.
copy_file() {
    local src="${REPO_DIR}/$1" target="$2"

    if [[ ! -e "$src" ]]; then
        warn "Skipped ${target} (missing ${1})"
        return 0
    fi

    mkdir -p "$(dirname "$target")"

    if [[ -e "$target" ]] && cmp -s "$src" "$target"; then
        info "${1} → ${target} (already up to date)"
        return 0
    fi

    if [[ -e "$target" ]]; then
        cp -f "$target" "${target}.bak"
        warn "Backed up ${target} → ${target}.bak"
    fi

    cp -f "$src" "$target"
    info "Copied ${1} → ${target}"
}

# Dotfiles this repo owns, as "repo-relative-source|target". Iterated to link
# below, and again by --check, so the two can't drift apart.
#
# local/.shell-common.zsh is deliberately absent: .zshrc and .zprofile source it
# from the repo by path rather than through a symlink of its own.
LINKS=(
    "local/.zshrc|$HOME/.zshrc"
    "local/.zprofile|$HOME/.zprofile"
    "local/.p10k.zsh|$HOME/.p10k.zsh"
    "local/.tmux.conf|$HOME/.tmux.conf"
    "vim/.vimrc|$HOME/.vimrc"
    "vim/.gvimrc|$HOME/.gvimrc"
    "vim|$HOME/.vim"
    # `h` — color-coded command tutorials. Linked into ~/.local/bin (on PATH per
    # local/.shell-common.zsh) so it's runnable as `h <command>`.
    "bin/h|$HOME/.local/bin/h"
    # tmux-bell-notify — the tmux alert-bell hook calls this to post a macOS
    # notification for a window that rang the bell. See docs/tmux.md.
    "bin/tmux-bell-notify|$HOME/.local/bin/tmux-bell-notify"
)

# Alacritty — macOS only. This config's whole job is translating Cmd chords
# into the ESC sequences ~/.tmux.conf listens for, and `Command` only exists
# as a modifier on macOS. See docs/tmux.md.
if [[ "$OS" == macos ]]; then
    LINKS+=("local/alacritty.toml|$HOME/.config/alacritty/alacritty.toml")
fi

# Alacritty — WSL only, installed onto the Windows host, since Alacritty runs
# there as a native Windows process rather than inside WSL. Uses COPIES (see
# copy_file above), not LINKS: a WSL symlink into the Linux filesystem isn't
# resolvable by native Windows apps. local/alacritty-windows.toml is the
# Windows counterpart of local/alacritty.toml — see its header.
COPIES=()
if [[ "$OS" == wsl ]]; then
    WIN_APPDATA="$(cmd.exe /c 'echo %APPDATA%' 2>/dev/null | tr -d '\r')"
    if [[ -n "$WIN_APPDATA" ]] && WIN_APPDATA_WSL="$(wslpath -u "$WIN_APPDATA" 2>/dev/null)"; then
        COPIES+=("local/alacritty-windows.toml|${WIN_APPDATA_WSL}/alacritty/alacritty.toml")
    else
        warn "Could not resolve Windows %APPDATA% via cmd.exe — skipping Alacritty install"
    fi
fi

# VS Code stores user settings in a different place on every platform
case "$OS" in
    macos)
        LINKS+=("vscode-user-settings.json|$HOME/Library/Application Support/Code/User/settings.json")
        ;;
    linux)
        LINKS+=("vscode-user-settings.json|$HOME/.config/Code/User/settings.json")
        ;;
    wsl)
        # VS Code runs on the Windows host; only the server's machine settings
        # live inside WSL, and they can't hold editor/extension settings.
        VSCODE_SKIPPED=1
        ;;
esac

if [[ $CHECK_ONLY -eq 0 ]]; then
    for entry in "${LINKS[@]}"; do
        link "${entry%%|*}" "${entry#*|}"
    done

    for entry in "${COPIES[@]}"; do
        copy_file "${entry%%|*}" "${entry#*|}"
    done

    if [[ -n "${VSCODE_SKIPPED:-}" ]]; then
        warn "Skipped VS Code settings: on WSL they live on the Windows host."
        printf '  Copy %s\n  to   %%APPDATA%%\\Code\\User\\settings.json\n' \
            "${REPO_DIR}/vscode-user-settings.json"
    fi

    printf "\n${GREEN}Setup complete.${NC} Open a new terminal to load the configuration.\n"
fi

# ── Check mode ──────────────────────────────────────────────────────
#
# Read-only report: which expected tools are present, whether every dotfile
# points at this repo, and whether an interactive zsh starts without errors.
# Exits non-zero if anything is missing, so CI can consume it.

if [[ $CHECK_ONLY -eq 1 ]]; then
    FAILED=0

    printf '\n'
    for tool in "${TOOLS[@]}"; do
        IFS='|' read -r t_cmd t_pkg t_fallback t_note <<< "$tool"
        if command -v "$t_cmd" >/dev/null 2>&1; then
            info "$(printf '%-6s %s' "$t_cmd" "$(command -v "$t_cmd")")"
        else
            err "$(printf '%-6s not found' "$t_cmd")"
            FAILED=1
        fi
    done

    # This repo's .tmux.conf uses `terminal-features`, added in tmux 3.2.
    if command -v tmux >/dev/null 2>&1; then
        tmux_have="$(tmux -V | cut -d' ' -f2 | tr -d 'a-z')"
        if [[ "$(printf '%s\n3.2\n' "$tmux_have" | sort -V | head -1)" == 3.2 ]]; then
            info "$(printf '%-6s %s' "" "$(tmux -V) (>= 3.2, full .tmux.conf)")"
        else
            warn "$(printf '%-6s %s' "" "$(tmux -V) is older than 3.2 — RGB colour setup in .tmux.conf is skipped")"
        fi
    fi

    printf '\n'
    for entry in "${LINKS[@]}"; do
        src="${REPO_DIR}/${entry%%|*}" target="${entry#*|}"
        if [[ -L "$target" && "$(readlink "$target")" == "$src" ]]; then
            info "${target/#$HOME/~} → ${entry%%|*}"
        elif [[ -L "$target" ]]; then
            err "${target/#$HOME/~} → $(readlink "$target") (points elsewhere)"
            FAILED=1
        elif [[ -e "$target" ]]; then
            err "${target/#$HOME/~} exists but is not a symlink"
            FAILED=1
        else
            err "${target/#$HOME/~} missing"
            FAILED=1
        fi
    done
    for entry in "${COPIES[@]}"; do
        src="${REPO_DIR}/${entry%%|*}" target="${entry#*|}"
        if [[ -e "$target" ]] && cmp -s "$src" "$target"; then
            info "${target} → ${entry%%|*}"
        else
            err "${target} not up to date with ${entry%%|*}"
            FAILED=1
        fi
    done

    if [[ -n "${VSCODE_SKIPPED:-}" ]]; then
        warn "VS Code settings not linked on WSL (they live on the Windows host)"
    fi

    printf '\n'
    if [[ -d "$HOME/.oh-my-zsh" ]]; then
        info "oh-my-zsh installed"
    else
        err "oh-my-zsh missing"
        FAILED=1
    fi
    if [[ -d "${ZSH_CUSTOM:-$HOME/.oh-my-zsh/custom}/themes/powerlevel10k" ]]; then
        info "powerlevel10k installed"
    else
        err "powerlevel10k missing"
        FAILED=1
    fi

    # A clean startup is the real test of the dotfiles: no missing commands, no
    # vim/zsh error codes. Interactive so .zshrc is read.
    if command -v zsh >/dev/null 2>&1; then
        zsh_out="$(zsh -i -c exit 2>&1 || true)"
        if printf '%s' "$zsh_out" | grep -Eq 'command not found|parse error|E[0-9]+:'; then
            err "zsh -i reported errors:"
            printf '%s\n' "$zsh_out" | sed 's/^/    /'
            FAILED=1
        else
            info "zsh -i starts clean"
        fi
    fi

    printf '\n'
    if [[ $FAILED -eq 0 ]]; then
        info "Environment looks complete."
    else
        err "Some checks failed — run ./setup.sh to fix."
    fi
    exit $FAILED
fi
