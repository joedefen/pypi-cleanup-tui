"""Headless tests for the interactive release table.

The console-window ``HeadlessBackend`` lets the whole application be built and
drawn without a TTY, so these tests describe the screen's contract rather than
whatever terminal happens to run them.
"""

from __future__ import annotations

import curses
from datetime import datetime, timedelta, timezone

import pytest
from console_window.backend import HeadlessBackend

from pypi_cleanup_tui import tui as tui_mod
from pypi_cleanup_tui.ini import IniManager
from pypi_cleanup_tui.main import (
    APP_NAME,
    DEFAULTS,
    HOST_TEST,
    SORT_BY_DATE,
    SORT_BY_VERSION,
    CleanupTui,
    Release,
)

NOW = datetime(2024, 5, 1, 12, 0, tzinfo=timezone.utc)
EDT = timezone(timedelta(hours=-4), 'EDT')


@pytest.fixture(autouse=True)
def _headless_curses_stubs(monkeypatch):
    # curses.has_colors() and curses.color_pair() raise until initscr() has
    # succeeded; the window's theme setup may still probe them.  The ACS
    # constants are absent on a curses build that never initialised a screen,
    # yet render() draws the header/body separator with ACS_HLINE.
    monkeypatch.setattr(curses, 'has_colors', lambda: False, raising=False)
    monkeypatch.setattr(curses, 'color_pair', lambda n=0: n << 8, raising=False)
    monkeypatch.setattr(curses, 'ACS_HLINE', '-', raising=False)


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


def _app(cleanup=None, rows=20, cols=100, ini=None, zone=None):
    return tui_mod.CleanupApp(
        cleanup or _cleanup(),
        backend=HeadlessBackend(rows=rows, cols=cols),
        singleton=False,
        ini=ini,
        zone=zone or tui_mod.UTC_MODE,
    )


def _ini(tmp_path):
    """A throwaway option store shaped like the real one."""
    return IniManager(APP_NAME, config_path=tmp_path / 'config.ini', **DEFAULTS)


def _draw(app):
    """Draw the main screen and return it, so tests read like a run loop."""
    app.screens[tui_mod.MAIN_ST].draw_screen()
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
        assert app.win.head.texts[0] == (
            f'x:mark X:mark{tui_mod.DOWN_MARK} unmark '
            f'Unmark{tui_mod.DOWN_MARK} zone quit ?:help')
        # The summary is a fancy header: [p] and [h] are key styled, User is
        # literal.  It is not dimmed, unlike the hint and column lines.
        assert app.win.head.texts[1] == 'User=alice pack=demo host=pypi'
        summary_attrs = [attr for attr, _ in app.win.head.text_attrs[1]]
        assert not any(attr and attr & curses.A_DIM for attr in summary_attrs)
        assert any(attr and attr & curses.A_UNDERLINE for attr in summary_attrs)
        assert 'Times' not in app.win.head.texts[1]
        assert 'Sort' not in app.win.head.texts[1]
        assert 'Releases' not in app.win.head.texts[1]
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


def test_the_summary_line_shows_n_a_without_a_user():
    app = _app(CleanupTui('demo'))
    try:
        _draw(app)

        assert app.win.head.texts[1] == 'User=n/a pack=demo host=pypi'
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

        cleanup.versions[0].delete = True
        app.win.clear()
        _draw(app)

        assert app.win.head.texts[0].startswith('del ')
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


# --- the d placeholder ----------------------------------------------------

def test_d_flashes_the_pending_deletion_count(monkeypatch):
    cleanup = _cleanup3()
    cleanup.versions[0].delete = True
    cleanup.versions[2].delete = True
    app = _app(cleanup)
    calls = []
    try:
        _draw(app)
        monkeypatch.setattr(
            app.win, 'flash',
            lambda message, duration=0: calls.append((message, duration)),
        )

        _press(app, ord('d'))

        assert calls == [('To delete 2 versions [TODO]', 2.0)]
    finally:
        app.win.stop_curses()


def test_d_does_nothing_when_nothing_is_marked(monkeypatch):
    app = _app(_cleanup3())
    calls = []
    try:
        _draw(app)
        monkeypatch.setattr(app.win, 'flash', lambda *args, **kwargs: calls.append(args))

        _press(app, ord('d'))

        assert calls == []
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
                     'd - delete the marked versions (TODO)'):
            assert hint in text
        assert tui_mod.UTC_MODE in text
        assert tui_mod.LOCAL_MODE in text
    finally:
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


def test_run_tui_draws_and_returns_after_q():
    backend = HeadlessBackend(rows=20, cols=100)
    backend.queue_keys(ord('q'))

    assert tui_mod.run_tui(_cleanup(), backend=backend, singleton=False) == 0
    assert backend.stopped is True
