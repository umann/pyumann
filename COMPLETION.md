# md CLI Shell Completion Setup

The `md` command supports tab completion for subcommands and options in bash, zsh, and fish shells.

## Quick Start (Bash)

```bash
cd /path/to/pyumann
bash scripts/install_completion.sh bash
```

Then add to your `~/.bashrc`:

```bash
if [[ -f ~/.local/share/bash-completion/completions/md ]]; then
    source ~/.local/share/bash-completion/completions/md
fi
```

Or source it immediately:

```bash
source ~/.local/share/bash-completion/completions/md
```

## Test Completion

After installation, test tab completion:

```bash
md [TAB]                 # Shows subcommands: chk, get, set, soul
md get [TAB]             # Shows files in current directory
md get -[TAB]            # Shows option flags
md get --tr[TAB]         # Auto-completes to --transform
md get -t [TAB]          # Shows additional files
md get -d image.jpg      # Works with multiple files
```

## Installation for Other Shells

### Zsh

```bash
bash scripts/install_completion.sh zsh
```

Add to `~/.zshrc`:

```zsh
if [[ -f ~/.local/share/zsh/site-functions/_md ]]; then
    fpath=(~/.local/share/zsh/site-functions $fpath)
    autoload -Uz compinit && compinit
fi
```

### Fish

```bash
bash scripts/install_completion.sh fish
```

Completions are automatically loaded from `~/.config/fish/completions/md.fish`.

## How It Works

The `generate_completion.py` script uses Click's built-in completion system to generate shell-specific completion functions, with a custom enhancement for bash that handles file arguments better:

1. Sets `_MD_COMPLETE=bash_complete` (or shell-specific variant)
2. Sets `COMP_WORDS` and `COMP_CWORD` with the current command line
3. Invokes the `md` command, which detects the completion request and outputs completion options
4. **Fallback mechanism** (bash only): If Click returns no completions, bash's default file completion is enabled
   - This allows `md get [TAB]` to show files even though Click doesn't provide them
   - Provides intuitive behavior for file arguments

## Troubleshooting

If completion isn't working:

1. **Reload your shell**: Open a new terminal or run `exec bash`
2. **Verify installation**: Run `complete -p md` (bash) or `type _md_completion` (bash)
3. **Check file exists**: Verify `~/.local/share/bash-completion/completions/md` exists
4. **Source manually**: Run `source ~/.local/share/bash-completion/completions/md` to test

## What Gets Completed

For `md get` command:

- **Subcommands**: `get`, `set`, `chk`, `soul`
- **Options**: `--dictify`, `--transform`, `--fix-iptc-encoding`, etc.
- **Choices**: Tab-completing `--transform` shows available transformations
- **Files**: After options, shell provides file completions (default behavior)
