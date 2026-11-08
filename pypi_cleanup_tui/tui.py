"""Interactive terminal interface for pypi-cleanup-tui.

The window presents the release history fetched by
:class:`pypi_cleanup_tui.main.CleanupTui` as a table and lets the user mark the
releases to delete.  It is selection only: nothing is uploaded, deleted or
shelled out to yet, so every key here is safe to experiment with.

Three header lines sit above the table: the key hints, the project summary, and
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

``z`` cycles the time zone used by the ``DATE`` column between UTC and the
machine's local zone; the ``DATE`` title names the zone in force.  ``s`` flips
the table between version order and upload-date order -- it is listed on the
help screen only -- and the sorted column carries a ``*`` before its title.

``d`` is advertised at the front of the hint line once anything is marked.  It
is a placeholder for the deletion step: it reports the pending count in a short
message box, because deletion itself is not wired up yet.
"""

from __future__ import annotations

import curses
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import TYPE_CHECKING

from console_window import (
    BasicHelpScreen,
    ConsoleWindow,
    ConsoleWindowOpts,
    Context,
    Glyph,
    HeaderLine,
    OptionSpinner,
    Screen,
    ScreenStack,
    Theme,
    semantic_attr,
)

from pypi_cleanup_tui.main import SORT_BY_DATE, SORT_BY_VERSION

if TYPE_CHECKING:  # pragma: no cover - typing only
    from datetime import tzinfo

    from console_window.backend import RenderBackend

    from pypi_cleanup_tui.main import CleanupTui, Release

MAIN_ST = 0
HELP_ST = 1
SCREEN_NAMES = ("MAIN", "HELP")

#: Marker drawn in the DEL column of a release that will be deleted.  It is
#: declared to the window as a glyph, so a terminal without the character draws
#: a plain ``x`` instead of losing the meaning of the column.
DEL_MARK = "✘"

#: The "from here down" arrow in the hint line.  console-window already owns
#: this character as its ``alert_down`` glyph, so an ASCII terminal draws a
#: plain ``v`` without any registration here.
DOWN_MARK = "▼"

#: The two values of the ``z`` spinner: show the upload time as recorded (UTC),
#: or converted to the machine's local time zone.
UTC_MODE = "UTC"
LOCAL_MODE = "Local"

#: Column widths.  ``DATE`` is ``YYYY/MM/DD HH:MM`` (16 cells); ``DAYS`` is
#: right-aligned because it is the only numeric column.
DEL_WIDTH = 3
DATE_WIDTH = 16
DAYS_WIDTH = 5
VERSION_GAP = 2


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


class CleanupApp:
    """The console-window application showing one project's release history."""

    def __init__(
        self,
        cleanup: CleanupTui,
        backend: RenderBackend | None = None,
        singleton: bool = True,
    ) -> None:
        self.cleanup = cleanup
        self.running = True
        self.opts = SimpleNamespace()

        win_opts = ConsoleWindowOpts(
            head_line=True,
            min_cols_rows=(60, 10),
            # Ctrl-C must not tear the TUI down.  Leaving 0x3 unbound means the
            # window swallows it instead of dispatching a quit action.
            ctrl_c_terminates=False,
            # The deletion marker is decoration, so the window owns its ASCII
            # fallback and rewrites it when the terminal cannot draw it.
            glyphs={'delete_mark': Glyph(DEL_MARK, 'x')},
        )
        self.win = ConsoleWindow(opts=win_opts, backend=backend, singleton=singleton)

        screens = self.screens = {
            MAIN_ST: MainScreen(self),
            HELP_ST: HelpScreen(self),
        }
        self.stack = ScreenStack(self.win, self.opts, SCREEN_NAMES, screens)

        spin = self.spin = OptionSpinner(stack=self.stack)
        spin.add_key('quit', 'q - quit', genre='action', keys=[ord('q')])
        spin.add_key('help_screen', '? - help', genre='action',
                     keys=[ord('?')], scope={MAIN_ST})
        spin.add_key('escape', 'ESC - back', genre='action',
                     keys=[27], scope={HELP_ST})
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
        # Placeholder for the deletion step: the hint only appears once
        # something is marked, and pressing d reports the pending count.
        spin.add_key('delete', 'd - delete the marked versions (TODO)',
                     genre='action', keys=[ord('d')], scope={MAIN_ST})
        # A cycle, not an action: z rewrites the option in place and the next
        # draw reads it, so there is no time_zone_ACTION method to implement.
        spin.add_key('time_zone', 'z - date time zone',
                     vals=[UTC_MODE, LOCAL_MODE], keys=[ord('z')],
                     scope={MAIN_ST})
        # Sorting changes the model rather than a spinner value, so it is an
        # action; the help screen is the only place it is advertised.
        spin.add_key('sort', 's - change the sort order',
                     genre='action', keys=[ord('s')], scope={MAIN_ST})
        self.win.set_handled_keys(spin.keys)

    def handle_key(self, key: int) -> None:
        """Route one key returned by the window to the spinner's action."""
        if key in self.spin.keys:
            self.spin.do_key(key, self.win)

    def main_loop(self) -> None:
        """Draw the current screen until an action clears :attr:`running`."""
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
    """Base screen: every screen can receive the global quit action."""

    app: CleanupApp

    def quit_ACTION(self) -> None:
        self.app.running = False


