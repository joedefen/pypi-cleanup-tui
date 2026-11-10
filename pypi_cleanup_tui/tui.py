"""Interactive terminal interface for pypi-cleanup-tui.

The window presents the release history fetched by
:class:`pypi_cleanup_tui.main.CleanupTui` as a table and lets the user mark the
releases to delete.  The marking itself is local; the one key that reaches
outside the process is ``d``, which hands the marked versions to
``pypi-cleanup``.  The hand-off runs it twice: a ``--query-only`` dry run
first, then -- once both questions are answered -- the ``--do-it`` deletion.

Three header lines sit above the table: the key hints, the package summary, and
the column titles.  The column titles live in the header rather than in the
body, so the pick can never land on them and every body row is a release.

Two gestures come from the workflow this table replaces:

* ``x`` marks the release under the pick and steps down, so a run of adjacent
  releases is marked with a run of keypresses.  ``u`` is its inverse and also
  steps down.
* ``X`` marks the release under the pick and every release below it -- "keep
  what is above this line" -- and then steps up, leaving the pick on the last
  release the cut keeps.  ``U`` is its inverse and also steps up.

While anything is marked, the releases that will survive are painted in the
``SUCCESS`` role; a marked row instead keeps its ``DEL`` cell plain (so the
marker stays legible) and dims the rest of the line.  The table therefore shows
both what is kept and what goes.

The hint line is built from fixed-width blocks: a block that does not apply is
replaced by spaces of exactly the same width, so a key appearing or
disappearing never shifts the keys to its right.  Which block is filled in
follows the row under the pick -- an unmarked row offers ``x``/``X``, a marked
one offers ``u``/``U`` instead -- and ``X`` and ``U`` are inert against a row
already in the state they would produce.

``z`` cycles the time zone used by the ``DATE`` column between UTC and the
machine's local zone; the ``DATE`` title names the zone in force.  The key also
works on the help screen, where the option list shows the value the table will
use.  ``s`` flips the table between version order and upload-date order, and the
sorted column carries a ``*`` before its title.  Both settings are stored as
soon as they change, so the next run opens the table the way this one left it;
the help screen lists the saved options.

``/`` opens an incremental search at the end of the hint line; the bare ``/``
is always shown, even with an empty pattern.  The pattern is a case-insensitive
regular expression (the same shape as vappman's filter) matched against the
version column; typing narrows the table, ``ENTER`` closes the pattern and
``ESC`` restores the text it started with.  A pattern that is empty -- or not
yet a valid expression, as while a character class is being typed -- leaves
the table unfiltered rather than flashing it empty.  Once the pattern is
closed, ``x``, ``X``, ``u`` and ``U`` act on the visible rows only.

``T`` opens the THEMES screen from the table or the help screen, where ``t``
cycles the color theme and ``ESC`` returns to the screen that opened it; ``t``
cycles the same list on the help screen too.  The theme key is listed on the
help screen only, not in the hint line.  The app's ``mono`` choice is not a
palette: it turns semantic color off, exactly like ``--no-color``, and the
choice is remembered for the next run just like the other saved options.

``d`` is advertised at the front of the hint line once anything is marked and
no pattern is in force: a filtered table can hide the releases a deletion would
act on.  Pressing it leaves curses -- the way vappman runs an external command
-- shows the ``pypi-cleanup`` command built from the marked versions, asks for
a dry run, shows what that run reports, and then asks before deleting for
real.  The whole history is the one marking that cannot go through:
``pypi-cleanup`` refuses to remove every release, so the newest one -- by
upload time, never by version number -- is unmarked first and the bare
terminal is told which version was given back.  A history holding that single
release answers with a ``Cannot delete the last remaining version.`` box that
dismisses itself after three seconds, and curses is never left at all.
Both questions take ``yes``, ``no``, or a bare ENTER, which chooses the
safe answer: the dry run is on by default and the deletion is off.  A deletion
that fails is offered again behind a ``RETRY:`` prompt until it succeeds or the
user declines.  A successful deletion is believed before it is re-verified: the
versions leave the table at once, and the re-query runs behind that local view,
because the index's CDN may keep serving the old history for up to fifteen
minutes.  While a deleted version is still listed it stays hidden, and the
summary line carries a bold ``STALE [12m]`` after ``host=``; a fetch that no
longer lists it clears both.  Every trace of the old view -- the marks, the
search pattern and the pick -- is dropped, so the refreshed history is what the
user sees when the final ENTER brings the table back.  A ``--read-only`` run
never offers ``d``: the hint block reads ``R/O`` instead, always.

Each ``(package, host)`` pair keeps a complete state for the run -- its rows and
marks, hidden versions, load status and last fetch time.  A pair that has never
loaded shows ``ERROR [12s]`` in the body, or ``NO PACKAGE [12s]`` when the index
reports no such package; no alert interrupts a first load.  A pair that loaded
before and then fails keeps its old table, becomes ``STALE [12m]`` and shows the
usual alert.  The state markers update as time passes.  Switching package or
index saves the pair on screen and restores the one being entered; a revisited
pair is fetched at once, except an error-state pair, which is retried only after
fifteen minutes unless ``f`` is pressed.

``f`` fetches the current package's history again without leaving the package,
which is how a release uploaded since the table was opened shows up.  The marks
in force survive the fetch: each marked version is put back on the row that
lists it in the refreshed history, because the decision was about a release, not
about the row it happened to sit on.  A version the index no longer lists has
nothing left to delete and stays gone.  A failed fetch is different: the old
table and its marks are restored and marked ``STALE``, so the user keeps the
view they had.  ``f`` is also how the ``STALE`` marker is settled: once the
index has caught up with a deletion the marker clears and a brief ``Fresh`` says
so, while a deleted version the index still lists keeps the marker.  The pick
starts over with the new table.  ``p`` and ``h`` switch to another pair and let
that pair's saved state decide what happens next.

``g`` is the stability filter, and it means something different on each screen:
on the help screen it rotates the gap -- 3, 7, 14, 30 or 60 days -- and on the
table it applies that gap, unmarking every marked release that no other release
followed within that many days.  A release that stayed current for the whole
gap is the one people actually installed, so the sweep keeps it; the newest
release counts as stable too, because nothing followed it at all.  The table
judges the whole history rather than the visible rows, the key only ever
unmarks, and a run starts with the gap at 30 days.  The gap is stored like the
other settings, so the next run applies the same one; the hint line carries the
value as ``gap30``, so the gap in force is always in view.

``P`` opens the working package list.  Every row carries a check mark once this
run has loaded the package on either host, its name, and one ``VERs``/``DELs``
pair per index; the pair for the index the table is using leads the row, above
it a line such as ``-- pypi --- -- test ---`` labels each pair.  A host that has
not loaded shows ``-`` in both of its columns.  The pick starts on the package
``p`` would show next, so ``ESC`` -- which opens the picked package in the table
and returns -- is one keypress from the table's package to the next one; with
the list emptied there is nothing to open, so ``ESC`` leaves the program
instead.  ``x`` removes the name from the list (the index keeps it), and ``?``
opens the help screen, whose ``ESC`` returns to the list.  The list is what the
command line remembers, and package arguments are cumulative: a run's names go
in front of the stored ones with duplicates dropped, keeping the first.
"""

from __future__ import annotations

import bisect
import curses
import os
import re
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING

from console_window import (
    BasicHelpScreen,
    ConsoleWindow,
    ConsoleWindowOpts,
    Context,
    Glyph,
    HeaderLine,
    IncrementalSearchBar,
    OptionSpinner,
    Screen,
    ScreenStack,
    Theme,
    appearance,
    semantic_attr,
)
from console_window import help as help_text

