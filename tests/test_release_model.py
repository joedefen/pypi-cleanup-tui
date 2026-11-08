"""Tests for the release-history model and the command-line entry point.

The network is never touched: the PyPI JSON API is replaced by a fake response,
so the tests describe the parsing and sorting contract, not the index's state.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import requests
from packaging.version import Version

from pypi_cleanup_tui import main as cli
from pypi_cleanup_tui.ini import IniManager
from pypi_cleanup_tui.main import (
    APP_NAME,
    DEFAULTS,
    HOST_TEST,
    LOCAL_MODE,
    SORT_BY_DATE,
    SORT_BY_VERSION,
    UTC_MODE,
    CleanupTui,
    Release,
    _parse_upload_time,
    _parsed_version,
)

NOW = datetime(2024, 5, 1, 12, 0, tzinfo=timezone.utc)


def release(version: str, days: int = 0) -> Release:
    return Release(version, NOW + timedelta(days=days))


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f'HTTP {self.status_code}')

    def json(self):
        return self._payload


# --- timestamps and versions ---------------------------------------------

def test_parse_upload_time_normalizes_to_utc():
    expected = datetime(2024, 5, 1, 12, 0, tzinfo=timezone.utc)

    assert _parse_upload_time('2024-05-01T12:00:00Z') == expected
    assert _parse_upload_time('2024-05-01T12:00:00') == expected
    assert _parse_upload_time('2024-05-01T08:00:00-04:00') == expected


def test_parse_upload_time_refuses_rather_than_guesses():
    assert _parse_upload_time(None) is None
    assert _parse_upload_time('') is None
    assert _parse_upload_time('not-a-date') is None


def test_release_str_aligns_the_version_column():
    text = str(release('1.2.3'))

    assert text.startswith(f'{"1.2.3":<20}')
    assert text.endswith('2024-05-01 12:00')


def test_parsed_version_rejects_legacy_identifiers():
    assert _parsed_version(release('1.2.3')) == Version('1.2.3')
    assert _parsed_version(release('2.4pl1')) is None


# --- sorting --------------------------------------------------------------

def test_sort_by_version_puts_legacy_identifiers_last():
    tui = CleanupTui('demo')
    tui.versions = [release(name) for name in
                    ('1.0a1', '1.0', '2.4pl1', '1.0.post1', '0.9')]

    assert [item.version for item in tui.sort_versions()] == [
        '1.0.post1', '1.0', '1.0a1', '0.9', '2.4pl1']
    assert tui.sort == 'version'


def test_sort_by_version_ascending_also_keeps_legacy_last():
    tui = CleanupTui('demo')
    tui.versions = [release(name) for name in
                    ('1.0a1', '1.0', '2.4pl1', '1.0.post1', '0.9')]

    assert [item.version for item in tui.sort_versions(reverse=False)] == [
        '0.9', '1.0a1', '1.0', '1.0.post1', '2.4pl1']


def test_sort_by_date_orders_by_upload_time():
    tui = CleanupTui('demo')
    tui.versions = [release('1.0', -2), release('2.0', 0), release('1.5', -1)]

    assert [item.version for item in tui.sort_versions('date')] == [
        '2.0', '1.5', '1.0']
    assert [item.version for item in tui.sort_versions('date', reverse=False)] == [
        '1.0', '1.5', '2.0']
    assert tui.sort == 'date'


def test_sort_refuses_an_unknown_key():
    tui = CleanupTui('demo')

    with pytest.raises(ValueError, match='unknown sort key'):
        tui.sort_versions('size')


# --- URLs -----------------------------------------------------------------

def test_index_selection_follows_the_host():
    production = CleanupTui('demo')
    rehearsal = CleanupTui('demo', host=HOST_TEST)

    assert production.base_url == 'https://pypi.org/pypi'
    assert production.host == 'pypi.org'
    assert rehearsal.base_url == 'https://test.pypi.org/pypi'
    assert rehearsal.host == 'test.pypi.org'


def test_an_unknown_host_is_refused():
    with pytest.raises(ValueError, match='unknown host'):
        CleanupTui('demo', host='somewhere')


# --- fetching -------------------------------------------------------------

def test_fetch_versions_skips_empty_releases_and_uses_the_oldest_file(monkeypatch):
    payload = {'releases': {
        '1.0': [
            {'upload_time_iso_8601': '2024-05-01T10:00:00Z'},
            {'upload_time_iso_8601': '2024-05-01T09:00:00Z'},
        ],
        '0.9': [],
        '0.8': [{'upload_time': '2024-04-01T00:00:00'}],
    }}
    monkeypatch.setattr(cli.requests, 'get',
                        lambda url, **kwargs: FakeResponse(payload))
    tui = CleanupTui('demo')

    releases = {item.version: item.uploaded for item in tui.fetch_versions()}

    assert set(releases) == {'1.0', '0.8'}
    assert releases['1.0'] == datetime(2024, 5, 1, 9, 0, tzinfo=timezone.utc)
    assert releases['0.8'] == datetime(2024, 4, 1, 0, 0, tzinfo=timezone.utc)


def test_fetch_versions_names_the_missing_package(monkeypatch):
    monkeypatch.setattr(cli.requests, 'get',
                        lambda url, **kwargs: FakeResponse({}, status_code=404))

    with pytest.raises(LookupError, match='was not found on pypi.org'):
        CleanupTui('demo').fetch_versions()


def test_fetch_versions_surfaces_a_server_error(monkeypatch):
    monkeypatch.setattr(cli.requests, 'get',
                        lambda url, **kwargs: FakeResponse({}, status_code=500))

    with pytest.raises(requests.HTTPError):
        CleanupTui('demo').fetch_versions()


# --- the command-line entry point -----------------------------------------

@pytest.fixture
def config_path(tmp_path):
    """This test's own config file; the real ``~/.config`` is never touched."""
    return tmp_path / 'config.ini'


