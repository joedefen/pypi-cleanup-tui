"""Headless tests for the interactive release table.

The console-window ``HeadlessBackend`` lets the whole application be built and
drawn without a TTY, so these tests describe the screen's contract rather than
whatever terminal happens to run them.
"""

from __future__ import annotations

import curses
from datetime import UTC, datetime, timedelta, timezone

import pytest
from console_window import Theme, appearance
from console_window.backend import HeadlessBackend

from pypi_cleanup_tui import tui as tui_mod
from pypi_cleanup_tui.ini import IniManager
from pypi_cleanup_tui.main import (
    APP_NAME,
    DEFAULTS,
    HOST_PYPI,
    HOST_TEST,
    SORT_BY_DATE,
    SORT_BY_VERSION,
    CleanupTui,
    Release,
)

NOW = datetime(2024, 5, 1, 12, 0, tzinfo=UTC)
EDT = timezone(timedelta(hours=-4), 'EDT')


@pytest.fixture(autouse=True)
def _headless_curses_stubs(monkeypatch):
    # curses.has_colors() and curses.color_pair() raise until initscr() has
    # succeeded; the window's theme setup may still probe them.  The ACS
    # constants are absent on a curses build that never initialized a screen,
    # yet render() draws the header/body separator with ACS_HLINE.
    monkeypatch.setattr(curses, 'has_colors', lambda: False, raising=False)
    monkeypatch.setattr(curses, 'color_pair', lambda n=0: n << 8, raising=False)
    monkeypatch.setattr(curses, 'ACS_HLINE', '-', raising=False)


@pytest.fixture(autouse=True)
def _restore_appearance():
    """The color switch and theme are process state; put them back after."""
    colors, theme = appearance.colors_enabled(), Theme.get_current()
    yield
    appearance.set_colors_enabled(colors)
    Theme.set_active(theme)


@pytest.fixture(autouse=True)
def _no_scoped_credentials(monkeypatch):
    """A developer's own 4PYPI/4TEST credentials must not reach these tests."""
    for base in (*tui_mod.CREDENTIAL_ENV_VARS, tui_mod.USER_ENV_VAR):
        for suffix in tui_mod.CREDENTIAL_SUFFIXES.values():
            monkeypatch.delenv(base + suffix, raising=False)
    # The TUI reads the TOTP secret itself, scoped or not, so a developer's
    # own value must not leak into a hand-off test that prints the code.
    for suffix in tui_mod.CREDENTIAL_SUFFIXES.values():
        monkeypatch.delenv(tui_mod.totp.TOTP_SECRET_ENV_VAR + suffix,
                           raising=False)
    monkeypatch.delenv(tui_mod.totp.TOTP_SECRET_ENV_VAR, raising=False)


def _cleanup():
    cleanup = CleanupTui('demo', user='alice')
    cleanup.versions = [
        Release('2.0', NOW),
        Release('1.0', NOW - timedelta(days=10)),
    ]
    return cleanup


def _cleanup3():
    cleanup = CleanupTui('demo', user='alice')
    cleanup.versions = [
        Release('2.0', NOW),
        Release('1.1', NOW - timedelta(days=5)),
        Release('1.0', NOW - timedelta(days=10)),
    ]
    return cleanup


def _mixed():
    """Version order and upload order disagree: 2.0 is the older upload."""
    cleanup = CleanupTui('demo', user='alice')
    cleanup.versions = [
        Release('2.0', NOW - timedelta(days=10)),
        Release('1.1', NOW),
    ]
    return cleanup


def _app(cleanup=None, rows=20, cols=100, ini=None, zone=None,
         theme=None, no_color=None, sort=None, gap=None, read_only=None,
         packages=None):
    return tui_mod.CleanupApp(
        cleanup or _cleanup(),
        backend=HeadlessBackend(rows=rows, cols=cols),
        singleton=False,
        ini=ini,
        zone=zone or tui_mod.UTC_MODE,
        theme=theme,
        no_color=no_color,
        sort=sort or SORT_BY_VERSION,
        gap=gap if gap is not None else tui_mod.DEFAULT_GAP,
        read_only=bool(read_only),
        packages=packages,
    )


def _ini(tmp_path):
    """A throwaway option store shaped like the real one."""
    return IniManager(APP_NAME, config_path=tmp_path / 'config.ini', **DEFAULTS)


def _draw(app):
    """Draw the main screen and return it, so tests read like a run loop."""
    app.screens[tui_mod.MAIN_ST].draw_screen()
    return app


def _draw_packages(app):
    """Draw the package list on a clean window, so its rows become pickable."""
    app.win.clear()
    app.screens[tui_mod.PACKAGES_ST].draw_screen()
    return app


def _press(app, key):
    """Deliver one key exactly as the run loop does: bind, then dispatch."""
    app.handle_key(key)
    app.stack.perform_actions(app.spin)


# --- row formatting -------------------------------------------------------

def test_column_header_names_each_column_in_utc():
    # The default sort is by version, so VERSION carries the star.
    assert tui_mod.column_header().split() == [
        'DEL', 'DATE', '(UTC)', 'DAYS', '*VERSION']


def test_column_header_stars_the_sorted_column():
    by_date = tui_mod.column_header(sort=SORT_BY_DATE)
    by_version = tui_mod.column_header(sort=SORT_BY_VERSION)

    assert '*DATE (UTC)' in by_date
    assert '*VERSION' not in by_date
    assert '*VERSION' in by_version
    assert '*DATE' not in by_version


def test_the_sort_star_does_not_move_the_days_column():
    by_date = tui_mod.column_header(sort=SORT_BY_DATE)
    by_version = tui_mod.column_header(sort=SORT_BY_VERSION)

    assert by_date.index('DAYS') == by_version.index('DAYS') == 22


def test_column_header_names_the_zone_in_force():
    assert 'DATE (EDT)' in tui_mod.column_header(
        tui_mod.LOCAL_MODE, local_tz=EDT)


def test_zone_abbrev_switches_with_the_mode():
    assert tui_mod.zone_abbrev(tui_mod.UTC_MODE, NOW) == 'UTC'
    assert tui_mod.zone_abbrev(tui_mod.LOCAL_MODE, NOW, local_tz=EDT) == 'EDT'


def test_days_ago_never_goes_negative():
    assert tui_mod.days_ago(Release('3.0', NOW - timedelta(days=3)), NOW) == 3
    assert tui_mod.days_ago(Release('3.0', NOW + timedelta(days=1)), NOW) == 0


def test_days_ago_counts_dates_not_elapsed_hours():
    late = datetime(2024, 4, 30, 23, 59, tzinfo=UTC)
    early = datetime(2024, 5, 1, 0, 1, tzinfo=UTC)

    assert tui_mod.days_ago(Release('3.0', late), early) == 1
    assert tui_mod.days_ago(Release('3.0', early), late) == 0


def test_days_ago_counts_in_the_zone_the_table_shows():
    # 03:00 UTC on 1 May is 23:00 on 30 April in EDT, so the local calendar
    # makes the release one day old where the UTC calendar makes it zero.
    release = Release('1.0', datetime(2024, 5, 1, 3, 0, tzinfo=UTC))

    assert tui_mod.days_ago(release, NOW) == 0
    assert tui_mod.days_ago(release, NOW, tui_mod.LOCAL_MODE, EDT) == 1


def test_format_row_counts_days_in_the_zone_the_date_is_shown_in():
    # 03:00 UTC on 1 May is 23:00 on 30 April in EDT, so the row prints the
    # earlier date and must call it one day old, not zero.
    release = Release('1.0', datetime(2024, 5, 1, 3, 0, tzinfo=UTC))

    row = tui_mod.format_row(release, NOW, tui_mod.LOCAL_MODE, EDT)

    assert row.split()[:3] == ['2024/04/30', '23:00', '1']


def test_format_row_marks_deletion_and_formats_every_column():
    release = Release('1.2.3', NOW - timedelta(days=4), delete=True)

    assert tui_mod.format_row(release, NOW).split() == [
        tui_mod.DEL_MARK, '2024/04/27', '12:00', '4', '1.2.3']


def test_format_row_centres_the_marker_in_the_del_column():
    row = tui_mod.format_row(Release('1.2.3', NOW, delete=True), NOW)

    # DEL is three cells wide: one space, the marker, one space, then the
    # column separator.
    assert row.startswith(f' {tui_mod.DEL_MARK}  ')


def test_format_row_leaves_the_marker_blank_by_default():
    row = tui_mod.format_row(Release('1.2.3', NOW), NOW)

    assert row.startswith('    ')
    assert tui_mod.DEL_MARK not in row


def test_format_row_shows_local_time_in_local_mode():
    row = tui_mod.format_row(
        Release('1.2.3', NOW), NOW, tui_mod.LOCAL_MODE, local_tz=EDT)

    assert '2024/05/01 08:00' in row


def test_format_row_leaves_the_time_in_utc_by_default():
    row = tui_mod.format_row(Release('1.2.3', NOW), NOW)

    assert '2024/05/01 12:00' in row


# --- the main screen ------------------------------------------------------

def test_main_screen_draws_three_header_lines_and_one_row_per_release():
    app = _app()
    try:
        app.screens[tui_mod.MAIN_ST].draw_screen()

        assert app.win.head.row_cnt == 3
        # The del block is blanked (three spaces) while nothing is marked, and
        # the pick is on an unmarked row, so the marking pair is offered.
        assert app.win.head.texts[0] == (
            f'    x:mark X:mark{tui_mod.DOWN_MARK} '
            f'sort zone gap30 quit ?:help /')
        # The summary is a fancy header: [p] and [h] are key styled, User is
        # literal.  It is not dimmed, unlike the hint and column lines.
        assert app.win.head.texts[1] == 'User=alice pack=demo host=pypi'
        summary_attrs = [attr for attr, _ in app.win.head.text_attrs[1]]
        assert not any(attr and attr & curses.A_DIM for attr in summary_attrs)
        assert any(attr and attr & curses.A_UNDERLINE for attr in summary_attrs)
        assert 'Times' not in app.win.head.texts[1]
        assert 'Sort' not in app.win.head.texts[1]
        assert 'Releases' not in app.win.head.texts[1]
        # s is advertised as one terse block, not as an "s - ..." description;
        # that longer form belongs to the help screen.
        assert 's - ' not in app.win.head.texts[0]

        # The column titles are the third header line, dim and not underlined.
        assert app.win.head.texts[2] == tui_mod.column_header()
        runs = app.win.head.text_attrs[2]
        assert [run[0] for run in runs] == [curses.A_DIM]

        # Every body row is a release: the titles no longer occupy row 0.
        assert app.win.body.row_cnt == 2
        assert '2024/05/01 12:00' in app.win.body.texts[0]
        assert '2.0' in app.win.body.texts[0]
        assert '1.0' in app.win.body.texts[1]
    finally:
        app.win.stop_curses()