from pypi_cleanup_tui import totp
from pypi_cleanup_tui.main import (
    CLEANUP_TOOL,
    DEFAULT_GAP,
    DEFAULT_TOTP_METHOD,
    GAP_CHOICES,
    HOST_PYPI,
    HOST_TEST,
    HOSTS,
    LOCAL_MODE,
    MONO_THEME,
    SORT_BY_DATE,
    SORT_BY_VERSION,
    TOTP_AUTO,
    TOTP_EXPECT,
    TOTP_METHODS,
    TOTP_PRINT,
    UTC_MODE,
    ZONES,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable, Iterable, Mapping, Sequence
    from datetime import tzinfo
    from typing import TextIO

    from console_window.backend import RenderBackend

    from pypi_cleanup_tui.ini import IniManager
    from pypi_cleanup_tui.main import CleanupTui, Release

MAIN_ST = 0
HELP_ST = 1
THEME_ST = 2
PACKAGES_ST = 3
SCREEN_NAMES = ("MAIN", "HELP", "THEMES", "PACKAGES")

#: Every choice the picker cycles through.  ``mono`` is the app's pseudo-theme,
#: not a console-window palette; keeping it last makes ``t`` step from the final
#: palette into mono and wrap back to the first palette.
THEME_CHOICES = (*Theme.list_all(), MONO_THEME)

#: The states of one ``(package, host)`` release list.  ``LOADING`` is a
#: transient drawing state only and is never stored.
UNINITIALIZED = 'uninitialized'
LOADED = 'loaded'
ERROR = 'error'
STALE = 'stale'

#: Seconds before an error-state package is fetched again after it is revisited.
#: A pair that has never loaded is likely to keep failing, so switching back to
#: it inside this window shows the remembered error instead of hammering the
#: index.  ``f`` still forces a fetch.
ERROR_RETRY_SECONDS = 15 * 60

#: The narrow width an error description folds to, so the body stays readable
#: on a 40-column terminal.
ERROR_TEXT_WIDTH = 40

#: Marker drawn in the DEL column of a release that will be deleted.  It is
#: declared to the window as a glyph, so a terminal without the character draws
#: a plain ``x`` instead of losing the meaning of the column.
DEL_MARK = "✘"

#: Marker drawn in the untitled first column of the package list once this run
#: has loaded the package.  Declared as a glyph like DEL_MARK, so an ASCII
#: terminal draws a plain ``x`` instead of losing the column's meaning.
VISITED_MARK = "✓"

#: The "from here down" arrow in the hint line.  console-window already owns
#: this character as its ``alert_down`` glyph, so an ASCII terminal draws a
#: plain ``v`` without any registration here.
DOWN_MARK = "▼"

#: The ``d`` block of the hint line: the word it spells while deletion is on
#: offer.  The line reserves exactly this much room and blanks it otherwise, so
#: the blocks to its right never move.
DEL_HINT = "del"

#: The same block while the run is read-only.  It is deliberately as wide as
#: DEL_HINT, so a run that can never delete keeps the hint line's shape.
READ_ONLY_HINT = "R/O"

#: What the bare terminal is told when the marking covered the whole history.
#: ``pypi-cleanup`` will not leave a package with no release at all, so the
#: newest one is given back before the command is printed.  The version is
#: named because the row it was marked on is already out of sight.
UNMARKED_NEWEST_NOTICE = (
    'Automatically unmarked newest version ({version}); '
    'you cannot remove them all.'
)

#: The answer to a history that holds a single release: unmarking the newest
#: leaves nothing to hand off.  The box says why and dismisses itself, because
#: there is nothing here for the user to confirm.
LAST_VERSION_MESSAGE = 'Cannot delete the last remaining version.'

#: How long that box stays up before it goes away on its own.
LAST_VERSION_FLASH_SECONDS = 3.0

#: The prompt shown after the table has left curses for the deletion command.
#: The bare terminal has no window to draw in, so the line is decorated and set
#: off by blank lines to be unmistakable, the way vappman's does.
RETURN_PROMPT = "Press ENTER to return to the TUI"

#: The ``pypi-cleanup`` options that take a value.  The display quotes a flag's
#: value, so it has to know which words are values and which are switches.
VALUE_FLAGS = ('-u', '-t', '-p', '-r')

#: The mode switch appended to the command each phase runs with.  The command
#: printed before the first question omits it: it describes the deletion the
#: marked rows ask for, not either of the two runs that check it.
QUERY_ONLY = '--query-only'
DO_IT = '--do-it'

#: How the display lays a command out.  A continued line is indented under the
#: arguments of the first, and no line is longer than the width.
COMMAND_WIDTH = 78
COMMAND_INDENT = '   '

#: The variables ``pypi-cleanup`` reads its credentials from.  A value can be
#: scoped to one index by appending ``4PYPI`` or ``4TEST`` to the name, so the
#: test index's password never reaches the real one.  The TOTP secret is
#: deliberately absent: the tool has no variable for it and always prompts for
#: the six-digit code, which the TUI computes itself (see
#: :mod:`pypi_cleanup_tui.totp`).
CREDENTIAL_ENV_VARS = ('PYPI_CLEANUP_PASSWORD',)
CREDENTIAL_SUFFIXES = {HOST_PYPI: '4PYPI', HOST_TEST: '4TEST'}

#: Seconds pexpect waits for ``pypi-cleanup`` before giving up.  A deletion of
#: many releases can take minutes, so this is the hand-off's patience, not the
#: patience for one prompt.
EXPECT_TIMEOUT = 300

#: Ctrl+] (ASCII 29).  This is pexpect's default escape, stated explicitly so
#: a change in its default cannot silently take the choice away from the user.
EXPECT_ESCAPE = '\x1d'

#: The pattern pexpect waits for in ``auto`` mode.  It is deliberately
#: generous: a change from "Authentication code:" to "authentication code "
#: must still match, and the case is not part of the contract.
TOTP_PROMPT_PATTERN = r'(?i)authentication code[: ]'

#: Seconds between two blocks of the ``--totp-dump`` table.  The code itself
#: changes only every :data:`pypi_cleanup_tui.totp.TOTP_INTERVAL` seconds, so
#: three seconds keeps the countdown readable without scrolling the terminal.
TOTP_DUMP_INTERVAL = 3.0

#: Width of one index's group after its host name: ``": 123456 30s"``.  The
#: seconds are padded to two digits, so a group is the same width on every
#: block and the next host starts in the same column all the way down.
TOTP_GROUP_WIDTH = len(': ') + 6 + len(' ') + 2 + len('s')

#: The space between two indexes' groups on the dump line.  Modest on purpose:
#: the groups read apart without pushing the second host off an 80-cell line.
TOTP_GROUP_GAP = '    '

#: The block-quote instructions shown before an ``expect`` run.  The banner is
#: printed before pexpect starts, so the user knows the escape is available
#: while the password and device prompts are answered normally.  The bare
#: ``|`` lines above and below set the quote apart from the command text.
EXPECT_BANNER = (
    '|\n'
    '| About to run pypi-cleanup...\n'
    '| When prompted for "Authentication code:", press Ctrl+] to have this '
    'TUI supply the code automatically.\n'
    '|'
)

#: The variable that names the account for one index.  Its scoped form wins
#: over ``-u``, because a flag cannot be scoped to the index in use.
USER_ENV_VAR = 'PYPI_CLEANUP_USER'

#: The two questions asked between the runs.  The dry run defaults to yes
#: because it only reports; the destructive run defaults to no.
DRY_RUN_PROMPT = 'Dry-run [Yes OR no]?'
DELETE_PROMPT = "Del {count} Versions of '{package}'  [yes OR No]?"

#: The deletion question again, after a run failed.  It keeps the exact shape
#: of DELETE_PROMPT so a retry asks about the same versions the first attempt
#: did; only the word in front marks it as another try.
RETRY_PROMPT = 'RETRY: ' + DELETE_PROMPT

#: Width of the gap number in the hint line's ``gap30`` block.  The gap is one
#: or two digits, so the number is padded and the blocks to its right never
#: move when it changes.
GAP_HINT_WIDTH = 2

#: Column widths.  ``DATE`` is ``YYYY/MM/DD HH:MM`` (16 cells); ``DAYS`` is
#: right-aligned because it is the only numeric column.
DEL_WIDTH = 3
DATE_WIDTH = 16
DAYS_WIDTH = 5
VERSION_GAP = 2

#: The package list's untitled check column and its two numeric columns.  Each
#: host owns a ``VERs``/``DELs`` pair; the pair is the fixed width a host label
#: has to span.
CHECK_WIDTH = 1
VERS_WIDTH = 5
DELS_WIDTH = 5
PACKAGE_GROUP_WIDTH = VERS_WIDTH + 1 + DELS_WIDTH
PACKAGE_TITLE = "PACKAGE"

#: The shape of the index's "no such package" answer.  A failure that matches
#: it is shown as a single ``NO PACKAGE`` line rather than a full description.
MISSING_PACKAGE_PATTERN = re.compile(
    r"package .+ was not found on .+", re.IGNORECASE)

#: The word the package list puts at the start of its first header line, so the
#: screen names itself before listing the keys it accepts.
PACKAGES_TITLE = "PACKAGES"


def cleanup_command(
    cleanup: CleanupTui,
    versions: Sequence[str],
    mode: str | None = None,
) -> list[str]:
    """The ``pypi-cleanup`` command line that deletes *versions*.

    The marked versions become one anchored regular expression, so the command
    names exactly the rows the table showed and nothing else; ``re.escape``
    keeps a version identifier's dots and hyphens literal.  ``pypi-cleanup``
    wants a user, the index URL and a package, and the user falls back to the
    login name when no ``-u`` was given.  *mode* is the phase switch --
    ``--query-only`` or ``--do-it`` -- and is omitted for the summary command
    printed before the first question.
    """
    pattern = '^(' + '|'.join(re.escape(version) for version in versions) + ')$'
    command = [CLEANUP_TOOL]
    if mode:
        command.append(mode)
    command += [
        '-y',
        '-u', cleanup_user(cleanup),
        '-t', cleanup.host_url,
        '-p', cleanup.package,
        '-r', pattern,
    ]
    return command


def scoped_user(host: str,
                environ: Mapping[str, str] | None = None) -> str:
    """The account ``PYPI_CLEANUP_USER4...`` names for *host*, or ``''``."""
    env = os.environ if environ is None else environ
    suffix = CREDENTIAL_SUFFIXES.get(host)
    return env.get(USER_ENV_VAR + suffix, '') if suffix else ''


def cleanup_user(cleanup: CleanupTui,
                 environ: Mapping[str, str] | None = None) -> str:
    """The account ``pypi-cleanup`` should act as.

    ``PYPI_CLEANUP_USER4PYPI`` and ``PYPI_CLEANUP_USER4TEST`` name the account
    for one index and win over ``-u``: the flag cannot be scoped, so a single
    run that switches index would otherwise carry one name to both.  With the
    host's variable unset or empty, ``-u`` wins and the login name is last.
    """
    env = os.environ if environ is None else environ
    return (scoped_user(cleanup.host_key, env)
            or cleanup.user
            or env.get('USER', ''))


def credential_env(host: str,
                   environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Map each credential variable to the host-scoped one that supplies it.

    ``PYPI_CLEANUP_PASSWORD4PYPI`` and ``PYPI_CLEANUP_PASSWORD4TEST`` keep the
    two indexes' passwords apart.  Only a non-empty variable scoped to *host*
    is mapped; with none set the mapping is empty and the base variables are
    inherited unchanged.  The mapping holds variable names, never values, so it
    is safe to print above the command.  The TOTP secret is not here: the tool
    does not read one, so the TUI computes the code instead.
    """
    env = os.environ if environ is None else environ
    suffix = CREDENTIAL_SUFFIXES.get(host)
    if suffix is None:
        return {}
    return {
        base: base + suffix
        for base in CREDENTIAL_ENV_VARS
        if env.get(base + suffix)
    }


def cleanup_env(host: str,
                environ: Mapping[str, str] | None = None) -> dict[str, str] | None:
    """The environment for a ``pypi-cleanup`` run, or ``None`` to inherit.

    Each scoped variable's value is copied into the base name the tool reads,
    so the child sees ``PYPI_CLEANUP_PASSWORD`` whichever index the value was
    stored for; the rest of the environment passes through untouched.  When
    nothing is mapped, inheriting the parent's environment says the same thing,
    which is why the answer is ``None`` rather than a copy.
    """
    env = os.environ if environ is None else environ
    mapped = credential_env(host, env)
    if not mapped:
        return None
    return {**env, **{base: env[scoped] for base, scoped in mapped.items()}}


def totp_secret(host: str,
                environ: Mapping[str, str] | None = None) -> str:
    """The authenticator secret that applies to *host*, or ``''``.

    ``PYPI_CLEANUP_TOTP_SECRET4PYPI`` and ``...4TEST`` keep the two indexes'
    secrets apart and win over the unscoped variable, which is the fallback for
    a user with only one account.  This secret is read by the TUI itself:
    ``pypi-cleanup`` has no variable for it and always prompts for the code.
    """
    env = os.environ if environ is None else environ
    suffix = CREDENTIAL_SUFFIXES.get(host)
    scoped = env.get(totp.TOTP_SECRET_ENV_VAR + suffix, '') if suffix else ''
    return scoped or env.get(totp.TOTP_SECRET_ENV_VAR, '')


def show_authentication_code(host: str,
                             environ: Mapping[str, str] | None = None) -> None:
    """Print the code ``pypi-cleanup`` will prompt for, and its lifetime.

    The tool has no variable for the TOTP secret -- it always asks for the
    six-digit value -- so the secret the TUI holds is turned into the current
    code here, just before the child starts.  A code with only a few seconds
    left is not printed: the wait takes the next one, so the user has room to
    type it at the prompt.  With no secret set nothing is printed and the tool
    prompts as usual.  A malformed secret is reported rather than raised, so
    the deletion can still reach its own prompt.
    """
    secret = totp_secret(host, environ)
    if not secret:
        return
    try:
        code, remaining = totp.code_with_room(secret)
    except ValueError as error:
        print(f'warning: {error}')
    else:
        print(totp.format_code(code, remaining))


def no_totp_secrets_message() -> str:
    """The advice ``--totp-dump`` prints when the environment holds no secret."""
    names = [totp.TOTP_SECRET_ENV_VAR]
    names += [totp.TOTP_SECRET_ENV_VAR + suffix
              for suffix in CREDENTIAL_SUFFIXES.values()]
    return (f'no TOTP secrets are set ({", ".join(names)}), '
            'so there is nothing to dump.')


def totp_dump_rows(
    environ: Mapping[str, str] | None = None,
) -> list[tuple[str, str]]:
    """The secret in force for each index, as ``(host, secret)`` pairs.

    Each index resolves its secret the way a run does: the ``4PYPI``/``4TEST``
    form first, then the unscoped variable.  An index with neither is left out,
    so the dump shows only the hosts it can actually supply a code for.
    """
    env = os.environ if environ is None else environ
    rows: list[tuple[str, str]] = []
    for host in HOSTS:
        secret = totp_secret(host, env)
        if secret:
            rows.append((host, secret))
    return rows


def format_totp_group(host: str, secret: str, moment: float) -> str:
    """One index's ``host: code 30s`` group on the dump line.

    A secret that cannot be computed puts its error where the code would be
    instead of ending the dump.
    """
    try:
        code, remaining = totp.code_and_remaining(secret, moment)
    except ValueError as error:
        return f'{host}: {error}'
    return f'{host}: {code} {remaining:>2}s'


def format_totp_line(moment: float, rows: Sequence[tuple[str, str]]) -> str:
    """The dump's one line: the clock, then each index's group side by side.

    The clock leads the line so it reads as one moment in time, and every group
    is padded to :data:`TOTP_GROUP_WIDTH` past its host name, so the hosts and
    codes sit in the same columns on every block.
    """
    clock = time.strftime('%H:%M:%S', time.localtime(moment))
    groups = []
    for host, secret in rows:
        width = len(host) + TOTP_GROUP_WIDTH
        groups.append(format_totp_group(host, secret, moment).ljust(width))
    return f'{clock}  {TOTP_GROUP_GAP.join(groups)}'.rstrip()


def dump_totp_codes(
    environ: Mapping[str, str] | None = None,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
    out: TextIO | None = None,
) -> int:
    """Print the code in force for each index, a line every three seconds.

    One line per refresh carries the clock and a group per index, so the same
    columns can be read straight down the terminal.  With no secret at all
    there is nothing to dump: the message names the variables and the status is
    ``1``.  Ctrl-C is the way out, so it ends the loop and returns ``0``
    instead of raising.
    """
    rows = totp_dump_rows(environ)
    if not rows:
        print(no_totp_secrets_message(), file=sys.stderr)
        return 1
    stream = sys.stdout if out is None else out
    try:
        while True:
            print(format_totp_line(clock(), rows), file=stream)
            stream.flush()
            sleep(TOTP_DUMP_INTERVAL)
    except KeyboardInterrupt:
        return 0


def _quoted(value: str) -> str:
    """Show *value* in single quotes, always, the way the display wants it."""
    return "'" + value.replace("'", "'\\''") + "'"


def _split_alternatives(pattern: str) -> list[str]:
    """Break *pattern* after every unescaped ``|``, keeping the pipe.

    A pipe written by ``re.escape`` follows a backslash and stands for a
    literal ``|`` in a version, so it never becomes a break point.
    """
    segments: list[str] = []
    current = ''
    escaped = False
    for char in pattern:
        current += char
        if escaped:
            escaped = False
        elif char == '\\':
            escaped = True
        elif char == '|':
            segments.append(current)
            current = ''
    if current:
        segments.append(current)
    return segments


def _wrap_pattern(pattern: str, width: int) -> list[str]:
    """Split *pattern* after ``|`` so each piece fits in *width* characters."""
    pieces: list[str] = []
    current = ''
    for segment in _split_alternatives(pattern):
        if current and len(current) + len(segment) > width:
            pieces.append(current)
            current = segment
        else:
            current += segment
    if current:
        pieces.append(current)
    return pieces


def format_command(command: Sequence[str], width: int = COMMAND_WIDTH,
                   env: Mapping[str, str] | None = None) -> str:
    """Lay *command* out the way the hand-off prints it.

    The values are always quoted, a value too long for one line is broken
    after its ``|`` alternations, and no ``\\`` is printed at the end of a
    line.  The result is a description of the run, not a line to paste into a
    shell: it omits the phase switch, and a split line would not survive a
    copy.  ``pypi-cleanup`` is handed the argument list itself, so the printed
    text is never what runs.

    *env* is the :func:`credential_env` mapping; each pair is printed above the
    command as ``BASE=SCOPED``, naming where the value comes from without
    printing the value.
    """
    lines: list[str] = []
    env_lines = [f'{base}={scoped}' for base, scoped in (env or {}).items()]
    if env_lines:
        lines.append('+ ' + env_lines[0])
        lines.extend(COMMAND_INDENT + text for text in env_lines[1:])
        line = COMMAND_INDENT + command[0]
    else:
        line = '+ ' + command[0]

    def add_word(word: str) -> None:
        nonlocal line
        if len(line) + 1 + len(word) <= width:
            line += ' ' + word
        else:
            lines.append(line)
            line = COMMAND_INDENT + word

    def add_value(flag: str, value: str) -> None:
        nonlocal line
        quoted = _quoted(value)
        unit = f'{flag} {quoted}'
        if len(COMMAND_INDENT) + len(unit) <= width:
            # The flag and its value stay together, even when they move to a
            # continuation line, so a reader sees which value belongs to what.
            if len(line) + 1 + len(unit) <= width:
                line += ' ' + unit
            else:
                lines.append(line)
                line = COMMAND_INDENT + unit
            return
        # Too long for any single line: open the quotes on the flag's line and
        # break the pattern after its pipes, indenting the pieces to match.
        lines.append(line)
        available = width - len(COMMAND_INDENT) - len(flag) - 3
        pieces = _wrap_pattern(value, available)
        line = f"{COMMAND_INDENT}{flag} '{pieces[0]}"
        for piece in pieces[1:]:
            lines.append(line)
            line = COMMAND_INDENT + piece
        line += "'"

    index = 1
    while index < len(command):
        token = command[index]
        if token in VALUE_FLAGS and index + 1 < len(command):
            add_value(token, command[index + 1])
            index += 2
        else:
            add_word(token)
            index += 1
    lines.append(line)
    return '\n'.join(lines)


def ask_yes_no(question: str, default: bool) -> bool:
    """Ask *question* until the answer is ``yes``, ``no``, or a bare ENTER.

    The answer is compared case-insensitively and must be exactly one of the
    three; anything else re-asks.  A bare ENTER takes *default*, which lets the
    harmless dry run start with ENTER and keeps the destructive run unarmed.
    """
    while True:
        answer = input(f'====> {question} ').strip().lower()
        if not answer:
            return default
        if answer == 'yes':
            return True
        if answer == 'no':
            return False


def run_cleanup(command: Sequence[str],
                env: Mapping[str, str] | None = None) -> int:
    """Run *command* on the bare terminal and return its exit status.

    The argument list goes to :func:`subprocess.call` without a shell, so the
    pattern :func:`cleanup_command` built reaches ``pypi-cleanup`` exactly as
    written -- the backslashes ``re.escape`` added are not eaten by a shell.  A
    missing executable is reported rather than raised, so the table can still
    come back.  *env* is :func:`cleanup_env`'s answer; ``None`` inherits the
    parent's environment.
    """
    try:
        return subprocess.call(list(command), env=env)
    except OSError as error:
        print(f'error: could not run {CLEANUP_TOOL}: {error}')
        return 1


class ExpectUnavailable(RuntimeError):
    """pexpect could not be imported or could not start the child.

    It is raised only before the child has run, so the caller can safely fall
    back to printing the code and starting ``pypi-cleanup`` normally.  A
    failure after the child has started is reported as an exit status instead;
    re-running the deletion there could repeat it.
    """


def _start_pexpect(command, secret, env, pexpect_module):
    """Resolve pexpect, validate the secret, and spawn the child.

    Everything here happens before the child runs, so any failure is an
    :class:`ExpectUnavailable` the caller can safely answer by falling back to
    the plain subprocess.
    """
    module = pexpect_module
    if module is None:
        try:
            import pexpect as module
        except ImportError as error:
            raise ExpectUnavailable(error) from error
    try:
        totp.code_and_remaining(secret)
    except ValueError as error:
        raise ExpectUnavailable(error) from error
    try:
        child = module.spawn(
            command[0],
            list(command[1:]),
            encoding='utf-8',
            timeout=EXPECT_TIMEOUT,
            env=env,
        )
    except (OSError, module.ExceptionPexpect) as error:
        raise ExpectUnavailable(error) from error
    return module, child


def _run_pexpect(command, secret, env, pexpect_module, interactive):
    """Shared body of the ``expect`` and ``auto`` methods.

    *interactive* gives the terminal to the child until Ctrl+]; otherwise the
    child's output up to the generous prompt pattern is echoed before the code
    is sent.  A failure after the child has started is reported as an exit
    status, never by starting the command again.
    """
    module, child = _start_pexpect(command, secret, env, pexpect_module)
    try:
        if interactive:
            child.interact(escape_character=EXPECT_ESCAPE)
        else:
            child.expect(TOTP_PROMPT_PATTERN)
            if child.before:
                print(child.before, end='')
            if child.after:
                print(child.after, end='')
        code, _remaining = totp.code_with_room(secret)
        child.sendline(code)
        child.expect(module.EOF)
        if child.before:
            print(child.before, end='')
    except module.TIMEOUT:
        print(f'warning: {CLEANUP_TOOL} did not finish within '
              f'{EXPECT_TIMEOUT}s')
    except (module.EOF, OSError) as error:
        print(f'warning: pexpect could not supply the code: {error}')
    finally:
        child.close()
    return child.exitstatus if child.exitstatus is not None else 1


def run_cleanup_expect(command: Sequence[str], secret: str,
                       env: Mapping[str, str] | None = None,
                       pexpect_module=None) -> int:
    """Run under pexpect, handing the terminal back at Ctrl+].

    The child owns the terminal until the user presses Ctrl+], so the password
    and device prompts are answered normally.  At the ``Authentication code:``
    prompt the escape returns control here: a code with room left is generated
    and sent, then the child is allowed to finish.  Everything the child prints
    after the escape is echoed once it exits.
    """
    return _run_pexpect(
        command, secret, env, pexpect_module, interactive=True)


def run_cleanup_auto(command: Sequence[str], secret: str,
                     env: Mapping[str, str] | None = None,
                     pexpect_module=None) -> int:
    """Run under pexpect without ever giving the terminal to the user.

    This is for the run whose password is already supplied: the child's output
    is echoed, pexpect waits for the generous authentication-code prompt, and
    the code is sent.  If another prompt appears first, the wait times out
    rather than guessing at input; ``expect`` is the mode for that case.
    """
    return _run_pexpect(
        command, secret, env, pexpect_module, interactive=False)


def summary_line(action: str, package: str, status: int) -> str:
    """The one line printed under a finished ``pypi-cleanup`` run."""
    if status == 0:
        return f'{action} finished for {package!r}.'
    return f'{action} failed for {package!r} (exit status {status}).'


def press_enter(message: str = RETURN_PROMPT) -> None:
    """Wait for ENTER on the bare terminal, below two blank lines.

    The prompt is the last thing printed before curses returns, so it has to
    work without the window; a test replaces this function wholesale rather
    than feeding the real standard input.
    """
    input(f'\n\n===== {message} ====> ')


def _reset_terminal() -> None:
    """Clear the terminal curses has just handed back and fix its settings.

    ``stty sane`` undoes anything a subprocess left behind; it is harmless when
    stdin is not a terminal, which is how the headless tests see it.
    """
    os.system('clear; stty sane')


def is_missing_package_error(exc: BaseException) -> bool:
    """Whether *exc* is the index's "package not found" answer."""
    return (
        isinstance(exc, LookupError)
        and MISSING_PACKAGE_PATTERN.search(str(exc)) is not None
    )


