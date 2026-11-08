"""Interactive terminal interface for pypi-cleanup-tui.

The window presents the release history fetched by
:class:`pypi_cleanup_tui.main.CleanupTui` as a table and lets the user mark the
releases to delete.  It is selection only: nothing is uploaded, deleted or
shelled out to yet, so every key here is safe to experiment with.

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

``z`` cycles the time zone used by the ``DATE`` column between UTC and the
machine's local zone; the ``DATE`` title names the zone in force.  ``s`` flips
the table between version order and upload-date order -- it is listed on the
help screen only -- and the sorted column carries a ``*`` before its title.
Both settings are stored as soon as they change, so the next run opens the
table the way this one left it; the help screen lists the saved options.

``T`` opens the THEMES screen, where ``t`` cycles the color theme and ``ESC``
returns to the table.  The app's ``mono`` choice is not a palette: it turns
semantic color off, exactly like ``--no-color``, and the choice is remembered
for the next run just like the other saved options.

``d`` is advertised at the front of the hint line once anything is marked.  It
is a placeholder for the deletion step: it reports the pending count in a short
message box, because deletion itself is not wired up yet.
"""

from __future__ import annotations

import curses
import os
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
    appearance,
    semantic_attr,
)
from console_window import help as help_text

from pypi_cleanup_tui.main import (
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
SCREEN_NAMES = ("MAIN", "HELP", "THEMES")

#: Every choice the picker cycles through.  ``mono`` is the app's pseudo-theme,
#: not a console-window palette; keeping it last makes ``t`` step from the final
#: palette into mono and wrap back to the first palette.
THEME_CHOICES = (*Theme.list_all(), MONO_THEME)

#: Marker drawn in the DEL column of a release that will be deleted.  It is
#: declared to the window as a glyph, so a terminal without the character draws
#: a plain ``x`` instead of losing the meaning of the column.
DEL_MARK = "✘"

#: The "from here down" arrow in the hint line.  console-window already owns
#: this character as its ``alert_down`` glyph, so an ASCII terminal draws a
#: plain ``v`` without any registration here.
DOWN_MARK = "▼"

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
        packages: Sequence[str] | None = None,
    ) -> None:
        self.cleanup = cleanup
        #: Optional persistent options.  Without one the TUI runs exactly as
        #: before: changes apply to this session and are not written anywhere.
        self.ini = ini
        self.running = True
        #: The package list the command line supplied, shown one at a time.
        #: ``p`` rotates through it; the model's package is the current entry.
        self.packages = list(packages) if packages else [cleanup.package]
        if cleanup.package not in self.packages:
            self.packages.insert(0, cleanup.package)
        self.package_index = self.packages.index(cleanup.package)
        #: The order restored after every fetch, so a reload keeps the table
        #: the way the user arranged it.
        self.sort = sort
        #: State for the frame drawn while :meth:`load_versions` fetches.
        self.loading = False
        self.load_failed = False

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

        win_opts = ConsoleWindowOpts(
            head_line=True,
            min_cols_rows=(60, 10),
            # Ctrl-C must not tear the TUI down.  Leaving 0x3 unbound means the
            # window swallows it instead of dispatching a quit action.
            ctrl_c_terminates=False,
            # Seed the palette explicitly so the window does not inherit one
            # left behind by a previous run in the same process.
            theme=palette,
            # The deletion marker is decoration, so the window owns its ASCII
            # fallback and rewrites it when the terminal cannot draw it.
            glyphs={'delete_mark': Glyph(DEL_MARK, 'x')},
        )
        self.win = ConsoleWindow(opts=win_opts, backend=backend, singleton=singleton)

        screens = self.screens = {
            MAIN_ST: MainScreen(self),
            HELP_ST: HelpScreen(self),
            THEME_ST: ThemeScreen(self),
        }
        self.stack = ScreenStack(self.win, self.opts, SCREEN_NAMES, screens)

        spin = self.spin = OptionSpinner(stack=self.stack)
        spin.add_key('quit', 'q - quit', genre='action', keys=[ord('q')])
        spin.add_key('help_screen', '? - help', genre='action',
                     keys=[ord('?')], scope={MAIN_ST})
        # T opens the picker; it is the only way in, and t is bound only on
        # that screen so the table keeps its own keys untouched.
        spin.add_key('theme_screen', 'T - themes', genre='action',
                     keys=[ord('T')], scope={MAIN_ST})
        # p and h change what the table is looking at; the summary header
        # already advertises both as key hints ([p]ack / [h]ost).
        spin.add_key('package_next', 'p - next package', genre='action',
                     keys=[ord('p')], scope={MAIN_ST})
        spin.add_key('host_next', 'h - switch index', genre='action',
                     keys=[ord('h')], scope={MAIN_ST})
        spin.add_key('escape', 'ESC - back', genre='action',
                     keys=[27], scope={HELP_ST, THEME_ST})
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
        # handle_key() notices the new value and stores it.
        spin.add_key('time_zone', 'z - date time zone',
                     vals=list(ZONES), keys=[ord('z')],
                     scope={MAIN_ST})
        # The same shape for the theme: t only works on the THEMES screen, and
        # handle_key() is where the chosen palette or mono mode is applied.
        spin.add_key('theme', 't - cycle themes', vals=list(THEME_CHOICES),
                     keys=[ord('t')], scope={THEME_ST})
        # Sorting changes the model rather than a spinner value, so it is an
        # action; the help screen is the only place it is advertised.
        spin.add_key('sort', 's - change the sort order',
                     genre='action', keys=[ord('s')], scope={MAIN_ST})
        self.win.set_handled_keys(spin.keys)

    def handle_key(self, key: int) -> None:
        """Route one key to the spinner, storing the value it selects."""
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
        hints.bracket_key('?').text(':help ')
        hints.bracket_key('T').text(':themes')
        win.add_fancy_header(hints, line_attr=curses.A_DIM)

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

    def _marked_count(self) -> int:
        """How many releases are currently marked for deletion."""
        return sum(1 for release in self.app.cleanup.versions if release.delete)

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
        versions = self.app.cleanup.versions
        if not versions:
            # A failed load is already explained by the alert; an empty body
            # avoids claiming the history really has no releases.
            if self.app.load_failed:
                return
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
        self.app.persist(sort=cleanup.sort)

    def help_screen_ACTION(self) -> None:
        self.app.stack.push(HELP_ST, self.app.win.pick_pos)

    def theme_screen_ACTION(self) -> None:
        self.app.stack.push(THEME_ST, self.app.win.pick_pos)

    def package_next_ACTION(self) -> None:
        """Show the next package in the remembered list and reload it."""
        app = self.app
        if len(app.packages) < 2:
            return
        app.package_index = (app.package_index + 1) % len(app.packages)
        app.cleanup.package = app.packages[app.package_index]
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
    """The key-help screen; ESC returns to the release table."""

    def extra_help_paragraphs(self) -> Iterable[str]:
        """Explain the theme picker, then list the saved options."""
        paragraphs = [
            help_text.theme_paragraph(
                open_key='T',
                cycle_key='t',
                remembered=self.app.ini is not None,
            ),
        ]
        ini = self.app.ini
        if ini is not None:
            stored = ', '.join(
                f'{key}={getattr(ini.vals, key)!r}' for key in vars(ini.vals)
            )
            paragraphs.append(f'Saved options ({ini.config_file_path}): {stored}')
        return tuple(paragraphs)


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
        packages=packages,
    ).run()
