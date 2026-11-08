# pypi-cleanup-tui: working on the source tree

This is the developer companion to [`README.md`](../README.md), which documents
the tool for its users. Here we document the two things a maintainer needs and a
user does not: the **test gate** and the **release gate** (`./bless`).

This file lives in `tests/`, so its links point one directory up. The commands
assume the repository root, which is where the gate has to be run.

## Layout and single sources of truth

| Path | Owns |
| --- | --- |
| [`pypi_cleanup_tui/__init__.py`](../pypi_cleanup_tui/__init__.py) | `__version__`, and nothing else. The build backend reads it, `pypi-cleanup-tui --version` prints it, and `bless` reads the line without importing the package. |
| [`pypi_cleanup_tui/main.py`](../pypi_cleanup_tui/main.py) | The release-history model (`Release`, `CleanupTui`) and the command-line entry point. Deletion is still a future step; the interactive TUI will be layered here. |
| [`runner`](../runner) | The development launcher: runs `pypi_cleanup_tui.main` from this checkout as `__main__`, without installing anything and without claiming `~/.local/bin`. |
| [`pyproject.toml`](../pyproject.toml) | Name, description, keywords, `requires-python`, runtime dependencies, the `dev` extra, and the pytest, coverage, ruff and `[tool.bless]` configuration. |
| [`bless`](../bless) | The release gate, emitted verbatim from [`../../blessd/bless`](../../blessd/bless) by that repository's `build.py`. It holds no copy of this project's identity, and it is never edited here. |
| [`blessd/docs/release-strategy.md`](../../blessd/docs/release-strategy.md) | The release strategy every project shares: the branch model, the stages, the rehearsal, the credentials. This file documents only what is particular to `pypi-cleanup-tui`. |
| [`tests/inspect_dist.py`](inspect_dist.py) | The distribution inspector. `bless` refuses to upload a wheel and sdist it has not inspected with this file. |
| [`.gitignore`](../.gitignore) | Keeps gate artifacts (`build/`, `dist/`, `.coverage`, caches, `*.egg-info`) out of `git status`, because the gate refuses a dirty tree. |

The version lives in exactly one place. `pyproject.toml` declares
`dynamic = ["version"]`, and hatchling reads
[`pypi_cleanup_tui/__init__.py`](../pypi_cleanup_tui/__init__.py) through the
`[tool.hatch.version]` regex source. A `X.Y.Z.99.N` rehearsal rewrites that line
only inside a throwaway copy.

The package is at the repository root, not under `src/`. `bless` resolves the
package (and the inspector) relative to its own directory, so the flat layout is
what lets the gate read this tree.

Only one `[tool.bless]` setting is written out: `branches`, naming the branches
`publish` releases from. The distribution name comes from `[project] name`
(`pypi-cleanup-tui`), the package from that name with `-` and `.` turned into
`_` (`pypi_cleanup_tui`), the console script from the first
`[project.scripts]` entry, and the inspector from `tests/inspect_dist.py`.

## Where the package lives

This tree follows the per-project environment model: the package lives in the
checkout, not in a shared site directory. Nothing here installs with
`pip --user`, so no project can shadow another's dependency.

| Thing | Where | Made by |
| --- | --- | --- |
| Editable package + this project's `dev` extra | `.venv/` in this tree | `bt penv` |
| The runnable console script | `~/.local/bin/pypi-cleanup-tui` | `bt edit` (a symlink into `.venv/bin`) or `bt test` / `bt prod` / `pipx install` (pipx's own venv) |
| A released artifact, isolated per app | `~/.local/share/pipx/venvs/pypi-cleanup-tui` | `bt test` / `bt prod` |

Two invariants:

1. `.venv` is the **editable/debug** environment: the interpreter VS Code
   selects and the one `./bless`, pytest and a debugger run under, so
   breakpoints land in the tree. It holds an editable install
   (`-e '.[dev]'`), never a built copy.
2. Exactly **one owner** of `~/.local/bin/pypi-cleanup-tui` at a time -- `bt
   edit` links it into `.venv/bin`, `bt test`/`bt prod` let pipx own it -- and
   no command claims it with `pip --user`.

`bt edit` and `bt test`/`bt prod` are a switch, not two installs: the last one
run owns the link. Do not `pipx install --editable` for this project; that
would create a second editable install `bt edit` does not manage. `bt status`
prints the owner, pipx's own record, the editable `.venv` and the VS Code
interpreter, plus any leftover copy from the old model that `bt clean` removes.

VS Code selects `.venv` (that is the `Editable .venv` path `bt status` prints);
to debug a released artifact instead, select
`~/.local/share/pipx/venvs/pypi-cleanup-tui/bin/python`. This project ships no
systemd unit. If one is added, name the stable path so a restart re-resolves
the link:

    ExecStart=%h/.local/bin/pypi-cleanup-tui

## The test gate

Build what the gate needs with `bt`, which puts the editable package plus the
`dev` extra into this tree's `.venv` (and the gate's tool floors with it):

    bt penv        # from the project root; `bt penv pypi-cleanup-tui` from elsewhere

