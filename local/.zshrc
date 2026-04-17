# Enable Powerlevel10k instant prompt. Should stay close to the top of ~/.zshrc.
# Initialization code that may require console input (password prompts, [y/n]
# confirmations, etc.) must go above this block; everything else may go below.
if [[ -r "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh" ]]; then
  source "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh"
fi

# If you come from bash you might have to change your $PATH.
# export PATH=$HOME/bin:/usr/local/bin:$PATH

# Path to your oh-my-zsh installation.
if [ "$(uname 2> /dev/null)" != "Linux" ]; then
    # Not Linux, assumed to be OSX
    export ZSH="/Users/kohenchia/.oh-my-zsh"
else
    # Linux
    export ZSH="/home/kohenchia/.oh-my-zsh"
fi

# Set name of the theme to load --- if set to "random", it will
# load a random theme each time oh-my-zsh is loaded, in which case,
# to know which specific one was loaded, run: echo $RANDOM_THEME
# See https://github.com/ohmyzsh/ohmyzsh/wiki/Themes
ZSH_THEME="powerlevel10k/powerlevel10k"

# Set list of themes to pick from when loading at random
# Setting this variable when ZSH_THEME=random will cause zsh to load
# a theme from this variable instead of looking in $ZSH/themes/
# If set to an empty array, this variable will have no effect.
# ZSH_THEME_RANDOM_CANDIDATES=( "robbyrussell" "agnoster" )

# Uncomment the following line to use case-sensitive completion.
# CASE_SENSITIVE="true"

# Uncomment the following line to use hyphen-insensitive completion.
# Case-sensitive completion must be off. _ and - will be interchangeable.
# HYPHEN_INSENSITIVE="true"

# Uncomment the following line to disable bi-weekly auto-update checks.
# DISABLE_AUTO_UPDATE="true"

# Uncomment the following line to automatically update without prompting.
# DISABLE_UPDATE_PROMPT="true"

# Uncomment the following line to change how often to auto-update (in days).
# export UPDATE_ZSH_DAYS=13

# Uncomment the following line if pasting URLs and other text is messed up.
# DISABLE_MAGIC_FUNCTIONS=true

# Uncomment the following line to disable colors in ls.
# DISABLE_LS_COLORS="true"

# Uncomment the following line to disable auto-setting terminal title.
# DISABLE_AUTO_TITLE="true"

# Uncomment the following line to enable command auto-correction.
# ENABLE_CORRECTION="true"

# Uncomment the following line to display red dots whilst waiting for completion.
# COMPLETION_WAITING_DOTS="true"

# Uncomment the following line if you want to disable marking untracked files
# under VCS as dirty. This makes repository status check for large repositories
# much, much faster.
# DISABLE_UNTRACKED_FILES_DIRTY="true"

# Uncomment the following line if you want to change the command execution time
# stamp shown in the history command output.
# You can set one of the optional three formats:
# "mm/dd/yyyy"|"dd.mm.yyyy"|"yyyy-mm-dd"
# or set a custom format using the strftime function format specifications,
# see 'man strftime' for details.
# HIST_STAMPS="mm/dd/yyyy"

# Would you like to use another custom folder than $ZSH/custom?
# ZSH_CUSTOM=/path/to/new-custom-folder

# Which plugins would you like to load?
# Standard plugins can be found in $ZSH/plugins/
# Custom plugins may be added to $ZSH_CUSTOM/plugins/
# Example format: plugins=(rails git textmate ruby lighthouse)
# Add wisely, as too many plugins slow down shell startup.
plugins=(git)

source $ZSH/oh-my-zsh.sh

# User configuration

# export MANPATH="/usr/local/man:$MANPATH"

# You may need to manually set your language environment
# export LANG=en_US.UTF-8

# Preferred editor for local and remote sessions
# if [[ -n $SSH_CONNECTION ]]; then
#   export EDITOR='vim'
# else
#   export EDITOR='mvim'
# fi

# Compilation flags
# export ARCHFLAGS="-arch x86_64"

# Set personal aliases, overriding those provided by oh-my-zsh libs,
# plugins, and themes. Aliases can be placed here, though oh-my-zsh
# users are encouraged to define aliases within the ZSH_CUSTOM folder.
# For a full list of active aliases, run `alias`.
#
# Example aliases
# alias zshconfig="mate ~/.zshrc"
# alias ohmyzsh="mate ~/.oh-my-zsh"
source ~/.oh-my-zsh/custom/themes/powerlevel10k/powerlevel10k.zsh-theme

