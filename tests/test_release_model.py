"""Tests for the release-history model and the command-line entry point.

The network is never touched: the PyPI JSON API is replaced by a fake response,
so the tests describe the parsing and sorting contract, not the index's state.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import StringIO

import pytest
import requests
from packaging.version import Version

from pypi_cleanup_tui import main as cli
from pypi_cleanup_tui.main import (
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


# --- rendering and URLs ---------------------------------------------------

def test_dump_without_releases_says_so():
    stream = StringIO()
    CleanupTui('demo').dump(stream)

    assert stream.getvalue() == 'No releases found.\n'


def test_dump_prints_a_header_and_every_release():
    tui = CleanupTui('demo')
    tui.versions = [release('1.2.3'), release('1.0', -3)]
    stream = StringIO()

    tui.dump(stream)

    lines = stream.getvalue().splitlines()
    assert lines[0].startswith('VERSION')
    assert '1.2.3' in lines[2]
    assert '1.0' in lines[3]


def test_index_selection_follows_is_test_pypi():
    production = CleanupTui('demo')
    rehearsal = CleanupTui('demo', is_test_pypi=True)

    assert production.base_url == 'https://pypi.org/pypi'
    assert production.host == 'pypi.org'
    assert rehearsal.base_url == 'https://test.pypi.org/pypi'
    assert rehearsal.host == 'test.pypi.org'


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


def test_fetch_versions_names_the_missing_project(monkeypatch):
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

def test_main_requires_a_project(capsys):
    with pytest.raises(SystemExit) as caught:
        cli.main([])

    assert caught.value.code == 2
    assert 'a project name is required' in capsys.readouterr().err


def test_main_reports_a_project_the_index_does_not_know(monkeypatch, capsys):
    def missing(self):
        raise LookupError('project missing')

    monkeypatch.setattr(CleanupTui, 'fetch_versions', missing)

    assert cli.main(['demo']) == 1
    assert 'error: project missing' in capsys.readouterr().err


def test_main_reports_a_network_failure(monkeypatch, capsys):
    def broken(self):
        raise requests.ConnectionError('connection refused')

    monkeypatch.setattr(CleanupTui, 'fetch_versions', broken)

    assert cli.main(['demo']) == 1
    assert 'could not fetch pypi.org/demo' in capsys.readouterr().err


def test_main_explains_the_tui_is_not_implemented(monkeypatch, capsys):
    monkeypatch.setattr(CleanupTui, 'fetch_versions', lambda self: [])

    assert cli.main(['demo']) == 2
    assert 'not implemented yet' in capsys.readouterr().err


def test_main_dumps_the_table_in_the_requested_order(monkeypatch, capsys):
    def fetched(self):
        self.versions = [release('1.0', -2), release('2.0', 0)]
        return self.versions

    monkeypatch.setattr(CleanupTui, 'fetch_versions', fetched)

    assert cli.main(['demo', '--dump', '--sort', 'date']) == 0
    lines = capsys.readouterr().out.splitlines()
    assert '2.0' in lines[2]
    assert '1.0' in lines[3]
