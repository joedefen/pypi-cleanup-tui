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
pypi-cleanup-tui requests
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
| `D` | switch the `DATE` column between UTC and the local time zone |

A marked release shows `✘` in the `DEL` column and its remaining cells are
dimmed; the marker itself stays plain so it is still easy to read.  While
anything is marked, the releases that will be kept are drawn in the success
colour, so both halves of the decision are visible at once.

The column titles sit in a third, dim header line above the table (with no rule
under it), and the `DATE` title names the zone in force, e.g. `DATE (UTC)` or
`DATE (EDT)` after pressing `D`.  This is selection only: nothing is deleted
yet.

`--dump` prints the same table without the interactive interface:

```bash
pypi-cleanup-tui requests --dump
```

## Development

The checkout's `.venv` is built by `bt`, which installs the package editable
together with the `dev` extra (pytest, ruff, build and twine):

```bash
bt penv        # from the repository root; `bt penv pypi-cleanup-tui` elsewhere
```

Run the source tree without installing anything:

```bash
./runner requests          # the interactive table
./runner requests --dump   # the plain table
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