`bless` runs every stage with `sys.executable`, so it has to be *that*
interpreter -- the one holding the dev extra. Activate the virtualenv first, or
start the gate by hand:

    .venv/bin/python ./bless

Then the commands `bless` runs, in the same order, on the same interpreter:

    python -m ruff check .
    python -m compileall -q pypi_cleanup_tui tests
    python -m pytest -q --cov=pypi_cleanup_tui --cov-report=term-missing

The coverage floor (90%) is enforced through
`[tool.coverage.report] fail_under`. It was set just below the measured number
when the gate was adopted; raise it when the number rises, never lower it.

The ruff selection is committed rather than inherited
(`[tool.ruff.lint] select = ["E4", "E7", "E9", "F", "I", "UP", "B"]`,
`target-version = "py310"`) so that no user or global configuration can change
what the gate enforces.

`pypi-cleanup-tui --version` is answered by the argument parser before any
network work, because the smoke stage of the release gate runs it as an
ordinary user.

## The release gate: `./bless`

`./bless` takes no arguments and has no flag that skips a stage. It always runs
everything, then prints what it has in hand and asks one question:

    ====> Enter test or publish or quit:

Only `test` and `publish` are accepted, spelled in full; anything else is asked
again. Enter, `quit` or Ctrl-C stops with nothing tagged, uploaded or pushed.

**Stages, in order**

1. **preflight** -- clean tree, the `vX.Y.Z` tag absent, `twine>=7` and
   `packaging>=26` present.
2. **index check** -- refuses if `__version__` is already on PyPI, printing
   every published version, before anything is built or uploaded.
3. **gates** -- the three commands above.
4. **build** -- into `build/bless-<version>/`, wiped first, so no older
   artifact can be sent by mistake.
5. **inspect** -- `tests/inspect_dist.py` against the wheel and the sdist.
6. **check** -- `twine check --strict` on both files.
7. **smoke** -- installs the built wheel into a throwaway venv and runs
   `pypi-cleanup-tui --version`, which must print the version being released.
8. **branch plan** -- refuses a detached HEAD, a branch that is not one of the
   release branches, a release branch missing locally or on origin, two
   branches that have diverged, or a push that would not fast-forward.

**`test`** is the rehearsal and never spends the working version. It copies the
tree to `build/bless-test-<version>/src`, rewrites `__version__` to
`X.Y.Z.99.N` (99 keeps it clear of real releases; `N` is one past the highest
suffix TestPyPI already holds for that base), builds, inspects and smoke-tests
the copy, and uploads only to `test.pypi.org`. No tag, no branch, no push.

**`publish`** fast-forwards the release branches to one commit, tags `vX.Y.Z`,
uploads the two inspected files to PyPI, verifies the index, and pushes those
branches and the tag.

**Credentials** are resolved per index -- `TWINE_PASSWORD` for PyPI,
`TWINE_TESTPYPI_PASSWORD` for TestPyPI, each overruling the `~/.pypirc` section
whose `repository` matches that index's upload URL -- so a PyPI token is never
spent on a rehearsal.

There is no CI publish job, on purpose: the upload is irreversible and is run by
the owner from the development tree. CI stays a gate.

## The branch model is a setting, not a convention

`[tool.bless] branches` is `["main"]` here: one release branch, nothing aligned,
and `publish` pushes `main` and the tag. `["main", "dev"]` is the default for a
project with a development branch; this project commits to the trunk, so a
release needs no second branch.