def stored(config_path, **overrides):
    """Create the config file, optionally storing more than the defaults."""
    ini = IniManager(APP_NAME, config_path=config_path, **DEFAULTS)
    if overrides:
        ini.save(**overrides)
    return ini


def capture_tui(monkeypatch):
    """Replace run_tui, collecting every (cleanup, kwargs) it is given."""
    import pypi_cleanup_tui.tui as tui

    seen = []

    def fake_run_tui(cleanup, **kwargs):
        seen.append((cleanup, kwargs))
        return 0

    monkeypatch.setattr(tui, 'run_tui', fake_run_tui)
    return seen


def test_main_requires_a_package(capsys, config_path):
    with pytest.raises(SystemExit) as caught:
        cli.main([], config_path=config_path)

    assert caught.value.code == 2
    assert 'at least one package name is required' in capsys.readouterr().err


def test_main_reports_a_package_the_index_does_not_know(monkeypatch, capsys, config_path):
    def missing(self):
        raise LookupError('package missing')

    monkeypatch.setattr(CleanupTui, 'fetch_versions', missing)

    assert cli.main(['demo'], config_path=config_path) == 1
    assert 'error: package missing' in capsys.readouterr().err


def test_main_reports_a_network_failure(monkeypatch, capsys, config_path):
    def broken(self):
        raise requests.ConnectionError('connection refused')

    monkeypatch.setattr(CleanupTui, 'fetch_versions', broken)

    assert cli.main(['demo'], config_path=config_path) == 1
    assert 'could not fetch pypi.org/demo' in capsys.readouterr().err


def test_host_selects_the_index(monkeypatch, capsys, config_path):
    def broken(self):
        raise requests.ConnectionError('connection refused')

    monkeypatch.setattr(CleanupTui, 'fetch_versions', broken)

    assert cli.main(['demo', '--host', 'test'], config_path=config_path) == 1
    assert 'could not fetch test.pypi.org/demo' in capsys.readouterr().err


def test_main_launches_the_tui(monkeypatch, config_path):
    monkeypatch.setattr(CleanupTui, 'fetch_versions', lambda self: [])
    seen = capture_tui(monkeypatch)

    assert cli.main(['demo'], config_path=config_path) == 0

    cleanup, kwargs = seen[0]
    assert cleanup.package == 'demo'
    assert kwargs['zone'] == UTC_MODE
    assert kwargs['ini'].vals.packages == 'demo'


# --- what the command line remembers --------------------------------------

def test_the_saved_package_list_is_one_comma_separated_string(monkeypatch, config_path):
    monkeypatch.setattr(CleanupTui, 'fetch_versions', lambda self: [])
    seen = capture_tui(monkeypatch)

    assert cli.main(['pack1,pack2'], config_path=config_path) == 0

    # The table shows one package at a time; the list is remembered whole.
    assert [cleanup.package for cleanup, _ in seen] == ['pack1']
    assert stored(config_path).vals.packages == 'pack1,pack2'


def test_separate_package_arguments_are_joined_with_commas(monkeypatch, config_path):
    monkeypatch.setattr(CleanupTui, 'fetch_versions', lambda self: [])
    capture_tui(monkeypatch)

    assert cli.main(['pack1', 'pack2', 'pack3'], config_path=config_path) == 0

    assert stored(config_path).vals.packages == 'pack1,pack2,pack3'


def test_blank_package_names_are_dropped(monkeypatch, config_path):
    monkeypatch.setattr(CleanupTui, 'fetch_versions', lambda self: [])
    capture_tui(monkeypatch)

    assert cli.main(['pack1,,pack2,'], config_path=config_path) == 0

    assert stored(config_path).vals.packages == 'pack1,pack2'


