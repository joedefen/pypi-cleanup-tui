"""Tests for the INI-backed option store.

Every test uses a temporary config path, so nothing here reads or writes the
real ``~/.config`` directory.
"""

from __future__ import annotations

import configparser
from pathlib import Path

import pytest

from pypi_cleanup_tui.ini import IniManager

APP = 'test-app'


def manager(tmp_path: Path, **defaults):
    """An IniManager over ``<tmp>/config.ini`` with sensible defaults."""
    defaults.setdefault('name', 'demo')
    return IniManager(APP, config_path=tmp_path / 'config.ini', **defaults)


def section_of(path: Path) -> dict[str, str]:
    config = configparser.ConfigParser(interpolation=None)
    config.read(path, encoding='utf-8')
    return dict(config['options'])


def test_the_first_run_writes_the_defaults(tmp_path):
    ini = manager(tmp_path, threads=4)

    assert ini.config_file_path.exists()
    assert ini.vals.threads == 4
    assert section_of(ini.config_file_path)['name'] == 'demo'


def test_the_default_path_lives_under_the_config_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'home', staticmethod(lambda: tmp_path))

    ini = IniManager(APP, name='demo')

    assert ini.config_file_path == tmp_path / '.config' / APP / 'config.ini'
    assert ini.config_file_path.exists()


def test_an_app_name_is_required(tmp_path):
    with pytest.raises(ValueError, match='app_name'):
        IniManager('', config_path=tmp_path / 'config.ini', name='demo')


def test_the_file_wins_over_later_defaults(tmp_path):
    manager(tmp_path, name='first')

    assert manager(tmp_path, name='second').vals.name == 'first'


def test_values_come_back_with_the_type_of_the_default(tmp_path):
    fields = {'name': 'demo', 'threads': 4, 'ratio': 1.5,
              'verbose': False, 'hosts': ['a', 'b']}
    manager(tmp_path, **fields)

    reloaded = manager(tmp_path, **fields)

    assert reloaded.vals.name == 'demo'
    assert reloaded.vals.threads == 4
    assert reloaded.vals.ratio == 1.5
    assert reloaded.vals.verbose is False
    assert reloaded.vals.hosts == ['a', 'b']


def test_a_percent_sign_survives_a_round_trip(tmp_path):
    # Interpolation is off, so a value is never mistaken for a format string.
    manager(tmp_path, name='100%pure')

    assert manager(tmp_path).vals.name == '100%pure'


def test_an_unparseable_value_keeps_the_default(tmp_path):
    manager(tmp_path, threads=4)
    config_path = tmp_path / 'config.ini'
    config_path.write_text('[options]\nname = demo\nthreads = many\n',
                           encoding='utf-8')

    assert manager(tmp_path, threads=7).vals.threads == 7


def test_an_unreadable_file_falls_back_to_the_defaults(tmp_path):
    config_path = tmp_path / 'config.ini'
    config_path.write_text('this is not an ini file\n', encoding='utf-8')

    assert manager(tmp_path, threads=3).vals.threads == 3


def test_a_new_default_is_written_to_the_existing_file(tmp_path):
    manager(tmp_path)

    ini = manager(tmp_path, threads=2)

    assert ini.vals.threads == 2
    assert section_of(ini.config_file_path)['threads'] == '2'


def test_a_key_added_by_hand_is_dropped(tmp_path):
    ini = manager(tmp_path)
    ini.config_file_path.write_text('[options]\nname = demo\nstray = yes\n',
                                    encoding='utf-8')

    assert 'stray' not in section_of(manager(tmp_path).config_file_path)


def test_save_stores_the_change_and_writes_it(tmp_path):
    ini = manager(tmp_path, hosts=[])

    ini.save(name='changed', hosts=['x', 'y'])

    reloaded = manager(tmp_path, hosts=[])
    assert ini.vals.name == 'changed'
    assert reloaded.vals.name == 'changed'
    assert reloaded.vals.hosts == ['x', 'y']


def test_save_refuses_a_key_it_does_not_know(tmp_path):
    with pytest.raises(KeyError, match='unknown option'):
        manager(tmp_path).save(nope='x')


def test_read_reloads_the_file(tmp_path):
    ini = manager(tmp_path)
    ini.config_file_path.write_text('[options]\nname = edited\n', encoding='utf-8')

    ini.read()

    assert ini.vals.name == 'edited'


def test_read_without_the_section_keeps_the_values(tmp_path):
    ini = manager(tmp_path)
    ini.config_file_path.write_text('[other]\nname = edited\n', encoding='utf-8')

    ini.read()

    assert ini.vals.name == 'demo'