def test_the_summary_line_shows_n_a_without_a_user(monkeypatch):
    monkeypatch.delenv('USER', raising=False)
    app = _app(CleanupTui('demo'))
    try:
        _draw(app)

        assert app.win.head.texts[1] == 'User=n/a pack=demo host=pypi'
    finally:
        app.win.stop_curses()


def test_the_summary_line_names_the_login_name_as_the_effective_user(monkeypatch):
    monkeypatch.setenv('USER', 'login')
    app = _app(CleanupTui('demo'))
    try:
        _draw(app)

        # -u will carry the login name, so the header shows it too.
        assert app.win.head.texts[1] == 'User=login pack=demo host=pypi'
    finally:
        app.win.stop_curses()


def test_the_summary_line_names_the_scoped_user(monkeypatch):
    monkeypatch.setenv('PYPI_CLEANUP_USER4TEST', 'test-bot')
    app = _app(CleanupTui('demo', host=HOST_TEST))
    try:
        _draw(app)

        assert app.win.head.texts[1] == 'User=test-bot pack=demo host=test'
    finally:
        app.win.stop_curses()


def test_the_summary_line_names_the_host_key_not_its_domain():
    app = _app(CleanupTui('demo', user='alice', host=HOST_TEST))
    try:
        _draw(app)

        assert app.win.head.texts[1] == 'User=alice pack=demo host=test'
    finally:
        app.win.stop_curses()


def test_main_screen_marks_a_release_selected_for_deletion():
    cleanup = _cleanup()
    cleanup.versions[0].delete = True
    app = _app(cleanup)
    try:
        app.screens[tui_mod.MAIN_ST].draw_screen()

        assert app.win.body.texts[0].lstrip().startswith(tui_mod.DEL_MARK)
    finally:
        app.win.stop_curses()


def test_the_del_hint_leads_the_line_only_while_something_is_marked():
    cleanup = _cleanup3()
    app = _app(cleanup)
    try:
        _draw(app)
        assert not app.win.head.texts[0].startswith('del ')
        # The block is blanked rather than dropped: the same cells stay there
        # so the keys after it never move.
        assert app.win.head.texts[0].startswith(
            ' ' * (len(tui_mod.DEL_HINT) + 1))

        cleanup.versions[0].delete = True
        app.win.clear()
        _draw(app)

        assert app.win.head.texts[0].startswith('del ')
    finally:
        app.win.stop_curses()


def test_the_hint_line_offers_the_unmarking_pair_on_a_marked_row():
    cleanup = _cleanup3()
    cleanup.versions[0].delete = True
    app = _app(cleanup)
    try:
        _draw(app)

        line = app.win.head.texts[0]
        assert 'unmark ' in line
        assert f'Unmark{tui_mod.DOWN_MARK} ' in line
        assert 'x:mark' not in line
        assert f'X:mark{tui_mod.DOWN_MARK}' not in line
    finally:
        app.win.stop_curses()


def test_the_hint_line_keeps_its_shape_as_the_pick_changes_state():
    cleanup = _cleanup3()
    app = _app(cleanup)
    try:
        _draw(app)
        unmarked = app.win.head.texts[0]

        cleanup.versions[0].delete = True
        app.win.clear()
        _draw(app)
        marked = app.win.head.texts[0]

        # The words swap, but the blocks keep their width: the keys to the
        # right stay in the same columns.
        assert unmarked.endswith('sort zone gap30 quit ?:help /')
        assert marked.endswith('sort zone gap30 quit ?:help /')
        assert len(unmarked) == len(marked)
    finally:
        app.win.stop_curses()


def test_empty_history_shows_a_placeholder_under_the_column_titles():
    app = _app(CleanupTui('empty'))
    try:
        app.screens[tui_mod.MAIN_ST].draw_screen()

        assert app.win.head.texts[2] == tui_mod.column_header()
        assert app.win.body.texts == ['No releases found.']
    finally:
        app.win.stop_curses()


# --- selection ------------------------------------------------------------

def test_x_marks_the_picked_release_and_steps_down():
    app = _app(_cleanup())
    try:
        _draw(app)
        app.win.pick_pos = 0
        _press(app, ord('x'))

        assert app.cleanup.versions[0].delete is True
        assert app.cleanup.versions[1].delete is False
        assert app.win.pick_pos == 1
    finally:
        app.win.stop_curses()


def test_x_on_the_last_release_keeps_the_pick_there():
    app = _app(_cleanup())
    try:
        _draw(app)
        app.win.pick_pos = 1
        _press(app, ord('x'))

        assert app.cleanup.versions[1].delete is True
        assert app.win.pick_pos == 1
    finally:
        app.win.stop_curses()


def test_shift_x_marks_from_the_pick_downwards_and_steps_up():
    app = _app(_cleanup3())
    try:
        _draw(app)
        app.win.pick_pos = 1  # the 1.1 row
        _press(app, ord('X'))

        assert [release.delete for release in app.cleanup.versions] == [
            False, True, True]
        # One row up: the last release the cut keeps.
        assert app.win.pick_pos == 0
    finally:
        app.win.stop_curses()


def test_shift_x_on_the_top_release_keeps_the_pick_on_that_row():
    app = _app(_cleanup3())
    try:
        _draw(app)
        app.win.pick_pos = 0
        _press(app, ord('X'))

        assert all(release.delete for release in app.cleanup.versions)
        assert app.win.pick_pos == 0
    finally:
        app.win.stop_curses()


def test_u_unmarks_the_picked_release_and_steps_down():
    cleanup = _cleanup3()
    for release in cleanup.versions:
        release.delete = True
    app = _app(cleanup)
    try:
        _draw(app)
        app.win.pick_pos = 1
        _press(app, ord('u'))

        assert [release.delete for release in cleanup.versions] == [
            True, False, True]
        assert app.win.pick_pos == 2
    finally:
        app.win.stop_curses()


def test_u_on_the_last_release_keeps_the_pick_there():
    cleanup = _cleanup3()
    for release in cleanup.versions:
        release.delete = True
    app = _app(cleanup)
    try:
        _draw(app)
        app.win.pick_pos = 2
        _press(app, ord('u'))

        assert [release.delete for release in cleanup.versions] == [
            True, True, False]
        assert app.win.pick_pos == 2
    finally:
        app.win.stop_curses()


def test_shift_u_unmarks_from_the_pick_downwards_and_steps_up():
    cleanup = _cleanup3()
    for release in cleanup.versions:
        release.delete = True
    app = _app(cleanup)
    try:
        _draw(app)
        app.win.pick_pos = 1
        _press(app, ord('U'))

        assert [release.delete for release in cleanup.versions] == [
            True, False, False]
        assert app.win.pick_pos == 0
    finally:
        app.win.stop_curses()


def test_shift_u_on_the_top_release_keeps_the_pick_on_that_row():
    cleanup = _cleanup3()
    for release in cleanup.versions:
        release.delete = True
    app = _app(cleanup)
    try:
        _draw(app)
        app.win.pick_pos = 0
        _press(app, ord('U'))

        assert all(not release.delete for release in cleanup.versions)
        assert app.win.pick_pos == 0
    finally:
        app.win.stop_curses()


def test_shift_x_is_inert_on_a_row_that_is_already_marked():
    cleanup = _cleanup3()
    cleanup.versions[1].delete = True
    app = _app(cleanup)
    try:
        _draw(app)
        app.win.pick_pos = 1  # the marked 1.1 row, where the line offers U
        _press(app, ord('X'))

        assert [release.delete for release in cleanup.versions] == [
            False, True, False]
        assert app.win.pick_pos == 1
    finally:
        app.win.stop_curses()


def test_shift_u_is_inert_on_a_row_that_is_not_marked():
    cleanup = _cleanup3()
    for release in cleanup.versions:
        release.delete = True
    cleanup.versions[1].delete = False
    app = _app(cleanup)
    try:
        _draw(app)
        app.win.pick_pos = 1  # the unmarked 1.1 row, where the line offers X
        _press(app, ord('U'))

        assert [release.delete for release in cleanup.versions] == [
            True, False, True]
        assert app.win.pick_pos == 1
    finally:
        app.win.stop_curses()


def test_selection_keys_do_nothing_off_the_release_rows():
    app = _app(CleanupTui('empty'))
    try:
        _draw(app)  # the placeholder is DECOR: no release attached
        for key in (ord('x'), ord('X'), ord('u'), ord('U')):
            _press(app, key)

        assert app.win.pick_pos == 0
    finally:
        app.win.stop_curses()


def test_marked_rows_keep_a_plain_del_cell_and_dim_the_rest():
    cleanup = _cleanup3()
    cleanup.versions[1].delete = True
    app = _app(cleanup)
    try:
        _draw(app)

        runs = app.win.body.text_attrs[1]
        assert runs[0][0] == curses.A_NORMAL
        assert runs[1][0] == curses.A_DIM
        # The marker itself is in the plain first cell.
        assert app.win.body.texts[1].startswith(f' {tui_mod.DEL_MARK}  ')
    finally:
        app.win.stop_curses()


def test_kept_rows_use_the_success_role_once_anything_is_marked(monkeypatch):
    sentinel = 0x5000
    monkeypatch.setattr(tui_mod, 'semantic_attr', lambda role: sentinel)

    cleanup = _cleanup3()
    cleanup.versions[1].delete = True
    app = _app(cleanup)
    try:
        _draw(app)

        attrs = [run[0][0] for run in app.win.body.text_attrs]
        assert attrs == [sentinel, curses.A_NORMAL, sentinel]
    finally:
        app.win.stop_curses()


def test_rows_stay_uncoloured_while_nothing_is_marked(monkeypatch):
    monkeypatch.setattr(tui_mod, 'semantic_attr', lambda role: 0x5000)

    app = _app(_cleanup3())
    try:
        _draw(app)

        attrs = [run[0][0] for run in app.win.body.text_attrs]
        assert attrs == [curses.A_NORMAL, curses.A_NORMAL, curses.A_NORMAL]
    finally:
        app.win.stop_curses()


# --- the z spinner --------------------------------------------------------

def test_z_cycles_the_date_column_between_utc_and_local():
    app = _app(_cleanup3())
    try:
        _draw(app)
        assert ord('z') in app.spin.keys
        assert app.spin.get_value('time_zone') == tui_mod.UTC_MODE
        assert app.win.head.texts[2] == tui_mod.column_header()

        _press(app, ord('z'))
        assert app.spin.get_value('time_zone') == tui_mod.LOCAL_MODE

        _press(app, ord('z'))
        assert app.spin.get_value('time_zone') == tui_mod.UTC_MODE
    finally:
        app.win.stop_curses()


def test_the_date_title_names_the_local_zone_after_z():
    app = _app(_cleanup3())
    try:
        _draw(app)
        _press(app, ord('z'))

        app.win.clear()
        _draw(app)

        local = datetime.now().astimezone().tzname() or tui_mod.LOCAL_MODE
        assert f'DATE ({local})' in app.win.head.texts[2]
    finally:
        app.win.stop_curses()