# To customize prompt, run `p10k configure` or edit ~/.p10k.zsh.
[[ ! -f ~/.p10k.zsh ]] || source ~/.p10k.zsh

# ====================================
# Custom

export POWERLEVEL9K_COMMAND_EXECUTION_TIME_THRESHOLD=0

function drawline() {
    printf %"$COLUMNS"s | tr " " "-"
}

function ff() {
    find . -type f -name ${@}
}

function fd() {
    find . -type d -name ${@}
}

# Git aliases
unalias ga
alias ga='git add -A'
unalias gb
alias gb='git branch'
unalias gc
alias gc='git commit -v -m'  # This will force a commit message to be provided
unalias gd
alias gd='git diff -w "$@"'
alias ghist="git log --pretty=format:'%h %ad | %s%d [%an]' --graph --date=short"
function glc
{
    echo Counting all lines in the ${1:-master} branch...
    wc -l `git ls-tree -r ${1:-master} --name-only`
}
unalias gm
alias gm='git merge --no-commit --no-ff'
alias gpush='git push -f --tags -u origin "$@"'
alias gs='git status -s'
unalias gup
alias gup='git fetch --prune origin & git rebase -r'

# k8s
alias k='kubectl'

function ssd
{
    docker exec -e COLUMNS="`tput cols`" -e LINES="`tput lines`" -it ${1} sh -l
}

function ve
{
    # ANSI color codes
    local RED='\033[0;31m'
    local YELLOW='\033[0;33m'
    local NC='\033[0m' # No Color
    
    if ! type "uv" > /dev/null 2>&1; then
        echo "${RED}Error: Please first install uv on your system.${NC}"
        return 1
    fi

    if [[ -n "$1" ]]; then
        # Named environment at ~/.uv/<arg>
        local env_path="$HOME/.uv/$1"
        
        if [[ ! -d "$env_path" ]]; then
            echo "${RED}Error: Environment '$1' does not exist at $env_path${NC}"
            return 1
        fi
        
        # Check if already in this environment
        if [[ "$VIRTUAL_ENV" == "$env_path" ]]; then
            echo "${YELLOW}Warning: Already using environment '$1'${NC}"
            return 0
        fi
        
        # Deactivate current environment if any
        if [[ -n "$VIRTUAL_ENV" ]]; then
            deactivate
        fi
        
        # Activate the environment
        source "$env_path/bin/activate"
    else
        # Local .venv environment
        if [[ ! -d ".venv" ]]; then
            echo "${RED}Error: No local .venv folder found${NC}"
            echo "${YELLOW}Suggestion: Switch to a folder with a .venv folder, or provide an environment name (e.g., ve myenv)${NC}"
            return 1
        fi
        
        local env_path="$(pwd)/.venv"
        
        # Check if already in this environment
        if [[ "$VIRTUAL_ENV" == "$env_path" ]]; then
            echo "${YELLOW}Warning: Already in this environment${NC}"
            return 0
        fi
        
        # Deactivate current environment if any
        if [[ -n "$VIRTUAL_ENV" ]]; then
            deactivate
        fi
        
        # Activate the environment
        source .venv/bin/activate
    fi
}

function vc
{
    # ANSI color codes
    local RED='\033[0;31m'
    local YELLOW='\033[0;33m'
    local NC='\033[0m' # No Color
    
    if ! type "uv" > /dev/null 2>&1; then
        echo "${RED}Error: Please first install uv on your system.${NC}"
        return 1
    fi

    # Parse arguments
    local env_name=""
    local python_version=""
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            -p|--python)
                python_version="$2"
                shift 2
                ;;
            *)
                env_name="$1"
                shift
                ;;
        esac
    done

    # Build uv venv command with optional python version
    local uv_cmd="uv venv"
    if [[ -n "$python_version" ]]; then
        uv_cmd="$uv_cmd --python $python_version"
    fi

    if [[ -n "$env_name" ]]; then
        # Named environment at ~/.uv/<arg>
        local env_path="$HOME/.uv/$env_name"
        
        if [[ -d "$env_path" ]]; then
            echo "${RED}Error: Environment '$env_name' already exists at $env_path${NC}"
            return 1
        fi
        
        # Deactivate current environment if any
        if [[ -n "$VIRTUAL_ENV" ]]; then
            echo "Deactivating current environment: ${VIRTUAL_ENV}"
            deactivate
        fi
        
        # Create the virtual environment
        eval "$uv_cmd \"$env_path\""
        if [[ $? -ne 0 ]]; then
            echo "${RED}Error: Failed to create virtual environment${NC}"
            return 1
        fi
        
        # Activate the virtual environment
        source "$env_path/bin/activate"
    else
        # Local .venv environment
        if [[ -d ".venv" ]]; then
            echo "${RED}Error: A local environment already exists at .venv${NC}"
            echo "${YELLOW}Suggestion: Provide a name to create a named environment instead (e.g., vc myenv)${NC}"
            return 1
        fi
        
        # Deactivate current environment if any
        if [[ -n "$VIRTUAL_ENV" ]]; then
            echo "Deactivating current environment: ${VIRTUAL_ENV}"
            deactivate
        fi
        
        # Create the virtual environment
        eval "$uv_cmd .venv"
        if [[ $? -ne 0 ]]; then
            echo "${RED}Error: Failed to create virtual environment${NC}"
            return 1
        fi
        
        # Activate the virtual environment
        source .venv/bin/activate
    fi
}

