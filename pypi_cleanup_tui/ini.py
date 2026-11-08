"""Persistent options, stored in an INI file under ``~/.config``.

The design is borrowed from ``rmbloat``'s ``IniManager``: the constructor is
handed the option names together with their first-run defaults, seeds a
namespace with them, overrides that namespace with whatever the file already
holds, and writes the file back when it is missing or when its keys no longer
match the defaults.  Values are read back using the type of the default, so an
``int`` default returns an ``int`` and a ``list`` default (stored one item per
line) returns a list.

Only the names given to the constructor are ever read or written.  A key added
to the file by hand is dropped on the next write, and a default that is missing
from the file is filled in with its default value, so the file cannot drift away
from the code that reads it.
"""

from __future__ import annotations

import configparser
from pathlib import Path
from types import SimpleNamespace
from typing import Any

#: ConfigParser methods used to read a typed value back out of the file.
#: ``str`` is the fallback, and ``list`` is handled separately because it is
#: stored as one item per line.
_READERS: dict[type, Any] = {
    bool: configparser.ConfigParser.getboolean,
    int: configparser.ConfigParser.getint,
    float: configparser.ConfigParser.getfloat,
}


class IniManager:
    """Options held in ``<config dir>/<app_name>/config.ini``.

    The current values live in :attr:`vals` -- a :class:`types.SimpleNamespace`
    -- so callers read and assign ``ini.vals.option`` exactly like an argparse
    namespace.  :meth:`save` stores the changes and rewrites the file.
    """

    #: Single section holding every option.
    SECTION = 'options'

    def __init__(
        self,
        app_name: str,
        config_path: str | Path | None = None,
        **defaults: Any,
    ) -> None:
        """Load *app_name*'s options, using *defaults* on the first run.

        *config_path* exists for tests and for callers that keep their state
        somewhere other than ``~/.config/<app_name>/config.ini``.
        """
        if not app_name:
            raise ValueError('app_name must be provided')
        self.app_name = app_name
        self._defaults = defaults
        self.config_file_path = (
            Path(config_path) if config_path is not None
            else Path.home() / '.config' / app_name / 'config.ini'
        )
        self.vals = SimpleNamespace(**defaults)

        config = self._read_config_file()
        if config.has_section(self.SECTION):
            self._update_vals_from_config(config)
        # A missing file, a missing section, or a key set that no longer
        # matches the code all mean the file needs to be rewritten.
        if (not config.has_section(self.SECTION)
                or set(config.options(self.SECTION)) != set(defaults)):
            self.write()

    def read(self) -> None:
        """Reload :attr:`vals` from the file, leaving the file untouched."""
        config = self._read_config_file()
        if config.has_section(self.SECTION):
            self._update_vals_from_config(config)

    def save(self, **values: Any) -> None:
        """Store *values* on :attr:`vals` and write the whole file back."""
        unknown = set(values) - set(self._defaults)
        if unknown:
            raise KeyError(f'unknown option(s): {", ".join(sorted(unknown))}')
        for key, value in values.items():
            setattr(self.vals, key, value)
        self.write()

    def write(self) -> None:
        """Write every known option, as :attr:`vals` currently holds it."""
        config = configparser.ConfigParser(interpolation=None)
        config[self.SECTION] = {
            key: _as_text(getattr(self.vals, key)) for key in self._defaults
        }
        self.config_file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_file_path, 'w', encoding='utf-8') as handle:
            config.write(handle)

    def _read_config_file(self) -> configparser.ConfigParser:
        """Parse the file, or return an empty parser if it is unusable.

        Interpolation is off: a value such as a username containing ``%`` must
        come back exactly as it was written.
        """
        config = configparser.ConfigParser(interpolation=None)
        if self.config_file_path.exists():
            try:
                config.read(self.config_file_path, encoding='utf-8')
            except (configparser.Error, OSError):
                return configparser.ConfigParser(interpolation=None)
        return config

    def _update_vals_from_config(self, config: configparser.ConfigParser) -> None:
        """Copy every known option from *config* into :attr:`vals`."""
        section = config[self.SECTION]
        for key, default in self._defaults.items():
            if key not in section:
                continue
            try:
                setattr(self.vals, key, _read_value(config, self.SECTION, key, default))
            except ValueError:
                # An unparseable value (``threads = many``) keeps the default
                # instead of failing the whole run.
                continue


def _as_text(value: Any) -> str:  # noqa: ANN401 - values come from defaults
    """Render one option for the file; lists become one line per item."""
    if isinstance(value, list):
        return '\n'.join(str(item) for item in value)
    return str(value)


def _read_value(
    config: configparser.ConfigParser,
    section: str,
    key: str,
    default: Any,  # noqa: ANN401 - the default carries the type to read back
) -> Any:  # noqa: ANN401
    """Read *key* from *section* using the type of *default*."""
    kind = type(default)
    if kind is list:
        raw = config.get(section, key)
        return [line.strip() for line in raw.splitlines() if line.strip()]
    reader = _READERS.get(kind)
    if reader is not None:
        return reader(config, section, key)
    return config.get(section, key)
