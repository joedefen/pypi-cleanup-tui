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
pypi-cleanup-tui
```

## Development

The checkout's `.venv` is built by `bt`, which installs the package editable
together with the `dev` extra (pytest, ruff, build and twine):

```bash
bt penv        # from the repository root; `bt penv pypi-cleanup-tui` elsewhere
```

Run the source tree without installing anything:

```bash
./runner requests --dump
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
