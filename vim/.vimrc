" Encoding
" Must come first: the multibyte 'listchars' below fails outright when Vim's
" encoding is latin1, which is what a Linux/WSL shell with no LANG set gives us.

set encoding=utf-8
scriptencoding utf-8

" Pathogen
filetype off
call pathogen#incubate()
call pathogen#helptags()

" Default color scheme

syntax enable
colorscheme obsidian2

" Status line

function! InsertStatuslineColor(mode)
    if a:mode == 'i'
        hi statusline guibg=Green guifg=Black gui=NONE cterm=NONE term=NONE
    elseif a:mode == 'r'
        hi statusline guibg=Purple guifg=White gui=NONE cterm=NONE term=NONE
    else
        hi statusline guibg=DarkRed guifg=White gui=NONE cterm=NONE term=NONE
    endif
endfunction
call InsertStatuslineColor('v')

" Autocommands

if has('autocmd')
    filetype plugin indent on
    autocmd InsertEnter * call InsertStatuslineColor(v:insertmode)
    autocmd InsertLeave * call InsertStatuslineColor('v')
endif

" Navigate between windows using <Ctrl-[hjkl]>
" 'D' = command key

map <D-h> <C-w>h 
map <D-j> <C-w>j 
map <D-k> <C-w>k
map <D-l> <C-w>l

nmap <Space> zz
nmap <C-j> 2<C-e>2j
nmap <C-k> 2<C-y>2k

set ts=4 sw=4 sts=4 tabstop=4
set autoindent
set expandtab
set nobackup
set number
set cursorline
set list
set listchars=tab:▸\ ,eol:¬
set laststatus=2
set statusline=%m\ %n:\ %F\ (%p%%)\ l\:%l\ c:%c\ b:%b\ (0x%B)

" Mouse options
" if has('mouse')
"    set mouse=a
" endif

" Machine-specific overrides, not tracked in this repo
if filereadable(expand('~/.vimrc.local'))
    source ~/.vimrc.local
endif