# --- incremental search ---------------------------------------------------

def test_the_hint_line_keeps_a_bare_search_field_and_hides_the_theme_key():
    app = _app()
    try:
        _draw(app)

        assert app.win.head.texts[0].endswith(' /')
        assert 'T:themes' not in app.win.head.texts[0]
    finally:
        app.win.stop_curses()


def test_slash_opens_the_search_and_enter_closes_it():
    app = _app(_cleanup3())
    try:
        _draw(app)
        _press(app, ord('/'))

        assert app.search_bar.is_active is True
        assert app.win.passthrough_mode is True
        # ENTER has to be forwarded through the window for the bar to see it.
        assert 10 in app.win.handled_keys

        for char in '1.1':
            _press(app, ord(char))
        assert app.search_text == '1.1'

        _press(app, 10)
        assert app.search_bar.is_active is False
        assert app.win.passthrough_mode is False
    finally:
        app.win.stop_curses()


def test_typing_filters_the_body_as_the_search_runs():
    app = _app(_cleanup3())
    try:
        _draw(app)
        _press(app, ord('/'))
        for char in '1.1':
            _press(app, ord(char))

        assert [release.version for release in app.visible_versions()] == ['1.1']

        _press(app, 10)
        app.win.clear()
        _draw(app)
        assert app.win.body.row_cnt == 1
        assert '1.1' in app.win.body.texts[0]
        assert app.win.head.texts[0].endswith(' /1.1')
    finally:
        app.win.stop_curses()


def test_shift_x_marks_only_the_visible_rows_after_a_search():
    cleanup = _cleanup3()
    app = _app(cleanup)
    try:
        _draw(app)
        _press(app, ord('/'))
        for char in '1.1':
            _press(app, ord(char))
        _press(app, 10)
        app.win.clear()
        _draw(app)

        app.win.pick_pos = 0
        _press(app, ord('X'))

        assert [release.delete for release in cleanup.versions] == [
            False, True, False]
        assert app.win.pick_pos == 0
    finally:
        app.win.stop_curses()


def test_x_steps_down_through_the_visible_rows_only():
    cleanup = _cleanup3()
    app = _app(cleanup)
    try:
        _draw(app)
        _press(app, ord('/'))
        _press(app, ord('1'))
        _press(app, 10)
        app.win.clear()
        _draw(app)

        assert [release.version for release in app.visible_versions()] == [
            '1.1', '1.0']
        app.win.pick_pos = 0
        _press(app, ord('x'))

        assert [release.delete for release in cleanup.versions] == [
            False, True, False]
        assert app.win.pick_pos == 1
    finally:
        app.win.stop_curses()


def test_shift_u_unmarks_only_the_visible_rows_after_a_search():
    cleanup = _cleanup3()
    for release in cleanup.versions:
        release.delete = True
    app = _app(cleanup)
    try:
        _draw(app)
        _press(app, ord('/'))
        for char in '1.1':
            _press(app, ord(char))
        _press(app, 10)
        app.win.clear()
        _draw(app)

        app.win.pick_pos = 0
        _press(app, ord('U'))

        assert [release.delete for release in cleanup.versions] == [
            True, False, True]
        assert app.win.pick_pos == 0
    finally:
        app.win.stop_curses()


def test_escape_restores_the_pattern_the_search_started_with():
    app = _app(_cleanup3())
    try:
        _draw(app)
        _press(app, ord('/'))
        for char in '1.1':
            _press(app, ord(char))
        _press(app, 10)

        _press(app, ord('/'))
        for char in '0':
            _press(app, ord(char))
        assert app.search_text == '1.10'

        _press(app, 27)
        assert app.search_bar.is_active is False
        assert app.search_text == '1.1'
    finally:
        app.win.stop_curses()


def test_a_key_the_search_does_not_handle_closes_the_pattern_first():
    app = _app(_cleanup3())
    try:
        _draw(app)
        _press(app, ord('/'))
        for char in '1.1':
            _press(app, ord(char))

        _press(app, curses.KEY_DOWN)

        assert app.search_bar.is_active is False
        assert app.search_text == '1.1'
    finally:
        app.win.stop_curses()


def test_a_pattern_that_matches_nothing_says_so():
    app = _app(_cleanup3())
    try:
        _draw(app)
        _press(app, ord('/'))
        for char in 'zzz':
            _press(app, ord(char))
        _press(app, 10)

        app.win.clear()
        _draw(app)

        assert app.win.body.texts == ['No matching releases.']
    finally:
        app.win.stop_curses()


def _app_with_release_candidates():
    """A table with a mixed-case version and a release from a second series."""
    cleanup = CleanupTui('demo', user='alice')
    cleanup.versions = [
        Release('2.0', NOW),
        Release('1.2RC1', NOW - timedelta(days=5)),
        Release('1.0', NOW - timedelta(days=10)),
    ]
    return _app(cleanup)


def test_the_pattern_is_a_regular_expression():
    app = _app_with_release_candidates()
    try:
        _draw(app)
        _press(app, ord('/'))
        # The dot is escaped and [02] is a character class: a plain substring
        # match would find neither row.
        for char in '1\\.[02]':
            _press(app, ord(char))
        _press(app, 10)

        assert [release.version for release in app.visible_versions()] == [
            '1.2RC1', '1.0']
    finally:
        app.win.stop_curses()


def test_the_pattern_ignores_case():
    app = _app_with_release_candidates()
    try:
        _draw(app)
        _press(app, ord('/'))
        for char in 'rc':
            _press(app, ord(char))
        _press(app, 10)

        assert [release.version for release in app.visible_versions()] == [
            '1.2RC1']
    finally:
        app.win.stop_curses()


def test_escape_on_an_untouched_search_leaves_the_table_unfiltered():
    app = _app(_cleanup3())
    try:
        _draw(app)
        _press(app, ord('/'))
        _press(app, 27)

        assert app.search_bar.is_active is False
        assert app.search_text == ''
        assert [release.version for release in app.visible_versions()] == [
            '2.0', '1.1', '1.0']
    finally:
        app.win.stop_curses()


def test_a_pattern_that_does_not_compile_yet_shows_every_release():
    app = _app(_cleanup3())
    try:
        _draw(app)
        _press(app, ord('/'))
        _press(app, ord('['))
        _press(app, 10)

        assert [release.version for release in app.visible_versions()] == [
            '2.0', '1.1', '1.0']

        app.win.clear()
        _draw(app)
        assert app.win.body.row_cnt == 3
    finally:
        app.win.stop_curses()


# --- the theme picker -----------------------------------------------------


def test_t_opens_the_theme_screen_and_esc_returns():
    app = _app()
    try:
        _press(app, ord('T'))
        assert app.stack.curr.num == tui_mod.THEME_ST

        app.screens[tui_mod.THEME_ST].draw_screen()
        assert app.win.head.texts[0].startswith('COLOR THEME:')

        _press(app, 27)
        assert app.stack.curr.num == tui_mod.MAIN_ST
    finally:
        app.win.stop_curses()


def test_t_cycles_only_on_the_theme_screen():
    app = _app()
    try:
        starting = app.opts.theme

        _press(app, ord('t'))
        assert app.opts.theme == starting
        assert app.stack.curr.num == tui_mod.MAIN_ST

        _press(app, ord('T'))
        _press(app, ord('t'))
        assert app.opts.theme != starting
        assert app.stack.curr.num == tui_mod.THEME_ST
    finally:
        app.win.stop_curses()


def test_choosing_mono_turns_color_off_and_is_remembered(tmp_path):
    ini = _ini(tmp_path)
    app = _app(ini=ini)
    try:
        _press(app, ord('T'))
        while app.opts.theme != tui_mod.MONO_THEME:
            _press(app, ord('t'))

        assert appearance.colors_enabled() is False
        assert ini.vals.theme == tui_mod.MONO_THEME
        assert ini.vals.no_color is True
        assert _ini(tmp_path).vals.theme == tui_mod.MONO_THEME
        assert _ini(tmp_path).vals.no_color is True
    finally:
        app.win.stop_curses()


def test_choosing_a_palette_turns_color_back_on(tmp_path):
    ini = _ini(tmp_path)
    ini.save(theme=tui_mod.MONO_THEME, no_color=True)
    app = _app(ini=ini)
    try:
        assert appearance.colors_enabled() is False

        _press(app, ord('T'))
        assert app.opts.theme == tui_mod.MONO_THEME
        # mono is the last choice, so one step wraps to the first palette.
        _press(app, ord('t'))

        assert app.opts.theme == tui_mod.THEME_CHOICES[0]
        assert appearance.colors_enabled() is True
        assert ini.vals.theme == tui_mod.THEME_CHOICES[0]
        assert ini.vals.no_color is False
    finally:
        app.win.stop_curses()


def test_the_stored_mono_choice_starts_in_mono(tmp_path):
    ini = _ini(tmp_path)
    ini.save(theme=tui_mod.MONO_THEME, no_color=True)
    app = _app(ini=ini)
    try:
        assert app.opts.theme == tui_mod.MONO_THEME
        assert appearance.colors_enabled() is False

        app.screens[tui_mod.THEME_ST].draw_screen()
        assert app.win.head.texts[0].startswith('COLOR THEME:')
        assert tui_mod.MONO_THEME in app.win.head.texts[0]
    finally:
        app.win.stop_curses()


def test_no_color_environment_starts_in_mono():
    choice, palette, colors = tui_mod.resolve_theme(
        saved_theme='nord', environ={'NO_COLOR': '1'})

    assert colors is False
    assert choice == tui_mod.MONO_THEME
    assert palette == 'nord'


def test_an_explicit_theme_wins_over_the_environment():
    choice, palette, colors = tui_mod.resolve_theme(
        cli_theme='nord', environ={'NO_COLOR': '1'})

    assert (choice, palette, colors) == ('nord', 'nord', True)


def test_no_color_wins_over_an_explicit_theme():
    choice, palette, colors = tui_mod.resolve_theme(
        cli_theme='nord', cli_no_color=True)

    assert colors is False
    assert choice == tui_mod.MONO_THEME
    assert palette == 'nord'


def test_mono_as_an_explicit_theme_turns_color_off():
    choice, palette, colors = tui_mod.resolve_theme(
        cli_theme=tui_mod.MONO_THEME)

    assert colors is False
    assert choice == tui_mod.MONO_THEME
    assert palette in Theme.list_all()


# --- loading the release history ------------------------------------------

def test_load_versions_clears_and_shows_a_loading_frame(monkeypatch):
    cleanup = _cleanup()
    app = _app(cleanup)
    seen = []

    def fake_fetch(self):
        # What the body showed while the fetch was running: the old rows are
        # gone and only the loading line is left.
        seen.append((list(self.versions), list(app.win.body.texts)))
        self.versions = [Release('3.0', NOW)]
        return self.versions

    monkeypatch.setattr(CleanupTui, 'fetch_versions', fake_fetch)
    try:
        app.load_versions()

        versions_at_fetch, body_at_fetch = seen[0]
        assert versions_at_fetch == []
        assert body_at_fetch == ['Loading ...']
        assert [release.version for release in app.cleanup.versions] == ['3.0']
        assert app.loading is False
        assert app.load_failed is False
    finally:
        app.win.stop_curses()