def compact_delta_time(start: float, end: float | None = None) -> str:
    """A compact age for a state marker: ``12s``, ``42m`` or ``3h``.

    The unit changes only when the next one can say the same thing more
    compactly: seconds up to 99, whole minutes up to 99, then whole hours.  A
    negative difference (a clock skewed into the future) reads as ``0s``.  The
    caller passes two wall-clock timestamps, and :func:`time.time` supplies the
    end when it is omitted.
    """
    if end is None:
        end = time.time()
    delta_sec = max(int(end - start), 0)
    if delta_sec < 100:
        return f'{delta_sec}s'
    delta_min = delta_sec // 60
    if delta_min < 100:
        return f'{delta_min}m'
    return f'{delta_sec // 3600}h'


def days_since(uploaded: datetime, now: datetime | None = None,
               mode: str = UTC_MODE, local_tz: tzinfo | None = None) -> int:
    """Calendar days between *uploaded* and *now*, ignoring the time of day.

    The dates are compared, not the elapsed hours, so ``1`` always means
    yesterday: a release uploaded at 23:59 is one day old at 00:01 the next
    day, not zero.  Both timestamps are read in the zone *mode* selects, so the
    count agrees with the DATE cell printed beside it: 03:00 UTC on 1 May is
    23:00 on 30 April in EDT and counts as one day old, not zero.  A clock
    skewed into the future would otherwise produce a negative count; the table
    shows ``0`` for a date that is not before the current one.
    """
    now = now or datetime.now(UTC)
    if mode == LOCAL_MODE:
        uploaded = uploaded.astimezone(local_tz)
        now = now.astimezone(local_tz)
    return max((now.date() - uploaded.date()).days, 0)


def days_ago(release: Release, now: datetime | None = None,
             mode: str = UTC_MODE, local_tz: tzinfo | None = None) -> int:
    """Calendar days between *release*'s upload date and *now*'s date.

    The zone argument is the same one that formats the table, so the count
    follows the ``z`` switch.
    """
    return days_since(release.uploaded, now, mode, local_tz)


def zone_abbrev(mode: str, now: datetime | None = None,
                local_tz: tzinfo | None = None) -> str:
    """Short name of the zone *mode* selects, e.g. ``UTC`` or ``EDT``.

    ``local_tz`` exists for tests: passing it makes the local abbreviation
    deterministic instead of depending on the machine running the suite.
    """
    if mode != LOCAL_MODE:
        return UTC_MODE
    return (now or datetime.now()).astimezone(local_tz).tzname() or LOCAL_MODE


def format_row(release: Release, now: datetime | None = None,
               mode: str = UTC_MODE, local_tz: tzinfo | None = None) -> str:
    """Format one release as a DEL/DATE/DAYS/VERSION body row."""
    marker = DEL_MARK if release.delete else ""
    uploaded = release.uploaded
    if mode == LOCAL_MODE:
        uploaded = uploaded.astimezone(local_tz)
    return (
        f"{marker:^{DEL_WIDTH}} "
        f"{uploaded:%Y/%m/%d %H:%M} "
        f"{days_since(release.uploaded, now, mode, local_tz):>{DAYS_WIDTH}}"
        f"{' ' * VERSION_GAP}{release.version}"
    )