function vd
{
    # ANSI color codes
    local RED='\033[0;31m'
    local NC='\033[0m' # No Color
    
    if [[ -n "$VIRTUAL_ENV" ]]; then
        deactivate
    else
        echo "${RED}Error: Not currently in a virtualenv${NC}"
        return 1
    fi
}

function vls
{
    # ANSI color codes
    local RED='\033[0;31m'
    local GREEN='\033[0;32m'
    local YELLOW='\033[0;33m'
    local GRAY='\033[0;90m'
    local NC='\033[0m' # No Color
    
    echo "Named environments in ~/.uv/:"
    if [[ -d "$HOME/.uv" ]]; then
        local found=0
        # Use nullglob to handle empty directories without errors
        setopt local_options nullglob
        for env in "$HOME/.uv"/*; do
            if [[ -d "$env" ]]; then
                local env_name=$(basename "$env")
                local python_version=""
                if [[ -x "$env/bin/python" ]]; then
                    python_version=$("$env/bin/python" --version 2>&1 | awk '{print $2}')
                fi
                
                if [[ "$VIRTUAL_ENV" == "$env" ]]; then
                    echo "  ${GREEN}* $env_name${NC} ${GRAY}(Python $python_version)${NC}"
                else
                    echo "    ${YELLOW}$env_name${NC} ${GRAY}(Python $python_version)${NC}"
                fi
                found=1
            fi
        done
        if [[ $found -eq 0 ]]; then
            echo "  (none)"
        fi
    else
        echo "  (none)"
    fi
    
    echo ""
    
    # Check if there's an active environment that's not managed by uv
    local is_managed_env=0
    if [[ -n "$VIRTUAL_ENV" ]]; then
        # Check if it's a named environment in ~/.uv/
        if [[ "$VIRTUAL_ENV" == "$HOME/.uv/"* ]]; then
            is_managed_env=1
        fi
        # Check if it's the local .venv in current directory
        if [[ "$VIRTUAL_ENV" == "$(pwd)/.venv" ]]; then
            is_managed_env=1
        fi
    fi
    
    # If active environment is not managed, show it instead of local environment
    if [[ -n "$VIRTUAL_ENV" ]] && [[ $is_managed_env -eq 0 ]]; then
        echo "Active environment (not managed by uv):"
        local python_version=""
        if [[ -x "$VIRTUAL_ENV/bin/python" ]]; then
            python_version=$("$VIRTUAL_ENV/bin/python" --version 2>&1 | awk '{print $2}')
        fi
        echo "  ${GREEN}* $VIRTUAL_ENV${NC} ${GRAY}(Python $python_version)${NC}"
    else
        echo "Local environment in current directory:"
        if [[ -d ".venv" ]]; then
            local env_path="$(pwd)/.venv"
            local python_version=""
            if [[ -x ".venv/bin/python" ]]; then
                python_version=$(".venv/bin/python" --version 2>&1 | awk '{print $2}')
            fi
            
            if [[ "$VIRTUAL_ENV" == "$env_path" ]]; then
                echo "  ${GREEN}* .venv${NC} ${GRAY}(Python $python_version)${NC}"
            else
                echo "    ${YELLOW}.venv${NC} ${GRAY}(Python $python_version)${NC}"
            fi
        else
            echo "  (none)"
        fi
    fi
}

function vrm
{
    # ANSI color codes
    local RED='\033[0;31m'
    local YELLOW='\033[0;33m'
    local NC='\033[0m' # No Color
    
    if [[ -n "$1" ]]; then
        # Named environment at ~/.uv/<arg>
        local env_path="$HOME/.uv/$1"
        
        if [[ ! -d "$env_path" ]]; then
            echo "${RED}Error: Environment '$1' does not exist at $env_path${NC}"
            return 1
        fi
        
        # Deactivate if currently active
        if [[ "$VIRTUAL_ENV" == "$env_path" ]]; then
            echo "Deactivating environment '$1'..."
            deactivate
        fi
        
        # Delete the environment
        echo "Deleting environment '$1' at $env_path..."
        rm -rf "$env_path"
        echo "Environment '$1' has been deleted."
    else
        # Local .venv environment
        if [[ ! -d ".venv" ]]; then
            echo "${RED}Error: No local .venv folder found${NC}"
            echo "${YELLOW}Suggestion: Switch to a folder with a .venv folder, or provide an environment name (e.g., vrm myenv)${NC}"
            return 1
        fi
        
        local env_path="$(pwd)/.venv"
        
        # Deactivate if currently active
        if [[ "$VIRTUAL_ENV" == "$env_path" ]]; then
            echo "Deactivating local environment..."
            deactivate
        fi
        
        # Delete the environment
        echo "Deleting local .venv environment..."
        rm -rf .venv
        echo "Local .venv environment has been deleted."
    fi
}

# Setting options
setopt PUSHDSILENT

# Aliases
alias bb='cd ~/bitbucket'
alias cf='caffeinate'
alias cg='cd ~/github'
alias cputemp='sudo powermetrics --samplers smc | grep -i "CPU die temperature"'
alias d='docker'
alias dcp='docker-compose'
alias dev='cd ~/development'
alias home='cd ~'
alias l='ls -lFh'
alias ll='ls -alFh'
alias mkdv='uv pip install -e ".[dev]"'
alias p='uv run python'
alias p3='uv run python3'
alias pdt='uvx pipdeptree'
alias pvd='echo Starting debugpy server at port 17778. Waiting for client...; uv run python -ic "import debugpy; debugpy.listen(17778); debugpy.wait_for_client()"; print("Connected.")'
alias rn='npx react-native'
alias resetaudio='sudo kill -9 `ps ax|grep "coreaudio[a-z]" | awk "{print $1}"`'
alias tmp='cd /tmp'
alias ur='uv run'

function gt() {
    branch=`git branch 2> /dev/null | sed -n -e 's/^\* \(.*\)/\1/p'`
    git ls-tree -r --name-only ${1:-${branch}}
}

# Conda
function c() {
    if command -v conda >/dev/null 2>&1; then
        eval "$(conda shell.zsh hook)"
    else
        echo "conda not found. You cannot use the c() function to initialize conda."
        exit 1
    fi
}

# Application shortcuts
if [ "$(uname 2> /dev/null)" != "Linux" ]; then
    # Not Linux, assumed to be OSX
    alias m='open -a MacVim'
    alias vsc='open -a Visual\ Studio\ Code'
fi

export PATH="$HOME/.local/bin:$PATH"

export PATH="/usr/local/opt/ruby/bin:$PATH"

# Work stuff
if [[ -e "/Users/kohenchia/.zshrc_work" ]]; then
    source /Users/kohenchia/.zshrc_work
fi

# ── Git Worktree helpers ──────────────────────────────────────────────
# Work on multiple features in parallel without stashing or branch-switching.
#
# Usage:
#   wta <repo> <branch> [base]    Create a worktree and cd into it
#   wtl [repo]                    List active worktrees
#   wtc <repo> <branch>           cd into an existing worktree
#   wtr <repo> <branch>           Remove a finished worktree
#
# Worktrees live at ~/github/<repo>-wt/<branch>/
#
# Set WT_REPOS=(repo1 repo2 ...) before this block to control which repos
# appear in tab completion and wtl scanning. If unset, all git repos under
# ~/github/ are discovered automatically.

# Auto-discover git repos under ~/github/ (used when WT_REPOS is not set)
function _wt_discover_repos() {
    local dir
    setopt local_options nullglob
    for dir in ~/github/*/; do
        if [[ -d "${dir}.git" ]]; then
            echo "${dir:h:t}"
        fi
    done
}