Either way the gate refuses a branch it was not told about, a branch it has to
push that is missing on origin, two branches that have diverged, and a push that
would not fast-forward. What a single branch cannot do is notice that a
development branch was left behind: merging `dev` into `main` stays your job,
and the pair exists to make it the gate's job instead.

Switching to the pair is one line in `pyproject.toml` plus the branch itself:

    git branch dev
    git push -u origin dev

## What the inspector asserts

[`tests/inspect_dist.py`](inspect_dist.py) is the one implementation, used by
`bless` and, once CI is wired up, by CI; expectations are read from
`pyproject.toml` and the package, never from the artifact under test.

* **wheel** -- `Name`, `Version`, `Summary`, `Requires-Python`, `Keywords`,
  `License-Expression` and the *runtime* `Requires-Dist` names match
  `pyproject.toml`; every declared `license-files` entry is listed in
  `License-File`; every `pypi_cleanup_tui/*.py` is present; a `LICENSE` is
  carried; no `tests/`, no `.venv`, no `__pycache__`, no `.pyc`.
* **sdist** -- carries `pyproject.toml`, `README.md`, `LICENSE`,
  `pypi_cleanup_tui/__init__.py` and `pypi_cleanup_tui/main.py`; the
  `__version__` inside the sdist equals the artifact version; no venv or
  bytecode.

Run it by hand on any built pair:

    python tests/inspect_dist.py dist/pypi_cleanup_tui-1.0.0-py3-none-any.whl \
                                dist/pypi_cleanup_tui-1.0.0.tar.gz

## Releasing, in three steps

1. Bump `__version__` in
   [`pypi_cleanup_tui/__init__.py`](../pypi_cleanup_tui/__init__.py) and commit.
2. Run `./bless`. The gate runs in full.
3. Answer `test` to rehearse on TestPyPI, then run `./bless` again and answer
   `publish` -- or go straight to `publish`.

## Notes on this adoption

* This section is one run of
  [`../../blessd/docs/adopting.md`](../../blessd/docs/adopting.md), which is the
  procedure written for whoever converts the next project. If the two ever
  disagree, that document is the procedure and this is the record of one run.
* [`bless`](../bless) is emitted, byte for byte, from
  [`../../blessd/bless`](../../blessd/bless) -- SHA-256
  `5de3ad1a4c0a3dc9e3ff52d864bbcd4791e2e2ba545fe08ed36eadef870577fe` when this
  was written. It is not edited here: a change is made in `blessd` and
  re-emitted with `python3 ../../blessd/build.py --into .`, which replaces the
  file and prints the new hash.
* That build also gives the gate a read-only query mode,
  `./bless --branch-plan`, which prints this tree's branch plan as JSON without
  running a single gate. `bt` asks with it, so the branch note `bt` prints and
  the plan `publish` obeys are the same answer from the same code.
* The environment was moved to the per-project model, which is the postscript
  of the same procedure and changes where the *package* lives, not what `bless`
  does. `bt penv` built `.venv` around the tree (editable `pypi-cleanup-tui`
  plus the `dev` extra). [`runner`](../runner) runs the source tree as
  `__main__` without installing anything, and no entry point is installed on
  the development machine unless `bt edit` or a release claims it.
* The project needed six things for the gate: a flat layout (the package moved
  from `src/pypi_cleanup_tui/` to `pypi_cleanup_tui/`), one version location
  (`dynamic = ["version"]` with `[tool.hatch.version]`), an inspector, the
  `dev` extra with `build`, `twine>=7` and `packaging>=26`, a console script
  that answers `--version`, and a branch model -- here `branches = ["main"]`.
  The runtime `packaging` floor rose from `>=23` to `>=26` to match the gate's
  own floor, and the licence metadata moved to the PEP 639 `license` expression
  with `license-files`.
* [`tests/test_bless.py`](test_bless.py) pins the identity this tree derives and
  the inspector it uploads behind; what the gate itself does -- branch plan,
  refusals, prompt, index check, emitter -- is tested once, in
  [`../../blessd/tests/test_bless.py`](../../blessd/tests/test_bless.py).
  [`tests/test_release_model.py`](test_release_model.py) covers the release
  model and the command-line entry point this project owns.
* CI is not wired up yet. When it is, it must run the same three gate commands
  and the same inspector, never an equivalent.