def column_header(mode: str = UTC_MODE, sort: str = SORT_BY_VERSION,
                  now: datetime | None = None,
                  local_tz: tzinfo | None = None) -> str:
    """Format the column-label line, naming the zone and the active sort.

    The sorted column is marked with a ``*`` before its title: ``DATE`` when the
    table is ordered by upload time, ``VERSION`` otherwise.  The star fits
    inside the fixed width of whichever field it marks, so the columns below it
    never move.
    """
    date_label = f"DATE ({zone_abbrev(mode, now, local_tz)})"
    if sort == SORT_BY_DATE:
        date_label = f"*{date_label}"
        version_label = "VERSION"
    else:
        version_label = "*VERSION"
    return (
        f"{'DEL':<{DEL_WIDTH}} "
        f"{date_label:<{DATE_WIDTH}} "
        f"{'DAYS':>{DAYS_WIDTH}}"
        f"{' ' * VERSION_GAP}{version_label}"
    )


def unmark_newest_marked(releases: Sequence[Release]) -> Release | None:
    """Give back the newest release of a fully marked history.

    ``pypi-cleanup`` refuses to delete every release of a package, so a table
    with its whole history marked answers that wish by keeping one release:
    the one uploaded last, which is the version the index shows as current.
    Upload time decides, never the version identifier -- ``1.0.10`` sorts
    above ``1.0.9`` as a version, but a release published last week is still
    newer than one uploaded yesterday, and a tie keeps table order.

    A partly marked history is left untouched and answers ``None``, so the
    caller hands off exactly the marks it was given.  When the newest release
    was also the only one, the caller is left with nothing to delete.
    """
    if not releases or not all(release.delete for release in releases):
        return None
    newest = max(releases, key=lambda release: release.uploaded)
    newest.delete = False
    return newest


def stable_releases(versions: Sequence[Release], gap: int,
                    mode: str = UTC_MODE,
                    local_tz: tzinfo | None = None) -> list[Release]:
    """The marked releases that stayed current for at least *gap* days.

    A release is stable when the next release in the history arrived more than
    *gap* days after it, or never did because it is still the newest.  Those are
    the releases people actually installed, which is why the table's ``g``
    unmarks exactly these and so keeps them.  The comparison runs in upload
    order, whatever order the table is sorted in, and every release in the
    history counts: what was published next is a fact about the package, not
    about the marking.  Releases that are not marked are never returned.

    The count is in calendar days, in the zone *mode* selects, the same unit
    the ``DAYS`` column prints: a release followed the next morning has been
    current for one day, not for a few hours.  Moving ``z`` can therefore move
    a borderline release across the gap, exactly as it moves its ``DAYS``.
    """
    times = sorted({release.uploaded for release in versions})
    stable: list[Release] = []
    for release in versions:
        if not release.delete:
            continue
        index = bisect.bisect_right(times, release.uploaded)
        if index == len(times):
            stable.append(release)
        elif days_since(release.uploaded, times[index], mode, local_tz) > gap:
            stable.append(release)
    return stable


@dataclass
class PackageState:
    """Everything this run knows about one ``(package, host)`` release list.

    The state owns both the table view and the package list's totals, because
    both describe the same index resource.  ``releases`` is the durable copy:
    :attr:`CleanupApp.cleanup` points at it while the pair is on screen, and a
    failed fetch restores it instead of emptying the table.  ``visited`` and
    ``version_count`` are derived, so a never-loaded pair cannot pretend to
    know either a check mark or a count.
    """

    #: One of :data:`UNINITIALIZED`, :data:`LOADED`, :data:`ERROR`,
    #: :data:`STALE`.
    status: str = UNINITIALIZED
    #: The last known release list, including each row's delete mark.
    releases: list[Release] = field(default_factory=list)
    #: Versions this run deleted that the index has not yet stopped listing.
    hidden_versions: set[str] = field(default_factory=set)
    #: Wall-clock time the most recent fetch attempt started.
    last_attempt_at: float | None = None
    #: The message a failed fetch would have shown in the old alert.
    error_message: str = ''
    #: Whether the failure was the index's "package not found" answer.
    no_package: bool = False
    #: Versions removed from this pair during this run.
    deleted: int = 0

    @property
    def visited(self) -> bool:
        """True once a fetch for this pair has succeeded."""
        return self.status in (LOADED, STALE)

    @property
    def version_count(self) -> int:
        """How many releases the last successful view holds."""
        return len(self.releases)


def package_width(packages: Sequence[str]) -> int:
    """The PACKAGE column width: the longest name, but never under the title."""
    return max([len(PACKAGE_TITLE), *(len(name) for name in packages)])


def package_host_order(current_host: str) -> tuple[str, str]:
    """The two hosts with *current_host* first, so its columns lead the row."""
    other = HOST_TEST if current_host == HOST_PYPI else HOST_PYPI
    return (current_host, other)


def host_group_label(host: str) -> str:
    """A ``-- host ---`` label spanning one VERs/DELs pair.

    The label is centered in :data:`PACKAGE_GROUP_WIDTH` cells, with dashes
    filling both sides.  The host key (``pypi`` or ``test``) is used rather than
    the domain name because the fixed pair is too narrow for ``test.pypi.org``.
    """
    label = f' {host} '
    if len(label) >= PACKAGE_GROUP_WIDTH:
        return label[:PACKAGE_GROUP_WIDTH].ljust(PACKAGE_GROUP_WIDTH)
    remaining = PACKAGE_GROUP_WIDTH - len(label)
    left = remaining // 2
    return '-' * left + label + '-' * (remaining - left)


def package_host_header(width: int, hosts: Sequence[str]) -> str:
    """The line of host names above the two VERs/DELs column pairs."""
    prefix = ' ' * (CHECK_WIDTH + 1 + width + 1)
    return prefix + ' '.join(host_group_label(host) for host in hosts)


def package_header(width: int, hosts: Sequence[str]) -> str:
    """The package list's column titles; the check column stays untitled."""
    prefix = (
        f"{' ' * (CHECK_WIDTH + 1)}"
        f"{PACKAGE_TITLE:<{width}} "
    )
    groups = [
        f"{'VERs':>{VERS_WIDTH}} {'DELs':>{DELS_WIDTH}}"
        for _host in hosts
    ]
    return prefix + ' '.join(groups)


def format_package_row(
    name: str,
    states: Mapping[str, PackageState | None],
    width: int,
    hosts: Sequence[str],
) -> str:
    """Format one package-list row with one VERs/DELs pair per host.

    The check column means this run has loaded the package on either host.  A
    host with no successful fetch shows ``-`` in both of its columns, because
    the screen must not invent a count the run never fetched.
    """
    visited = any(
        state is not None and state.visited for state in states.values()
    )
    mark = VISITED_MARK if visited else ' '
    groups: list[str] = []
    for host in hosts:
        state = states.get(host)
        if state is None or not state.visited:
            versions = deleted = '-'
        else:
            versions = str(state.version_count)
            deleted = str(state.deleted)
        groups.append(f'{versions:>{VERS_WIDTH}} {deleted:>{DELS_WIDTH}}')
    return (
        f"{mark:^{CHECK_WIDTH}} "
        f"{name:<{width}} "
        + ' '.join(groups)
    )


def resolve_theme(
    cli_theme: str | None = None,
    cli_no_color: bool | None = None,
    saved_theme: str = "",
    saved_no_color: bool = False,
    environ: Mapping[str, str] | None = None,
) -> tuple[str, str, bool]:
    """Return ``(choice, palette, colors)`` for the start of a run.

    ``choice`` is what the picker shows -- ``mono`` while color is off --
    ``palette`` is the console-window theme to install, and ``colors`` is
    whether the semantic roles may use color.  An explicit ``--no-color`` wins
    over ``--theme``; otherwise an explicit theme, the ``NO_COLOR`` convention
    and the remembered choice decide, in that order.
    """
    env = os.environ if environ is None else environ
    # None means "not given", which is different from an explicit false.
    colors = None if cli_no_color is None else not cli_no_color
    if cli_theme == MONO_THEME:
        # mono is a color mode rather than a palette: it turns color off.
        colors = False
    elif cli_theme and colors is None:
        colors = True
    if colors is None:
        colors = (
            not env.get("NO_COLOR")
            and not saved_no_color
            and saved_theme != MONO_THEME
        )
    palette = cli_theme or saved_theme
    if palette == MONO_THEME:
        palette = ""
    palette = Theme.resolve(palette or Theme.get_current())
    choice = palette if colors else MONO_THEME
    return choice, palette, colors


