> **UNDER DEVELOPMENT --- BE PATIENT**

# pypi-cleanup-tui

A thin, visual skin over [`pypi-cleanup`](https://pypi.org/project/pypi-cleanup/), which performs the actual deletion. Consider using:

- this TUI to cull per-version and visually: selecting by hand, with the survivors in view;
- `pypi-cleanup` directly when cull rules are expressible and reusable (`.*rc\d+`, keep-newest, before-a-date), especially for automation across many packages.

```text
 del x:mark X:mark▼ sort zone gap60 quit ?:help /
 User=betazoid pack=vappman host=pypi
 DEL DATE (UTC)        DAYS  *VERSION
────────────────────────────────
     2026/11/06 22:04     1  2.2.2
     2026/10/31 18:13     7  2.2.1
  ✘  2026/10/28 00:07    10  2.2.0
>    2026/10/13 02:05    25  2.1.7
     2026/03/01 19:37   251  2.1.6
```

*The main screen (a mock-up; a GIF is planned). One release is marked `✘` and the pick sits on `2.1.7`. `x` marks a release, `X` marks everything below the pick, `d` previews and then performs the deletion, `?` lists every key, and `p` moves to the next package.*

## Features

- A package's whole history in one table, with upload date and age in calendar days (yesterday counts as 1, counted in the zone `z` shows), so a stale release is visible instead of inferred from a version number.
- Mark with `x`, mark a whole run below the pick with `X`, clear with `u`/`U` -- a selection you can see, with no pattern to get wrong.
- A stability gap (`g`) keeps the releases that stayed current for 3, 7, 14, 30 or 60 days: the ones people actually installed.
- Search (`/`) over the versions, after which the marking keys touch only the visible rows.
- Move between packages with `p`/`P`, between indexes with `h`, sort with `s`, change the date zone with `z`.
- Every deletion is a dry run first, with the command and its report shown before a second confirmation; `--read-only` browses with no delete key and no `pypi-cleanup` install.

## Installation

```bash
pipx install -f pypi-cleanup-tui   # install or refresh; -f makes one command do both
pipx install -f pypi-cleanup       # the tool the TUI hands the deletion to
```

> **Note:** pipx gives the TUI its own environment; the package itself needs Python 3.11 or newer. The TUI exposes only part of [`pypi-cleanup`](https://pypi.org/project/pypi-cleanup/); for anything it lacks, run that tool directly. `--read-only` browses without it installed.

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

The first name is the package the table opens; the rest is kept for `p` and for the next run. Package arguments are cumulative: a run puts its names in front of the remembered list and drops duplicates, keeping the first occurrence.

### Main screen

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

The second header line is the run: `User=...`, `[p]ack=...` and `[h]ost=...`. `User` shows `n/a` until `-u` is given, `host` shows the index key (`pypi` or `test`) rather than a domain, and `p` and `h` each reload the table. The body then loads: `Loading ...` first, releases after; a failed load opens a modal with the error and leaves the body empty for another package or index.

Marked releases take `✘` in `DEL` and dim their other cells, while the releases that will be kept stay in the success color, so both halves of the decision are visible at once. `T` lists the palettes with swatches; its last entry, `mono`, is not a palette but the switch that turns color off, exactly like `--no-color` and the `NO_COLOR` convention, and choosing a palette turns it back on.

The column titles are a dim third line, the sorted column carries a `*` (`*VERSION`, or `*DATE (UTC)` after `s`), and the `DATE` title names the zone in force (`DATE (EDT)` after `z`). The keys on the first line are blocks, and a block that does not apply is blanked rather than removed, so nothing to its right moves:

```text
x:mark X:mark▼ sort zone gap30 quit ?:help /     nothing marked, unmarked row
del unmark Unmark▼ sort zone gap30 quit ?:help /     marked, pick on a marked row
R/O unmark Unmark▼ sort zone gap30 quit ?:help /     read-only, d never offered
```

An unmarked row offers `x`/`X` and a marked row offers `u`/`U`, the two pairs have the same width, and the row under the pick chooses between them. `del` leads once something is marked and no pattern is filtering -- a filter can hide marked releases, so `d` is inert while one is in force. `--read-only` fills that block with `R/O` and never offers `d`. The search field is the one block whose width follows its text, and the theme key is listed on the help screen only.

### Search and the stability gap

- `/` filters on a case-insensitive regular expression over the version column -- `^1\.` for the 1.x releases, `[ab]` for a character class. An empty or not-yet-valid pattern (a lone `[` while it is being typed) leaves the table unfiltered; `ENTER` accepts, `ESC` restores the text the search started with. While a pattern is closed, `x`, `X`, `u` and `U` apply to the visible rows only.
- `g` means two things. On the help screen it rotates the stability gap -- 3, 7, 14, 30 or 60 days, starting at 30 -- and on the table it applies the gap in force: every marked release that another release superseded within that many days is unmarked, so what stays is what had time to be installed. The days are calendar days in the zone `z` shows, the same unit as the `DAYS` column, so switching zone can move a borderline release across the gap. The newest release counts as stable because nothing followed it. The test is over the whole history, not the visible rows, and `g` only ever unmarks, so a filter cannot hide a release from it. A two-second message reports how many marked releases were kept, and the gap is remembered for the next run.

### Package screen

`P` opens the package list, whose rows are also what `p` rotates through:

```text
PACKAGES  x:remove ESC:open ?:help
  PACKAGE  VERs  DELs
✓ alpha       3     0
✓ beta        2     0
  gamma       -     -
```

The untitled first column carries `✓` once this run has loaded that package; `VERs` is the release count at that load and `DELs` the versions deleted this run (a successful deletion does not update the counter yet). Both show `-` until the package is loaded, because the screen never invents a count. The pick opens on the package `p` would show next, so `ESC` is one keypress from the table's package to the next; it opens that package in the table and returns. `x` removes the picked name from this run's list and leaves the index untouched. With the list emptied there is nothing to open, so `ESC` leaves the program; `?` opens the help screen, whose `ESC` returns to the list.

### Running `pypi-cleanup`

The table hands the marked releases to [`pypi-cleanup`](https://pypi.org/project/pypi-cleanup/), which performs the actual deletion, so a normal run checks for it first and stops with a hint to install it when it is missing. `--read-only` skips that check and disarms the delete key: the run browses the history and the hint line shows `R/O` where `del` would be.

Pressing `d` leaves the table for the bare terminal, where it shows the `pypi-cleanup` command built from the marked versions, asks for a `--query-only` dry run, shows what that reports, and then asks again before the `--do-it` deletion. Each question takes `yes`, `no`, or a bare `ENTER` for the safe answer (yes to the dry run, no to the deletion); a no to the deletion leaves the index alone, and the final `ENTER` returns to the table. The command printed before each run is a description, not something to paste into a shell: the values are quoted for reading and a long version pattern is broken after its `|` alternations, so the text is not a copy-pasteable command line. When a scoped credential supplies a value, one extra line above the command names the mapping, never the value.

> **`pypi-cleanup` hints**
>
> * Read the tool's documentation at <https://pypi.org/project/pypi-cleanup/>.
> * Set `$PYPI_CLEANUP_PASSWORD` to your account's login password to skip its password prompt.
> * Set `$PYPI_CLEANUP_TOTP_SECRET` to skip the prompt for your 6-digit authenticator value on every run.
> * Scope either value to one index with a `4PYPI` or `4TEST` suffix -- `$PYPI_CLEANUP_PASSWORD4TEST`, `$PYPI_CLEANUP_TOTP_SECRET4PYPI` -- and the TUI passes it as the base variable only when that index is in use. Each base variable is left untouched when its suffix form is unset,
> * **The machine running this TUI must be "trusted".** If `pypi-cleanup` fails with an authentication or unrecognized device error, log into pypi.org and test.pypi.org using a browser on this same machine, and click the resulting verification link in the email from that same browser.

### Options are remembered

Your package list, sort order, date zone, gap, theme, user and index persist in `~/.config/pypi-cleanup-tui/config.ini`, so a bare `pypi-cleanup-tui` starts with you previous options. `--read-only` deliberately does not persist.

```bash
pypi-cleanup-tui newpack   # newpack, then the stored names
pypi-cleanup-tui pack2     # an already stored name keeps its position
```

`?` lists the saved options and the file they came from.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
