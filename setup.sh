#!/usr/bin/env zsh

set -e

GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

info() { print "${GREEN}✓${NC} $1" }
warn() { print "${YELLOW}⊘${NC} $1" }

# ── Prerequisites ───────────────────────────────────────────────────

# Ensure zsh is the default shell
if [[ "$SHELL" != */zsh ]]; then
    warn "Changing default shell to zsh..."
    chsh -s /bin/zsh
    info "Default shell set to zsh"
else
    info "Default shell is already zsh"
fi

# Install oh-my-zsh (idempotent — skips if already present)
if [[ -d "$HOME/.oh-my-zsh" ]]; then
    info "oh-my-zsh already installed"
else
    warn "Installing oh-my-zsh..."
    RUNZSH=no KEEP_ZSHRC=yes sh -c "$(curl -fsSL https://raw.github.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"
    info "oh-my-zsh installed"
fi

# Install powerlevel10k theme (idempotent)
P10K_DIR="${ZSH_CUSTOM:-$HOME/.oh-my-zsh/custom}/themes/powerlevel10k"
if [[ -d "$P10K_DIR" ]]; then
    info "powerlevel10k already installed"
else
    warn "Installing powerlevel10k..."
    git clone --depth=1 https://github.com/romkatv/powerlevel10k.git "$P10K_DIR"
    info "powerlevel10k installed"
fi

# Install uv (idempotent)
if command -v uv >/dev/null 2>&1; then
    info "uv already installed"
elif command -v brew >/dev/null 2>&1; then
    warn "Installing uv via Homebrew..."
    brew install uv
    info "uv installed"
else
    warn "Installing uv via standalone installer..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    info "uv installed"
fi

# Install fzf (idempotent) — powers the wt* worktree pickers when called without args
if command -v fzf >/dev/null 2>&1; then
    info "fzf already installed"
elif command -v brew >/dev/null 2>&1; then
    warn "Installing fzf via Homebrew..."
    brew install fzf
    info "fzf installed"
elif command -v apt-get >/dev/null 2>&1; then
    warn "Installing fzf via apt-get (WSL/Debian/Ubuntu)..."
    sudo apt-get update -qq
    sudo apt-get install -y fzf
    info "fzf installed"
else
    warn "Installing fzf via upstream installer into ~/.fzf..."
    if [[ ! -d "$HOME/.fzf" ]]; then
        git clone --depth 1 https://github.com/junegunn/fzf.git "$HOME/.fzf"
    fi
    "$HOME/.fzf/install" --bin
    # Symlink into ~/.local/bin (already on PATH per local/.zshrc)
    mkdir -p "$HOME/.local/bin"
    ln -sf "$HOME/.fzf/bin/fzf" "$HOME/.local/bin/fzf"
    info "fzf installed at ~/.fzf/bin/fzf (symlinked into ~/.local/bin)"
fi

# ── Symlinks ────────────────────────────────────────────────────────

link_file() {
    if [ -f "${2}" ] || [ -L "${2}" ]; then
        if [ -f "${2}.bak" ]; then
            unlink "${2}.bak"
        fi
        mv "${2}" "${2}.bak"
    fi
    ln -s "$(pwd)/${1}" "${2}"
    info "Linked ${1} → ${2}"
}

link_directory() {
    if [ -d "${2}" ] || [ -L "${2}" ]; then
        if [ -d "${2}.bak" ]; then
            unlink "${2}.bak"
        fi
        mv "${2}" "${2}.bak"
    fi
    ln -s "$(pwd)/${1}" "${2}"
    info "Linked ${1} → ${2}"
}

link_file local/.zshrc ~/.zshrc
link_file local/.zprofile ~/.zprofile
link_file local/.p10k.zsh ~/.p10k.zsh
link_file vim/.vimrc ~/.vimrc
link_file vim/.gvimrc ~/.gvimrc
link_directory vim ~/.vim
link_file vscode-user-settings.json "$HOME/Library/Application Support/Code/User/settings.json"

print "\n${GREEN}Setup complete.${NC} Open a new terminal to load the configuration."