def test_the_loading_line_uses_the_hotswap_role(monkeypatch):
    sentinel = 0x6000
    monkeypatch.setattr(tui_mod, 'semantic_attr', lambda role: sentinel)

    app = _app()
    try:
        app.loading = True
        _draw(app)

        assert app.win.body.texts == ['Loading ...']
        assert app.win.body.text_attrs[0][0][0] == sentinel
    finally:
        app.win.stop_curses()


def test_a_failed_load_alerts_and_leaves_the_body_empty(monkeypatch):
    app = _app()
    alerts = []

    def broken(self):
        raise LookupError("package 'demo' was not found on pypi.org")

    monkeypatch.setattr(CleanupTui, 'fetch_versions', broken)
    monkeypatch.setattr(
        app.win, 'alert',
        lambda message, title='ALERT': alerts.append((message, title)),
    )
    try:
        app.load_versions()

        message, title = alerts[0]
        assert title == 'LOAD ERROR'
        assert 'not found' in message
        assert 'LookupError' in message
        assert app.cleanup.versions == []
        assert app.load_failed is True

        _draw(app)
        assert app.win.body.row_cnt == 0
    finally:
        app.win.stop_curses()


def test_run_tui_loads_the_history_after_it_opens(monkeypatch):
    calls = []

    def fake_fetch(self):
        calls.append(self.package)
        self.versions = [Release('1.0', NOW)]
        return self.versions

    monkeypatch.setattr(CleanupTui, 'fetch_versions', fake_fetch)
    backend = HeadlessBackend(rows=20, cols=100)
    backend.queue_keys(ord('q'))

    assert tui_mod.run_tui(_cleanup(), backend=backend, singleton=False) == 0
    assert calls == ['demo']


def test_p_rotates_the_packages_and_reloads(monkeypatch):
    cleanup = CleanupTui('a', user='alice')
    app = _app(cleanup, packages=['a', 'b'])
    fetched = []

    def fake_fetch(self):
        fetched.append(self.package)
        self.versions = [Release('1.0', NOW)]
        return self.versions

    monkeypatch.setattr(CleanupTui, 'fetch_versions', fake_fetch)
    try:
        _press(app, ord('p'))
        assert app.cleanup.package == 'b'
        assert fetched == ['b']

        _press(app, ord('p'))
        assert app.cleanup.package == 'a'
        assert fetched == ['b', 'a']
    finally:
        app.win.stop_curses()


def test_p_with_one_package_does_not_reload(monkeypatch):
    app = _app(CleanupTui('solo'), packages=['solo'])
    fetched = []
    monkeypatch.setattr(CleanupTui, 'fetch_versions',
                        lambda self: fetched.append(self.package))
    try:
        _press(app, ord('p'))

        assert app.cleanup.package == 'solo'
        assert fetched == []
    finally:
        app.win.stop_curses()


def test_h_switches_the_index_and_reloads(tmp_path, monkeypatch):
    ini = _ini(tmp_path)
    app = _app(CleanupTui('demo', host=tui_mod.HOST_PYPI), ini=ini)
    fetched = []

    def fake_fetch(self):
        fetched.append(self.host_key)
        self.versions = []
        return self.versions

    monkeypatch.setattr(CleanupTui, 'fetch_versions', fake_fetch)
    try:
        _press(app, ord('h'))
        assert app.cleanup.host_key == tui_mod.HOST_TEST
        assert fetched == [tui_mod.HOST_TEST]
        assert ini.vals.host == tui_mod.HOST_TEST

        _press(app, ord('h'))
        assert app.cleanup.host_key == tui_mod.HOST_PYPI
        assert fetched == [tui_mod.HOST_TEST, tui_mod.HOST_PYPI]
        assert ini.vals.host == tui_mod.HOST_PYPI
    finally:
        app.win.stop_curses()


def test_a_package_list_without_the_current_package_is_repaired():
    app = _app(CleanupTui('b'), packages=['a'])
    try:
        assert app.packages == ['b', 'a']
        assert app.package_index == 0
    finally:
        app.win.stop_curses()


def test_the_next_package_of_an_empty_list_is_none():
    app = _app(CleanupTui('a'), packages=['a'])
    try:
        app.packages.clear()

        assert app.next_package_index() is None
    finally:
        app.win.stop_curses()


def test_the_next_package_falls_back_to_the_row_that_took_its_place():
    app = _app(CleanupTui('a'), packages=['a', 'b', 'c'])
    try:
        app.remove_package('a')

        # The table still shows 'a', which the list no longer holds, so the
        # row that took its place ('b') is what p and P step onto.
        assert app.packages == ['b', 'c']
        assert app.next_package_index() == 0
    finally:
        app.win.stop_curses()


def test_the_summary_follows_package_and_host_changes(monkeypatch):
    app = _app(CleanupTui('a', user='alice'), packages=['a', 'b'])
    monkeypatch.setattr(CleanupTui, 'fetch_versions', lambda self: [])
    try:
        _press(app, ord('p'))
        _draw(app)
        assert app.win.head.texts[1] == 'User=alice pack=b host=pypi'

        _press(app, ord('h'))
        _draw(app)
        assert app.win.head.texts[1] == 'User=alice pack=b host=test'
    finally:
        app.win.stop_curses()


# --- the package list -----------------------------------------------------

def test_package_header_leaves_the_check_column_untitled():
    header = tui_mod.package_header(7)

    assert header == '  PACKAGE  VERs  DELs'
    assert header.startswith(' ' * (tui_mod.CHECK_WIDTH + 1))


def test_format_package_row_uses_dashes_until_the_package_is_loaded():
    fresh = tui_mod.PackageSession()
    loaded = tui_mod.PackageSession(visited=True, versions=12, deleted=3)

    assert tui_mod.format_package_row('demo', fresh, 7) == (
        '  demo' + ' ' * 8 + '-' + ' ' * 5 + '-')
    assert tui_mod.format_package_row('demo', loaded, 7) == (
        f'{tui_mod.VISITED_MARK} demo' + ' ' * 7 + '12' + ' ' * 5 + '3')


def test_a_successful_load_marks_the_package_visited(monkeypatch):
    app = _app(CleanupTui('demo'))

    def fake_fetch(self):
        self.versions = [Release('2.0', NOW), Release('1.0', NOW)]
        return self.versions

    monkeypatch.setattr(CleanupTui, 'fetch_versions', fake_fetch)
    try:
        app.load_versions()

        session = app.session['demo']
        assert (session.visited, session.versions, session.deleted) == (True, 2, 0)
    finally:
        app.win.stop_curses()


def test_a_failed_load_leaves_the_package_unvisited(monkeypatch):
    def fail(self):
        raise LookupError('not found')

    app = _app(CleanupTui('demo'))
    monkeypatch.setattr(CleanupTui, 'fetch_versions', fail)
    monkeypatch.setattr(app.win, 'alert', lambda *args, **kwargs: None)
    try:
        app.load_versions()

        assert 'demo' not in app.session
    finally:
        app.win.stop_curses()


def test_the_package_list_shows_checks_and_the_session_totals(monkeypatch):
    cleanup = CleanupTui('a', user='alice')
    app = _app(cleanup, packages=['a', 'b'])
    versions = {
        'a': [Release('2.0', NOW), Release('1.0', NOW)],
        'b': [Release('3.0', NOW)],
    }

    def fake_fetch(self):
        self.versions = list(versions[self.package])
        return self.versions

    monkeypatch.setattr(CleanupTui, 'fetch_versions', fake_fetch)
    try:
        app.load_versions()            # the table's package, 'a', is loaded
        _press(app, ord('P'))

        assert app.stack.curr.num == tui_mod.PACKAGES_ST
        app.win.clear()
        app.screens[tui_mod.PACKAGES_ST].draw_screen()

        assert app.win.head.texts[0] == 'PACKAGES  x:remove ESC:open ?:help'
        assert app.win.head.texts[1] == tui_mod.package_header(7)
        assert app.win.body.row_cnt == 2
        # 'a' was loaded: check mark, name and its version total.
        assert app.win.body.texts[0].startswith(tui_mod.VISITED_MARK)
        assert app.win.body.texts[0] == (
            f'{tui_mod.VISITED_MARK} a' + ' ' * 11 + '2' + ' ' * 5 + '0')
        # 'b' was never fetched: no check mark and two dashes.
        assert app.win.body.texts[1] == '  b' + ' ' * 11 + '-' + ' ' * 5 + '-'
    finally:
        app.win.stop_curses()


def test_escape_opens_the_picked_package_and_returns_to_the_table(monkeypatch):
    app = _app(CleanupTui('a'), packages=['a', 'b'])
    fetched = []

    def fake_fetch(self):
        fetched.append(self.package)
        self.versions = [Release('1.0', NOW)]
        return self.versions

    monkeypatch.setattr(CleanupTui, 'fetch_versions', fake_fetch)
    try:
        app.load_versions()
        _press(app, ord('P'))
        _draw_packages(app)

        # P parks the pick on the package p would show next; ESC opens it.
        assert app.win.pick_pos == 1
        _press(app, 27)

        assert app.stack.curr.num == tui_mod.MAIN_ST
        assert app.cleanup.package == 'b'
        assert app.package_index == 1
        assert fetched == ['a', 'b']
        assert app.session['b'].versions == 1
    finally:
        app.win.stop_curses()


def test_the_package_list_starts_on_the_package_p_would_show(monkeypatch):
    monkeypatch.setattr(CleanupTui, 'fetch_versions', lambda self: [])
    app = _app(CleanupTui('c'), packages=['a', 'b', 'c'])
    try:
        _press(app, ord('P'))
        _draw_packages(app)

        # 'c' is the last package, so the list wraps to the first row.
        assert app.win.pick_pos == 0

        _press(app, 27)
        assert app.cleanup.package == 'a'
    finally:
        app.win.stop_curses()


def test_escape_on_the_table_package_does_not_reload(monkeypatch):
    calls = []

    def fake_fetch(self):
        calls.append(self.package)
        return []

    monkeypatch.setattr(CleanupTui, 'fetch_versions', fake_fetch)
    app = _app(CleanupTui('solo'), packages=['solo'])
    try:
        _press(app, ord('P'))
        _draw_packages(app)

        _press(app, 27)

        assert app.stack.curr.num == tui_mod.MAIN_ST
        assert app.cleanup.package == 'solo'
        assert calls == []
    finally:
        app.win.stop_curses()