class MainScreen(CleanupScreen):
    """The release table."""

    def draw_screen(self) -> None:
        win = self.app.win
        win.set_pick_mode(True, 1)
        self._draw_headers()
        self._draw_body()

    def _time_mode(self) -> str:
        """The ``D`` spinner's current value; UTC until the spinner is read."""
        return self.app.spin.get_value('time_zone') or UTC_MODE

    def _draw_headers(self) -> None:
        win = self.app.win
        hints = HeaderLine()
        # Once something is marked, the deletion placeholder leads the line.
        if self._marked_count():
            hints.bracket_key('d').text('el ')
        # Where the label starts with the key itself, the bracket form merges
        # into one word with the key underlined ("unmark", "zone", "quit").
        # The from-here-down keys trade "-all" for the arrow glyph.
        hints.bracket_key('x').text(':mark ')
        hints.bracket_key('X').text(f':mark{DOWN_MARK} ')
        hints.bracket_key('u').text('nmark ')
        hints.bracket_key('U').text(f'nmark{DOWN_MARK} ')
        hints.bracket_key('z').text('one ')
        hints.bracket_key('q').text('uit ')
        hints.bracket_key('?').text(':help')
        win.add_fancy_header(hints, line_attr=curses.A_DIM)

        cleanup = self.app.cleanup
        win.add_header(
            f'User: {cleanup.user or "-"}   '
            f'Project: {cleanup.package}   '
            f'Index: {cleanup.host}'
        )
        # The column titles are the third header line: dim, and deliberately
        # not underlined, so the releases below stay the visually strongest
        # thing on the screen.  The sorted column carries the star.
        win.add_header(
            column_header(self._time_mode(), cleanup.sort),
            attr=curses.A_DIM,
        )

    def _marked_count(self) -> int:
        """How many releases are currently marked for deletion."""
        return sum(1 for release in self.app.cleanup.versions if release.delete)

    def _draw_body(self) -> None:
        win = self.app.win
        versions = self.app.cleanup.versions
        if not versions:
            win.add_body(
                'No releases found.',
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
    # Every body row is a release, so the release with list index *i* is body
    # row *i*; the column titles live in the header and can never be picked.

    def _picked(self) -> Context | None:
        """The context of the release under the pick, or None off the rows."""
        ctx = self.app.win.get_picked_context()
        if ctx is None or not hasattr(ctx, 'release'):
            return None
        return ctx

    def _pick_release(self, index: int) -> None:
        """Point the pick at the release with list *index*."""
        self.app.win.pick_pos = index

    def mark_ACTION(self) -> None:
        """Mark the picked release and advance to the next one, if any."""
        ctx = self._picked()
        if ctx is None:
            return
        ctx.release.delete = True
        if ctx.index + 1 < len(self.app.cleanup.versions):
            self._pick_release(ctx.index + 1)

    def mark_from_here_ACTION(self) -> None:
        """Mark the picked release and all below it, then step up one row."""
        ctx = self._picked()
        if ctx is None:
            return
        for release in self.app.cleanup.versions[ctx.index:]:
            release.delete = True
        # The row above the block is the last release the cut keeps: parking
        # the pick there (and never above the first release) shows the boundary.
        self._pick_release(max(ctx.index - 1, 0))

    def unmark_ACTION(self) -> None:
        """Unmark the picked release, then step down like ``x`` does."""
        ctx = self._picked()
        if ctx is None:
            return
        ctx.release.delete = False
        if ctx.index + 1 < len(self.app.cleanup.versions):
            self._pick_release(ctx.index + 1)

    def unmark_from_here_ACTION(self) -> None:
        """Unmark the picked release and all below it, then step up one row."""
        ctx = self._picked()
        if ctx is None:
            return
        for release in self.app.cleanup.versions[ctx.index:]:
            release.delete = False
        self._pick_release(max(ctx.index - 1, 0))

    def delete_ACTION(self) -> None:
        """Report the pending deletions; the real deletion is still a TODO."""
        count = self._marked_count()
        if not count:
            return
        self.app.win.flash(f'To delete {count} versions [TODO]', duration=2.0)

    def sort_ACTION(self) -> None:
        """Flip the table between version order and upload-date order."""
        cleanup = self.app.cleanup
        order = (SORT_BY_DATE if cleanup.sort == SORT_BY_VERSION
                 else SORT_BY_VERSION)
        cleanup.sort_versions(order)

    def help_screen_ACTION(self) -> None:
        self.app.stack.push(HELP_ST, self.app.win.pick_pos)


class HelpScreen(CleanupScreen, BasicHelpScreen):
    """The key-help screen; ESC returns to the release table."""

    def escape_ACTION(self) -> None:
        self.app.stack.pop()


def run_tui(
    cleanup: CleanupTui,
    backend: RenderBackend | None = None,
    singleton: bool = True,
) -> int:
    """Present *cleanup* in the terminal and return the process exit status."""
    return CleanupApp(cleanup, backend=backend, singleton=singleton).run()
