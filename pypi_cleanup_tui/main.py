"""Release history model and command-line entry point for pypi-cleanup-tui.

This module owns the data layer: it fetches a package's
release history from the PyPI JSON API and keeps it sorted.
The TUI triggers the fetch after it opens.

The command line remembers what it was told for future runs.

Package arguments are cumulative;  a run's names go in front of the remembered ones,
and a name both lists hold keeps its first position.
The first name is therefore the package the table opens,
and, with no args, opens the same one as before.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import requests
from packaging.version import InvalidVersion, Version

from pypi_cleanup_tui import __version__
from pypi_cleanup_tui.ini import IniManager

APP_NAME = "pypi-cleanup-tui"
CLEANUP_TOOL = "pypi-cleanup"
MONO_THEME = "mono"
HOST_PYPI = "pypi"
HOST_TEST = "test"
HOSTS = (HOST_PYPI, HOST_TEST)
_INDEXES = {
    HOST_PYPI: ("https://pypi.org/pypi", "pypi.org"),
    HOST_TEST: ("https://test.pypi.org/pypi", "test.pypi.org"),
}

UTC_MODE = "UTC"
LOCAL_MODE = "Local"
ZONES = (UTC_MODE, LOCAL_MODE) # values of ``z`` spinner

SORT_BY_VERSION = "version"
SORT_BY_DATE = "date"
SORTS = (SORT_BY_VERSION, SORT_BY_DATE) # values of ``s`` spinner

GAP_CHOICES = (3, 7, 14, 30, 60) # values of ``g`` spinner
DEFAULT_GAP = 30

TOTP_EXPECT = 'expect' # pexpect drives til ^], then send fresh Auth code
TOTP_AUTO = 'auto' # use pexpect but sends code at the prompt w/o user at all
TOTP_PRINT = 'print' # only prints the code above each run;
TOTP_OFF = 'off' # leaves the prompt to the user.
TOTP_METHODS = (TOTP_EXPECT, TOTP_AUTO, TOTP_PRINT, TOTP_OFF)
DEFAULT_TOTP_METHOD = TOTP_EXPECT

REQUEST_TIMEOUT = 30.0 # Seconds to wait for the PyPI JSON API.

# Headers sent with every JSON API request.
# - The cache directives sometimes actually prevent stale version list ;-)
REQUEST_HEADERS = {
    "Accept": "application/json",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

# Every disk persistent option..
DEFAULTS = {
    'user': '',
    'host': HOST_PYPI,
    'packages': '', # comma separated list
    'zone': UTC_MODE,
    'sort': SORT_BY_VERSION,
    'gap': DEFAULT_GAP,
    'theme': '',
    'no_color': False,
    'totp_method': DEFAULT_TOTP_METHOD,
}


@dataclass
class Release:
    """A single release of a package plus the upload date of its oldest file."""

    version: str
    uploaded: datetime
    delete: bool = False # marked this release for deletion?

    def __str__(self) -> str:
        return f"{self.version:<20} {self.uploaded:%Y-%m-%d %H:%M}"


def _parse_upload_time(raw: str | None) -> datetime | None:
    """Parse a PyPI timestamp into an aware UTC ``datetime``.

    The JSON API exposes both ``upload_time_iso_8601``
    (``...Z``) and the older ``upload_time`` (naive).
    Both are treated as UTC so they can be compared.
    """
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parsed_version(release: Release) -> Version | None:
    """Return the PEP 440 version, or ``None`` for a legacy identifier."""
    try:
        return Version(release.version)
    except InvalidVersion:
        return None


class CleanupTui:
    """Release history of one package, ready to be presented by the TUI."""

    def __init__(
        self,
        package: str,
        user: str | None = None,
        host: str = HOST_PYPI,
    ) -> None:
        if host not in _INDEXES:
            raise ValueError(f"unknown host {host!r}; expected one of {HOSTS}")
        self.package = package
        self.user = user
        self.host_key = host
        self.versions: list[Release] = [] # Sorted by :meth:`sort_versions`.
        self.sort = SORT_BY_VERSION # current Sort order order

    @property
    def base_url(self) -> str:
        """JSON API prefix of the index being queried."""
        return _INDEXES[self.host_key][0]

    @property
    def host(self) -> str:
        """Human-readable host of the index being queried."""
        return _INDEXES[self.host_key][1]

    @property
    def host_url(self) -> str:
        """The index prefix ``pypi-cleanup`` wants for ``-t``.

        The JSON API prefix ends in ``/pypi``; the deletion program wants the site itself,
        with the trailing slash its default shows (``https://pypi.org/``).
        """
        return f"https://{self.host}/"

    def fetch_versions(self) -> list[Release]:
        """Fetch all releases that still have files, replacing :attr:`versions`.

        Releases without any files are skipped: PyPI keeps such "empty" releases around,
        they cannot be deleted, and ``pypi-cleanup`` ignores them as well.
        """
        url = f"{self.base_url}/{self.package}/json"
        response = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers=REQUEST_HEADERS,
        )
        if response.status_code == 404:
            raise LookupError(
                f"package {self.package!r} was not found on {self.host}"
            )
        response.raise_for_status()

        releases: dict[str, list[dict]] = response.json().get("releases") or {}
        versions: list[Release] = []
        for version, files in releases.items():
            timestamps = []
            for file_info in files or []:
                raw = (
                    file_info.get("upload_time_iso_8601")
                    or file_info.get("upload_time")
                )
                parsed = _parse_upload_time(raw)
                if parsed is not None:
                    timestamps.append(parsed)
            if not timestamps:
                continue
            versions.append(Release(version=version, uploaded=min(timestamps)))

        self.versions = versions
        return self.versions

    def sort_versions(
        self,
        key: str = SORT_BY_VERSION,
        reverse: bool = True,
    ) -> list[Release]:
        """Sort :attr:`versions` in place and return it.

        Both supported orders are descending by default: newest release
        first for ``"date"`` and highest version first for ``"version"``.
        """
        if key == SORT_BY_DATE:
            self.versions.sort(key=lambda release: release.uploaded, reverse=reverse)
        elif key == SORT_BY_VERSION:
            parsed = [(_parsed_version(release), release) for release in self.versions]
            valid = [(version, release) for version, release in parsed if version is not None]
            legacy = [release for version, release in parsed if version is None]
            # Legacy identifiers never sort among PEP 440 versions;
            # they keep their relative order at the bottom of the table.
            valid.sort(key=lambda item: item[0], reverse=reverse)
            legacy.sort(key=lambda release: release.version, reverse=reverse)
            self.versions = [release for _, release in valid] + legacy
        else:
            raise ValueError(f"unknown sort key {key!r}; expected one of {SORTS}")
        self.sort = key
        return self.versions


def split_packages(raw: Sequence[str] | str) -> list[str]:
    """Split the package argument into names, accepting both input forms.

    The command line collects the positional arguments into a list,
    but the stored option is a single comma separated string; both ``pack1,pack2``
    and ``pack1 pack2`` therefore describe the same list of packages.
    Blank names (``"pack1,,pack2"``) are dropped.
    """
    arguments = [raw] if isinstance(raw, str) else raw
    names = [name.strip() for argument in arguments for name in argument.split(',')]
    return [name for name in names if name]


def merge_packages(
    argument: Sequence[str] | str,
    remembered: Sequence[str] | str,
) -> list[str]:
    """Combine this run's package arguments with the remembered list.

    The command line is cumulative: its names go in front of the stored ones,
    so the first argument is the package the table opens,
    and a name held by both lists keeps the position it has in the front list.
    ``dict.fromkeys`` does the de-duplication in order, which is exactly "keep the first".
    """
    return list(dict.fromkeys(
        split_packages(argument) + split_packages(remembered)
    ))


def _normalize(value: str, allowed: Sequence[str], fallback: str) -> str:
    """Return *value* if it is one of *allowed*, else *fallback*.

    The stored options are read from a file a user can edit,
    and argparse does not validate a default,
    so a hand-edited ``host = somewhere`` has to fall back instead of reaching the model.
    """
    return value if value in allowed else fallback


def _normalize_gap(value: object) -> int:
    """Return *value* as a gap if it is one of *GAP_CHOICES*, else the default.

    The stored gap is a number in a file a user can edit,
    so it gets the same care as the other stored choices: an unknown
    value falls back instead of reaching the stability filter,
    and anything that is not a number falls back too.
    """
    try:
        gap = int(str(value))
    except (TypeError, ValueError):
        return DEFAULT_GAP
    return gap if gap in GAP_CHOICES else DEFAULT_GAP


def _theme_choices() -> tuple[str, ...]:
    """The theme names, imported lazily so ``--version`` stays light.

    The palette list belongs to console-window,
    and this module avoids importing the terminal stack until the TUI is actually needed.
    """
    from pypi_cleanup_tui.tui import THEME_CHOICES

    return THEME_CHOICES


def _theme_choice(raw: str) -> str:
    """argparse ``type=`` for ``--theme``; refuses a name nobody knows."""
    choices = _theme_choices()
    if raw not in choices:
        raise argparse.ArgumentTypeError(
            f"unknown theme {raw!r}; choose one of {', '.join(choices)}"
        )
    return raw


def _normalize_theme(value: str) -> str:
    """Return *value* if the theme picker knows it, else no explicit theme.

    A hand-edited ``theme = nonsense`` falls back to the library default
    instead of being stored and handed to the TUI again on every run.
    """
    if not value:
        return ''
    return value if value in _theme_choices() else ''


def cleanup_tool_available() -> bool:
    """Whether the program that performs the deletion is on the ``PATH``."""
    return shutil.which(CLEANUP_TOOL) is not None


def missing_cleanup_tool_message() -> str:
    """The advice printed when the deletion program cannot be found."""
    return (
        f'error: {CLEANUP_TOOL} is not on the PATH, so nothing could be '
        'deleted.\n'
        f'Install it with "pip install {CLEANUP_TOOL}" and try again, or run '
        'with --read-only to browse the history without deleting.'
    )


def _build_parser(vals: SimpleNamespace) -> argparse.ArgumentParser:
    """Build the parser, defaulting every option to its stored value."""
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description=(
            "Browse the release history of a PyPI package and choose which "
            "versions to keep."
        ),
        epilog=(
            f"Defaults come from ~/.config/{APP_NAME}/config.ini; the command "
            "line and the TUI save them back."
        ),
    )
    # The release gate's smoke stage runs the installed console script
    # with `--version` and requires this project's version in the output.
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    packages_help = (
        "PyPI package names, either one comma separated list "
        '("package1,package2") or separate arguments'
    )
    if vals.packages:
        packages_help += f" [dflt={vals.packages}]"
    parser.add_argument("packages", nargs="*", help=packages_help)
    parser.add_argument(
        "--host",
        choices=HOSTS,
        default=vals.host,
        help=f"package index to query [dflt={vals.host}]",
    )
    parser.add_argument(
        "-u",
        "--user",
        default=vals.user,
        help="PyPI username (kept for the later cleanup step)"
             f' [dflt={vals.user or "(none)"}]',
    )
    parser.add_argument(
        "--totp-method",
        choices=TOTP_METHODS,
        default=vals.totp_method,
        help="how to supply the authenticator code: 'expect' (default) drives "
             "the pypi-cleanup prompt and sends the code at Ctrl+], 'auto' "
             "sends it without handing control back, 'print' only prints it "
             "above each run, 'off' leaves the prompt to you "
             f"[dflt={vals.totp_method}]",
    )
    parser.add_argument(
        "--totp-dump",
        action="store_true",
        help="print the authenticator code in force for pypi and test -- each "
             "index uses its scoped secret, else the unscoped one -- "
             "refreshing every 3 seconds, and exit on Ctrl-C; needs no "
             "package name",
    )
    parser.add_argument(
        "--theme",
        type=_theme_choice,
        default=None,
        metavar="THEME",
        help="color theme to install; 'mono' turns color off (the TUI's "
             "THEMES screen lists the palette names)",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        default=None,
        help="draw the semantic roles with attributes instead of color; "
             "remembered for the next run, and NO_COLOR does the same when "
             "the switch is absent",
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="skip the pypi-cleanup check and browse without the ability to "
             "delete; the hint line shows R/O and d is never offered",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    config_path: str | Path | None = None,
) -> int:
    """Command-line entry point.  Returns the process exit status."""
    ini = IniManager(APP_NAME, config_path=config_path, **DEFAULTS)
    vals = ini.vals
    parser = _build_parser(vals)
    args = parser.parse_args(argv)

    # The dump is a standalone report: it names no package and deletes nothing,
    # so it runs before the package, tool and saved-option handling below.
    # A plain dump never loads the terminal stack.
    if args.totp_dump:
        from pypi_cleanup_tui.tui import dump_totp_codes

        return dump_totp_codes()

    # The command line is cumulative: this run's names go in front of the remembered list,
    # and duplicates keep their first position.
    # An empty command line therefore runs the stored list unchanged.
    packages = merge_packages(args.packages, vals.packages)
    if not packages:
        parser.error("at least one package name is required")

    # The deletion is delegated, and a normal run needs the program that performs it.
    # The check happens before anything is saved.
    if not args.read_only and not cleanup_tool_available():
        print(missing_cleanup_tool_message(), file=sys.stderr)
        return 1

    host = _normalize(args.host, HOSTS, HOST_PYPI)
    zone = _normalize(vals.zone, ZONES, UTC_MODE)
    sort = _normalize(vals.sort, SORTS, SORT_BY_VERSION)
    gap = _normalize_gap(vals.gap)
    totp_method = _normalize(
        args.totp_method, TOTP_METHODS, DEFAULT_TOTP_METHOD)
    # The command line wins; without it the remembered choice is used,
    # and a hand-edited unknown name falls back to "no explicit theme".
    theme = _normalize_theme(args.theme or vals.theme)
    if args.no_color:
        no_color = True
    elif args.theme:
        # An explicit theme is a request for color unless it is the mono mode.
        no_color = theme == MONO_THEME
    else:
        # A remembered mono choice means color stayed off even if the
        # stored flag was written by an older version of the file.
        no_color = bool(vals.no_color) or theme == MONO_THEME

    # The table shows one package at a time; the whole list is kept for the next run,
    # where it becomes the default package argument.
    # The TUI owns the fetch: it opens first, draws a loading line,
    # then loads the history and turns any failure into an alert over the table.
    cleanup = CleanupTui(packages[0], user=args.user or None, host=host)

    # Remember what this run asked for, so the next run needs no arguments.
    # A home directory that cannot be written is a warning,
    # not a failure: the table is still worth showing.
    try:
        ini.save(
            user=args.user or '',
            host=host,
            packages=','.join(packages),
            zone=zone,
            sort=sort,
            gap=gap,
            theme=theme,
            no_color=no_color,
            totp_method=totp_method,
        )
    except OSError as exc:
        print(f"warning: could not save {ini.config_file_path}: {exc}", file=sys.stderr)

    # Imported here so `--version` does not pay for the terminal stack.
    from pypi_cleanup_tui.tui import run_tui

    return run_tui(
        cleanup,
        ini=ini,
        zone=zone,
        sort=sort,
        gap=gap,
        read_only=args.read_only,
        packages=packages,
        theme=args.theme,
        no_color=args.no_color,
        totp_method=totp_method,
    )


if __name__ == "__main__":
    raise SystemExit(main())
