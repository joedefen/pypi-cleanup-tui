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
machine's local zone; the ``DATE`` title names the zone in force.  ``s`` flips
the table between version order and upload-date order, and the sorted column
carries a ``*`` before its title.  Both settings are stored as soon as they
change, so the next run opens the table the way this one left it; the help
screen lists the saved options.

``/`` opens an incremental search at the end of the hint line; the bare ``/``
is always shown, even with an empty pattern.  The pattern is a case-insensitive
regular expression (the same shape as vappman's filter) matched against the
version column; typing narrows the table, ``ENTER`` closes the pattern and
``ESC`` restores the text it started with.  A pattern that is empty -- or not
yet a valid expression, as while a character class is being typed -- leaves
the table unfiltered rather than flashing it empty.  Once the pattern is
closed, ``x``, ``X``, ``u`` and ``U`` act on the visible rows only.

``T`` opens the THEMES screen, where ``t`` cycles the color theme and ``ESC``
returns to the table.  The theme key is listed on the help screen only, not in
the hint line.  The app's ``mono`` choice is not a palette: it turns semantic
color off, exactly like ``--no-color``, and the choice is remembered for the
next run just like the other saved options.

``d`` is advertised at the front of the hint line once anything is marked and
no pattern is in force: a filtered table can hide the releases a deletion would
act on.  Pressing it leaves curses -- the way vappman runs an external command
-- shows the ``pypi-cleanup`` command built from the marked versions, asks for
a dry run, shows what that run reports, and then asks before deleting for
real.  Both questions take ``yes``, ``no``, or a bare ENTER, which chooses the
safe answer: the dry run is on by default and the deletion is off.  A deletion
that fails is offered again behind a ``RETRY:`` prompt until it succeeds or the
user declines.  Once a deletion succeeds the table re-queries the package and
drops every trace of the old view -- markings, the search pattern and the pick
-- exactly as if the package/host pair had just been entered, so the refreshed
history is what the user sees when the final ENTER brings the table back.  A
``--read-only`` run never offers ``d``: the hint block reads ``R/O`` instead,
always.

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
run has loaded the package, its name, how many versions the history held, and
how many versions this run has deleted; both numbers show ``-`` until the
package is loaded.  The pick starts on the package ``p`` would show next, so
``ESC`` -- which opens the picked package in the table and returns -- is one
keypress from the table's package to the next one; with the list emptied there
is nothing to open, so ``ESC`` leaves the program instead.  ``x`` removes the
name from the list (the index keeps it), and ``?`` opens the help screen, whose
``ESC`` returns to the list.  The list is what the command line remembers, and
package arguments are cumulative: a run's names go in front of the stored ones
with duplicates dropped, keeping the first.
"""

from __future__ import annotations

import bisect
import curses
import os
import re
import subprocess
import textwrap
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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

from pypi_cleanup_tui.main import (
    CLEANUP_TOOL,
    DEFAULT_GAP,
    GAP_CHOICES,
    HOST_PYPI,
    HOST_TEST,
    LOCAL_MODE,
    MONO_THEME,
    SORT_BY_DATE,
    SORT_BY_VERSION,
    UTC_MODE,
    ZONES,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterable, Mapping, Sequence
    from datetime import tzinfo

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

#: The package list's untitled check column and its two numeric columns.
CHECK_WIDTH = 1
VERS_WIDTH = 5
DELS_WIDTH = 5
PACKAGE_TITLE = "PACKAGE"

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
        '-u', cleanup.user or os.environ.get('USER', ''),
        '-t', cleanup.host_url,
        '-p', cleanup.package,
        '-r', pattern,
    ]
    return command


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


def format_command(command: Sequence[str], width: int = COMMAND_WIDTH) -> str:
    """Lay *command* out the way the hand-off prints it.

    The values are always quoted, a value too long for one line is broken
    after its ``|`` alternations, and no ``\\`` is printed at the end of a
    line.  The result is a description of the run, not a line to paste into a
    shell: it omits the phase switch, and a split line would not survive a
    copy.  ``pypi-cleanup`` is handed the argument list itself, so the printed
    text is never what runs.
    """
    lines: list[str] = []
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


def run_cleanup(command: Sequence[str]) -> int:
    """Run *command* on the bare terminal and return its exit status.

    The argument list goes to :func:`subprocess.call` without a shell, so the
    pattern :func:`cleanup_command` built reaches ``pypi-cleanup`` exactly as
    written -- the backslashes ``re.escape`` added are not eaten by a shell.  A
    missing executable is reported rather than raised, so the table can still
    come back.
    """
    try:
        return subprocess.call(list(command))
    except OSError as error:
        print(f'error: could not run {CLEANUP_TOOL}: {error}')
        return 1


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


def days_ago(release: Release, now: datetime | None = None) -> int:
    """Whole days between *release*'s upload time and *now* (UTC).

    A clock skewed into the future would otherwise produce a negative age; the
    table shows ``0`` for a release that is not older than the current moment.
    """
    now = now or datetime.now(timezone.utc)
    return max((now - release.uploaded).days, 0)


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
        f"{days_ago(release, now):>{DAYS_WIDTH}}"
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


def stable_releases(versions: Sequence[Release], gap: int) -> list[Release]:
    """The marked releases that stayed current for at least *gap* days.

    A release is stable when the next release in the history arrived more than
    *gap* days after it, or never did because it is still the newest.  Those are
    the releases people actually installed, which is why the table's ``g``
    unmarks exactly these and so keeps them.  The comparison runs in upload
    order, whatever order the table is sorted in, and every release in the
    history counts: what was published next is a fact about the package, not
    about the marking.  Releases that are not marked are never returned.
    """
    times = sorted({release.uploaded for release in versions})
    limit = timedelta(days=gap)
    stable: list[Release] = []
    for release in versions:
        if not release.delete:
            continue
        index = bisect.bisect_right(times, release.uploaded)
        if index == len(times) or times[index] - release.uploaded > limit:
            stable.append(release)
    return stable


@dataclass
class PackageSession:
    """What this run has learned about one package in the working list.

    The package list draws from this ledger rather than from the model, so a
    package the run has not loaded cannot pretend to know its version count.
    ``deleted`` is waiting for the deletion step: it stays zero until a real
    deletion adds to it, which is why a visited package shows ``0`` rather than
    a made-up total.
    """

    #: True once :meth:`CleanupApp.load_versions` fetched this package.
    visited: bool = False
    #: Releases the history held at the last successful load.
    versions: int = 0
    #: Versions removed from this package during this run.
    deleted: int = 0


def package_width(packages: Sequence[str]) -> int:
    """The PACKAGE column width: the longest name, but never under the title."""
    return max([len(PACKAGE_TITLE), *(len(name) for name in packages)])


def package_header(width: int) -> str:
    """The package list's column titles; the check column stays untitled."""
    return (
        f"{' ' * (CHECK_WIDTH + 1)}"
        f"{PACKAGE_TITLE:<{width}} "
        f"{'VERs':>{VERS_WIDTH}} "
        f"{'DELs':>{DELS_WIDTH}}"
    )


def format_package_row(name: str, session: PackageSession, width: int) -> str:
    """Format one package-list row: check mark, name, version and delete totals.

    An unvisited package shows a blank check cell and ``-`` in both number
    columns: the screen must not suggest a count the run never fetched.
    """
    mark = VISITED_MARK if session.visited else ' '
    versions = str(session.versions) if session.visited else '-'
    deleted = str(session.deleted) if session.visited else '-'
    return (
        f"{mark:^{CHECK_WIDTH}} "
        f"{name:<{width}} "
        f"{versions:>{VERS_WIDTH}} "
        f"{deleted:>{DELS_WIDTH}}"
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
        #: This run's ledger per package: loaded or not, its version count and
        #: how many versions were deleted from it.  Kept on the application,
        #: not in the options file, because it describes only this session.
        self.session: dict[str, PackageSession] = {}
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
        # stored values the starting values: registration only normalises a
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
        # z rewrites the time zone the DATE column names.
        spin.add_key('time_zone', 'z - date time zone',
                     vals=list(ZONES), keys=[ord('z')],
                     scope={MAIN_ST})
        # t only works on the THEMES screen; handle_key() applies the palette
        # or the mono color mode as soon as the value changes.
        spin.add_key('theme', 't - cycle themes', vals=list(THEME_CHOICES),
                     keys=[ord('t')], scope={THEME_ST})
        # The stability gap is a hidden option: g rotates it on the help screen
        # and applies it on the table, so one key is bound twice with two
        # meanings -- a cycle on one screen, an action on the other.
        spin.add_key('gap', 'g - stability gap, in days', vals=list(GAP_CHOICES),
                     keys=[ord('g')], scope={HELP_ST})
        # T opens the picker; it is the only way in, and t is bound only on
        # that screen so the table keeps its own keys untouched.
        spin.add_key('theme_screen', 'T - themes', genre='action',
                     keys=[ord('T')], scope={MAIN_ST})
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

    def hand_off_to_cleanup(self, versions: Sequence[str]) -> None:
        """Leave curses for ``pypi-cleanup``, show the runs, and come back.

        The window is suspended, not stopped, the same way vappman runs its
        helper commands: ``endwin()`` restores the tty -- so the subprocess and
        its questions work -- and ``resume_curses()`` reattaches the screen,
        which the redrawing ``render()`` repaints from the preserved table.
        The flow is two runs: a ``--query-only`` dry run, then a ``--do-it``
        deletion that is retried until it succeeds; each question defaults to
        the harmless answer, a bare ENTER takes it, and anything but ``yes`` or
        ``no`` re-asks.  Answering no to the dry run only skips it; the deletion
        still needs its own yes.  A deletion that succeeds makes the table
        re-query the package, so the view the user returns to is the history
        that is actually left, not the one the marks were made against.
        """
        base = cleanup_command(self.cleanup, versions)
        package = self.cleanup.package
        count = len(versions)
        deleted = 0
        self.win.suspend_curses()
        try:
            _reset_terminal()
            print(format_command(base))
            print()
            if ask_yes_no(DRY_RUN_PROMPT, default=True):
                query = cleanup_command(self.cleanup, versions, QUERY_ONLY)
                print(format_command(query))
                print(summary_line('Dry run', package, run_cleanup(query)))
                print()
            if ask_yes_no(
                DELETE_PROMPT.format(count=count, package=package),
                default=False,
            ):
                if self._delete_with_retry(versions, package, count):
                    deleted = count
            press_enter()
        finally:
            self.win.resume_curses()
        if deleted:
            self.reload_after_deletion(deleted)
        self.win.render(redraw=True)

    def _delete_with_retry(
        self,
        versions: Sequence[str],
        package: str,
        count: int,
    ) -> bool:
        """Run the ``--do-it`` deletion, reissuing it until it succeeds.

        ``pypi-cleanup`` reports success through its exit status.  A run that
        fails is offered again behind a ``RETRY:`` prompt, because the marked
        versions have not changed while the terminal was idle and the same
        command can be repeated; the loop ends when a run succeeds or the user
        declines.  Returns whether the marked versions were deleted.
        """
        while True:
            destroy = cleanup_command(self.cleanup, versions, DO_IT)
            print(format_command(destroy))
            status = run_cleanup(destroy)
            print(summary_line('Deletion', package, status))
            print()
            if status == 0:
                return True
            if not ask_yes_no(
                RETRY_PROMPT.format(count=count, package=package),
                default=False,
            ):
                return False

    def reload_after_deletion(self, deleted: int) -> None:
        """Fetch the package again after a successful deletion.

        A deletion changes the history, so the table is rebuilt from a fresh
        query and every trace of the old view -- the marks, the search pattern
        and the pick -- is dropped, exactly as if the package/host pair had
        just been entered.  The session ledger keeps the count, so the package
        list's DELs column reflects what this run actually removed.
        """
        session = self.package_session(self.cleanup.package)
        session.deleted += deleted
        self.search_text = ''
        self.search_re = None
        self.search_anchor = None
        self.load_versions()

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

    def package_session(self, package: str) -> PackageSession:
        """This run's ledger for *package*, created empty on first look."""
        return self.session.setdefault(package, PackageSession())

    def note_loaded(self) -> None:
        """Record that the current package's history has just been fetched."""
        session = self.package_session(self.cleanup.package)
        session.visited = True
        session.versions = len(self.cleanup.versions)

    def select_package(self, package: str) -> None:
        """Make *package* the table's package without fetching it.

        The package list only offers names it holds, so a name that is not in
        the list is ignored rather than added behind the user's back.
        """
        if package not in self.packages:
            return
        self.package_index = self.packages.index(package)
        self.cleanup.package = package

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
        """Clear the table, show ``Loading ...``, then fetch and sort.

        The failure path is a modal alert carrying the exception type and
        text; the table is left empty so the user can pick another package
        (``p``) or index (``h``) instead of losing the terminal.
        """
        self.loading = True
        self.load_failed = False
        self.cleanup.versions = []
        self.win.pick_pos = 0
        self.win.clear()
        self._draw_current_screen()
        self.win.render()
        try:
            self.cleanup.fetch_versions()
        except Exception as exc:
            # A lookup, network or JSON failure is the same to the user: show
            # the details and let them choose another package or index.
            self.load_failed = True
            self.win.alert(
                f'Could not load {self.cleanup.package!r} from '
                f'{self.cleanup.host}.\n\n'
                f'{type(exc).__name__}: {exc}',
                title='LOAD ERROR',
            )
            return
        finally:
            self.loading = False
            self.win.clear()
        self.cleanup.sort_versions(self.sort)
        # Only a successful fetch makes the package visited: a failed one has
        # no version count, and the package list must not invent a zero.
        self.note_loaded()

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
        # into one word with the key underlined ("sort", "zone", "quit").  The
        # from-here-down keys trade "-all" for the arrow glyph.
        hints.bracket_key('s').text('ort ')
        hints.bracket_key('z').text('one ')
        # The gap in force, because g applies it right here.  The number is
        # padded so a one-digit gap does not move the keys to its right.
        hints.bracket_key('g').text(f'ap{self._gap_days():<{GAP_HINT_WIDTH}} ')
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
        summary.text(f'User={cleanup.user or "n/a"} ')
        summary.bracket_key('p').text(f'ack={cleanup.package} ')
        summary.bracket_key('h').text(f'ost={cleanup.host_key}')
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
        versions = self.app.visible_versions()
        if not versions:
            # A failed load is already explained by the alert; an empty body
            # avoids claiming the history really has no releases.
            if self.app.load_failed:
                return
            win.add_body(
                ('No matching releases.' if self.app.search_text
                 else 'No releases found.'),
                attr=curses.A_DIM,
                context=Context(genre='DECOR'),
            )
            return
        now = datetime.now(timezone.utc)
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
        """
        if not self._deletion_offered():
            return
        self.app.hand_off_to_cleanup([
            release.version
            for release in self.app.cleanup.versions
            if release.delete
        ])

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
        stable = stable_releases(app.cleanup.versions, gap)
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

    def theme_screen_ACTION(self) -> None:
        self.app.stack.push(THEME_ST, self.app.win.pick_pos)

    def packages_screen_ACTION(self) -> None:
        """Open the working package list, ready to open the next package."""
        app = self.app
        app.packages_pick = app.next_package_index()
        app.stack.push(PACKAGES_ST, app.win.pick_pos)

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
        app.cleanup.package = app.packages[next_index]
        app.load_versions()

    def host_next_ACTION(self) -> None:
        """Switch between pypi.org and test.pypi.org and reload."""
        cleanup = self.app.cleanup
        cleanup.host_key = (
            HOST_TEST if cleanup.host_key == HOST_PYPI else HOST_PYPI
        )
        self.app.persist(host=cleanup.host_key)
        self.app.load_versions()


class HelpScreen(CleanupScreen, BasicHelpScreen):
    """The key-help screen; ESC returns to the screen that opened it."""

    def extra_help_paragraphs(self) -> Iterable[str]:
        """The essentials under the option list, one short bullet each.

        The option list above already names every key, so these bullets only
        say what a key name cannot: what a value means, which screen a key
        acts on, and what the next step is.  :meth:`draw_notes` adds the
        marker and the hanging indent, so the strings here carry none.
        """
        bullets = [
            help_text.theme_paragraph(
                open_key='T',
                cycle_key='t',
                remembered=self.app.ini is not None,
            ),
            '/ opens the incremental search at the end of the hint line. The '
            'pattern is a case-insensitive regular expression matched against '
            'the version column; ENTER closes it, ESC restores it, and a '
            'closed pattern limits x, X, u and U to the visible rows only.',
            'The hint line follows the pick: an unmarked row offers x and X, a '
            'marked row u and U instead. X and U are inert on a row already in '
            'the state they would produce.',
            'd hands the marked releases to pypi-cleanup. It leaves the table '
            'for the terminal, shows the command, asks for a --query-only dry '
            'run, then asks again before the --do-it deletion; ENTER takes the '
            'safe answer (yes to the dry run, no to the deletion) and only '
            'yes or no are accepted. A failed deletion is offered again behind '
            'a RETRY: prompt until it succeeds or is declined, and a successful '
            'one re-queries the package and clears the marks, search and pick '
            'as if the package had just been opened. The printed command '
            'describes the run and is not meant to be copied. A read-only run '
            '(--read-only) never offers d: the hint line reads R/O in its place.',
            'g is the stability filter. On this screen it rotates the gap -- '
            '3, 7, 14, 30 or 60 days; a run starts at 30 and remembers the '
            'choice -- and on the main screen it unmarks every marked release '
            'that no newer release followed within that gap, keeping the ones '
            'that stayed current. The newest release counts as stable too, '
            'because nothing followed it, and the whole table is judged, not '
            'just the visible rows.',
            'P opens the working package list. ESC opens the picked package, x '
            'removes it, and package arguments are cumulative across runs.',
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
            ):
                target.add_body(line, attr=curses.A_DIM)


class PackagesScreen(CleanupScreen):
    """The working package list, with this session's totals beside each name.

    The list is what ``p`` rotates through and what the command line remembers;
    removing a name here never touches the index itself.  ``ESC`` opens the
    picked package in the table and returns -- the pick starts on the package
    ``p`` would show next, so the two keys agree -- ``x`` removes the picked
    name from the list, and ``?`` opens the help screen (whose ``ESC`` returns
    here, because the screen stack remembers who pushed it).  With the list
    emptied there is nothing to open, so ``ESC`` leaves the program rather than
    returning to a table whose package list is empty.
    """

    def draw_screen(self) -> None:
        win = self.app.win
        win.set_pick_mode(True, 1)
        width = package_width(self.app.packages)
        win.add_fancy_header(self._hint_line(), line_attr=curses.A_DIM)
        win.add_header(package_header(width), attr=curses.A_DIM)
        self._draw_body(width)
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

    def _draw_body(self, width: int) -> None:
        win = self.app.win
        if not self.app.packages:
            win.add_body(
                'No packages in the list.',
                attr=curses.A_DIM,
                context=Context(genre='DECOR'),
            )
            return
        for name in self.app.packages:
            row = format_package_row(name, self.app.package_session(name), width)
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
        changed = package != app.cleanup.package
        app.select_package(package)
        # Pop first: load_versions() draws the current screen while it fetches,
        # and the loading frame must land on the table, not on this list.
        app.stack.pop()
        if changed:
            app.load_versions()

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
    ).run()