def test_x_removes_a_package_from_the_list_not_from_the_index(tmp_path):
    ini = _ini(tmp_path)
    app = _app(CleanupTui('a', user='alice'), ini=ini, packages=['a', 'b', 'c'])
    try:
        _press(app, ord('P'))
        _draw_packages(app)
        app.win.pick_pos = 1

        _press(app, ord('x'))

        assert app.packages == ['a', 'c']
        assert app.cleanup.package == 'a'
        assert app.package_index == 0
        assert ini.vals.packages == 'a,c'
        assert _ini(tmp_path).vals.packages == 'a,c'
    finally:
        app.win.stop_curses()


def test_removing_the_current_package_leaves_it_in_the_table(monkeypatch):
    app = _app(CleanupTui('a'), packages=['a', 'b', 'c'])
    monkeypatch.setattr(CleanupTui, 'fetch_versions', lambda self: [])
    try:
        app.load_versions()
        _press(app, ord('P'))
        _draw_packages(app)
        app.win.pick_pos = 0

        _press(app, ord('x'))
        _draw_packages(app)

        assert app.packages == ['b', 'c']
        # The list is a working set, not the index: the table keeps 'a'.
        assert app.cleanup.package == 'a'

        # The row that took 'a's place stays reachable: ESC opens 'b', and p
        # still rotates from there.
        _press(app, 27)
        assert app.cleanup.package == 'b'

        _press(app, ord('p'))
        assert app.cleanup.package == 'c'
    finally:
        app.win.stop_curses()


def test_escape_leaves_the_program_when_the_package_list_is_emptied():
    app = _app(CleanupTui('a'), packages=['a'])
    try:
        _press(app, ord('P'))
        _draw_packages(app)
        _press(app, ord('x'))
        _draw_packages(app)

        assert app.packages == []
        assert app.cleanup.package == 'a'
        assert app.win.body.texts == ['No packages in the list.']

        # With no row to act on, x is inert.
        _press(app, ord('x'))
        assert app.packages == []

        # With no row to open, ESC is the way out.
        _press(app, 27)
        assert app.running is False
    finally:
        app.win.stop_curses()


def test_an_unknown_package_is_neither_selected_nor_removed():
    app = _app(CleanupTui('a'), packages=['a', 'b'])
    try:
        app.select_package('ghost')
        app.remove_package('ghost')

        assert app.packages == ['a', 'b']
        assert app.cleanup.package == 'a'
        assert app.package_index == 0
    finally:
        app.win.stop_curses()


def test_help_from_the_package_list_returns_to_it():
    app = _app(CleanupTui('a'), packages=['a', 'b'])
    try:
        _press(app, ord('P'))
        _press(app, ord('?'))

        assert app.stack.curr.num == tui_mod.HELP_ST

        _press(app, 27)
        assert app.stack.curr.num == tui_mod.PACKAGES_ST
    finally:
        app.win.stop_curses()


# --- the d hand-off -------------------------------------------------------

def test_the_cleanup_command_names_the_marked_versions():
    cleanup = CleanupTui('demo', user='alice')

    command = tui_mod.cleanup_command(cleanup, ['2.0', '1.0'])

    # The versions become one anchored expression, with the dots literal, so
    # the command names exactly the rows the table showed; -y answers the
    # program's own warning prompt and -t names the index being queried.
    assert command == [
        'pypi-cleanup', '-y', '-u', 'alice', '-t', 'https://pypi.org/',
        '-p', 'demo', '-r', '^(2\\.0|1\\.0)$',
    ]


def test_the_cleanup_command_carries_the_index_url():
    cleanup = CleanupTui('demo', user='alice', host=HOST_TEST)

    command = tui_mod.cleanup_command(cleanup, ['1.0'])

    assert command[command.index('-t') + 1] == 'https://test.pypi.org/'


def test_the_mode_flag_follows_the_tool_name():
    cleanup = CleanupTui('demo', user='alice')

    query = tui_mod.cleanup_command(cleanup, ['1.0'], tui_mod.QUERY_ONLY)
    destroy = tui_mod.cleanup_command(cleanup, ['1.0'], tui_mod.DO_IT)

    assert query[:2] == ['pypi-cleanup', '--query-only']
    assert destroy[:2] == ['pypi-cleanup', '--do-it']
    assert '--do-it' not in query


def test_the_cleanup_command_falls_back_to_the_login_name(monkeypatch):
    monkeypatch.setenv('USER', 'login')

    command = tui_mod.cleanup_command(CleanupTui('demo'), ['1.0'])

    assert command[command.index('-u') + 1] == 'login'


def test_the_hosts_scoped_user_wins_over_the_flag(monkeypatch):
    monkeypatch.setenv('PYPI_CLEANUP_USER4PYPI', 'pypi-bot')
    monkeypatch.setenv('PYPI_CLEANUP_USER4TEST', 'test-bot')

    def user_for(host):
        command = tui_mod.cleanup_command(
            CleanupTui('demo', user='flag', host=host), ['1.0'])
        return command[command.index('-u') + 1]

    assert user_for(HOST_PYPI) == 'pypi-bot'
    assert user_for(HOST_TEST) == 'test-bot'


def test_a_scoped_user_wins_over_the_login_name(monkeypatch):
    monkeypatch.setenv('USER', 'login')
    monkeypatch.setenv('PYPI_CLEANUP_USER4PYPI', 'pypi-bot')

    command = tui_mod.cleanup_command(CleanupTui('demo'), ['1.0'])

    assert command[command.index('-u') + 1] == 'pypi-bot'


def test_an_empty_scoped_user_leaves_the_flag_in_charge(monkeypatch):
    monkeypatch.setenv('USER', 'login')
    monkeypatch.setenv('PYPI_CLEANUP_USER4TEST', '')

    command = tui_mod.cleanup_command(
        CleanupTui('demo', user='flag', host=HOST_TEST), ['1.0'])

    assert command[command.index('-u') + 1] == 'flag'


def test_credential_env_maps_only_the_hosts_non_empty_password():
    environ = {
        'PYPI_CLEANUP_PASSWORD4PYPI': 'pypi-password',
        'PYPI_CLEANUP_TOTP_SECRET4PYPI': 'pypi-totp',
        'PYPI_CLEANUP_PASSWORD4TEST': 'test-password',
        'PYPI_CLEANUP_TOTP_SECRET4TEST': '',
    }

    assert tui_mod.credential_env(HOST_PYPI, environ) == {
        'PYPI_CLEANUP_PASSWORD': 'PYPI_CLEANUP_PASSWORD4PYPI',
    }
    assert tui_mod.credential_env(HOST_TEST, environ) == {
        'PYPI_CLEANUP_PASSWORD': 'PYPI_CLEANUP_PASSWORD4TEST',
    }
    # The TOTP secret is read by the TUI, never copied into the child's env.
    assert 'PYPI_CLEANUP_TOTP_SECRET' not in tui_mod.cleanup_env(
        HOST_PYPI, environ)


def test_credential_env_maps_nothing_without_a_scoped_value():
    assert tui_mod.credential_env(
        HOST_TEST, {'PYPI_CLEANUP_PASSWORD': 'base'}) == {}
    assert tui_mod.credential_env(
        'nowhere', {'PYPI_CLEANUP_PASSWORD4TEST': 'x'}) == {}


def test_cleanup_env_copies_the_scoped_value_over_the_base_name():
    environ = {
        'PATH': '/bin',
        'PYPI_CLEANUP_PASSWORD': 'base-password',
        'PYPI_CLEANUP_PASSWORD4TEST': 'test-password',
    }

    env = tui_mod.cleanup_env(HOST_TEST, environ)

    assert env['PYPI_CLEANUP_PASSWORD'] == 'test-password'
    assert env['PATH'] == '/bin'
    # The scoped name is the user's, and it passes through untouched.
    assert env['PYPI_CLEANUP_PASSWORD4TEST'] == 'test-password'


def test_cleanup_env_inherits_when_nothing_is_scoped():
    assert tui_mod.cleanup_env(
        HOST_TEST, {'PYPI_CLEANUP_PASSWORD': 'base'}) is None


def test_totp_secret_prefers_the_hosts_scoped_value():
    environ = {
        'PYPI_CLEANUP_TOTP_SECRET': 'base-secret',
        'PYPI_CLEANUP_TOTP_SECRET4PYPI': 'pypi-secret',
        'PYPI_CLEANUP_TOTP_SECRET4TEST': '',
    }

    assert tui_mod.totp_secret(HOST_PYPI, environ) == 'pypi-secret'
    # An empty scoped value leaves the unscoped secret as the fallback, and an
    # unknown host has no scoped form at all.
    assert tui_mod.totp_secret(HOST_TEST, environ) == 'base-secret'
    assert tui_mod.totp_secret('nowhere', environ) == 'base-secret'


def test_no_totp_secret_prints_nothing(capsys):
    tui_mod.show_authentication_code(HOST_PYPI, {})

    assert capsys.readouterr().out == ''


def test_the_authentication_code_is_printed_for_the_prompt(monkeypatch, capsys):
    monkeypatch.setattr(
        tui_mod.totp, 'code_with_room', lambda secret: ('123456', 24))

    tui_mod.show_authentication_code(
        HOST_PYPI, {'PYPI_CLEANUP_TOTP_SECRET':
                    'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'})

    assert capsys.readouterr().out == (
        'Authentication code: 123456 (expires in 24s)\n')


def test_a_bad_totp_secret_is_reported_not_raised(capsys):
    tui_mod.show_authentication_code(
        HOST_PYPI, {'PYPI_CLEANUP_TOTP_SECRET': 'not base 32!'})

    out = capsys.readouterr().out
    assert 'warning: could not compute a TOTP code' in out


def test_the_display_names_the_credentials_it_will_map():
    text = tui_mod.format_command(
        ['pypi-cleanup', '-y'],
        env={'PYPI_CLEANUP_PASSWORD': 'PYPI_CLEANUP_PASSWORD4TEST'},
    )

    assert text.splitlines() == [
        '+ PYPI_CLEANUP_PASSWORD=PYPI_CLEANUP_PASSWORD4TEST',
        '   pypi-cleanup -y',
    ]


def test_the_display_quotes_every_value():
    assert tui_mod.format_command(
        ['pypi-cleanup', '-y', '-u', 'alice', '-p', 'demo']
    ) == "+ pypi-cleanup -y -u 'alice' -p 'demo'"


def test_the_display_breaks_before_the_pattern():
    command = tui_mod.cleanup_command(
        CleanupTui('demo', user='alice'), ['2.0', '1.0'])

    lines = tui_mod.format_command(command).splitlines()

    assert lines == [
        "+ pypi-cleanup -y -u 'alice' -t 'https://pypi.org/' -p 'demo'",
        "   -r '^(2\\.0|1\\.0)$'",
    ]


def test_a_long_display_wraps_at_a_flag():
    # A bare switch that will not fit moves to its own continuation line.
    text = tui_mod.format_command(
        ['pypi-cleanup', '-y', '--query-only', '-v'], width=24)

    assert text.splitlines() == [
        '+ pypi-cleanup -y',
        '   --query-only -v',
    ]