def test_a_later_run_needs_no_arguments(monkeypatch, config_path):
    monkeypatch.setattr(CleanupTui, 'fetch_versions', lambda self: [])
    seen = capture_tui(monkeypatch)

    assert cli.main(['-u', 'alice', '--host', 'test', 'pack1,pack2'],
                    config_path=config_path) == 0
    assert cli.main([], config_path=config_path) == 0

    assert [cleanup.package for cleanup, _ in seen] == ['pack1', 'pack1']
    cleanup = seen[1][0]
    assert cleanup.user == 'alice'
    assert cleanup.host_key == 'test'


def test_the_command_line_replaces_what_was_stored(monkeypatch, config_path):
    stored(config_path, user='alice', host='test', packages='old1,old2')
    monkeypatch.setattr(CleanupTui, 'fetch_versions', lambda self: [])
    seen = capture_tui(monkeypatch)

    assert cli.main(['new'], config_path=config_path) == 0

    assert stored(config_path).vals.packages == 'new'
    assert seen[0][0].package == 'new'


def test_the_stored_sort_and_zone_are_used_at_startup(monkeypatch, config_path):
    stored(config_path, sort=SORT_BY_DATE, zone=LOCAL_MODE)
    monkeypatch.setattr(CleanupTui, 'fetch_versions', lambda self: [])
    seen = capture_tui(monkeypatch)

    assert cli.main(['demo'], config_path=config_path) == 0

    cleanup, kwargs = seen[0]
    assert cleanup.sort == SORT_BY_DATE
    assert kwargs['zone'] == LOCAL_MODE


def test_the_theme_switch_is_stored_and_passed_on(monkeypatch, config_path):
    monkeypatch.setattr(CleanupTui, 'fetch_versions', lambda self: [])
    seen = capture_tui(monkeypatch)

    assert cli.main(['demo', '--theme', 'nord'], config_path=config_path) == 0

    _, kwargs = seen[0]
    assert kwargs['theme'] == 'nord'
    assert kwargs['no_color'] is None
    assert stored(config_path).vals.theme == 'nord'
    assert stored(config_path).vals.no_color is False


def test_no_color_is_stored_for_the_next_run(monkeypatch, config_path):
    monkeypatch.setattr(CleanupTui, 'fetch_versions', lambda self: [])
    seen = capture_tui(monkeypatch)

    assert cli.main(['demo', '--no-color'], config_path=config_path) == 0

    _, kwargs = seen[0]
    assert kwargs['no_color'] is True
    assert stored(config_path).vals.no_color is True


def test_mono_on_the_command_line_stores_color_off(monkeypatch, config_path):
    monkeypatch.setattr(CleanupTui, 'fetch_versions', lambda self: [])
    capture_tui(monkeypatch)

    assert cli.main(['demo', '--theme', cli.MONO_THEME],
                    config_path=config_path) == 0

    assert stored(config_path).vals.theme == cli.MONO_THEME
    assert stored(config_path).vals.no_color is True


def test_an_unknown_theme_is_refused(capsys, config_path):
    with pytest.raises(SystemExit) as caught:
        cli.main(['demo', '--theme', 'nope'], config_path=config_path)

    assert caught.value.code == 2
    assert 'unknown theme' in capsys.readouterr().err


def test_the_stored_theme_and_no_color_are_used_at_startup(monkeypatch, config_path):
    stored(config_path, theme='nord', no_color=True)
    monkeypatch.setattr(CleanupTui, 'fetch_versions', lambda self: [])
    seen = capture_tui(monkeypatch)

    assert cli.main(['demo'], config_path=config_path) == 0

    _, kwargs = seen[0]
    # Without a switch the TUI reads the remembered choice from the store.
    assert kwargs['theme'] is None
    assert kwargs['no_color'] is None
    assert stored(config_path).vals.theme == 'nord'
    assert stored(config_path).vals.no_color is True


def test_a_hand_edited_config_falls_back_to_known_values(monkeypatch, config_path):
    config_path.write_text(
        '[options]\nuser = \nhost = elsewhere\npackages = demo\n'
        'zone = Mars\nsort = size\ntheme = nonsense\nno_color = maybe\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(CleanupTui, 'fetch_versions', lambda self: [])
    seen = capture_tui(monkeypatch)

    assert cli.main([], config_path=config_path) == 0

    cleanup, kwargs = seen[0]
    assert cleanup.host_key == 'pypi'
    assert cleanup.sort == SORT_BY_VERSION
    assert kwargs['zone'] == UTC_MODE
    assert stored(config_path).vals.theme == ''
    assert stored(config_path).vals.no_color is False


def test_a_save_failure_is_only_a_warning(monkeypatch, capsys, config_path):
    monkeypatch.setattr(CleanupTui, 'fetch_versions', lambda self: [])
    capture_tui(monkeypatch)

    def broken(self, **values):
        raise OSError('read-only home')

    monkeypatch.setattr(IniManager, 'save', broken)

    assert cli.main(['demo'], config_path=config_path) == 0
    assert 'could not save' in capsys.readouterr().err
