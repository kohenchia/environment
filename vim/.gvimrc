" GUI settings. 'transparency' exists only in MacVim, and MacVim's
" Font:h<size> syntax is rejected by GTK gvim (E596), so both are gated.

if has('gui_macvim')
    set gfn=Menlo:h12
    set transparency=8
elseif has('gui_gtk') || has('gui_gtk3')
    set guifont=Monospace\ 12
endif

set linespace=1
colorscheme obsidian2

if exists('*InsertStatuslineColor')
    call InsertStatuslineColor('v')
endif