def test_a_long_pattern_is_broken_after_its_pipes():
    versions = [f'1.{minor}.0' for minor in range(20)]
    command = tui_mod.cleanup_command(
        CleanupTui('demo', user='alice'), versions)

    lines = tui_mod.format_command(command).splitlines()

    pattern_lines = lines[1:]
    assert pattern_lines[0].startswith("   -r '")
    # Every break follows an alternation, so only the last piece is unclosed.
    assert all(line.endswith('|') for line in pattern_lines[:-1])
    assert pattern_lines[-1].endswith(")$'")
    assert all(len(line) <= tui_mod.COMMAND_WIDTH for line in lines)


def test_a_bare_enter_takes_each_question_default(monkeypatch):
    answers = iter(['', ''])
    monkeypatch.setattr('builtins.input', lambda prompt='': next(answers))

    assert tui_mod.ask_yes_no(tui_mod.DRY_RUN_PROMPT, default=True) is True
    assert tui_mod.ask_yes_no('Del?', default=False) is False


def test_the_answer_is_read_in_any_case(monkeypatch):
    answers = iter(['YES', 'No'])
    monkeypatch.setattr('builtins.input', lambda prompt='': next(answers))

    assert tui_mod.ask_yes_no('Dry-run?', default=False) is True
    assert tui_mod.ask_yes_no('Dry-run?', default=True) is False


def test_an_unrecognised_answer_is_asked_again(monkeypatch):
    prompts, answers = [], iter(['maybe', 'yes'])

    def fake_input(prompt=''):
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr('builtins.input', fake_input)

    assert tui_mod.ask_yes_no('Dry-run?', default=False) is True
    assert prompts == ['====> Dry-run? ', '====> Dry-run? ']


def test_the_run_hands_subprocess_an_argument_list(monkeypatch):
    calls = []
    monkeypatch.setattr(
        tui_mod.subprocess, 'call',
        lambda command, env=None: calls.append((command, env)) or 0,
    )

    status = tui_mod.run_cleanup(['pypi-cleanup', '-r', '^(1\\.0)$'])

    assert status == 0
    # A list, not a command string: no shell can eat the pattern's backslashes.
    assert calls == [(['pypi-cleanup', '-r', '^(1\\.0)$'], None)]


def test_the_run_hands_subprocess_the_cleanup_environment(monkeypatch):
    calls = []
    monkeypatch.setattr(
        tui_mod.subprocess, 'call',
        lambda command, env=None: calls.append((command, env)) or 0,
    )
    env = {'PYPI_CLEANUP_PASSWORD': 'test-password'}

    assert tui_mod.run_cleanup(['pypi-cleanup'], env) == 0

    assert calls == [(['pypi-cleanup'], env)]


def test_a_missing_cleanup_tool_is_reported(monkeypatch, capsys):
    def missing(command, env=None):
        raise OSError('not found')

    monkeypatch.setattr(tui_mod.subprocess, 'call', missing)

    assert tui_mod.run_cleanup(['pypi-cleanup']) == 1
    assert 'could not run pypi-cleanup' in capsys.readouterr().out


def test_the_summary_line_reports_the_exit_status():
    assert (tui_mod.summary_line('Deletion', 'demo', 0)
            == "Deletion finished for 'demo'.")
    assert (tui_mod.summary_line('Deletion', 'demo', 2)
            == "Deletion failed for 'demo' (exit status 2).")


def test_the_prompt_is_decorated_and_waits_for_enter(monkeypatch):
    prompts = []
    monkeypatch.setattr('builtins.input', lambda prompt='': prompts.append(prompt))

    tui_mod.press_enter()

    assert prompts == ['\n\n===== Press ENTER to return to the TUI ====> ']


def test_the_terminal_is_cleared_after_curses(monkeypatch):
    calls = []
    monkeypatch.setattr(tui_mod.os, 'system', calls.append)

    tui_mod._reset_terminal()

    assert calls == ['clear; stty sane']


def test_d_hands_the_marked_versions_to_pypi_cleanup(monkeypatch):
    cleanup = _cleanup3()
    cleanup.versions[0].delete = True
    cleanup.versions[2].delete = True
    app = _app(cleanup)
    versions = []
    try:
        _draw(app)
        monkeypatch.setattr(app, 'hand_off_to_cleanup', versions.append)

        _press(app, ord('d'))

        # Table order, so the dry run and the deletion name the same rows.
        assert versions == [['2.0', '1.0']]
    finally:
        app.win.stop_curses()


def test_the_hand_off_runs_the_dry_run_then_the_deletion(monkeypatch, capsys):
    app = _app()
    runs, prompts = [], []

    def fake_fetch(self):
        self.versions = [Release('3.0', NOW)]
        return self.versions

    monkeypatch.setattr(CleanupTui, 'fetch_versions', fake_fetch)
    try:
        monkeypatch.setattr(tui_mod, '_reset_terminal', lambda: None)
        monkeypatch.setattr(
            tui_mod, 'press_enter', lambda: prompts.append('enter'))
        monkeypatch.setattr(
            tui_mod, 'ask_yes_no',
            lambda question, default: prompts.append(question) or True,
        )
        monkeypatch.setattr(
            tui_mod, 'run_cleanup',
            lambda command, env=None: runs.append(command) or 0,
        )

        app.hand_off_to_cleanup(['2.0', '1.0'])

        assert runs == [
            ['pypi-cleanup', '--query-only', '-y', '-u', 'alice',
             '-t', 'https://pypi.org/', '-p', 'demo', '-r', '^(2\\.0|1\\.0)$'],
            ['pypi-cleanup', '--do-it', '-y', '-u', 'alice',
             '-t', 'https://pypi.org/', '-p', 'demo', '-r', '^(2\\.0|1\\.0)$'],
        ]
        assert prompts == [
            tui_mod.DRY_RUN_PROMPT,
            "Del 2 Versions of 'demo'  [yes OR No]?",
            'enter',
        ]
        out = capsys.readouterr().out
        assert "+ pypi-cleanup -y -u 'alice'" in out
        assert "Dry run finished for 'demo'." in out
        assert "Deletion finished for 'demo'." in out
        # The window left curses for the runs and is attached again after.
        assert app.win.suspended is False
    finally:
        app.win.stop_curses()


def test_the_hand_off_maps_the_hosts_scoped_credentials(monkeypatch, capsys):
    cleanup = _cleanup()
    cleanup.host_key = HOST_TEST
    app = _app(cleanup)
    supplied = []
    try:
        monkeypatch.setattr(tui_mod, '_reset_terminal', lambda: None)
        monkeypatch.setattr(tui_mod, 'press_enter', lambda: None)
        monkeypatch.setattr(
            tui_mod, 'ask_yes_no',
            lambda question, default: question == tui_mod.DRY_RUN_PROMPT)
        monkeypatch.setattr(
            tui_mod, 'run_cleanup',
            lambda command, env=None: supplied.append(env) or 0,
        )
        monkeypatch.setenv('PYPI_CLEANUP_PASSWORD4TEST', 'test-password')

        app.hand_off_to_cleanup(['1.0'])

        assert supplied[0]['PYPI_CLEANUP_PASSWORD'] == 'test-password'
        # The printed description names the mapping, never the value.
        out = capsys.readouterr().out
        assert ('+ PYPI_CLEANUP_PASSWORD='
                'PYPI_CLEANUP_PASSWORD4TEST') in out
        assert 'test-password' not in out
    finally:
        app.win.stop_curses()