function _wt_repo_list() {
    if [[ -n "${WT_REPOS+x}" ]]; then
        echo "${WT_REPOS[@]}"
    else
        _wt_discover_repos
    fi
}

function wta() {
    if [[ $# -lt 2 ]]; then
        print "Usage: wta <repo> <branch> [base-branch]"
        print "  e.g. wta belle my-feature"
        print "  e.g. wta belle my-feature origin/main"
        return 1
    fi

    local repo=$1
    local branch=$2
    local base=${3:-HEAD}
    local repo_dir=~/github/${repo}
    local wt_dir=~/github/${repo}-wt/${branch}

    if [[ ! -d "$repo_dir/.git" ]]; then
        print "\033[0;31m✗\033[0m ~/github/${repo} is not a git repo"
        return 1
    fi

    if [[ -d "$wt_dir" ]]; then
        print "\033[0;33m⊘\033[0m Worktree already exists at ${wt_dir}"
        print "  Run: wtc ${repo} ${branch}"
        return 1
    fi

    git -C "$repo_dir" fetch --quiet 2>/dev/null

    if git -C "$repo_dir" show-ref --verify --quiet "refs/heads/${branch}" 2>/dev/null; then
        git -C "$repo_dir" worktree add "$wt_dir" "$branch"
    else
        git -C "$repo_dir" worktree add -b "$branch" "$wt_dir" "$base"
    fi

    if [[ $? -eq 0 ]]; then
        print "\033[0;32m✓\033[0m Worktree ready at \033[1m${wt_dir}\033[0m"
        cd "$wt_dir"
    fi
}

function wtl() {
    local filter=$1
    local found=false
    local repos=($(_wt_repo_list))

    for repo in $repos; do
        if [[ -n "$filter" && "$repo" != "$filter" ]]; then
            continue
        fi
        local repo_dir=~/github/${repo}
        if [[ ! -d "$repo_dir/.git" ]]; then
            continue
        fi

        local wt_output=$(git -C "$repo_dir" worktree list 2>/dev/null)
        local wt_count=$(echo "$wt_output" | wc -l)

        if [[ $wt_count -gt 1 ]]; then
            if ! $found; then
                print "\033[1mActive worktrees:\033[0m"
                found=true
            fi
            print "\n  \033[1m\033[0;36m${repo}\033[0m"
            echo "$wt_output" | while read -r line; do
                print "    ${line}"
            done
        fi
    done

    if ! $found; then
        if [[ -n "$filter" ]]; then
            print "No worktrees for ${filter}."
        else
            print "No active worktrees."
        fi
    fi
}

function wtr() {
    if [[ $# -lt 2 ]]; then
        print "Usage: wtr <repo> <branch>"
        return 1
    fi

    local repo=$1
    local branch=$2
    local repo_dir=~/github/${repo}
    local wt_dir=~/github/${repo}-wt/${branch}

    if [[ ! -d "$wt_dir" ]]; then
        print "\033[0;31m✗\033[0m No worktree at ${wt_dir}"
        return 1
    fi

    if [[ "$(pwd)" == "${wt_dir}"* ]]; then
        cd "$repo_dir"
    fi

    git -C "$repo_dir" worktree remove "$wt_dir"
    if [[ $? -eq 0 ]]; then
        print "\033[0;32m✓\033[0m Removed worktree \033[1m${wt_dir}\033[0m"
        rmdir ~/github/${repo}-wt 2>/dev/null

        read "del?Delete branch '${branch}' too? [y/N] "
        if [[ "$del" =~ ^[Yy]$ ]]; then
            git -C "$repo_dir" branch -d "$branch" 2>/dev/null || \
            git -C "$repo_dir" branch -D "$branch"
            print "\033[0;32m✓\033[0m Branch '${branch}' deleted"
        fi
    fi
}

function wtc() {
    if [[ $# -lt 2 ]]; then
        print "Usage: wtc <repo> <branch>"
        return 1
    fi

    local wt_dir=~/github/${1}-wt/${2}

    if [[ ! -d "$wt_dir" ]]; then
        print "\033[0;31m✗\033[0m No worktree at ${wt_dir}"
        print "Create one with: wta ${1} ${2}"
        return 1
    fi

    cd "$wt_dir"
    print "Now in \033[1m${wt_dir}\033[0m ($(git rev-parse --abbrev-ref HEAD))"
}

# ── Worktree tab completions ─────────────────────────────────────────

function _wt_existing_branches() {
    local wt_parent=~/github/${1}-wt
    if [[ -d "$wt_parent" ]]; then
        setopt local_options nullglob
        for d in "$wt_parent"/*(/:t); do
            echo "$d"
        done
    fi
}

function _wt_all_branches() {
    local repo_dir=~/github/${1}
    if [[ -d "$repo_dir/.git" ]]; then
        git -C "$repo_dir" for-each-ref --format='%(refname:short)' refs/heads/ refs/remotes/ 2>/dev/null | sed 's|^origin/||' | sort -u
    fi
}

function _wt_complete_repos() {
    if [[ -n "${WT_REPOS+x}" ]]; then
        compadd -a WT_REPOS
    else
        compadd $(_wt_discover_repos)
    fi
}

function _wta() {
    case $CURRENT in
        2) _wt_complete_repos ;;
        3) compadd $(_wt_all_branches "${words[2]}") ;;
        4) compadd $(_wt_all_branches "${words[2]}") ;;
    esac
}
compdef _wta wta

function _wtl() {
    case $CURRENT in
        2) _wt_complete_repos ;;
    esac
}
compdef _wtl wtl

function _wtr() {
    case $CURRENT in
        2) _wt_complete_repos ;;
        3) compadd $(_wt_existing_branches "${words[2]}") ;;
    esac
}
compdef _wtr wtr

function _wtc() {
    case $CURRENT in
        2) _wt_complete_repos ;;
        3) compadd $(_wt_existing_branches "${words[2]}") ;;
    esac
}
compdef _wtc wtc

# ── Worktree symlinks ────────────────────────────────────────────────
#
# Create and remove local symlinks that point to worktrees.
# Works from any directory — useful for workspaces that aggregate repos
# via symlinks (e.g. ace).

function wts() {
    if [[ $# -lt 2 ]]; then
        print "Usage: wts <repo> <branch>"
        print "  Creates a symlink in the current directory pointing to the worktree."
        print "  e.g. wts benchmark feature/launch-ifp"
        print "       -> benchmark@feature-launch-ifp"
        return 1
    fi

    local repo=$1
    local branch=$2
    local wt_dir=~/github/${repo}-wt/${branch}
    local link_name="${repo}@${branch//\//-}"

    if [[ ! -d "$wt_dir" ]]; then
        print "\033[0;31m✗\033[0m No worktree at ${wt_dir}"
        print "  Create one with: wta ${repo} ${branch}"
        return 1
    fi

    if [[ -e "$link_name" || -L "$link_name" ]]; then
        local resolved="${wt_dir:A}"
        local link_resolved="$(readlink -f "$link_name" 2>/dev/null)"
        if [[ "$link_resolved" == "$resolved" ]]; then
            print "\033[0;33m⊘\033[0m ${link_name} already links to this worktree"
            return 0
        else
            print "\033[0;31m✗\033[0m ${link_name} already exists"
            return 1
        fi
    fi

    ln -s "${wt_dir:A}" "$link_name"
    print "\033[0;32m✓\033[0m ${link_name} -> ${wt_dir}"
}

function wtu() {
    if [[ $# -lt 2 ]]; then
        print "Usage: wtu <repo> <branch>"
        print "  Removes a worktree symlink from the current directory."
        print "  e.g. wtu benchmark feature/launch-ifp"
        print "       -> removes benchmark@feature-launch-ifp"
        return 1
    fi

    local repo=$1
    local branch=$2
    local link_name="${repo}@${branch//\//-}"

    if [[ ! -L "$link_name" ]]; then
        print "\033[0;31m✗\033[0m No symlink '${link_name}' in current directory"
        return 1
    fi

    rm "$link_name"
    print "\033[0;32m✓\033[0m Removed ${link_name}"
}

function _wts() {
    case $CURRENT in
        2) _wt_complete_repos ;;
        3) compadd $(_wt_existing_branches "${words[2]}") ;;
    esac
}
compdef _wts wts

function _wtu() {
    # Complete with worktree symlinks in the current directory.
    case $CURRENT in
        2) _wt_complete_repos ;;
        3) compadd $(_wt_existing_branches "${words[2]}") ;;
    esac
}
compdef _wtu wtu

export NVM_DIR="$HOME/.nvm"
if [ -s "$NVM_DIR/nvm.sh" ]; then \. "$NVM_DIR/nvm.sh"; fi # This loads nvm
if [ -s "$NVM_DIR/bash_completion" ]; then \. "$NVM_DIR/bash_completion"; fi  # This loads nvm bash_completion

# UV
. "$HOME/.local/bin/env"
