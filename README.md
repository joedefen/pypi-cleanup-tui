> **UNDER DEVELOPMENT --- BE PATIENT**
# pypi-cleanup-tui

A thin, visual skin over [`pypi-cleanup`](https://pypi.org/project/pypi-cleanup/), the command line tool for deleting PyPI releases: this TUI hands it the marked versions, but makes choosing which versions to keep visual and regex-free -- a selection that is easier to review and less error prone than hand-written patterns.

## Features

- A visual release table with the `DEL`, `DATE`, `DAYS` and `VERSION` columns: mark releases with `x`, mark a whole range below the pick with `X`, and unmark with `u`/`U`.
- Cycle through your packages without retyping names: `p` shows the next package, `P` opens the package list, and `x` removes a name from this run's list.
- A stability gap (`g`) that keeps the releases which stayed current long enough to be installed -- 3, 7, 14, 30 or 60 days.
- Incremental, case-insensitive search (`/`) over the version column; once the pattern is closed, marking keys touch only the visible rows.
- Sort by version or upload date (`s`), switch the `DATE` column between UTC and local time (`z`), and switch between pypi.org and test.pypi.org (`h`).
- A dry run before every deletion: `d` runs `pypi-cleanup --query-only`, shows the command and its report, then asks again before the `--do-it` deletion.
- Browse-only mode (`--read-only`) that disarms the delete key and needs no `pypi-cleanup` install.
- Themes, a `mono`/`--no-color` mode, and remembered options so the next run starts with the same packages, index, zone, sort order, gap and theme.
- Built with Python 3.10+.

## Installation

```bash
pip install pypi-cleanup-tui
```

## Usage

### Command line

```bash
pypi-cleanup-tui package             # one package
pypi-cleanup-tui pack1,pack2,pack3   # one comma separated list
pypi-cleanup-tui pack1 pack2 pack3   # ... or one argument each
pypi-cleanup-tui --host test pack1   # query test.pypi.org instead of pypi.org
pypi-cleanup-tui -u alice pack1      # the PyPI user, kept for the cleanup step
pypi-cleanup-tui --theme nord pack1  # install a palette (see the THEMES screen)
pypi-cleanup-tui --no-color pack1    # attributes instead of color; remembered
pypi-cleanup-tui --read-only pack1   # browse only: no delete key, no checks
```

The first name is the package the table opens, and the rest of the list is kept for `p` and for the next run. Package arguments are cumulative: a run puts its names in front of the remembered list and drops duplicates, keeping the first occurrence.

### Main screen

The release table opens in the terminal:

| Key | Action |
| --- | ------ |
| `q` | quit |
| `?` | open the help screen; `ESC` returns to the screen that opened it |
| `/` | open the incremental search; `ENTER` closes it, `ESC` restores the pattern |
| `T` | open the THEMES screen; `ESC` returns to the table |
| `t` | cycle the color theme (THEMES screen only; `mono` turns color off) |
| `p` | show the next package in the list and reload |
| `P` | open the package list |
| `h` | switch between pypi.org and test.pypi.org and reload |
| `x` | mark the picked release for deletion, then step down |
| `X` | mark the picked release and every release below it, then step up (unmarked row only) |
| `u` | unmark the picked release, then step down |
| `U` | unmark the picked release and every release below it, then step up (marked row only) |
| `z` | switch the `DATE` column between UTC and the local time zone |
| `s` | change the sort order |
| `d` | leave the table, run a `pypi-cleanup` dry run, then the deletion after a second confirmation |
| `g` | apply the stability gap on the table; on the help screen, rotate the gap instead |

The second header line summarises the run: `User=...`, `[p]ack=...` and `[h]ost=...`. `User` is read-only and shows `n/a` until `-u` is given; `p` rotates through the package list and `h` switches the index, reloading the table in both cases. `host` shows the index key (`pypi` or `test`), not its domain name.

The table loads after it opens: the body shows `Loading ...` in the hot-swap colour, then the releases appear. `p` does not reload when the list holds only one package. A failed load opens a modal alert with the error details; dismissing it leaves the body empty, ready for another package or index.

The first header line always ends with a search field: a bare `/` before anything is typed, then `/pattern` after a search. Pressing `/` opens it and typing filters the releases as you go. The pattern is a case-insensitive regular expression matched against the version column, the same shape as vappman's filter: `^1\.` selects the 1.x releases and `[ab]` is a character class. An empty pattern -- or one that does not compile yet, such as a lone `[` while it is being typed -- leaves the table unfiltered. `ENTER` accepts the pattern and `ESC` restores the text the search started with. Once the pattern is closed, `x`, `X`, `u` and `U` apply to the visible rows only, so a filtered table can be marked without touching the hidden releases.

A marked release shows `✘` in the `DEL` column and its remaining cells are dimmed; the marker itself stays plain so it is still easy to read. While anything is marked, the releases that will be kept are drawn in the success colour, so both halves of the decision are visible at once.

The column titles sit in a third, dim header line above the table (with no rule under it), and the `DATE` title names the zone in force, e.g. `DATE (UTC)` or `DATE (EDT)` after pressing `z`. The sorted column carries a `*` before its title: `*VERSION` by default, or `*DATE (UTC)` after `s` switches to upload-date order.

The first header line is made of space separated blocks, and a block that does not apply is blanked instead of removed, so its width never changes and the keys to its right never move:

```text
    x:mark X:mark▼ sort zone gap30 quit ?:help /     nothing marked, unmarked row
del unmark Unmark▼ sort zone gap30 quit ?:help /     marked, pick on a marked row
R/O unmark Unmark▼ sort zone gap30 quit ?:help /     read-only, d never offered
```

The marking pair and the unmarking pair are the same width, and the row under the pick chooses between them: an unmarked row offers `x`/`X`, a marked row offers `u`/`U`. `X` therefore only marks down from an unmarked row, and `U` only unmarks down from a marked row. `del` leads the line once something is marked and no pattern is filtering the table -- a filter can hide marked releases, so `d` is inert while one is in force. A `--read-only` run fills that same block with `R/O` and never offers `d` at all. The search field at the end is the one block whose width follows its text. The theme key is listed on the help screen only; `gap30` is the stability gap in force, and pressing `g` applies it.

`g` is the stability filter, and it means something different on each screen: on the help screen it rotates the gap -- 3, 7, 14, 30 or 60 days; a first run starts at 30 -- and on the table it applies the current gap. Every marked release that no other release followed within that many days is unmarked, so the releases that stayed current long enough to be the one people installed are kept; the newest release counts as stable as well, because nothing followed it at all. The table judges the whole history, not just the visible rows -- how quickly a release was superseded is a fact about the package -- and `g` only ever unmarks, so a hidden release cannot be swept up by it. The hint line shows the gap in force as `gap30`, and a two-second message box reports how many of the marked releases were kept. The gap is one of the remembered options, so the next run starts with the value the last one ended with.

The THEMES screen shows the palette names and their swatches. Its last entry, `mono`, is not a palette: choosing it turns semantic color off, exactly like `--no-color` (and the `NO_COLOR` convention), while a palette turns color back on. The swatches follow that switch, so `mono` previews what the table looks like without color.

### Package screen

`P` opens the package list, whose rows are also what `p` rotates through:

```text
PACKAGES  x:remove ESC:open ?:help
  PACKAGE  VERs  DELs
✓ alpha       3     0
✓ beta        2     0
  gamma       -     -
```

The untitled first column carries `✓` once this run has loaded that package; `VERs` is the number of releases its history held at that load, and `DELs` is the number of versions this run has deleted from it (a successful deletion run does not update this counter yet). Both numbers show `-` until the package is loaded, because the screen never invents a count.

The screen opens with the pick on the package `p` would show next, so `ESC` -- which opens the picked package in the table and returns -- is one keypress from the table's package to the next one. `x` removes the picked name from the list: the index itself is untouched, so a removed package is simply no longer visited by `p` or remembered for the next run. With the list emptied there is nothing to open, so `ESC` leaves the program; `?` opens the help screen, whose `ESC` returns to the package list.

### Running `pypi-cleanup`

The table hands the marked releases to [`pypi-cleanup`](https://pypi.org/project/pypi-cleanup/), which performs the actual deletion, so a normal run checks for it first and stops with a hint to install it when it is missing. `--read-only` skips that check and disarms the delete key: the run browses the history and the hint line shows `R/O` where `del` would be.

Pressing `d` leaves the table for the bare terminal, where it shows the `pypi-cleanup` command built from the marked versions, asks for a `--query-only` dry run, shows what that reports, and then asks again before the `--do-it` deletion. Each question takes `yes`, `no`, or a bare `ENTER` for the safe answer (yes to the dry run, no to the deletion); a no to the deletion leaves the index alone, and the final `ENTER` returns to the table. The command printed before each run is a description, not something to paste into a shell: the values are quoted for reading and a long version pattern is broken after its `|` alternations, so the text is not a copy-pasteable command line.

> **`pypi-cleanup` hints**
>
> * Read the tool's documentation at <https://pypi.org/project/pypi-cleanup/>.
> * Set `$PYPI_CLEANUP_PASSWORD` to your account's login password to skip its password prompt.
> * Set `$PYPI_CLEANUP_TOTP_SECRET` to skip the prompt for your 6-digit authenticator value on every run.

### Options are remembered

The user, the index, the package list, the settings the table itself can change (`z` for the date zone, `s` for the sort order, and the stability `gap` that `g` rotates on the help screen), and the appearance (`theme` and whether color is on) are stored in `~/.config/pypi-cleanup-tui/config.ini`. Every option's default is the stored value, so after the first run

```bash
pypi-cleanup-tui
```

re-opens the same package from the same index, with the same zone, order, stability gap and theme. The package list is kept as one comma separated value -- which is why the two spellings above are equivalent -- and the table still shows one package per run, the first in the list. `--read-only` is deliberately not remembered: it covers a single run, so a browse-only session can never quietly disarm the next one.

```bash
pypi-cleanup-tui newpack     # list becomes: newpack, then the stored names
pypi-cleanup-tui pack2       # a name already stored keeps its first position
```

The help screen (`?`) lists the saved options and the file they came from.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