def test_the_hand_off_prints_the_code_before_the_run(monkeypatch, capsys):
    app = _app()
    answers = iter([True, False])   # yes to the dry run, no to the deletion
    try:
        monkeypatch.setattr(tui_mod, '_reset_terminal', lambda: None)
        monkeypatch.setattr(tui_mod, 'press_enter', lambda: None)
        monkeypatch.setattr(
            tui_mod, 'ask_yes_no',
            lambda question, default: next(answers),
        )
        monkeypatch.setattr(
            tui_mod, 'run_cleanup', lambda command, env=None: 0)
        monkeypatch.setattr(
            tui_mod.totp, 'code_with_room', lambda secret: ('123456', 30))
        monkeypatch.setenv(
            'PYPI_CLEANUP_TOTP_SECRET', 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ')

        app.hand_off_to_cleanup(['2.0'])

        out = capsys.readouterr().out
        assert out.count('Authentication code: ') == 1
        assert 'Authentication code: 123456 (expires in 30s)' in out
        # The code sits between the printed command and its report, so it is
        # the value the prompt after that command will ask for.
        assert (out.index('--query-only')
                < out.index('Authentication code:')
                < out.index('Dry run finished'))
    finally:
        app.win.stop_curses()


def test_a_no_to_the_dry_run_skips_it(monkeypatch):
    app = _app()
    runs = []
    try:
        monkeypatch.setattr(tui_mod, '_reset_terminal', lambda: None)
        monkeypatch.setattr(tui_mod, 'press_enter', lambda: None)
        monkeypatch.setattr(
            tui_mod, 'ask_yes_no', lambda question, default: False)
        monkeypatch.setattr(
            tui_mod, 'run_cleanup',
            lambda command, env=None: runs.append(command) or 0,
        )

        app.hand_off_to_cleanup(['2.0'])

        assert runs == []
    finally:
        app.win.stop_curses()


def test_a_no_to_the_deletion_leaves_the_index_alone(monkeypatch, capsys):
    app = _app()
    answers, runs = iter([True, False]), []
    try:
        monkeypatch.setattr(tui_mod, '_reset_terminal', lambda: None)
        monkeypatch.setattr(tui_mod, 'press_enter', lambda: None)
        monkeypatch.setattr(
            tui_mod, 'ask_yes_no',
            lambda question, default: next(answers),
        )
        monkeypatch.setattr(
            tui_mod, 'run_cleanup',
            lambda command, env=None: runs.append(command) or 0,
        )

        app.hand_off_to_cleanup(['2.0'])

        assert [command[1] for command in runs] == ['--query-only']
        assert 'Deletion' not in capsys.readouterr().out
    finally:
        app.win.stop_curses()


def test_a_failed_deletion_is_retried_until_it_succeeds(monkeypatch, capsys):
    app = _app()
    prompts, runs = [], []
    statuses = iter([0, 1, 0])          # query ok, first delete fails, retry ok

    def fake_fetch(self):
        self.versions = [Release('3.0', NOW)]
        return self.versions

    def answer(question, default):
        prompts.append(question)
        return True

    monkeypatch.setattr(CleanupTui, 'fetch_versions', fake_fetch)
    try:
        monkeypatch.setattr(tui_mod, '_reset_terminal', lambda: None)
        monkeypatch.setattr(tui_mod, 'press_enter', lambda: None)
        monkeypatch.setattr(tui_mod, 'ask_yes_no', answer)
        monkeypatch.setattr(
            tui_mod, 'run_cleanup',
            lambda command, env=None: runs.append(command) or next(statuses),
        )

        app.hand_off_to_cleanup(['2.0'])

        assert [command[1] for command in runs] == [
            '--query-only', '--do-it', '--do-it']
        assert "RETRY: Del 1 Versions of 'demo'  [yes OR No]?" in prompts
        out = capsys.readouterr().out
        assert "Deletion failed for 'demo' (exit status 1)." in out
        assert "Deletion finished for 'demo'." in out
    finally:
        app.win.stop_curses()


def test_a_no_to_the_retry_leaves_the_history_alone(monkeypatch):
    cleanup = _cleanup()
    cleanup.versions[0].delete = True
    app = _app(cleanup)
    prompts, runs = [], []
    answers = iter([True, True, False])  # dry run yes, delete yes, retry no

    def answer(question, default):
        prompts.append(question)
        return next(answers)

    try:
        monkeypatch.setattr(tui_mod, '_reset_terminal', lambda: None)
        monkeypatch.setattr(tui_mod, 'press_enter', lambda: None)
        monkeypatch.setattr(tui_mod, 'ask_yes_no', answer)
        monkeypatch.setattr(
            tui_mod, 'run_cleanup',
            lambda command, env=None: runs.append(command) or 1,
        )

        app.hand_off_to_cleanup(['2.0'])

        # A no to the retry stops the loop: no second do-it, no reload.
        assert [command[1] for command in runs] == ['--query-only', '--do-it']
        assert [release.version for release in cleanup.versions] == ['2.0', '1.0']
        assert app.session.get('demo') is None
        assert prompts[-1] == "RETRY: Del 1 Versions of 'demo'  [yes OR No]?"
    finally:
        app.win.stop_curses()


def test_a_successful_deletion_reloads_and_clears_the_view(monkeypatch):
    cleanup = _cleanup()
    cleanup.versions[0].delete = True
    app = _app(cleanup)
    fresh = [Release('3.0', NOW), Release('2.1', NOW)]

    def fake_fetch(self):
        self.versions = list(fresh)
        return self.versions

    monkeypatch.setattr(CleanupTui, 'fetch_versions', fake_fetch)
    try:
        app.search_text = '2'
        app.compile_search()
        app.win.pick_pos = 0
        monkeypatch.setattr(tui_mod, '_reset_terminal', lambda: None)
        monkeypatch.setattr(tui_mod, 'press_enter', lambda: None)
        monkeypatch.setattr(
            tui_mod, 'ask_yes_no', lambda question, default: True)
        monkeypatch.setattr(tui_mod, 'run_cleanup', lambda command, env=None: 0)

        app.hand_off_to_cleanup(['2.0'])
        # The run loop redraws the table straight after an action; doing the
        # same here lets the pick settle on the rebuilt body.
        _draw(app)
        app.win.render()

        # The table now holds only what the fresh query returned, and every
        # trace of the old view -- marks, search and pick -- is gone.
        assert [release.version for release in cleanup.versions] == ['3.0', '2.1']
        assert not any(release.delete for release in cleanup.versions)
        assert app.search_text == ''
        assert app.search_re is None
        assert app.win.pick_pos == 0
        session = app.session['demo']
        assert (session.deleted, session.versions) == (1, 2)
    finally:
        app.win.stop_curses()


def test_the_hand_off_comes_back_even_if_the_prompt_fails(monkeypatch):
    app = _app()
    try:
        monkeypatch.setattr(tui_mod, '_reset_terminal', lambda: None)
        monkeypatch.setattr(
            tui_mod, 'ask_yes_no', lambda question, default: False)

        def interrupted():
            raise KeyboardInterrupt

        monkeypatch.setattr(tui_mod, 'press_enter', interrupted)

        with pytest.raises(KeyboardInterrupt):
            app.hand_off_to_cleanup(['2.0'])

        # The finally clause must not leave the terminal in the bare state.
        assert app.win.suspended is False
    finally:
        app.win.stop_curses()


def test_d_does_nothing_when_nothing_is_marked(monkeypatch):
    app = _app(_cleanup3())
    calls = []
    try:
        _draw(app)
        monkeypatch.setattr(app, 'hand_off_to_cleanup', calls.append)

        _press(app, ord('d'))

        assert calls == []
    finally:
        app.win.stop_curses()


def test_the_del_hint_waits_for_the_pattern_to_close():
    cleanup = _cleanup3()
    cleanup.versions[0].delete = True
    app = _app(cleanup)
    try:
        _draw(app)
        assert app.win.head.texts[0].startswith('del ')

        _press(app, ord('/'))
        _press(app, ord('1'))
        _press(app, 10)
        app.win.clear()
        _draw(app)

        # The filter can hide marked releases, so the block goes blank.
        assert not app.win.head.texts[0].startswith('del ')
        assert app.win.head.texts[0].startswith(
            ' ' * (len(tui_mod.DEL_HINT) + 1))
    finally:
        app.win.stop_curses()


def test_escape_clears_the_pattern_and_brings_the_del_hint_back():
    cleanup = _cleanup3()
    cleanup.versions[0].delete = True
    app = _app(cleanup)
    try:
        _draw(app)
        _press(app, ord('/'))
        _press(app, ord('1'))
        _press(app, 27)  # ESC restores the empty pattern the search started with

        assert app.search_text == ''
        app.win.clear()
        _draw(app)

        assert app.win.head.texts[0].startswith('del ')
    finally:
        app.win.stop_curses()


def test_d_is_inert_while_a_pattern_is_in_force(monkeypatch):
    cleanup = _cleanup3()
    cleanup.versions[0].delete = True
    app = _app(cleanup)
    calls = []
    try:
        _draw(app)
        monkeypatch.setattr(app, 'hand_off_to_cleanup', calls.append)
        _press(app, ord('/'))
        _press(app, ord('1'))
        _press(app, 10)

        # 2.0 is marked but the pattern '1' hides it: d must not offer it.
        _press(app, ord('d'))

        assert calls == []
    finally:
        app.win.stop_curses()


def test_a_read_only_run_shows_ro_where_d_would_be():
    cleanup = _cleanup3()
    cleanup.versions[0].delete = True
    app = _app(cleanup, read_only=True)
    try:
        _draw(app)

        # The pick is on a marked row, so the rest of the line is the u/U pair.
        assert app.win.head.texts[0].startswith('R/O unmark')
        # The block is as wide as "del", so the keys to its right stay put.
        assert len(tui_mod.READ_ONLY_HINT) == len(tui_mod.DEL_HINT)
    finally:
        app.win.stop_curses()


def test_a_read_only_run_never_offers_d(monkeypatch):
    cleanup = _cleanup3()
    cleanup.versions[0].delete = True
    app = _app(cleanup, read_only=True)
    calls = []
    try:
        _draw(app)
        monkeypatch.setattr(app, 'hand_off_to_cleanup', calls.append)

        _press(app, ord('d'))

        assert calls == []
    finally:
        app.win.stop_curses()


# --- the g stability gap --------------------------------------------------

def _history(*days_ago):
    """A history whose newest release is *days_ago[0]* days old."""
    cleanup = CleanupTui('demo', user='alice')
    cleanup.versions = [
        Release(f'v{index}', NOW - timedelta(days=days))
        for index, days in enumerate(days_ago)
    ]
    return cleanup


def test_stable_releases_keeps_the_versions_that_stayed_current():
    cleanup = _history(0, 5, 40, 50)
    for release in cleanup.versions:
        release.delete = True

    stable = tui_mod.stable_releases(cleanup.versions, 30)

    # v0 is the newest, so nothing followed it, and v2 was current for 35 days;
    # v1 was superseded after 5 days and v3 after 10, so both stay marked.
    assert [release.version for release in stable] == ['v0', 'v2']


def test_the_gap_decides_which_versions_count_as_stable():
    cleanup = _history(0, 5, 40, 50)
    for release in cleanup.versions:
        release.delete = True

    assert len(tui_mod.stable_releases(cleanup.versions, 3)) == 4
    assert len(tui_mod.stable_releases(cleanup.versions, 7)) == 3
    assert len(tui_mod.stable_releases(cleanup.versions, 30)) == 2


def test_the_gap_counts_calendar_days_in_the_zone_the_table_shows():
    cleanup = CleanupTui('demo', user='alice')
    cleanup.versions = [
        Release('2.0', datetime(2024, 5, 2, 4, 0, tzinfo=UTC)),
        Release('1.0', datetime(2024, 5, 1, 3, 0, tzinfo=UTC)),
    ]
    for release in cleanup.versions:
        release.delete = True

    # In UTC the second release was followed one calendar day later, so it
    # did not clear a one-day gap.  In EDT those same uploads are 30 April
    # 23:00 and 2 May 00:00 -- two calendar days apart -- so it did.
    assert tui_mod.stable_releases(cleanup.versions, 1) == [cleanup.versions[0]]
    assert tui_mod.stable_releases(
        cleanup.versions, 1, tui_mod.LOCAL_MODE, EDT) == cleanup.versions


def test_the_hint_line_shows_the_gap_in_force():
    app = _app()
    try:
        _draw(app)
        assert 'gap30 ' in app.win.head.texts[0]

        app.opts.gap = 7
        app.win.clear()
        _draw(app)
        # The block keeps its width across one- and two-digit gaps, so the
        # keys to its right stay in the same columns.
        assert app.win.head.texts[0].endswith('gap7  quit ?:help /')
    finally:
        app.win.stop_curses()


def test_the_gap_reads_upload_times_not_the_table_order():
    cleanup = CleanupTui('demo', user='alice')
    cleanup.versions = [
        Release('2.0', NOW - timedelta(days=35)),
        Release('1.1', NOW - timedelta(days=40)),
    ]
    for release in cleanup.versions:
        release.delete = True

    # 2.0 was uploaded later, so it is the newest release and is kept; the
    # row order the table happens to show must not decide that.
    for order in (cleanup.versions, list(reversed(cleanup.versions))):
        assert [release.version for release in
                tui_mod.stable_releases(order, 30)] == ['2.0']


def test_g_judges_the_whole_history_while_the_table_is_filtered(monkeypatch):
    cleanup = _history(0, 5, 40, 50)
    for release in cleanup.versions:
        release.delete = True
    app = _app(cleanup)
    try:
        _draw(app)
        monkeypatch.setattr(app.win, 'flash', lambda *args, **kwargs: None)
        _press(app, ord('/'))
        _press(app, ord('v'))
        _press(app, ord('0'))
        _press(app, 10)

        _press(app, ord('g'))

        # v2 is kept even though the pattern hides it: how quickly a release
        # was superseded is a fact about the package, not about the filter.
        assert [release.delete for release in cleanup.versions] == [
            False, True, False, True]
    finally:
        app.win.stop_curses()


def test_stable_releases_ignores_the_versions_that_are_not_marked():
    cleanup = _history(0, 5, 40, 50)
    cleanup.versions[1].delete = True

    assert tui_mod.stable_releases(cleanup.versions, 30) == []


def test_g_keeps_the_marked_releases_that_stayed_stable(monkeypatch):
    cleanup = _history(0, 5, 40, 50)
    for release in cleanup.versions:
        release.delete = True
    app = _app(cleanup)
    calls = []
    try:
        _draw(app)
        monkeypatch.setattr(
            app.win, 'flash',
            lambda message, duration=0: calls.append((message, duration)),
        )

        _press(app, ord('g'))

        assert [release.delete for release in cleanup.versions] == [
            False, True, False, True]
        assert calls == [('Kept 2 of 4 marked versions, gap 30 days', 2.0)]
    finally:
        app.win.stop_curses()


def test_g_rotates_the_gap_on_the_help_screen():
    app = _app()
    try:
        app.opts.help_screen = True
        app.stack.perform_actions(app.spin)
        assert app.opts.gap == tui_mod.DEFAULT_GAP

        _press(app, ord('g'))
        assert app.opts.gap == tui_mod.GAP_CHOICES[-1]

        _press(app, ord('g'))
        assert app.opts.gap == tui_mod.GAP_CHOICES[0]

        app.win.clear()
        app.screens[tui_mod.HELP_ST].draw_screen()
        assert 'g - stability gap, in days' in '\n'.join(app.win.body.texts)
    finally:
        app.win.stop_curses()


def test_the_starting_gap_is_the_one_the_run_was_handed():
    # main() reads the store and normalizes the value before it builds the app,
    # so the constructor only has to seed the option with it.
    app = _app(gap=7)
    try:
        _draw(app)

        assert app.opts.gap == 7
        assert 'gap7 ' in app.win.head.texts[0]
    finally:
        app.win.stop_curses()


def test_an_unknown_starting_gap_falls_back_to_the_default():
    # A hand-edited gap that is not one of the choices must not reach the
    # stability filter.
    app = _app(gap=5)
    try:
        _draw(app)

        assert app.opts.gap == tui_mod.DEFAULT_GAP
        assert 'gap30 ' in app.win.head.texts[0]
    finally:
        app.win.stop_curses()


def test_g_stores_the_gap_for_the_next_run(tmp_path):
    ini = _ini(tmp_path)
    app = _app(ini=ini)
    try:
        app.opts.help_screen = True
        app.stack.perform_actions(app.spin)

        _press(app, ord('g'))

        assert app.opts.gap == tui_mod.GAP_CHOICES[-1]
        assert ini.vals.gap == tui_mod.GAP_CHOICES[-1]
        # The choice reaches the file, so the next run starts with it.
        assert _ini(tmp_path).vals.gap == tui_mod.GAP_CHOICES[-1]
    finally:
        app.win.stop_curses()


def test_g_does_nothing_off_the_table_and_the_help_screen():
    cleanup = _history(0, 5, 40, 50)
    for release in cleanup.versions:
        release.delete = True
    app = _app(cleanup)
    try:
        app.stack.push(tui_mod.PACKAGES_ST)

        _press(app, ord('g'))

        assert app.opts.gap == tui_mod.DEFAULT_GAP
        assert all(release.delete for release in cleanup.versions)
    finally:
        app.win.stop_curses()


# --- the s sort action ----------------------------------------------------

def test_s_flips_the_sort_order_and_moves_the_star():
    cleanup = _mixed()
    app = _app(cleanup)
    try:
        _draw(app)
        assert cleanup.sort == SORT_BY_VERSION
        assert '*VERSION' in app.win.head.texts[2]

        _press(app, ord('s'))
        assert cleanup.sort == SORT_BY_DATE
        assert [release.version for release in cleanup.versions] == [
            '1.1', '2.0']

        app.win.clear()
        _draw(app)
        assert '*DATE (UTC)' in app.win.head.texts[2]
        assert '*VERSION' not in app.win.head.texts[2]

        _press(app, ord('s'))
        assert cleanup.sort == SORT_BY_VERSION
        assert [release.version for release in cleanup.versions] == [
            '2.0', '1.1']
    finally:
        app.win.stop_curses()


# --- remembered settings ---------------------------------------------------

def test_z_stores_the_zone_for_the_next_run(tmp_path):
    ini = _ini(tmp_path)
    app = _app(ini=ini)
    try:
        _press(app, ord('z'))

        assert ini.vals.zone == tui_mod.LOCAL_MODE
        assert _ini(tmp_path).vals.zone == tui_mod.LOCAL_MODE
    finally:
        app.win.stop_curses()


def test_s_stores_the_sort_order_for_the_next_run(tmp_path):
    ini = _ini(tmp_path)
    app = _app(_mixed(), ini=ini)
    try:
        _press(app, ord('s'))

        assert ini.vals.sort == SORT_BY_DATE
        assert _ini(tmp_path).vals.sort == SORT_BY_DATE
    finally:
        app.win.stop_curses()


def test_saving_a_setting_also_stores_the_index_in_use(tmp_path):
    ini = _ini(tmp_path)
    app = _app(CleanupTui('demo', host='test'), ini=ini)
    try:
        _press(app, ord('z'))

        assert ini.vals.host == 'test'
    finally:
        app.win.stop_curses()


def test_the_stored_zone_is_the_starting_zone():
    app = _app(zone=tui_mod.LOCAL_MODE)
    try:
        assert app.spin.get_value('time_zone') == tui_mod.LOCAL_MODE
    finally:
        app.win.stop_curses()


def test_an_unknown_starting_zone_falls_back_to_utc():
    app = _app(zone='Mars')
    try:
        assert app.spin.get_value('time_zone') == tui_mod.UTC_MODE
    finally:
        app.win.stop_curses()


def test_a_key_bound_to_another_screen_stores_nothing(tmp_path):
    ini = _ini(tmp_path)
    app = _app(ini=ini)
    try:
        app.opts.help_screen = True
        app.stack.perform_actions(app.spin)
        _press(app, ord('z'))

        assert app.stack.curr.num == tui_mod.HELP_ST
        assert ini.vals.zone == tui_mod.UTC_MODE
    finally:
        app.win.stop_curses()


def test_persisting_without_a_store_changes_nothing():
    app = _app()
    try:
        assert app.persist(zone=tui_mod.LOCAL_MODE) is None
        assert app.spin.get_value('time_zone') == tui_mod.UTC_MODE
    finally:
        app.win.stop_curses()


# --- actions --------------------------------------------------------------

def test_help_screen_lists_the_selection_and_zone_keys():
    app = _app()
    try:
        app.screens[tui_mod.HELP_ST].draw_screen()

        text = '\n'.join(app.win.body.texts)
        for hint in ('x - mark this release', 'X - mark this release',
                     'u - unmark this release', 'U - unmark this release',
                     'z - date time zone', 's - change the sort order',
                     'p - next package', 'h - switch index', 'P - package list',
                     'T - themes', '/ - incremental search',
                     'x - remove from the package list [Package Screen]',
                     'ESC - back, or open the picked package',
                     'd - delete the marked versions with pypi-cleanup',
                     'g - stability gap, in days',
                     'g - keep the releases that stayed stable [Main Screen]'):
            assert hint in text
        assert tui_mod.UTC_MODE in text
        assert tui_mod.LOCAL_MODE in text
        assert 'Color theme' in text
        assert 'visible rows only' in text
        assert 'working package list' in text
        # The bullets are wrapped, so compare them with the breaks removed.
        assert 'newest release counts as stable' in ' '.join(text.split())
        assert 'leaves the table for the terminal' in ' '.join(text.split())
        assert 'asks for a --query-only dry run' in ' '.join(text.split())
        assert 'not meant to be copied' in ' '.join(text.split())
        assert '--read-only' in text
        # The notes read as a bulleted list with a hanging indent.
        assert any(line.startswith('* Color theme') for line in app.win.body.texts)
        assert any(line.startswith('  ') for line in app.win.body.texts)
    finally:
        app.win.stop_curses()


def test_the_help_screen_lists_the_cycles_before_the_other_keys():
    app = _app()
    try:
        app.screens[tui_mod.HELP_ST].draw_screen()

        body = app.win.body.texts

        def row(hint):
            return next(index for index, line in enumerate(body)
                        if line.startswith(hint))

        assert row('q - quit') < row('? - help')
        for hint in ('z - date time zone', 't - cycle themes',
                     'g - stability gap, in days'):
            assert row('? - help') < row(hint) < row('x - mark this release')
        assert row('x - mark this release') < row(
            'x - remove from the package list [Package Screen]')
    finally:
        app.win.stop_curses()


def test_the_help_screen_names_the_read_only_mode():
    app = _app(read_only=True)
    try:
        app.screens[tui_mod.HELP_ST].draw_screen()

        text = ' '.join('\n'.join(app.win.body.texts).split())
        assert 'd - delete the marked versions (read-only mode)' in text
    finally:
        app.win.stop_curses()


def test_the_help_screen_can_add_the_symbol_note():
    app = _app()
    try:
        screen = app.screens[tui_mod.HELP_ST]
        # The base screen offers this note; this app leaves it off, but the
        # bulleted notes must still fold it in when it is turned on.
        screen.show_display_notes = True
        screen.draw_screen()

        assert any(line.startswith('* Symbols')
                   for line in app.win.body.texts)
    finally:
        screen.show_display_notes = False
        app.win.stop_curses()


def test_the_help_screen_lists_the_saved_options(tmp_path):
    ini = _ini(tmp_path)
    ini.save(user='alice', packages='demo')
    app = _app(ini=ini)
    try:
        app.screens[tui_mod.HELP_ST].draw_screen()

        text = '\n'.join(app.win.body.texts)
        assert 'Saved options' in text
        assert 'config.ini' in text
        assert "user='alice'" in text
        assert "packages='demo'" in text
    finally:
        app.win.stop_curses()


def test_help_screen_is_pushed_and_esc_pops_back():
    app = _app()
    try:
        app.opts.help_screen = True
        app.stack.perform_actions(app.spin)
        assert app.stack.curr.num == tui_mod.HELP_ST

        app.screens[tui_mod.HELP_ST].draw_screen()
        assert app.win.body.row_cnt > 0

        app.opts.escape = True
        app.stack.perform_actions(app.spin)
        assert app.stack.curr.num == tui_mod.MAIN_ST
    finally:
        app.win.stop_curses()


def test_q_quits_but_ctrl_c_is_ignored():
    app = _app()
    try:
        assert app.win.opts.ctrl_c_terminates is False
        assert 0x3 not in app.spin.keys

        app.opts.quit = True
        app.stack.perform_actions(app.spin)
        assert app.running is False

        app.running = True
        app.handle_key(0x3)
        assert app.running is True
    finally:
        app.win.stop_curses()


def test_run_tui_draws_and_returns_after_q(monkeypatch):
    monkeypatch.setattr(CleanupTui, 'fetch_versions', lambda self: [])
    backend = HeadlessBackend(rows=20, cols=100)
    backend.queue_keys(ord('q'))

    assert tui_mod.run_tui(_cleanup(), backend=backend, singleton=False) == 0
    assert backend.stopped is True
