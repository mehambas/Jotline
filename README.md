# Jotline

Jotline is a small inline Markdown scratchpad for a terminal. It opens ready
for typing, keeps the current line as raw Markdown, and renders other lines in
the same text area. It works in any macOS or Linux terminal; cmux is optional.

## Quick start

From a checkout:

```sh
./install.sh
jotline
```

`install.sh` creates a virtual environment, installs dependencies, and puts a
`jotline` launcher in `~/.local/bin`. Add that directory to `PATH` if needed:

```sh
export PATH="$HOME/.local/bin:$PATH"
```

The default note is `~/.local/share/jotline/scratch.md`; the file and its
parent directory are created on first save. Open another file with
`jotline path/to/note.md`; it does not need to exist first. Use `jotline -t`
for a memory-only note that leaves no file or lock behind.

## Editing

- `Ctrl+Q` saves and quits; `Ctrl+S` saves immediately.
- `Ctrl+Z` / `Ctrl+Y` undo and redo.
- `Ctrl+T` toggles a task checkbox on the current line.
- Mouse clicks move the cursor; drag to select and use the wheel to scroll.
- `F1` opens the short in-app help; `Esc` closes it.
- In cmux, `Ctrl+B` or the `>` / `<` status control collapses and restores the
  note pane. A narrow strip remains because cmux enforces a minimum pane size.

When a pane loses focus, all lines switch to rendered Markdown and the cursor
is hidden. Returning to the pane restores the editable line. The note stores
the original Markdown source and auto-saves it atomically.

## Markdown support

Jotline uses `markdown-it-py` and supports headings H1–H6, Setext headings,
lists and checkboxes, bold, italic, strikethrough, inline code, blockquotes,
links, images as an accessible placeholder, fenced and indented code blocks,
tables, footnotes, and simple inline HTML (`b`, `strong`, `i`, `em`, `s`,
`del`, `u`, `code`). Code highlighting uses Pygments and the terminal's ANSI
palette. The terminal supplies the background and default foreground; Jotline
does not impose an RGB theme. Browser actions, image downloads, and arbitrary
HTML layout are outside this terminal editor's scope.

## Global cmux note

Run this inside cmux:

```sh
jotline -g
jotline -g /absolute/path/shared.md
jotline -gs
jotline --global-stop
```

The watcher adds one shared note pane to each local workspace in the current
cmux window, places it on the far right, and gives it a predictable width. New
workspaces are picked up automatically. Remote SSH workspaces are skipped.
When a workspace no longer contains any pane besides its Jotline pane, that
global view closes itself; the same note remains in other workspaces. Global
views share the file and refresh quickly. Concurrent edits are protected; a
conflicting draft is saved as a `*-conflict-*.md` file.

`-gs` (or `--global-stop`) stops the watcher and closes its views without
deleting the note. Global state and logs live below `~/.local/state/jotline` (or
`XDG_STATE_HOME`).

## Development

```sh
.venv/bin/python -m unittest -v
```

The editor uses [prompt_toolkit](https://python-prompt-toolkit.readthedocs.io/),
[markdown-it-py](https://markdown-it-py.readthedocs.io/), and
[Pygments](https://pygments.org/). Windows is not currently supported because
file locking uses `fcntl`; WSL works as a Linux environment.
