"""Release history model and command-line entry point for pypi-cleanup-tui.

This module currently provides the data layer only: it fetches a project's
release history from the PyPI JSON API, keeps it sorted, and can dump it as a
plain table.  The interactive TUI will be layered on top of
:class:`CleanupTui` later; deletion itself is delegated to ``pypi-cleanup``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TextIO

import requests
from packaging.version import InvalidVersion, Version

from pypi_cleanup_tui import __version__

#: JSON API prefixes for the production and test package indexes.  The test
#: index is always the last entry, so ``urls[is_test_pypi]`` selects it.
PYPI_URL = "https://pypi.org/pypi"
TEST_PYPI_URL = "https://test.pypi.org/pypi"

#: Accepted values for the sort order.
SORT_BY_VERSION = "version"
SORT_BY_DATE = "date"
SORTS = (SORT_BY_VERSION, SORT_BY_DATE)

#: Seconds to wait for the PyPI JSON API.
REQUEST_TIMEOUT = 30.0


@dataclass
class Release:
    """A single release of a project plus the upload date of its oldest file."""

    version: str
    uploaded: datetime

    def __str__(self) -> str:
        return f"{self.version:<20} {self.uploaded:%Y-%m-%d %H:%M}"


def _parse_upload_time(raw: str | None) -> datetime | None:
    """Parse a PyPI timestamp into an aware UTC ``datetime``.

    The JSON API exposes both ``upload_time_iso_8601`` (``...Z``) and the older
    ``upload_time`` (naive).  Both are treated as UTC so they can be compared.
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
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parsed_version(release: Release) -> Version | None:
    """Return the PEP 440 version, or ``None`` for a legacy identifier."""
    try:
        return Version(release.version)
    except InvalidVersion:
        return None


class CleanupTui:
    """Release history of one project, ready to be presented by the TUI."""

    def __init__(
        self,
        package: str,
        user: str | None = None,
        is_test_pypi: bool = False,
    ) -> None:
        self.package = package
        self.user = user
        self.is_test_pypi = is_test_pypi
        #: Sorted on demand by :meth:`sort_versions`.
        self.versions: list[Release] = []
        #: ``[pypi prefix, test.pypi prefix]``.
        self.urls = [PYPI_URL, TEST_PYPI_URL]
        #: Sort order currently applied to :attr:`versions`.
        self.sort = SORT_BY_VERSION

    @property
    def base_url(self) -> str:
        """JSON API prefix of the index being queried."""
        return self.urls[1 if self.is_test_pypi else 0]

    @property
    def host(self) -> str:
        """Human-readable host of the index being queried."""
        return "test.pypi.org" if self.is_test_pypi else "pypi.org"

    def fetch_versions(self) -> list[Release]:
        """Fetch all releases that still have files, replacing :attr:`versions`.

        Releases without any files are skipped: PyPI keeps such "empty"
        releases around, they cannot be deleted, and ``pypi-cleanup`` ignores
        them as well.
        """
        url = f"{self.base_url}/{self.package}/json"
        response = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={"Accept": "application/json"},
        )
        if response.status_code == 404:
            raise LookupError(
                f"project {self.package!r} was not found on {self.host}"
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

        Both supported orders are descending by default: newest release first
        for ``"date"`` and highest version first for ``"version"``.
        """
        if key == SORT_BY_DATE:
            self.versions.sort(key=lambda release: release.uploaded, reverse=reverse)
        elif key == SORT_BY_VERSION:
            parsed = [(_parsed_version(release), release) for release in self.versions]
            valid = [(version, release) for version, release in parsed if version is not None]
            legacy = [release for version, release in parsed if version is None]
            # Legacy identifiers never sort among PEP 440 versions; they keep
            # their relative order at the bottom of the table.
            valid.sort(key=lambda item: item[0], reverse=reverse)
            legacy.sort(key=lambda release: release.version, reverse=reverse)
            self.versions = [release for _, release in valid] + legacy
        else:
            raise ValueError(f"unknown sort key {key!r}; expected one of {SORTS}")
        self.sort = key
        return self.versions

    def dump(self, stream: TextIO | None = None) -> None:
        """Write the version/date table to *stream* (stdout by default)."""
        stream = stream or sys.stdout
        if not self.versions:
            print("No releases found.", file=stream)
            return
        width = max([len("VERSION"), *(len(r.version) for r in self.versions)])
        print(f"{'VERSION':<{width}} UPLOADED (UTC)", file=stream)
        print(f"{'-' * width} {'-' * 16}", file=stream)
        for release in self.versions:
            print(f"{release.version:<{width}} {release.uploaded:%Y-%m-%d %H:%M}", file=stream)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pypi-cleanup-tui",
        description=(
            "Browse the release history of a PyPI project and choose which "
            "versions to keep."
        ),
    )
    # The release gate's smoke stage runs the installed console script with
    # `--version` and requires this project's version in the output.
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "project",
        nargs="?",
        help="PyPI project name (required until the interactive TUI lands)",
    )
    parser.add_argument(
        "-s",
        "--sort",
        choices=SORTS,
        default=SORT_BY_VERSION,
        help="sort order, descending (default: %(default)s)",
    )
    parser.add_argument(
        "--dump",
        action="store_true",
        help="print the version/date table and exit",
    )
    parser.add_argument(
        "--test-pypi",
        action="store_true",
        help="query test.pypi.org instead of pypi.org",
    )
    parser.add_argument(
        "-u",
        "--user",
        default=None,
        help="PyPI username (kept for the later cleanup step)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point.  Returns the process exit status."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.project:
        parser.error("a project name is required")

    cleanup = CleanupTui(
        args.project,
        user=args.user,
        is_test_pypi=args.test_pypi,
    )
    try:
        cleanup.fetch_versions()
    except LookupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except requests.RequestException as exc:
        print(
            f"error: could not fetch {cleanup.host}/{args.project}: {exc}",
            file=sys.stderr,
        )
        return 1

    cleanup.sort_versions(args.sort)

    if not args.dump:
        print(
            "error: the interactive TUI is not implemented yet; "
            "rerun with --dump to print the release table",
            file=sys.stderr,
        )
        return 2

    cleanup.dump()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