class CleanupApp:
    """The console-window application showing one package's release history."""

    def __init__(
        self,
        cleanup: CleanupTui,
        backend: RenderBackend | None = None,
        singleton: bool = True,
        ini: IniManager | None = None,
        zone: str = UTC_MODE,
        theme: str | None = None,
        no_color: bool | None = None,
        sort: str = SORT_BY_VERSION,
        gap: int = DEFAULT_GAP,
        read_only: bool = False,
        packages: Sequence[str] | None = None,
        totp_method: str = DEFAULT_TOTP_METHOD,
    ) -> None:
        self.cleanup = cleanup
        #: Optional persistent options.  Without one the TUI runs exactly as
        #: before: changes apply to this session and are not written anywhere.
        self.ini = ini
        #: A read-only run never offers to delete: the hint line says ``R/O``
        #: instead of ``del``, and ``d`` is inert even when releases are marked.
        #: It is a switch for this run only, never a stored option -- a sticky
        #: read-only flag would quietly disarm the program.
        self.read_only = bool(read_only)
        #: How the authenticator prompt is answered.  The command line
        #: normalizes the stored choice; this guard keeps a direct caller from
        #: injecting one the hand-off cannot honor.
        self.totp_method = (
            totp_method if totp_method in TOTP_METHODS else DEFAULT_TOTP_METHOD
        )
        self.running = True
        #: The package list the command line supplied, shown one at a time.
        #: ``p`` rotates through it and ``P`` edits it; the model's package is
        #: the current entry.  De-duplication keeps the first occurrence, the
        #: same rule the command line applies to its own list.
        self.packages = (
            list(dict.fromkeys(packages)) if packages else [cleanup.package]
        )
        if cleanup.package not in self.packages:
            self.packages.insert(0, cleanup.package)
        self.package_index = self.packages.index(cleanup.package)
        #: Complete state of every ``(package, host)`` pair this run has seen.
        #: It holds the table and the package-list totals together, and it is
        #: kept on the application because it describes only this session.
        self.states: dict[tuple[str, str], PackageState] = {}
        #: Wall-clock source for state deltas and the error-retry window.  A
        #: test can replace it with a frozen clock.
        self.clock: Callable[[], float] = time.time
        #: The row the package list should put the pick on the next time it
        #: draws.  ``P`` sets it to the package ``p`` would show next, so the
        #: list opens one rotation step ahead of the table; the draw that
        #: follows consumes it, because a row only exists once the body is
        #: built.
        self.packages_pick: int | None = None
        #: The order restored after every fetch, so a reload keeps the table
        #: the way the user arranged it.
        self.sort = sort
        #: State for the frame drawn while :meth:`load_versions` fetches.
        self.loading = False
        #: Whether the most recent fetch attempt failed.  The display reads the
        #: state instead; this flag is what ``f`` uses to avoid re-applying the
        #: old marks over a table that was just restored.
        self.load_failed = False
        #: Text of the incremental search.  An empty string shows every
        #: release; anything else narrows the body to the matching rows.
        self.search_text = ''
        #: ``search_text`` compiled once per change, so drawing a body cannot
        #: recompile the pattern row by row.  ``None`` means no filter is in
        #: force: the pattern is empty, whitespace, or not valid yet.
        self.search_re: re.Pattern[str] | None = None
        #: The release picked when the search started, so closing the bar can
        #: return the pick to the same release when the pattern still shows it.
        self.search_anchor: Release | None = None
        self.search_bar = IncrementalSearchBar(
            on_change=self._on_search_change,
            on_accept=self._finish_search,
            on_cancel=self._finish_search,
        )

        # The color switch is process-wide, so it has to be settled before the
        # window installs a palette or the first frame is painted in the wrong
        # mode.  The remembered choice is read from the same store as the rest.
        stored_theme = getattr(ini.vals, 'theme', '') if ini is not None else ''
        stored_no_color = (
            bool(getattr(ini.vals, 'no_color', False)) if ini is not None else False
        )
        choice, palette, colors = resolve_theme(
            cli_theme=theme,
            cli_no_color=no_color,
            saved_theme=stored_theme,
            saved_no_color=stored_no_color,
        )
        appearance.set_colors_enabled(colors)

        self.opts = SimpleNamespace()
        # Seeding the options before they are registered is what makes the
        # stored values the starting values: registration only normalizes a
        # missing value.
        self.opts.theme = choice
        if zone in ZONES:
            self.opts.time_zone = zone
        # The stability gap is stored too, so the run starts with the one the
        # previous run left in force.  Registering the option would otherwise
        # seed it from the head of GAP_CHOICES, and an unknown stored value
        # falls back to a month rather than to the shortest gap.
        self.opts.gap = gap if gap in GAP_CHOICES else DEFAULT_GAP

        win_opts = ConsoleWindowOpts(
            head_line=True,
            min_cols_rows=(60, 10),
            # Ctrl-C must not tear the TUI down.  Leaving 0x3 unbound means the
            # window swallows it instead of dispatching a quit action.
            ctrl_c_terminates=False,
            # Seed the palette explicitly so the window does not inherit one
            # left behind by a previous run in the same process.
            theme=palette,
            # Both markers are decoration, so the window owns their ASCII
            # fallbacks and rewrites them when the terminal cannot draw them.
            glyphs={
                'delete_mark': Glyph(DEL_MARK, 'x'),
                'visited_mark': Glyph(VISITED_MARK, 'x'),
            },
        )
        self.win = ConsoleWindow(opts=win_opts, backend=backend, singleton=singleton)

        screens = self.screens = {
            MAIN_ST: MainScreen(self),
            HELP_ST: HelpScreen(self),
            THEME_ST: ThemeScreen(self),
            PACKAGES_ST: PackagesScreen(self),
        }
        self.stack = ScreenStack(self.win, self.opts, SCREEN_NAMES, screens)

        spin = self.spin = OptionSpinner(stack=self.stack)
        spin.add_key('quit', 'q - quit', genre='action', keys=[ord('q')])
        spin.add_key('help_screen', '? - help', genre='action',
                     keys=[ord('?')], scope={MAIN_ST, PACKAGES_ST})
        # The cycles come next, so the help screen lists every option that
        # takes a value before the keys that only fire once.  A cycle needs no
        # _ACTION method: it rewrites the option in place, the next draw reads
        # it, and handle_key() is where the remembered ones are stored.
        #
        # z rewrites the time zone the DATE column names.  The help screen
        # lists the same cycle, so the key works there too and the value shown
        # beside it is the one the table will use.
        spin.add_key('time_zone', 'z - date time zone',
                     vals=list(ZONES), keys=[ord('z')],
                     scope={MAIN_ST, HELP_ST})
        # t works on the THEMES screen and on the help screen; handle_key()
        # applies the palette or the mono color mode as soon as the value
        # changes.
        spin.add_key('theme', 't - cycle themes', vals=list(THEME_CHOICES),
                     keys=[ord('t')], scope={THEME_ST, HELP_ST})
        # The stability gap is a hidden option: g rotates it on the help screen
        # and applies it on the table, so one key is bound twice with two
        # meanings -- a cycle on one screen, an action on the other.
        spin.add_key('gap', 'g - stability gap, in days', vals=list(GAP_CHOICES),
                     keys=[ord('g')], scope={HELP_ST})
        # T opens the picker from the table or the help screen, so ESC returns
        # to whichever screen pushed it.  It is not bound on the picker itself,
        # so the stack cannot recurse, and t is not bound on the table, so the
        # table keeps its own keys untouched.
        spin.add_key('theme_screen', 'T - themes', genre='action',
                     keys=[ord('T')], scope={MAIN_ST, HELP_ST})
        # P opens the working package list, which is a different view of the
        # same list p rotates through: p steps the table to the next package,
        # P edits the list itself.
        spin.add_key('packages_screen', 'P - package list', genre='action',
                     keys=[ord('P')], scope={MAIN_ST})
        # p and h change what the table is looking at; the summary header
        # already advertises both as key hints ([p]ack / [h]ost).
        spin.add_key('package_next', 'p - next package', genre='action',
                     keys=[ord('p')], scope={MAIN_ST})
        spin.add_key('host_next', 'h - switch index', genre='action',
                     keys=[ord('h')], scope={MAIN_ST})
        # f reloads the package already on screen, which is how a new upload
        # is picked up without rotating to another package first.
        spin.add_key('refresh', 'f - refresh the release list', genre='action',
                     keys=[ord('f')], scope={MAIN_ST})
        # ESC is the way back on every pushed screen, but it is the way
        # forward on the package list: there it opens the picked package
        # before returning, which is why one binding is enough -- each screen
        # decides what its own ESC means.
        spin.add_key('escape', 'ESC - back, or open the picked package',
                     genre='action',
                     keys=[27], scope={HELP_ST, THEME_ST, PACKAGES_ST})
        spin.add_key('mark', 'x - mark this release, move down',
                     genre='action', keys=[ord('x')], scope={MAIN_ST})
        spin.add_key('mark_from_here',
                     'X - mark this release and all below, move up',
                     genre='action', keys=[ord('X')], scope={MAIN_ST})
        spin.add_key('unmark', 'u - unmark this release, move down',
                     genre='action', keys=[ord('u')], scope={MAIN_ST})
        spin.add_key('unmark_from_here',
                     'U - unmark this release and all below, move up',
                     genre='action', keys=[ord('U')], scope={MAIN_ST})
        # The deletion step: the hint only appears once something is marked and
        # no pattern is filtering the table.  Pressing d hands the marked
        # versions to pypi-cleanup; a read-only run says so in the help list.
        spin.add_key(
            'delete',
            'd - delete the marked versions' + (
                ' (read-only mode)' if read_only else ' with pypi-cleanup'),
            genre='action', keys=[ord('d')], scope={MAIN_ST},
        )
        # Sorting changes the model rather than a spinner value, so it is an
        # action; the hint line advertises it between the marking keys and z.
        spin.add_key('sort', 's - change the sort order',
                     genre='action', keys=[ord('s')], scope={MAIN_ST})
        # g's action: the qualifier names its screen because g also rotates
        # the gap on the help screen, and the help body lists both lines.
        spin.add_key('apply_gap',
                     'g - keep the releases that stayed stable [Main Screen]',
                     genre='action', keys=[ord('g')], scope={MAIN_ST})
        # "/" opens the incremental search field in the first header line.
        spin.add_key('search', '/ - incremental search',
                     genre='action', keys=[ord('/')], scope={MAIN_ST})
        # The package list's row key.  It is scoped to that screen, so x there
        # removes a name while x on the table still marks a release; the
        # qualifier keeps the two x lines apart in the help body.
        spin.add_key('package_remove',
                     'x - remove from the package list [Package Screen]',
                     genre='action', keys=[ord('x')], scope={PACKAGES_ST})
        # ENTER is how the search bar closes its pattern on the table, so it
        # has to reach the application even though no spinner option binds it.
        self.win.set_handled_keys(
            set(spin.keys) | {10, 13, curses.KEY_ENTER},
        )

    def handle_key(self, key: int) -> None:
        """Route one key to the search bar, then the spinner.

        While the bar is active it owns printable and editing keys.  Any key
        it does not handle (navigation, Ctrl-C) closes the pattern first and
        then continues to its normal destination, so the table never traps the
        keyboard in search mode.
        """
        if self.search_bar.is_active:
            if self.search_bar.handle_key(key):
                return
            # ENTER closes the bar without changing the text; the key that
            # was not ours still reaches the spinner/navigation below.
            self.search_bar.handle_key(10)
        if key not in self.spin.keys:
            return
        option = self._option_for(key)
        value = self.spin.do_key(key, self.win)
        # Cycle options change a setting rather than firing an action, and both
        # preferences are worth keeping between runs.
        if option is None or option.genre != 'cycle' or value is None:
            return
        if option.attr == 'time_zone':
            self.persist(zone=str(value))
        elif option.attr == 'theme':
            self.apply_theme_choice(str(value))
        elif option.attr == 'gap':
            # The gap rotates on the help screen and applies on the table; the
            # value is worth keeping either way, so the next run starts with it.
            self.persist(gap=int(value))

    def compile_search(self) -> None:
        """Compile the search text into :attr:`search_re`.

        The pattern is a case-insensitive regular expression, mirroring the
        filter vappman offers.  An expression that does not compile yet (a
        lone ``[`` halfway through typing one, say) drops the filter instead
        of flashing an empty table; the next keystroke compiles it again.
        """
        pattern = self.search_text.strip()
        self.search_re = None
        if pattern:
            try:
                self.search_re = re.compile(pattern, re.IGNORECASE)
            except re.error:
                self.search_re = None

    def release_matches(self, release: Release) -> bool:
        """Whether *release*'s version matches the compiled pattern.

        Version identifiers are the one stable piece of text a release owns;
        matching dates as well would make a one-digit pattern match almost
        every row because of the time of day.  With no filter in force every
        release matches, which is what :meth:`visible_versions` relies on.
        """
        if self.search_re is None:
            return True
        return self.search_re.search(release.version) is not None

    def visible_versions(self) -> list[Release]:
        """The releases the table currently shows, in table order."""
        return [release for release in self.cleanup.versions
                if self.release_matches(release)]

    def _clamp_pick(self) -> None:
        """Keep the pick inside the visible rows after the pattern changes."""
        count = len(self.visible_versions())
        self.win.pick_pos = min(self.win.pick_pos, count - 1) if count else 0

    def _restore_search_pick(self) -> None:
        """Put the pick back on the anchored release, or at the top."""
        visible = self.visible_versions()
        anchor = self.search_anchor
        self.search_anchor = None
        if anchor is not None:
            for index, release in enumerate(visible):
                if release is anchor:
                    self.win.pick_pos = index
                    return
        self.win.pick_pos = 0

    def _on_search_change(self, text: str) -> None:
        """Filter as the pattern is typed, keeping the pick in range."""
        self.search_text = text
        self.compile_search()
        self._clamp_pick()

    def _finish_search(self, text: str) -> None:
        """Accept or cancel: stop editing and restore the logical pick."""
        self.search_text = text
        # ESC restores the old text without emitting on_change, so the
        # pattern has to be compiled again on this path too.
        self.compile_search()
        self.win.passthrough_mode = False
        self._restore_search_pick()

    def start_search(self) -> None:
        """Open the search bar with the current pattern and anchor the pick."""
        visible = self.visible_versions()
        position = self.win.pick_pos
        self.search_anchor = (
            visible[position] if 0 <= position < len(visible) else None
        )
        self.search_bar.start(self.search_text)
        self.win.passthrough_mode = True

    def apply_theme_choice(self, choice: str) -> None:
        """Make a picker *choice* live and remember it.

        ``mono`` is the app's pseudo-theme: a color mode rather than a palette,
        so it flips the process-wide switch and leaves the installed palette
        where it was (the same way ``--no-color`` keeps ``--theme``).  Choosing
        a real palette is a request for color, so it lifts the switch again and
        installs the palette.
        """
        self.opts.theme = choice
        if choice == MONO_THEME:
            appearance.set_colors_enabled(False)
            self.persist(theme=MONO_THEME, no_color=True)
            return
        appearance.set_colors_enabled(True)
        self.win.set_theme(choice)
        self.persist(theme=choice, no_color=False)

    def hand_off_to_cleanup(self, versions: Sequence[str],
                            notice: str | None = None) -> None:
        """Leave curses for ``pypi-cleanup``, show the runs, and come back.

        The window is suspended, not stopped, the same way vappman runs its
        helper commands: ``endwin()`` restores the tty -- so the subprocess and
        its questions work -- and ``resume_curses()`` reattaches the screen,
        which the redrawing ``render()`` repaints from the preserved table.
        *notice* is a line to say on the bare terminal before the command; the
        caller uses it for a change it made behind the table's back, such as
        the newest release unmarked because the whole history was marked.
        Nothing is printed for ``None``, which is the ordinary hand-off.
        The flow is two runs: a ``--query-only`` dry run, then a ``--do-it``
        deletion that is retried until it succeeds; each question defaults to
        the harmless answer, a bare ENTER takes it, and anything but ``yes`` or
        ``no`` re-asks.  Answering no to the dry run only skips it; the deletion
        still needs its own yes.  A deletion that succeeds drops the deleted
        versions from the table and re-queries the package behind them, so the
        view the user returns to never shows a release they just deleted, even
        while the index's cache still lists it.
        Credentials scoped with ``4PYPI`` or ``4TEST`` are copied into the base
        variables the tool reads and named above the printed command, so one
        index's password is never offered to the other.  How the authenticator
        prompt is answered follows ``--totp-method``: ``expect`` drives the
        child through pexpect and sends a code at Ctrl+], ``print`` only prints
        the code above the run, and ``off`` leaves the prompt to the user; see
        :meth:`_run_cleanup`.
        """
        base = cleanup_command(self.cleanup, versions)
        package = self.cleanup.package
        count = len(versions)
        mapped = credential_env(self.cleanup.host_key)
        env = cleanup_env(self.cleanup.host_key)
        deleted = 0
        self.win.suspend_curses()
        try:
            _reset_terminal()
            if notice:
                # The table that held the mark is out of sight, so the one
                # thing the screen cannot say on its own is said here, above
                # the command, instead of being lost with the redraw.
                print(notice)
                print()
            print(format_command(base, env=mapped))
            print()
            if ask_yes_no(DRY_RUN_PROMPT, default=True):
                query = cleanup_command(self.cleanup, versions, QUERY_ONLY)
                print(format_command(query, env=mapped))
                print(summary_line(
                    'Dry run', package, self._run_cleanup(query, env)))
                print()
            if ask_yes_no(
                DELETE_PROMPT.format(count=count, package=package),
                default=False,
            ):
                if self._delete_with_retry(versions, package, count,
                                           mapped, env):
                    deleted = count
            press_enter()
        finally:
            self.win.resume_curses()
        if deleted:
            self.reload_after_deletion(versions)
        self.win.render(redraw=True)

    def _delete_with_retry(
        self,
        versions: Sequence[str],
        package: str,
        count: int,
        mapped: Mapping[str, str] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> bool:
        """Run the ``--do-it`` deletion, reissuing it until it succeeds.

        ``pypi-cleanup`` reports success through its exit status.  A run that
        fails is offered again behind a ``RETRY:`` prompt, because the marked
        versions have not changed while the terminal was idle and the same
        command can be repeated; the loop ends when a run succeeds or the user
        declines.  Returns whether the marked versions were deleted.  *mapped*
        and *env* are the credential mapping and the child environment, so the
        retry names and hands over exactly what the first run did; the
        authenticator method is applied again for each attempt.
        """
        while True:
            destroy = cleanup_command(self.cleanup, versions, DO_IT)
            print(format_command(destroy, env=mapped))
            status = self._run_cleanup(destroy, env)
            print(summary_line('Deletion', package, status))
            print()
            if status == 0:
                return True
            if not ask_yes_no(
                RETRY_PROMPT.format(count=count, package=package),
                default=False,
            ):
                return False

    def _run_cleanup(self, command: Sequence[str],
                     env: Mapping[str, str] | None = None) -> int:
        """Run ``pypi-cleanup`` using the configured authenticator method.

        ``print`` prints a code with room left and then uses subprocess.
        ``expect`` gives the child to pexpect: the user answers the password
        and device prompts, presses Ctrl+] at the authentication prompt, and
        the TUI sends the code.  ``auto`` also uses pexpect but never hands the
        terminal back; it is for a run whose password is supplied, so the only
        prompt is the code.  With no secret there is nothing to send, so the
        tool prompts as usual.  If pexpect cannot start the child at all, the
        run falls back to ``print`` -- never after the child has started,
        because re-running there could repeat a deletion.  ``off`` always uses
        the plain run and leaves the prompt to the user.
        """
        if self.totp_method == TOTP_PRINT:
            show_authentication_code(self.cleanup.host_key)
            return run_cleanup(command, env)
        if self.totp_method in (TOTP_EXPECT, TOTP_AUTO):
            secret = totp_secret(self.cleanup.host_key)
            if not secret:
                return run_cleanup(command, env)
            if self.totp_method == TOTP_EXPECT:
                print(EXPECT_BANNER)
                runner = run_cleanup_expect
            else:
                runner = run_cleanup_auto
            try:
                return runner(command, secret, env)
            except ExpectUnavailable as error:
                print(f'warning: pexpect could not start: {error}; '
                      'printing the code instead.')
                show_authentication_code(self.cleanup.host_key)
                return run_cleanup(command, env)
        return run_cleanup(command, env)

    def reload_after_deletion(self, versions: Sequence[str]) -> None:
        """Hide the deleted versions, then fetch the package again.

        The versions are hidden before the fetch rather than after it: the
        deletion is known to have happened, while the fetch is only a second
        opinion from an index whose CDN may still serve the old history for up
        to fifteen minutes.  A refetch that lists a deleted version must not put
        it back on the table, so the hidden set outlives the fetch and the
        summary line says ``STALE`` until a fetch returns a history without it.
        The visible rows are reduced at once, so a failed refetch restores a
        table that still honours the deletion.  Every trace of the old view --
        the marks, the search pattern and the pick -- is dropped, and the pair's
        state keeps the deletion count for the package list's DELs column.
        """
        state = self.state
        state.deleted += len(versions)
        # A second deletion while the first is still unconfirmed adds to the
        # hidden set; replacing it would let the older versions reappear in
        # the next fetch that still lists them.
        state.hidden_versions |= set(versions)
        state.releases = [
            release for release in state.releases
            if release.version not in state.hidden_versions
        ]
        for release in state.releases:
            release.delete = False
        self.cleanup.versions = state.releases
        state.status = STALE
        self.search_text = ''
        self.search_re = None
        self.search_anchor = None
        self.load_versions()

    def _settle_hidden_versions(self) -> None:
        """Keep hidden versions out of a fetched history and note the result.

        A successful fetch is the second opinion on a deletion: a version it no
        longer lists is settled, so it needs no hiding, while a version it still
        lists stays hidden and keeps the ``STALE`` marker -- the display never
        re-adds a release the user already deleted.  With nothing left to hide
        the history is what the index holds and the marker clears.
        """
        state = self.state
        if not state.hidden_versions:
            state.status = LOADED
            return
        fetched = {release.version for release in self.cleanup.versions}
        state.hidden_versions &= fetched
        if state.hidden_versions:
            self.cleanup.versions = [
                release for release in self.cleanup.versions
                if release.version not in state.hidden_versions
            ]
        state.status = STALE if state.hidden_versions else LOADED

    def _option_for(self, key: int) -> SimpleNamespace | None:
        """The spinner option bound to *key* on the current screen, if any."""
        current = self.stack.curr
        if current is not None:
            option = self.spin.key_scopes.get((key, current.num))
            if option is not None:
                return option
        return self.spin.key_to_option.get(key)

    def persist(self, **values: object) -> None:
        """Store the settings a change has just made, for the next run.

        The index in use is written on every save as well, so a host change
        would be remembered without every caller having to repeat it.
        """
        if self.ini is None:
            return
        values.setdefault('host', self.cleanup.host_key)
        self.ini.save(**values)

    @property
    def state(self) -> PackageState:
        """The mutable state of the ``(package, host)`` pair on screen."""
        key = (self.cleanup.package, self.cleanup.host_key)
        return self.states.setdefault(key, PackageState())

    @property
    def hidden_versions(self) -> set[str]:
        """The hidden versions of the pair on screen (read-only view)."""
        return self.state.hidden_versions

    @property
    def stale(self) -> bool:
        """Whether the pair on screen is in its ``STALE`` state."""
        return self.state.status == STALE

    def state_for(self, package: str, host: str) -> PackageState | None:
        """The saved state for a pair, or ``None`` if this run never saw it."""
        return self.states.get((package, host))

    def switch_to(self, package: str, host: str) -> None:
        """Show another pair, restoring the complete state saved for it.

        The pair on screen keeps its rows, marks, hidden versions and state
        marker in :attr:`states`, so revisiting it returns all of them.  A
        never-loaded pair is fetched at once.  A pair whose last attempt failed
        is fetched only once the error-retry window has passed; inside that
        window its remembered error is shown instead.  An explicit refresh
        (``f``) bypasses this method and always fetches.
        """
        if package == self.cleanup.package and host == self.cleanup.host_key:
            return
        # The model is the current pair's live copy; make the durable state
        # point at it before the model is pointed at another pair.
        self.state.releases = self.cleanup.versions
        self.cleanup.package = package
        self.cleanup.host_key = host
        target = self.state
        self.cleanup.versions = list(target.releases)
        self.cleanup.sort_versions(self.sort)
        marked = {
            release.version for release in target.releases if release.delete
        }
        self.win.pick_pos = 0
        if target.status == ERROR and not self._error_retry_due(target):
            self.win.clear()
            return
        self.load_versions()
        if self.load_failed:
            return
        # A successful visit replaces the rows, so the saved marks are put
        # back by version: the decision belonged to the release, not the row.
        for release in self.cleanup.versions:
            if release.version in marked:
                release.delete = True
        target.releases = self.cleanup.versions

    def _error_retry_due(self, state: PackageState) -> bool:
        """Whether an error-state pair is old enough to be fetched again."""
        return (
            state.last_attempt_at is None
            or self.clock() - state.last_attempt_at >= ERROR_RETRY_SECONDS
        )

    def select_package(self, package: str) -> None:
        """Make *package* the table's package on the current host.

        The package list only offers names it holds, so a name that is not in
        the list is ignored rather than added behind the user's back.  Landing
        on the package already shown changes nothing; landing on another
        restores that pair's saved table or fetches it as :meth:`switch_to`
        decides.
        """
        if package not in self.packages:
            return
        self.package_index = self.packages.index(package)
        self.switch_to(package, self.cleanup.host_key)

    def remove_package(self, package: str) -> None:
        """Drop *package* from the working list, leaving the index untouched.

        Removing the package the table shows is allowed: the list is a working
        set, not the index, so the table keeps its package.  The rotation index
        is repaired to the current package when it is still listed, or to the
        row that took the removed name's place.  The new list is stored, so the
        next run does not bring the name back.
        """
        if package not in self.packages:
            return
        self.packages.remove(package)
        if self.cleanup.package in self.packages:
            self.package_index = self.packages.index(self.cleanup.package)
        elif self.packages:
            self.package_index = min(self.package_index, len(self.packages) - 1)
        else:
            self.package_index = 0
        self.persist(packages=','.join(self.packages))

    def next_package_index(self) -> int | None:
        """The row after the table's package, wrapping to the first one.

        The next package is found from the table's own package rather than
        from the stored index, so the rotation stays correct after a name was
        removed from the list while the table was showing a different one.
        A name the list no longer holds falls back to the row that took its
        place, which is how ``p`` still switches away from a removed package.
        ``None`` means there is no row to step onto because the list is empty.
        """
        if not self.packages:
            return None
        if self.cleanup.package in self.packages:
            index = self.packages.index(self.cleanup.package)
            return (index + 1) % len(self.packages)
        return min(self.package_index, len(self.packages) - 1)

    def load_versions(self) -> None:
        """Show ``Loading ...``, fetch, and move the pair to its next state.

        A successful fetch replaces the rows.  A failure depends on whether
        this pair has ever loaded: a pair that has keeps the old table, becomes
        ``STALE`` and shows the modal alert; a pair that never loaded keeps no
        rows, becomes ``ERROR`` and shows the error in the body instead.  The
        pair's state is durable, so switching away and back restores whichever
        result this produced.
        """
        state = self.state
        previous_status = state.status
        previous_pick = self.win.pick_pos
        self.loading = True
        self.load_failed = False
        self.cleanup.versions = []
        self.win.pick_pos = 0
        self.win.clear()
        self._draw_current_screen()
        self.win.render()
        state.last_attempt_at = self.clock()
        try:
            self.cleanup.fetch_versions()
        except Exception as exc:
            self.load_failed = True
            self._handle_load_failure(
                state, previous_status, previous_pick, exc)
            return
        finally:
            self.loading = False
            self.win.clear()
        self.cleanup.sort_versions(self.sort)
        state.releases = self.cleanup.versions
        state.error_message = ''
        state.no_package = False
        state.status = LOADED
        self._settle_hidden_versions()
        state.releases = self.cleanup.versions

    def _load_error_message(self, exc: BaseException) -> str:
        """The alert text a failed fetch has always used."""
        return (
            f'Could not load {self.cleanup.package!r} from '
            f'{self.cleanup.host}.\n\n'
            f'{type(exc).__name__}: {exc}'
        )

    def _handle_load_failure(
        self,
        state: PackageState,
        previous_status: str,
        previous_pick: int,
        exc: BaseException,
    ) -> None:
        """Record a failed fetch and choose the alert or the body error.

        A pair that has loaded before is stale: its old rows and marks are
        restored, and the failure is a modal alert.  A pair that has never
        loaded is an error: there is no table to keep, and the body itself
        carries the explanation, so no alert interrupts the user.
        """
        message = self._load_error_message(exc)
        state.error_message = message
        state.no_package = is_missing_package_error(exc)
        if previous_status in (LOADED, STALE):
            state.status = STALE
            self.cleanup.versions = state.releases
            self.cleanup.sort_versions(self.sort)
            count = len(self.visible_versions())
            self.win.pick_pos = min(previous_pick, count - 1) if count else 0
            self.win.alert(message, title='LOAD ERROR')
            return
        state.status = ERROR
        state.releases = []
        self.cleanup.versions = []

    def _draw_current_screen(self) -> None:
        """Draw the screen on top, or the table before the first push."""
        current = self.stack.curr
        screen_num = current.num if current is not None else MAIN_ST
        self.screens[screen_num].draw_screen()

    def main_loop(self) -> None:
        """Load the first history, then draw until an action clears running."""
        # Entering the TUI before the fetch is what lets the loading frame and
        # the failure alert use the real terminal.
        self.load_versions()
        while self.running:
            self.screens[self.stack.curr.num].draw_screen()
            self.win.render()
            key = self.win.prompt(seconds=1.0)
            if key is not None:
                self.handle_key(key)
            self.stack.perform_actions(self.spin)
            self.win.clear()

    def run(self) -> int:
        """Run the application and always leave the terminal usable."""
        try:
            self.main_loop()
        finally:
            self.win.stop_curses()
        return 0


class CleanupScreen(Screen):
    """Base screen: every screen can receive the global quit/back actions."""

    app: CleanupApp

    def quit_ACTION(self) -> None:
        self.app.running = False

    def escape_ACTION(self) -> None:
        """A pushed screen hands control back to the one below it."""
        self.app.stack.pop()

    def help_screen_ACTION(self) -> None:
        """Push the help screen, remembering the pick to return to."""
        self.app.stack.push(HELP_ST, self.app.win.pick_pos)

    def theme_screen_ACTION(self) -> None:
        """Push the theme picker; ESC returns to the screen that pushed it."""
        self.app.stack.push(THEME_ST, self.app.win.pick_pos)


class MainScreen(CleanupScreen):
    """The release table."""

    def draw_screen(self) -> None:
        win = self.app.win
        # While the pattern is being typed the bar is the focus; suppressing
        # the row highlight keeps the cursor in the header unambiguous.
        win.set_pick_mode(not self.app.search_bar.is_active, 1)
        self._draw_headers()
        self._draw_body()

    def _time_mode(self) -> str:
        """The ``D`` spinner's current value; UTC until the spinner is read."""
        return self.app.spin.get_value('time_zone') or UTC_MODE

    def _gap_days(self) -> int:
        """The stability gap the spinner holds, in days."""
        return int(self.app.spin.get_value('gap') or DEFAULT_GAP)

    def _hint_line(self) -> HeaderLine:
        """The first header line: one fixed-width block per key.

        A block that has nothing to say is replaced by spaces of exactly the
        same width, so keys appearing and disappearing never shift the keys to
        their right.  The marking pair and the unmarking pair are already the
        same width (``x:mark``/``unmark``, ``X:mark▼``/``Unmark▼``), which is
        what lets the row under the pick choose between them without moving the
        line.  The search field is the one block whose width follows its text;
        it sits last, so even that moves nothing.
        """
        hints = HeaderLine()
        # The deletion block leads the line.  A read-only run always says R/O:
        # it can never delete, and the block is as wide as "del", so the keys
        # to its right stay put.  Otherwise the block is only filled while d
        # may fire -- a pattern in force can hide marked releases, so d must
        # not offer to delete what the screen does not show.
        if self.app.read_only:
            hints.text(READ_ONLY_HINT)
        elif self._deletion_offered():
            hints.bracket_key('d').text(DEL_HINT[1:])
        else:
            hints.text(' ' * len(DEL_HINT))
        hints.text(' ')
        picked = self._release_at_pick()
        if picked is not None and picked.delete:
            # On a marked row the inverse pair applies; each key is inert
            # against a row already in the state it would produce.
            hints.bracket_key('u').text('nmark ')
            hints.bracket_key('U').text(f'nmark{DOWN_MARK} ')
        else:
            hints.bracket_key('x').text(':mark ')
            hints.bracket_key('X').text(f':mark{DOWN_MARK} ')
        # Where the label starts with the key itself, the bracket form merges
        # into one word with the key underlined ("sort", "zone", "fresh",
        # "quit").  The from-here-down keys trade "-all" for the arrow glyph.
        hints.bracket_key('s').text('ort ')
        hints.bracket_key('z').text('one ')
        # The gap in force, because g applies it right here.  The number is
        # padded so a one-digit gap does not move the keys to its right.
        hints.bracket_key('g').text(f'ap{self._gap_days():<{GAP_HINT_WIDTH}} ')
        # f sits just before q: a reload is the last thing to do before leaving.
        hints.bracket_key('f').text('resh ')
        hints.bracket_key('q').text('uit ')
        hints.bracket_key('?').text(':help')
        # The search field is always present, even with an empty pattern; the
        # T key is advertised on the help screen only.
        hints.extend(self._search_header_line())
        return hints

    def _draw_headers(self) -> None:
        win = self.app.win
        win.add_fancy_header(self._hint_line(), line_attr=curses.A_DIM)

        # The package summary.  A fancy header, so the bracketed letters read
        # as key hints, but not dimmed: it sits between the dim hint line and
        # the dim column titles.  ``User=`` is literal -- there is no key for
        # it -- while ``[p]`` rotates the package list and ``[h]`` switches the
        # index; either one reloads the table.  The host shows the index key
        # (``pypi`` or ``test``), not its domain name.
        cleanup = self.app.cleanup
        summary = HeaderLine()
        summary.text(f'User={cleanup_user(cleanup) or "n/a"} ')
        summary.bracket_key('p').text(f'ack={cleanup.package} ')
        summary.bracket_key('h').text(f'ost={cleanup.host_key}')
        # The table is stale when the last fetch failed or when a deletion the
        # index has not acknowledged yet leaves hidden versions.  The LABEL
        # role renders bold, and the age says how long ago the attempt that
        # produced this view was made.
        state = self.app.state
        if state.status == STALE:
            now = self.app.clock()
            start = state.last_attempt_at
            age = compact_delta_time(now if start is None else start, now)
            summary.label(f' STALE [{age}]')
        win.add_fancy_header(summary)
        # The column titles are the third header line: dim, and deliberately
        # not underlined, so the releases below stay the visually strongest
        # thing on the screen.  The sorted column carries the star.
        win.add_header(
            column_header(self._time_mode(), cleanup.sort),
            attr=curses.A_DIM,
        )

    def _search_header_line(self) -> HeaderLine:
        """The ``/pattern`` field at the end of the hint line.

        ``IncrementalSearchBar.as_header_line()`` hides itself while idle with
        an empty buffer; this app keeps the bare ``/`` visible so the search is
        discoverable before anything has been typed.
        """
        line = self.app.search_bar.as_header_line(prefix='/')
        if not line:
            line.search('', prefix='/')
        display = HeaderLine()
        display.text(' ')
        display.extend(line)
        return display

    def _marked_count(self) -> int:
        """How many releases are currently marked for deletion."""
        return sum(1 for release in self.app.cleanup.versions if release.delete)

    def _deletion_offered(self) -> bool:
        """Whether ``d`` may fire: something is marked and nothing is filtered.

        A pattern in force can hide marked releases, so deleting behind it
        would act on rows the screen does not show.  A pattern that does not
        compile yet leaves the table unfiltered and so blocks nothing.  A
        read-only run never offers the key at all.
        """
        return (
            not self.app.read_only
            and self._marked_count() > 0
            and self.app.search_re is None
        )

    def _release_at_pick(self) -> Release | None:
        """The visible release under the pick, or ``None`` when there is none.

        Unlike :meth:`_picked` this answers while the search bar is active: the
        hint line describes the row the pick sits on, and the bar takes every
        printable key before a selection action could fire anyway.
        """
        visible = self.app.visible_versions()
        position = self.app.win.pick_pos
        if 0 <= position < len(visible):
            return visible[position]
        return None

    def _draw_body(self) -> None:
        win = self.app.win
        # The loading frame is drawn by load_versions(); it deliberately shows
        # no releases, so the old package's rows cannot be mistaken for new.
        if self.app.loading:
            win.add_body(
                'Loading ...',
                attr=semantic_attr(Theme.HOTSWAP),
                context=Context(genre='DECOR'),
            )
            return
        state = self.app.state
        if state.status == ERROR:
            self._draw_error_body(state)
            return
        versions = self.app.visible_versions()
        if not versions:
            win.add_body(
                ('No matching releases.' if self.app.search_text
                 else 'No releases found.'),
                attr=curses.A_DIM,
                context=Context(genre='DECOR'),
            )
            return
        now = datetime.now(UTC)
        mode = self._time_mode()
        # Once anything is marked, the surviving releases are the interesting
        # rows: paint them in SUCCESS.  A marked row keeps its DEL cell plain
        # so the marker stays legible and dims the rest of the line.
        keep_attr = semantic_attr(Theme.SUCCESS) if self._marked_count() else None
        for index, release in enumerate(versions):
            row = format_row(release, now, mode)
            context = Context(genre='item', release=release, index=index)
            if release.delete:
                win.add_body(row[:DEL_WIDTH], context=context)
                win.add_body(row[DEL_WIDTH:], attr=curses.A_DIM, resume=True)
            else:
                win.add_body(row, attr=keep_attr, context=context)

    def _draw_error_body(self, state: PackageState) -> None:
        """Draw a never-loaded pair's failure instead of a release table.

        The body is the only explanation for an ``ERROR`` pair: no popup
        interrupts the first load.  A missing package answers with one line;
        anything else shows the age, a blank line, and the wrapped description
        an alert would have contained.  Every line carries the same HOTSWAP
        role, so the block reads as one piece of state rather than as rows.
        """
        win = self.app.win
        attr = semantic_attr(Theme.HOTSWAP)
        context = Context(genre='DECOR')
        now = self.app.clock()
        start = state.last_attempt_at
        age = compact_delta_time(now if start is None else start, now)
        if state.no_package:
            win.add_body(f'NO PACKAGE [{age}]', attr=attr, context=context)
            return
        win.add_body(f'ERROR [{age}]', attr=attr, context=context)
        win.add_body('', attr=attr, context=context)
        width = max(ERROR_TEXT_WIDTH, min(win.get_pad_width(), 78))
        for index, paragraph in enumerate(state.error_message.split('\n\n')):
            if index:
                win.add_body('', attr=attr, context=context)
            for line in textwrap.wrap(
                paragraph, width=width, break_on_hyphens=False
            ):
                win.add_body(line, attr=attr, context=context)

    # --- selection -------------------------------------------------------
    #
    # Every body row is a release, so the release with visible-row index *i*
    # is body row *i*; the column titles live in the header and can never be
    # picked.  The model index may differ while a search is filtering the
    # table, which is why the actions slice the visible list.

    def _picked(self) -> Context | None:
        """The context of the release under the pick, or None off the rows."""
        ctx = self.app.win.get_picked_context()
        if ctx is None or not hasattr(ctx, 'release'):
            return None
        return ctx

    def _pick_release(self, index: int) -> None:
        """Point the pick at the visible row *index*."""
        self.app.win.pick_pos = index

    def mark_ACTION(self) -> None:
        """Mark the picked release and advance to the next visible one."""
        ctx = self._picked()
        if ctx is None:
            return
        visible = self.app.visible_versions()
        ctx.release.delete = True
        if ctx.index + 1 < len(visible):
            self._pick_release(ctx.index + 1)

    def mark_from_here_ACTION(self) -> None:
        """Mark the picked visible row and every visible row below it.

        The hint line offers ``X`` on an unmarked row only: with the pick
        already marked the gesture has nothing to add, and the line has swapped
        in ``U`` for it, so a marked row leaves this key inert.
        """
        ctx = self._picked()
        if ctx is None or ctx.release.delete:
            return
        visible = self.app.visible_versions()
        for release in visible[ctx.index:]:
            release.delete = True
        # The row above the block is the last release the cut keeps: parking
        # the pick there (and never above the first release) shows the boundary.
        self._pick_release(max(ctx.index - 1, 0))

    def unmark_ACTION(self) -> None:
        """Unmark the picked visible row, then step down like ``x`` does."""
        ctx = self._picked()
        if ctx is None:
            return
        visible = self.app.visible_versions()
        ctx.release.delete = False
        if ctx.index + 1 < len(visible):
            self._pick_release(ctx.index + 1)

    def unmark_from_here_ACTION(self) -> None:
        """Unmark the picked visible row and every visible row below it.

        The mirror of :meth:`mark_from_here_ACTION`: ``U`` is offered on a
        marked row only, so an unmarked row leaves it inert.
        """
        ctx = self._picked()
        if ctx is None or not ctx.release.delete:
            return
        visible = self.app.visible_versions()
        for release in visible[ctx.index:]:
            release.delete = False
        self._pick_release(max(ctx.index - 1, 0))

    def delete_ACTION(self) -> None:
        """Hand the marked releases to ``pypi-cleanup`` and wait to come back.

        The key is inert whenever its block is blank -- nothing marked, a
        pattern filtering the table, or a read-only run -- so a hidden release
        can never be swept up by a deletion the user could not see coming.  The
        marked versions are read in table order, so the dry run and the
        deletion name exactly the rows that were on screen.

        A marking that covers the whole history cannot go through, because
        ``pypi-cleanup`` refuses to leave a package with no release at all:
        the newest release is unmarked first and the hand-off says so.  With a
        history that holds only that one release there is nothing left to ask
        about, so the answer is a brief box instead of the bare terminal.
        """
        if not self._deletion_offered():
            return
        releases = self.app.cleanup.versions
        notice = None
        given_back = unmark_newest_marked(releases)
        if given_back is not None:
            if not any(release.delete for release in releases):
                self.app.win.flash(
                    LAST_VERSION_MESSAGE,
                    duration=LAST_VERSION_FLASH_SECONDS,
                )
                return
            notice = UNMARKED_NEWEST_NOTICE.format(version=given_back.version)
        self.app.hand_off_to_cleanup(
            [release.version for release in releases if release.delete],
            notice=notice,
        )

    def apply_gap_ACTION(self) -> None:
        """Keep the marked releases that stayed current for the stability gap.

        ``g`` rotates the gap on the help screen and applies it here.  The whole
        history is judged, not just the visible rows, because whether a release
        was followed quickly is a fact about the package and not about the
        filter; the key only ever unmarks, so a hidden release cannot be swept
        up by it.  The flash always answers, even with nothing marked, because
        otherwise a hidden key would look broken.
        """
        app = self.app
        gap = self._gap_days()
        marked = self._marked_count()
        stable = stable_releases(
            app.cleanup.versions, gap, self._time_mode())
        for release in stable:
            release.delete = False
        app.win.flash(
            f'Kept {len(stable)} of {marked} marked versions, gap {gap} days',
            duration=2.0,
        )

    def sort_ACTION(self) -> None:
        """Flip the table between version order and upload-date order."""
        cleanup = self.app.cleanup
        order = (SORT_BY_DATE if cleanup.sort == SORT_BY_VERSION
                 else SORT_BY_VERSION)
        cleanup.sort_versions(order)
        self.app.persist(sort=cleanup.sort)

    def search_ACTION(self) -> None:
        """Open the incremental search bar at the end of the hint line."""
        self.app.start_search()

    def packages_screen_ACTION(self) -> None:
        """Open the working package list, ready to open the next package."""
        app = self.app
        app.packages_pick = app.next_package_index()
        app.stack.push(PACKAGES_ST, app.win.pick_pos)

    def refresh_ACTION(self) -> None:
        """Fetch the current package again, carrying the marks onto the new rows.

        The table is rebuilt from a fresh query of the same package and index,
        so a release uploaded since the last fetch joins the list.  The marks
        are collected by version before ``load_versions`` drops the old rows,
        and every version the refreshed history still lists is marked again:
        the user decided about a release, not about the row it sat on, so a new
        upload above it must not undo the choice.  A failed fetch is different
        now: the restored stale table already carries its marks, so there is
        nothing to reapply and the user keeps the view they had.

        A refresh is also how a deletion is confirmed: the fetch settles the
        hidden versions, and when the last one is gone a brief ``Fresh`` says
        the table now matches the index instead of leaving the marker's
        disappearance unexplained.
        """
        app = self.app
        was_stale = app.state.status == STALE
        marked = {release.version for release in app.cleanup.versions
                  if release.delete}
        app.load_versions()
        if app.load_failed:
            return
        for release in app.cleanup.versions:
            if release.version in marked:
                release.delete = True
        if was_stale and app.state.status == LOADED:
            app.win.flash('Fresh', duration=2.0)

    def package_next_ACTION(self) -> None:
        """Show the next package in the remembered list and reload it.

        A list holding only the current package has no next package, which
        keeps ``p`` from reloading what is already on screen.
        """
        app = self.app
        next_index = app.next_package_index()
        if next_index is None or app.packages[next_index] == app.cleanup.package:
            return
        app.package_index = next_index
        app.switch_to(app.packages[next_index], app.cleanup.host_key)

    def host_next_ACTION(self) -> None:
        """Switch between pypi.org and test.pypi.org and reload."""
        cleanup = self.app.cleanup
        target = HOST_TEST if cleanup.host_key == HOST_PYPI else HOST_PYPI
        self.app.persist(host=target)
        self.app.switch_to(cleanup.package, target)


class HelpScreen(CleanupScreen, BasicHelpScreen):
    """The key-help screen; ESC returns to the screen that opened it."""

    def extra_help_paragraphs(self) -> Iterable[str]:
        """The non-obvious bits under the option list, one short bullet each.

        The option list above already names every key, so these bullets are
        kept to what a key name cannot say and a developer would not guess.
        :meth:`draw_notes` adds the marker and the hanging indent, so the
        strings here carry none.
        """
        bullets = [
            '/ filters the version column only, as a case-insensitive regular '
            'expression; while a pattern is in force, only the visible rows '
            'can be marked.',
            'd never removes the whole history: pypi-cleanup keeps one '
            'release, so the newest is unmarked first, and a package with a '
            'single release is not offered for deletion at all.',
            'f refetches the package and keeps the marks; a failed fetch keeps '
            'the old table as STALE, and once the index stops listing a deleted '
            'version STALE clears and Fresh flashes.',
            'g is the stability gap: here it rotates 3, 7, 14, 30 or 60 days, '
            'on the table it unmarks the releases a newer one superseded within '
            'the gap, and the newest release counts as stable.',
            'With --totp-method expect (the default), press Ctrl+] at the '
            'Authentication code prompt and the TUI types the code.',
            'P is the working package list; x drops a name from the list, '
            'never from the index.',
        ]
        ini = self.app.ini
        if ini is not None:
            stored = ', '.join(
                f'{key}={getattr(ini.vals, key)!r}' for key in vars(ini.vals)
            )
            bullets.append(f'Saved options ({ini.config_file_path}): {stored}')
        return tuple(bullets)

    def draw_notes(self, win: ConsoleWindow | None = None) -> None:
        """Draw the bullets dim and wrapped, with a hanging indent.

        ``BasicHelpScreen.draw_notes`` wraps each paragraph flush left; a list
        reads better when the marker holds a column of its own and a continued
        line stays under the first line's text rather than under the marker.
        The wrap never breaks on hyphens, so an option name such as
        ``--read-only`` stays in one piece for the reader to copy.
        """
        target = win if win is not None else self.app.win
        paragraphs = list(self.extra_help_paragraphs())
        if self.show_display_notes:
            paragraphs.append(help_text.glyph_paragraph(target))
        width = max(getattr(target, 'cols', 80) - 8, 20)
        for paragraph in paragraphs:
            for line in textwrap.wrap(
                paragraph,
                width=width,
                initial_indent='* ',
                subsequent_indent='  ',
                break_on_hyphens=False,
            ):
                target.add_body(line, attr=curses.A_DIM)


class PackagesScreen(CleanupScreen):
    """The working package list, with a VERs/DELs pair for each index.

    The list is what ``p`` rotates through and what the command line remembers;
    removing a name here never touches the index itself.  Each row carries one
    ``VERs``/``DELs`` pair per host, and the pair for the index the table is
    using leads the row; a host label line above the column titles spans each
    pair.  ``ESC`` opens the picked package in the table and returns -- the
    pick starts on the package ``p`` would show next, so the two keys agree --
    ``x`` removes the picked name from the list, and ``?`` opens the help
    screen (whose ``ESC`` returns here, because the screen stack remembers who
    pushed it).  With the list emptied there is nothing to open, so ``ESC``
    leaves the program rather than returning to a table whose package list is
    empty.
    """

    def draw_screen(self) -> None:
        win = self.app.win
        win.set_pick_mode(True, 1)
        width = package_width(self.app.packages)
        hosts = package_host_order(self.app.cleanup.host_key)
        win.add_fancy_header(self._hint_line(), line_attr=curses.A_DIM)
        win.add_header(package_host_header(width, hosts), attr=curses.A_DIM)
        win.add_header(package_header(width, hosts), attr=curses.A_DIM)
        self._draw_body(width, hosts)
        self._place_pick()

    def _place_pick(self) -> None:
        """Consume the pending start row, scrolling it into view.

        ``P`` names the row the pick should start on, but a row only exists
        once the body has been built, so the placement waits for the draw.
        """
        start = self.app.packages_pick
        if start is None:
            return
        self.app.packages_pick = None
        win = self.app.win
        win.pick_pos = start
        win.scroll_pos = 0
        # fix_positions() clamps the row to the body and scrolls the viewport
        # down when the start row is below the fold.
        win.fix_positions()

    @staticmethod
    def _hint_line() -> HeaderLine:
        """The screen's name, then one block per key available here."""
        hints = HeaderLine()
        hints.label(PACKAGES_TITLE).text('  ')
        hints.bracket_key('x').text(':remove ')
        hints.bracket_key('ESC').text(':open ')
        hints.bracket_key('?').text(':help')
        return hints

    def _draw_body(self, width: int, hosts: Sequence[str]) -> None:
        win = self.app.win
        if not self.app.packages:
            win.add_body(
                'No packages in the list.',
                attr=curses.A_DIM,
                context=Context(genre='DECOR'),
            )
            return
        for name in self.app.packages:
            states = {
                host: self.app.state_for(name, host)
                for host in hosts
            }
            row = format_package_row(name, states, width, hosts)
            win.add_body(row, context=Context(genre='item', package=name))

    def _picked_package(self) -> str | None:
        """The package under the pick, or ``None`` off the rows."""
        ctx = self.app.win.get_picked_context()
        if ctx is None or not hasattr(ctx, 'package'):
            return None
        return ctx.package

    def escape_ACTION(self) -> None:
        """Open the picked package in the table, or leave when there is none.

        There is no "return without switching" on this screen: the pick starts
        on the next package, so ESC is the way to switch, and a table that
        already shows the picked package needs no second fetch.  An emptied
        list has no row to open, which is the only case that leaves the
        program.
        """
        app = self.app
        package = self._picked_package()
        if package is None:
            app.running = False
            return
        # Pop first: a switch may call load_versions(), which draws the
        # current screen while it fetches, and the loading frame must land on
        # the table, not on this list.
        app.stack.pop()
        app.select_package(package)

    def package_remove_ACTION(self) -> None:
        """Remove the picked name from the list, keeping the pick on a row."""
        package = self._picked_package()
        if package is None:
            return
        self.app.remove_package(package)
        count = len(self.app.packages)
        self.app.win.pick_pos = min(self.app.win.pick_pos, count - 1) if count else 0


class ThemeScreen(Theme.create_picker_screen(CleanupScreen, cycle_key='t')):
    """The color-theme picker: ``t`` cycles the choice, ESC returns.

    The picker's swatches follow the shared color switch, so cycling into the
    app's ``mono`` choice previews exactly what ``--no-color`` looks like: the
    same rows, painted with the role attributes instead of a palette.  The
    header names ``mono`` while color is off, because that is the choice in
    effect; a palette is what turns color back on.
    """

    def theme_label(self, theme_name: str | None) -> str:
        if not appearance.colors_enabled():
            return MONO_THEME
        return super().theme_label(theme_name)


def run_tui(
    cleanup: CleanupTui,
    backend: RenderBackend | None = None,
    singleton: bool = True,
    ini: IniManager | None = None,
    zone: str = UTC_MODE,
    theme: str | None = None,
    no_color: bool | None = None,
    sort: str = SORT_BY_VERSION,
    gap: int = DEFAULT_GAP,
    read_only: bool = False,
    packages: Sequence[str] | None = None,
    totp_method: str = DEFAULT_TOTP_METHOD,
) -> int:
    """Present *cleanup* in the terminal and return the process exit status."""
    return CleanupApp(
        cleanup,
        backend=backend,
        singleton=singleton,
        ini=ini,
        zone=zone,
        theme=theme,
        no_color=no_color,
        sort=sort,
        gap=gap,
        read_only=read_only,
        packages=packages,
        totp_method=totp_method,
    ).run()
