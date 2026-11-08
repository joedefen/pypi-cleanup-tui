> **UNDER DEVELOPMENT --- BE PATIENT**
# pypi-cleanup-tui

A terminal user interface (TUI) for cleaning up PyPI packages.

## Features

- Interactive terminal interface for managing PyPI packages
- Built with Python 3.10+

## Installation

```bash
pip install pypi-cleanup-tui
```

For development, install in editable mode:

```bash
git clone https://github.com/your-username/pypi-cleanup-tui.git
cd pypi-cleanup-tui
pip install -e .
```

## Usage

```bash
pypi-cleanup-tui requests            # one package
pypi-cleanup-tui pack1,pack2,pack3   # one comma separated list
pypi-cleanup-tui pack1 pack2 pack3   # ... or one argument each
pypi-cleanup-tui --host test pack1   # query test.pypi.org instead of pypi.org
pypi-cleanup-tui -u alice pack1      # the PyPI user, kept for the cleanup step
```

The release table opens in the terminal:

| Key | Action |
| --- | ------ |
| `q` | quit |
| `?` | open the help screen; `ESC` returns to the table |
| `x` | mark the picked release for deletion, then step down |
| `X` | mark the picked release and every release below it, then step up |
| `u` | unmark the picked release, then step down |
| `U` | unmark the picked release and every release below it, then step up |
| `z` | switch the `DATE` column between UTC and the local time zone |
| `s` | change the sort order (listed on the help screen only) |
| `d` | show the pending deletion count (placeholder; nothing is deleted yet) |

The second header line summarises the run: `User=...`, `[p]ack=...` and
`[h]ost=...`.  `User` is read-only and shows `n/a` until `-u` is given; `p` and
`h` are placeholders for actions still to come, and `host` shows the index key
(`pypi` or `test`), not its domain name.

A marked release shows `✘` in the `DEL` column and its remaining cells are
dimmed; the marker itself stays plain so it is still easy to read.  While
anything is marked, the releases that will be kept are drawn in the success
colour, so both halves of the decision are visible at once.

The column titles sit in a third, dim header line above the table (with no rule
under it), and the `DATE` title names the zone in force, e.g. `DATE (UTC)` or
`DATE (EDT)` after pressing `z`.  The sorted column carries a `*` before its
title: `*VERSION` by default, or `*DATE (UTC)` after `s` switches to upload-date
order.

The hint line reads `X:mark▼` / `Unmark▼` for the "this row and everything
below" keys, and leads with `del` once at least one release is marked.  Pressing
`d` then shows `To delete N versions [TODO]` in a two-second message box.  This
is selection only: nothing is deleted yet.

### Options are remembered

The user, the index, the package list, and the two settings the table itself
can change (`z` for the date zone, `s` for the sort order) are stored in
`~/.config/pypi-cleanup-tui/config.ini`.  Every option's default is the stored
value, so after the first run

```bash
pypi-cleanup-tui
```

re-opens the same package from the same index, with the same zone and order.
The package list is kept as one comma separated value -- which is why the two
spellings above are equivalent -- and the table still shows one package per
run, the first in the list.  The help screen (`?`) lists the saved options and
the file they came from.

## Development

The checkout's `.venv` is built by `bt`, which installs the package editable
together with the `dev` extra (pytest, ruff, build and twine):

```bash
bt penv        # from the repository root; `bt penv pypi-cleanup-tui` elsewhere
```

Run the source tree without installing anything:

```bash
./runner requests              # the interactive table
./runner --host test requests  # the same table, from test.pypi.org
```

`runner` executes [`pypi_cleanup_tui/main.py`](pypi_cleanup_tui/main.py) as
`__main__`, so live edits are picked up immediately. In the checkout's `.venv`,
use `.venv/bin/python ./runner`; the equivalent one-off is
`python -m pypi_cleanup_tui.main`. It installs nothing and does not touch
`~/.local/bin`.

Run the test gate with the same commands `./bless` runs, on that interpreter:

```bash
.venv/bin/python -m ruff check .
.venv/bin/python -m pytest -q --cov=pypi_cleanup_tui
```

Releases go through `./bless`, never through a hand-run build or upload; see
[`tests/README-DEV.md`](tests/README-DEV.md) for the gate, its stages and the
branch model.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
