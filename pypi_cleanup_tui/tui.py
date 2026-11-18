"""Interactive terminal interface for pypi-cleanup-tui.

- The window presents the release history fetched by :class:`pypi_cleanup_tui.main.CleanupTui`
  as a table and lets the user mark the releases to delete.
- The marking itself is local;  ``d`` hands the marked versions to ``pypi-cleanup``.
- The hand-off offers a (``--query-only``) dry run first, then
  offers offers the (``--do-it``) actual deletion.
"""

from __future__ import annotations

import bisect
import curses
import os
import re
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING

from console_window import (
    Appearance,
    BasicHelpScreen,
    ConsoleWindow,
    ConsoleWindowOpts,
    Context,
    HeaderLine,
    IncrementalSearchBar,
    OptionSpinner,
    Screen,
    ScreenStack,
    Theme,
    semantic_attr,
)

from pypi_cleanup_tui import totp
from pypi_cleanup_tui.main import (
    CLEANUP_TOOL,
    DEFAULT_GAP,
    DEFAULT_TOTP_METHOD,
    GAP_CHOICES,
    HOST_PYPI,
    HOST_TEST,
    HOSTS,
    LOCAL_MODE,
    MONO_THEME,
    SORT_BY_DATE,
    SORT_BY_VERSION,
    TOTP_AUTO,
    TOTP_EXPECT,
    TOTP_METHODS,
    TOTP_PRINT,
    UTC_MODE,
    ZONES,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable, Iterable, Mapping, Sequence
    from datetime import tzinfo
    from typing import TextIO

    from console_window.backend import RenderBackend

    from pypi_cleanup_tui.ini import IniManager
    from pypi_cleanup_tui.main import CleanupTui, Release

MAIN_ST = 0
HELP_ST = 1
THEME_ST = 2
PACKAGES_ST = 3
THEME_CHOICES = tuple(Theme.list_all()) # NOTE: 't' steps from last ('mono') and wraps back to first

# The states of one ``(package, host)`` release list.
UNINITIALIZED = 'uninitialized'
LOADED = 'loaded'
ERROR = 'error'
STALE = 'stale'

ERROR_RETRY_SECONDS = 15 * 60
ERROR_TEXT_WIDTH = 40
DEL_MARK = "✘"
VISITED_MARK = "✓"
DOWN_MARK = "▼"
DEL_HINT = "del"
READ_ONLY_HINT = "R/O"
UNMARKED_NEWEST_NOTICE = (
    'Automatically unmarked newest version ({version}); '
    'you cannot remove them all.'
)
LAST_VERSION_MESSAGE = 'Cannot delete the last remaining version.'
LAST_VERSION_FLASH_SECONDS = 3.0
RETURN_PROMPT = "Press ENTER to return to the TUI"
VALUE_FLAGS = ('-u', '-t', '-p', '-r')
QUERY_ONLY = '--query-only'
DO_IT = '--do-it'
COMMAND_WIDTH = 78
COMMAND_INDENT = '   '
CREDENTIAL_ENV_VARS = ('PYPI_CLEANUP_PASSWORD',)
CREDENTIAL_SUFFIXES = {HOST_PYPI: '4PYPI', HOST_TEST: '4TEST'}
EXPECT_TIMEOUT = 300
EXPECT_ESCAPE = '\x1d'
TOTP_PROMPT_PATTERN = r'(?i)authentication code[: ]'
TOTP_DUMP_INTERVAL = 3.0
TOTP_GROUP_WIDTH = len(': ') + 6 + len(' ') + 2 + len('s')
TOTP_GROUP_GAP = '    '
EXPECT_BANNER = (
    '|\n'
    '| About to run pypi-cleanup...\n'
    '| When prompted for "Authentication code:", press Ctrl+] to have this '
    'TUI supply the code automatically.\n'
    '|'
)
USER_ENV_VAR = 'PYPI_CLEANUP_USER'
DRY_RUN_PROMPT = 'Dry-run [Yes OR no]?'
DELETE_PROMPT = "Del {count} Versions of '{package}'  [yes OR No]?"
RETRY_PROMPT = 'RETRY: ' + DELETE_PROMPT
GAP_HINT_WIDTH = 2
DEL_WIDTH = 3
DATE_WIDTH = 16
DAYS_WIDTH = 5
VERSION_GAP = 2
CHECK_WIDTH = 1
VERS_WIDTH = 5
DELS_WIDTH = 5
PACKAGE_GROUP_WIDTH = VERS_WIDTH + 1 + DELS_WIDTH
PACKAGE_TITLE = "PACKAGE"
MISSING_PACKAGE_PATTERN = re.compile(r"package .+ was not found on .+", re.IGNORECASE)
PACKAGES_TITLE = "PACKAGES"
PACKAGES_HINT = PACKAGES_TITLE + '  [x]:remove ESC:open [?]:help'


def cleanup_command(
    cleanup: CleanupTui,
    versions: Sequence[str],
    mode: str | None = None,
) -> list[str]:
    """The ``pypi-cleanup`` command line that deletes *versions*.

    The marked versions become one anchored regular expression,
    so the command names exactly the rows the table showed and nothing else;
    ``re.escape`` keeps a version identifier's dots and hyphens literal.
    ``pypi-cleanup`` wants a user, the index URL and a package,
    and the user falls back to the login name when no ``-u`` was given.
    *mode* is the phase switch -- ``--query-only`` or ``--do-it`` -- and
    is omitted for the summary command printed before the first question.
    """
    pattern = '^(' + '|'.join(re.escape(version) for version in versions) + ')$'
    command = [CLEANUP_TOOL]
    if mode:
        command.append(mode)
    command += [
        '-y',
        '-u', cleanup_user(cleanup),
        '-t', cleanup.host_url,
        '-p', cleanup.package,
        '-r', pattern,
    ]
    return command


def scoped_user(host: str,
                environ: Mapping[str, str] | None = None) -> str:
    """The account ``PYPI_CLEANUP_USER4...`` names for *host*, or ``''``."""
    env = os.environ if environ is None else environ
    suffix = CREDENTIAL_SUFFIXES.get(host)
    return env.get(USER_ENV_VAR + suffix, '') if suffix else ''


def cleanup_user(cleanup: CleanupTui,
                 environ: Mapping[str, str] | None = None) -> str:
    """The account ``pypi-cleanup`` should act as.

    ``PYPI_CLEANUP_USER4PYPI`` and ``PYPI_CLEANUP_USER4TEST`` name the
    account for one index and win over ``-u``: the flag cannot be scoped,
    so a single run that switches index would otherwise carry one name to both.
    With the host's variable unset or empty, ``-u`` wins and the login name is last.
    """
    env = os.environ if environ is None else environ
    return (scoped_user(cleanup.host_key, env)
            or cleanup.user
            or env.get('USER', ''))


def credential_env(host: str,
                   environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Map each credential variable to the host-scoped one that supplies it."""
    env = os.environ if environ is None else environ
    suffix = CREDENTIAL_SUFFIXES.get(host)
    if suffix is None:
        return {}
    return {
        base: base + suffix
        for base in CREDENTIAL_ENV_VARS
        if env.get(base + suffix)
    }


def cleanup_env(host: str,
                environ: Mapping[str, str] | None = None) -> dict[str, str] | None:
    """The environment for a ``pypi-cleanup`` run, or ``None`` to inherit."""
    env = os.environ if environ is None else environ
    mapped = credential_env(host, env)
    if not mapped:
        return None
    return {**env, **{base: env[scoped] for base, scoped in mapped.items()}}


def totp_secret(host: str,
                environ: Mapping[str, str] | None = None) -> str:
    """The authenticator secret that applies to *host*, or ``''``.

    ``PYPI_CLEANUP_TOTP_SECRET4PYPI`` and ``...4TEST`` keep the
    two indexes' secrets apart and win over the unscoped variable,
    which is the fallback for a user with only one account.

    **NOTE**: This secret is read by the TUI itself: ``pypi-cleanup``
    has no variable for it and always prompts for the code.  Arrrgh.
    """
    env = os.environ if environ is None else environ
    suffix = CREDENTIAL_SUFFIXES.get(host)
    scoped = env.get(totp.TOTP_SECRET_ENV_VAR + suffix, '') if suffix else ''
    return scoped or env.get(totp.TOTP_SECRET_ENV_VAR, '')


def show_authentication_code(host: str,
                             environ: Mapping[str, str] | None = None) -> None:
    """Print the code ``pypi-cleanup`` will prompt for, and its lifetime."""
    secret = totp_secret(host, environ)
    if not secret:
        return
    try:
        code, remaining = totp.code_with_room(secret)
    except ValueError as error:
        print(f'warning: {error}')
    else:
        print(totp.format_code(code, remaining))


def no_totp_secrets_message() -> str:
    """The advice ``--totp-dump`` prints when the environment holds no secret."""
    names = [totp.TOTP_SECRET_ENV_VAR]
    names += [totp.TOTP_SECRET_ENV_VAR + suffix
              for suffix in CREDENTIAL_SUFFIXES.values()]
    return (f'no TOTP secrets are set ({", ".join(names)}), '
            'so there is nothing to dump.')


def totp_dump_rows(
    environ: Mapping[str, str] | None = None,
) -> list[tuple[str, str]]:
    """The secret in force for each index, as ``(host, secret)`` pairs."""
    env = os.environ if environ is None else environ
    rows: list[tuple[str, str]] = []
    for host in HOSTS:
        secret = totp_secret(host, env)
        if secret:
            rows.append((host, secret))
    return rows


def format_totp_group(host: str, secret: str, moment: float) -> str:
    """One index's ``host: code 30s`` group on the dump line."""
    try:
        code, remaining = totp.code_and_remaining(secret, moment)
    except ValueError as error:
        return f'{host}: {error}'
    return f'{host}: {code} {remaining:>2}s'


def format_totp_line(moment: float, rows: Sequence[tuple[str, str]]) -> str:
    """The dump's one line: the clock, then each index's group side by side."""
    clock = time.strftime('%H:%M:%S', time.localtime(moment))
    groups = []
    for host, secret in rows:
        width = len(host) + TOTP_GROUP_WIDTH
        groups.append(format_totp_group(host, secret, moment).ljust(width))
    return f'{clock}  {TOTP_GROUP_GAP.join(groups)}'.rstrip()


def dump_totp_codes(
    environ: Mapping[str, str] | None = None,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
    out: TextIO | None = None,
) -> int:
    """Print the code in force for each index, a line every three seconds."""
    rows = totp_dump_rows(environ)
    if not rows:
        print(no_totp_secrets_message(), file=sys.stderr)
        return 1
    stream = sys.stdout if out is None else out
    try:
        while True:
            print(format_totp_line(clock(), rows), file=stream)
            stream.flush()
            sleep(TOTP_DUMP_INTERVAL)
    except KeyboardInterrupt: # Ctrl-C is the way out
        return 0


def _quoted(value: str) -> str:
    """Show *value* in single quotes, always, the way the display wants it."""
    return "'" + value.replace("'", "'\\''") + "'"


def _split_alternatives(pattern: str) -> list[str]:
    """Break *pattern* after every unescaped ``|``, keeping the pipe.

    A pipe written by ``re.escape`` follows a backslash
    and stands for a literal ``|`` in a version, so it never becomes a break point.
    """
    segments: list[str] = []
    current = ''
    escaped = False
    for char in pattern:
        current += char
        if escaped:
            escaped = False
        elif char == '\\':
            escaped = True
        elif char == '|':
            segments.append(current)
            current = ''
    if current:
        segments.append(current)
    return segments


def _wrap_pattern(pattern: str, width: int) -> list[str]:
    """Split *pattern* after ``|`` so each piece fits in *width* characters."""
    pieces: list[str] = []
    current = ''
    for segment in _split_alternatives(pattern):
        if current and len(current) + len(segment) > width:
            pieces.append(current)
            current = segment
        else:
            current += segment
    if current:
        pieces.append(current)
    return pieces


def format_command(command: Sequence[str], width: int = COMMAND_WIDTH,
                   env: Mapping[str, str] | None = None) -> str:
    """Lay *command* out the way the hand-off prints it, suggestively"""
    lines: list[str] = []
    env_lines = [f'{base}={scoped}' for base, scoped in (env or {}).items()]
    if env_lines:
        lines.append('+ ' + env_lines[0])
        lines.extend(COMMAND_INDENT + text for text in env_lines[1:])
        line = COMMAND_INDENT + command[0]
    else:
        line = '+ ' + command[0]

    def add_word(word: str) -> None:
        nonlocal line
        if len(line) + 1 + len(word) <= width:
            line += ' ' + word
        else:
            lines.append(line)
            line = COMMAND_INDENT + word

    def add_value(flag: str, value: str) -> None:
        nonlocal line
        quoted = _quoted(value)
        unit = f'{flag} {quoted}'
        if len(COMMAND_INDENT) + len(unit) <= width:
            # The flag and its value stay together,
            # even when they move to a continuation line,
            # so a reader sees which value belongs to what.
            if len(line) + 1 + len(unit) <= width:
                line += ' ' + unit
            else:
                lines.append(line)
                line = COMMAND_INDENT + unit
            return
        # Too long for any single line: open the quotes on the
        # flag's line and break the pattern after its pipes, indenting the pieces to match.
        lines.append(line)
        available = width - len(COMMAND_INDENT) - len(flag) - 3
        pieces = _wrap_pattern(value, available)
        line = f"{COMMAND_INDENT}{flag} '{pieces[0]}"
        for piece in pieces[1:]:
            lines.append(line)
            line = COMMAND_INDENT + piece
        line += "'"

    index = 1
    while index < len(command):
        token = command[index]
        if token in VALUE_FLAGS and index + 1 < len(command):
            add_value(token, command[index + 1])
            index += 2
        else:
            add_word(token)
            index += 1
    lines.append(line)
    return '\n'.join(lines)


def ask_yes_no(question: str, default: bool) -> bool:
    """Ask *question* until the answer is ``yes``, ``no``, or a bare ENTER."""
    while True:
        answer = input(f'====> {question} ').strip().lower()
        if not answer:
            return default
        if answer == 'yes':
            return True
        if answer == 'no':
            return False


def run_cleanup(command: Sequence[str],
                env: Mapping[str, str] | None = None) -> int:
    """Run *command* on the bare terminal and return its exit status."""
    try:
        return subprocess.call(list(command), env=env)
    except OSError as error:
        print(f'error: could not run {CLEANUP_TOOL}: {error}')
        return 1


class ExpectUnavailable(RuntimeError):
    """pexpect could not be imported or could not start the child."""


def _start_pexpect(command, secret, env, pexpect_module):
    """Resolve pexpect, validate the secret, and spawn the child."""
    module = pexpect_module
    if module is None:
        try:
            import pexpect as module
        except ImportError as error:
            raise ExpectUnavailable(error) from error
    try:
        totp.code_and_remaining(secret)
    except ValueError as error:
        raise ExpectUnavailable(error) from error
    try:
        child = module.spawn(
            command[0],
            list(command[1:]),
            encoding='utf-8',
            timeout=EXPECT_TIMEOUT,
            env=env,
        )
    except (OSError, module.ExceptionPexpect) as error:
        raise ExpectUnavailable(error) from error
    return module, child


def _run_pexpect(command, secret, env, pexpect_module, interactive):
    """Shared body of the ``expect`` and ``auto`` methods.

    *interactive* gives the terminal to the child until Ctrl+]; otherwise the child's
    output up to the generous prompt pattern is echoed before the code is sent.
    A failure after the child has started is reported as an exit status.
    """
    module, child = _start_pexpect(command, secret, env, pexpect_module)
    try:
        if interactive:
            child.interact(escape_character=EXPECT_ESCAPE)
        else:
            child.expect(TOTP_PROMPT_PATTERN)
            if child.before:
                print(child.before, end='')
            if child.after:
                print(child.after, end='')
        code, _remaining = totp.code_with_room(secret)
        child.sendline(code)
        child.expect(module.EOF)
        if child.before:
            print(child.before, end='')
    except module.TIMEOUT:
        print(f'warning: {CLEANUP_TOOL} did not finish within '
              f'{EXPECT_TIMEOUT}s')
    except (module.EOF, OSError) as error:
        print(f'warning: pexpect could not supply the code: {error}')
    finally:
        child.close()
    return child.exitstatus if child.exitstatus is not None else 1


def run_cleanup_expect(command: Sequence[str], secret: str,
                       env: Mapping[str, str] | None = None,
                       pexpect_module=None) -> int:
    """Run under pexpect, handing the terminal back at Ctrl+].

    The child owns the terminal until the user presses Ctrl+],
    so the user answer the password and device prompts.
    At the ``Authentication code:`` prompt, the user supposedly returns
    control here; we send the Auth code and child process finishes
    hopefully never prompting again or everybody is screwed.
    """
    return _run_pexpect(
        command, secret, env, pexpect_module, interactive=True)


def run_cleanup_auto(command: Sequence[str], secret: str,
                     env: Mapping[str, str] | None = None,
                     pexpect_module=None) -> int:
    """Run under pexpect without ever giving the terminal to the user.

    This is for the run whose login password is supplied in the ENV;
    the child's output is echoed, pexpect waits for the authentication-code prompt,
    and we send the code.  If another prompt appears first,
    the wait times out rather than guessing at input;
    ``expect`` was the correct the mode to specify for that case, duh.
    """
    return _run_pexpect(
        command, secret, env, pexpect_module, interactive=False)


def summary_line(action: str, package: str, status: int) -> str:
    """The one line printed under a finished ``pypi-cleanup`` run."""
    if status == 0:
        return f'{action} finished for {package!r}.'
    return f'{action} failed for {package!r} (exit status {status}).'


def press_enter(message: str = RETURN_PROMPT) -> None:
    """Wait for ENTER on the bare terminal, below two blank lines."""
    input(f'\n\n===== {message} ====> ')


def _reset_terminal() -> None:
    """Clear the terminal curses has just handed back and fix its settings."""
    subprocess.run("clear; stty sane", shell=True, check=False)


def is_missing_package_error(exc: BaseException) -> bool:
    """Whether *exc* is the index's "package not found" answer."""
    return (
        isinstance(exc, LookupError)
        and MISSING_PACKAGE_PATTERN.search(str(exc)) is not None
    )


def compact_delta_time(start: float, end: float | None = None) -> str:
    """A compact age for a state marker: ``12s``, ``42m`` or ``3h``.

    - The unit changes only when the next say it more compactly;
      seconds up to 99, whole minutes up to 99, then whole hours.
    - A negative difference reads as ``0s``.
    - Passes wall-clock timestamps
    """
    if end is None:
        end = time.time()
    delta_sec = max(int(end - start), 0)
    if delta_sec < 100:
        return f'{delta_sec}s'
    delta_min = delta_sec // 60
    if delta_min < 100:
        return f'{delta_min}m'
    return f'{delta_sec // 3600}h'


def days_since(uploaded: datetime, now: datetime | None = None,
               mode: str = UTC_MODE, local_tz: tzinfo | None = None) -> int:
    """Calendar days between *uploaded* and *now*, ignoring the time of day.

    Honors ``mode``. ``1`` means yesterday.
    ``0`` means a date that is not before the current one.
    """
    now = now or datetime.now(UTC)
    if mode == LOCAL_MODE:
        uploaded = uploaded.astimezone(local_tz)
        now = now.astimezone(local_tz)
    return max((now.date() - uploaded.date()).days, 0)


def days_ago(release: Release, now: datetime | None = None,
             mode: str = UTC_MODE, local_tz: tzinfo | None = None) -> int:
    """Calendar days between *release*'s upload date and *now*'s date."""
    return days_since(release.uploaded, now, mode, local_tz)


def zone_abbrev(mode: str, now: datetime | None = None,
                local_tz: tzinfo | None = None) -> str:
    """Short name of the zone *mode* selects, e.g. ``UTC`` or ``EDT``"""
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
        f"{days_since(release.uploaded, now, mode, local_tz):>{DAYS_WIDTH}}"
        f"{' ' * VERSION_GAP}{release.version}"
    )


def column_header(mode: str = UTC_MODE, sort: str = SORT_BY_VERSION,
                  now: datetime | None = None,
                  local_tz: tzinfo | None = None) -> str:
    """Format the column-label line, naming the zone and the active sort."""
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


def unmark_newest_marked(releases: Sequence[Release]) -> Release | None:
    """Give back the newest release of a fully marked history or None"""
    if not releases or not all(release.delete for release in releases):
        return None
    newest = max(releases, key=lambda release: release.uploaded)
    newest.delete = False
    return newest


def stable_releases(versions: Sequence[Release], gap: int,
                    mode: str = UTC_MODE,
                    local_tz: tzinfo | None = None) -> list[Release]:
    """The marked releases that stayed current for at least *gap* days."""
    times = sorted({release.uploaded for release in versions})
    stable: list[Release] = []
    for release in versions:
        if not release.delete:
            continue
        index = bisect.bisect_right(times, release.uploaded)
        if index == len(times):
            stable.append(release)
        elif days_since(release.uploaded, times[index], mode, local_tz) > gap:
            stable.append(release)
    return stable


@dataclass
class PackageState:
    """Everything this run knows about one ``(package, host)`` release list.

    The state owns both the table view and the package list's totals,
    because both describe the same index resource.
    ``releases`` is the durable copy: :attr:`CleanupApp.cleanup`
    points at it while the pair is on screen,
    and a failed fetch restores it instead of emptying the table.
    ``visited`` and ``version_count`` are derived,
    so a never-loaded pair cannot pretend to know either a check mark or a count.
    """

    status: str = UNINITIALIZED # or LOADED, ERROR, STALE
    releases: list[Release] = field(default_factory=list) # last list w marks
    hidden_versions: set[str] = field(default_factory=set)
    last_attempt_at: float | None = None
    error_message: str = ''
    no_package: bool = False
    deleted: int = 0

    @property
    def visited(self) -> bool:
        """True once a fetch for this pair has succeeded."""
        return self.status in (LOADED, STALE)

    @property
    def version_count(self) -> int:
        """How many releases the last successful view holds."""
        return len(self.releases)


def package_width(packages: Sequence[str]) -> int:
    """The PACKAGE column width: the longest name, but never under the title."""
    return max([len(PACKAGE_TITLE), *(len(name) for name in packages)])


def package_host_order(current_host: str) -> tuple[str, str]:
    """The two hosts with *current_host* first, so its columns lead the row."""
    other = HOST_TEST if current_host == HOST_PYPI else HOST_PYPI
    return (current_host, other)


def host_group_label(host: str) -> str:
    """A ``-- host ---`` label spanning one VERs/DELs pair.

    The label is centered in :data:`PACKAGE_GROUP_WIDTH` cells,
    with dashes filling both sides.
    The host key (``pypi`` or ``test``) is used for simplicity.
    """
    label = f' {host} '
    if len(label) >= PACKAGE_GROUP_WIDTH:
        return label[:PACKAGE_GROUP_WIDTH].ljust(PACKAGE_GROUP_WIDTH)
    remaining = PACKAGE_GROUP_WIDTH - len(label)
    left = remaining // 2
    return '-' * left + label + '-' * (remaining - left)


def package_host_header(width: int, hosts: Sequence[str]) -> str:
    """The line of host names above the two VERs/DELs column pairs."""
    prefix = ' ' * (CHECK_WIDTH + 1 + width + 1)
    return prefix + ' '.join(host_group_label(host) for host in hosts)


def package_header(width: int, hosts: Sequence[str]) -> str:
    """The package list's column titles; the check column stays untitled."""
    prefix = (
        f"{' ' * (CHECK_WIDTH + 1)}"
        f"{PACKAGE_TITLE:<{width}} "
    )
    groups = [
        f"{'VERs':>{VERS_WIDTH}} {'DELs':>{DELS_WIDTH}}"
        for _host in hosts
    ]
    return prefix + ' '.join(groups)


def format_package_row(
    name: str,
    states: Mapping[str, PackageState | None],
    width: int,
    hosts: Sequence[str],
) -> str:
    """Format one package-list row with one VERs/DELs pair per host.

    The check column means this run has loaded the package on either host.
    A host with no successful fetch shows ``-`` in both of its columns.
    """
    visited = any(
        state is not None and state.visited for state in states.values()
    )
    mark = VISITED_MARK if visited else ' '
    groups: list[str] = []
    for host in hosts:
        state = states.get(host)
        if state is None or not state.visited:
            versions = deleted = '-'
        else:
            versions = str(state.version_count)
            deleted = str(state.deleted)
        groups.append(f'{versions:>{VERS_WIDTH}} {deleted:>{DELS_WIDTH}}')
    return (
        f"{mark:^{CHECK_WIDTH}} "
        f"{name:<{width}} "
        + ' '.join(groups)
    )


def resolve_theme(
    cli_theme: str | None = None,
    cli_no_color: bool | None = None,
    saved_theme: str = "",
    saved_no_color: bool = False,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Return the theme a run starts with: a palette name or ``mono``."""
    explicit = MONO_THEME if cli_no_color else cli_theme
    saved = MONO_THEME if saved_no_color else saved_theme
    return (
        Appearance.resolve_appearance(
            cli_theme=explicit, saved_theme=saved, environ=environ)
        or Theme.resolve(Theme.get_current())
    )


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
        gap: int = DEFAULT_GAP,
        read_only: bool = False,
        packages: Sequence[str] | None = None,
        totp_method: str = DEFAULT_TOTP_METHOD,
    ) -> None:
        self.cleanup = cleanup
        self.ini = ini
        self.read_only = bool(read_only)
        self.totp_method = (
            totp_method if totp_method in TOTP_METHODS else DEFAULT_TOTP_METHOD
        )
        self.running = True
        self.packages = (
            list(dict.fromkeys(packages)) if packages else [cleanup.package]
        )
        if cleanup.package not in self.packages:
            self.packages.insert(0, cleanup.package)
        self.package_index = self.packages.index(cleanup.package)
        self.states: dict[tuple[str, str], PackageState] = {}
        self.clock: Callable[[], float] = time.time
        self.packages_pick: int | None = None
        self.sort = sort
        self.loading = False
        self.load_failed = False
        self.search_text = ''
        self.search_re: re.Pattern[str] | None = None
        self.search_anchor: Release | None = None
        self.search_bar = IncrementalSearchBar(
            on_change=self._on_search_change,
            on_accept=self._finish_search,
            on_cancel=self._finish_search,
        )

        stored_theme = getattr(ini.vals, 'theme', '') if ini is not None else ''
        stored_no_color = (
            bool(getattr(ini.vals, 'no_color', False)) if ini is not None else False
        )
        self.opts = SimpleNamespace()
        self.opts.theme = resolve_theme(
            cli_theme=theme,
            cli_no_color=no_color,
            saved_theme=stored_theme,
            saved_no_color=stored_no_color,
        )
        Theme.set_active(self.opts.theme)
        if zone in ZONES:
            self.opts.time_zone = zone
        self.opts.gap = gap if gap in GAP_CHOICES else DEFAULT_GAP

        win_opts = ConsoleWindowOpts(
            min_cols_rows=(60, 10),
            ctrl_c_terminates=False,
            theme=self.opts.theme,
        )
        self.win = ConsoleWindow(opts=win_opts, backend=backend, singleton=singleton)

        # Screens are numbered in declaration order,
        # which is what the module's screen constants name;
        # the stack assigns each its number and itself.
        self.stack = ScreenStack.from_screens(
            self.win,
            self.opts,
            (
                MainScreen(self),
                HelpScreen(self),
                ThemeScreen(self),
                PackagesScreen(self),
            ),
        )

        spin = self.spin = OptionSpinner(stack=self.stack)
        # quit (q, ^C) and escape (ESC, ^J, ENTER) are registered by the spinner itself;
        # the screens supply the ACTION methods,
        # so the help page lists them once in its navigation block and never as options.
        spin.add_key('help_screen', '? - help', genre='action',
                     keys=[ord('?')], scope={MAIN_ST, PACKAGES_ST})
        # The cycles come next, so the help screen lists every option that takes
        # a value before the keys that only fire once.
        # A cycle needs no _ACTION method: it rewrites the option in place,
        # the next draw reads it, and handle_key() is where the remembered ones are stored.
        #
        # z rewrites the time zone the DATE column names.
        # The help screen lists the same cycle, so the key works there too and the value
        # shown beside it is the one the table will use.
        spin.add_key('time_zone', 'z - date time zone',
                     vals=list(ZONES), keys=[ord('z')],
                     scope={MAIN_ST, HELP_ST})
        # t works on the THEMES screen and on the help
        # screen; handle_key() applies the theme,
        # mono included, as soon as the value changes.
        spin.add_key('theme', 't - cycle themes', vals=list(THEME_CHOICES),
                     keys=[ord('t')], scope={THEME_ST, HELP_ST})
        # The stability gap is a hidden option: g rotates
        # it on the help screen and applies it on the table,
        # so one key is bound twice with two meanings -- a cycle on one screen,
        # an action on the other.
        spin.add_key('gap', 'g - stability gap, in days', vals=list(GAP_CHOICES),
                     keys=[ord('g')], scope={HELP_ST})
        # T opens the picker from the table or the help screen,
        # so ESC returns to whichever screen pushed it.
        # It is not bound on the picker itself, so the stack cannot recurse,
        # and t is not bound on the table, so the table keeps its own keys untouched.
        spin.add_key('theme_screen', 'T - themes', genre='action',
                     keys=[ord('T')], scope={MAIN_ST, HELP_ST})
        # P opens the working package list,
        # which is a different view of the same list p rotates
        # through: p steps the table to the next package, P edits the list itself.
        spin.add_key('packages_screen', 'P - package list', genre='action',
                     keys=[ord('P')], scope={MAIN_ST})
        # p and h change what the table is looking at; the summary
        # header already advertises both as key hints ([p]ack / [h]ost).
        spin.add_key('package_next', 'p - next package', genre='action',
                     keys=[ord('p')], scope={MAIN_ST})
        spin.add_key('host_next', 'h - switch index', genre='action',
                     keys=[ord('h')], scope={MAIN_ST})
        # f reloads the package already on screen,
        # which is how a new upload is picked up without rotating to another package first.
        spin.add_key('refresh', 'f - refresh the release list', genre='action',
                     keys=[ord('f')], scope={MAIN_ST})
        # ESC is the way back on every pushed screen because the built-in escape action pops
        # one; the package list overrides its ACTION to open the picked package instead,
        # so one built-in binding is enough.
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
        # The deletion step: the hint only appears once something
        # is marked and no pattern is filtering the table.
        # Pressing d hands the marked versions to pypi-cleanup;
        # a read-only run says so in the help list.
        spin.add_key(
            'delete',
            'd - delete the marked versions' + (
                ' (read-only mode)' if read_only else ' with pypi-cleanup'),
            genre='action', keys=[ord('d')], scope={MAIN_ST},
        )
        # Sorting changes the model rather than a spinner value,
        # so it is an action; the hint line advertises it between the marking keys and z.
        spin.add_key('sort', 's - change the sort order',
                     genre='action', keys=[ord('s')], scope={MAIN_ST})
        # g's action: the qualifier names its screen
        # because g also rotates the gap on the help screen,
        # and the help body lists both lines.
        spin.add_key('apply_gap',
                     'g - keep the releases that stayed stable [Main Screen]',
                     genre='action', keys=[ord('g')], scope={MAIN_ST})
        # "/" opens the incremental search field in the first header line.
        spin.add_key('search', '/ - incremental search',
                     genre='action', keys=[ord('/')], scope={MAIN_ST})
        # The package list's row key.  It is scoped to that screen,
        # so x there removes a name while x on the table still marks a
        # release; the qualifier keeps the two x lines apart in the help body.
        spin.add_key('package_remove',
                     'x - remove from the package list [Package Screen]',
                     genre='action', keys=[ord('x')], scope={PACKAGES_ST})
        # The built-in escape binding is what delivers ENTER (10 and curses.KEY_ENTER); 13
        # still has to reach the search bar as a handled key on the terminals that send it.
        self.win.set_handled_keys(set(spin.keys) | {13})

    def handle_key(self, key: int) -> None:
        """Route one key to the search bar, then the spinner.

        While the bar is active it owns printable and editing keys.
        Any key it does not handle (navigation, Ctrl-C) closes the pattern first
        and then continues to its normal destination,
        """
        if self.search_bar.is_active:
            if self.search_bar.handle_key(key):
                return
            self.search_bar.handle_key(10)
        if key not in self.spin.keys:
            return
        option = self._option_for(key)
        value = self.spin.do_key(key, self.win)
        if option is None or option.genre != 'cycle' or value is None:
            return
        if option.attr == 'time_zone':
            self.persist(zone=str(value))
        elif option.attr == 'theme':
            self.apply_theme_choice(str(value))
        elif option.attr == 'gap':
            self.persist(gap=int(value))

    def compile_search(self) -> None:
        """Compile the search text into :attr:`search_re`.

        The pattern is a case-insensitive python regular expression.
        """
        pattern = self.search_text.strip()
        self.search_re = None
        if pattern:
            try:
                self.search_re = re.compile(pattern, re.IGNORECASE)
            except re.error:
                self.search_re = None

    def release_matches(self, release: Release) -> bool:
        """Whether *release*'s version matches the compiled pattern."""
        if self.search_re is None:
            return True
        return self.search_re.search(release.version) is not None

    def visible_versions(self) -> list[Release]:
        """The releases the table currently shows, in table order."""
        return [release for release in self.cleanup.versions
                if self.release_matches(release)]

    def _clamp_pick(self) -> None:
        """Keep the pick inside the visible rows after the pattern changes."""
        count = len(self.visible_versions())
        self.win.pick_pos = min(self.win.pick_pos, count - 1) if count else 0

    def _restore_search_pick(self) -> None:
        """Put the pick back on the anchored release, or at the top."""
        visible = self.visible_versions()
        anchor = self.search_anchor
        self.search_anchor = None
        if anchor is not None:
            for index, release in enumerate(visible):
                if release is anchor:
                    self.win.pick_pos = index
                    return
        self.win.pick_pos = 0

    def _on_search_change(self, text: str) -> None:
        """Filter as the pattern is typed, keeping the pick in range."""
        self.search_text = text
        self.compile_search()
        self._clamp_pick()

    def _finish_search(self, text: str) -> None:
        """Accept or cancel: stop editing and restore the logical pick."""
        self.search_text = text
        # ESC restores the old text without emitting on_change,
        # so the pattern has to be compiled again on this path too.
        self.compile_search()
        self.win.passthrough_mode = False
        self._restore_search_pick()

    def start_search(self) -> None:
        """Open the search bar with the current pattern and anchor the pick."""
        visible = self.visible_versions()
        position = self.win.pick_pos
        self.search_anchor = (
            visible[position] if 0 <= position < len(visible) else None
        )
        self.search_bar.start(self.search_text)
        self.win.passthrough_mode = True

    def apply_theme_choice(self, choice: str) -> None:
        """Make a picker *choice* live and remember it."""
        self.opts.theme = choice
        self.win.set_theme(choice)
        self.persist(theme=choice, no_color=choice == MONO_THEME)

    def hand_off_to_cleanup(self, versions: Sequence[str],
                            notice: str | None = None) -> None:
        """Leave curses for ``pypi-cleanup``, show the runs, and come back."""
        base = cleanup_command(self.cleanup, versions)
        package = self.cleanup.package
        count = len(versions)
        mapped = credential_env(self.cleanup.host_key)
        env = cleanup_env(self.cleanup.host_key)
        deleted = 0
        self.win.suspend_curses()
        try:
            _reset_terminal()
            if notice:
                # The table that held the mark is out of sight, so...
                print(notice)
                print()
            print(format_command(base, env=mapped))
            print()
            if ask_yes_no(DRY_RUN_PROMPT, default=True):
                query = cleanup_command(self.cleanup, versions, QUERY_ONLY)
                print(format_command(query, env=mapped))
                print(summary_line(
                    'Dry run', package, self._run_cleanup(query, env)))
                print()
            if ask_yes_no(
                DELETE_PROMPT.format(count=count, package=package),
                default=False,
            ):
                if self._delete_with_retry(versions, package, count,
                                           mapped, env):
                    deleted = count
            press_enter()
        finally:
            self.win.resume_curses()
        if deleted:
            self.reload_after_deletion(versions)
        self.win.render(redraw=True)

    def _delete_with_retry(
        self,
        versions: Sequence[str],
        package: str,
        count: int,
        mapped: Mapping[str, str] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> bool:
        """Run the ``--do-it`` deletion, reissuing it until it succeeds.

        A run that fails is offered again behind a ``RETRY:`` prompt,
        the authenticator method is applied again to change the outcome possibly.
        """
        while True:
            destroy = cleanup_command(self.cleanup, versions, DO_IT)
            print(format_command(destroy, env=mapped))
            status = self._run_cleanup(destroy, env)
            print(summary_line('Deletion', package, status))
            print()
            if status == 0:
                return True
            if not ask_yes_no(
                RETRY_PROMPT.format(count=count, package=package),
                default=False,
            ):
                return False

    def _run_cleanup(self, command: Sequence[str],
                     env: Mapping[str, str] | None = None) -> int:
        """Run ``pypi-cleanup`` using the configured authenticator method."""
        if self.totp_method == TOTP_PRINT:
            show_authentication_code(self.cleanup.host_key)
            return run_cleanup(command, env)
        if self.totp_method in (TOTP_EXPECT, TOTP_AUTO):
            secret = totp_secret(self.cleanup.host_key)
            if not secret:
                return run_cleanup(command, env)
            if self.totp_method == TOTP_EXPECT:
                print(EXPECT_BANNER)
                runner = run_cleanup_expect
            else:
                runner = run_cleanup_auto
            try:
                return runner(command, secret, env)
            except ExpectUnavailable as error:
                print(f'warning: pexpect could not start: {error}; '
                      'printing the code instead.')
                show_authentication_code(self.cleanup.host_key)
                return run_cleanup(command, env)
        return run_cleanup(command, env)

    def reload_after_deletion(self, versions: Sequence[str]) -> None:
        """Hide the deleted versions, then fetch the package again."""
        state = self.state
        state.deleted += len(versions)
        # A second deletion while the first is still unconfirmed
        # adds to the hidden set.
        state.hidden_versions |= set(versions)
        state.releases = [
            release for release in state.releases
            if release.version not in state.hidden_versions
        ]
        for release in state.releases:
            release.delete = False
        self.cleanup.versions = state.releases
        state.status = STALE
        self.search_text = ''
        self.search_re = None
        self.search_anchor = None
        self.load_versions()

    def _settle_hidden_versions(self) -> None:
        """Keep hidden versions out of a fetched history and note the result."""
        state = self.state
        if not state.hidden_versions:
            state.status = LOADED
            return
        fetched = {release.version for release in self.cleanup.versions}
        state.hidden_versions &= fetched
        if state.hidden_versions:
            self.cleanup.versions = [
                release for release in self.cleanup.versions
                if release.version not in state.hidden_versions
            ]
        state.status = STALE if state.hidden_versions else LOADED

    def _option_for(self, key: int) -> SimpleNamespace | None:
        """The spinner option bound to *key* on the current screen, if any."""
        current = self.stack.curr
        if current is not None:
            option = self.spin.key_scopes.get((key, current.num))
            if option is not None:
                return option
        return self.spin.key_to_option.get(key)

    def persist(self, **values: object) -> None:
        """Store the settings a change has just made, for the next run."""
        if self.ini is None:
            return
        values.setdefault('host', self.cleanup.host_key)
        self.ini.save(**values)

    @property
    def state(self) -> PackageState:
        """The mutable state of the ``(package, host)`` pair on screen."""
        key = (self.cleanup.package, self.cleanup.host_key)
        return self.states.setdefault(key, PackageState())

    @property
    def hidden_versions(self) -> set[str]:
        """The hidden versions of the pair on screen (read-only view)."""
        return self.state.hidden_versions

    @property
    def stale(self) -> bool:
        """Whether the pair on screen is in its ``STALE`` state."""
        return self.state.status == STALE

    def state_for(self, package: str, host: str) -> PackageState | None:
        """The saved state for a pair, or ``None`` if this run never saw it."""
        return self.states.get((package, host))

    def switch_to(self, package: str, host: str) -> None:
        """Show another pair, restoring the complete state saved for it."""
        if package == self.cleanup.package and host == self.cleanup.host_key:
            return
        # The model is the current pair's live copy; make the durable
        # state point at it before the model is pointed at another pair.
        self.state.releases = self.cleanup.versions
        self.cleanup.package = package
        self.cleanup.host_key = host
        target = self.state
        self.cleanup.versions = list(target.releases)
        self.cleanup.sort_versions(self.sort)
        marked = {
            release.version for release in target.releases if release.delete
        }
        self.win.pick_pos = 0
        if target.status == ERROR and not self._error_retry_due(target):
            return
        self.load_versions()
        if self.load_failed:
            return
        # A successful visit replaces the rows, so the saved marks are restored.
        for release in self.cleanup.versions:
            if release.version in marked:
                release.delete = True
        target.releases = self.cleanup.versions

    def _error_retry_due(self, state: PackageState) -> bool:
        """Whether an error-state pair is old enough to be fetched again."""
        return (
            state.last_attempt_at is None
            or self.clock() - state.last_attempt_at >= ERROR_RETRY_SECONDS
        )

    def select_package(self, package: str) -> None:
        """Make *package* the table's package on the current host."""
        if package not in self.packages:
            return
        self.package_index = self.packages.index(package)
        self.switch_to(package, self.cleanup.host_key)

    def remove_package(self, package: str) -> None:
        """Drop *package* from the working list, leaving the index untouched."""
        if package not in self.packages:
            return
        self.packages.remove(package)
        if self.cleanup.package in self.packages:
            self.package_index = self.packages.index(self.cleanup.package)
        elif self.packages:
            self.package_index = min(self.package_index, len(self.packages) - 1)
        else:
            self.package_index = 0
        self.persist(packages=','.join(self.packages))

    def next_package_index(self) -> int | None:
        """The row after the table's package, wrapping to the first one."""
        if not self.packages:
            return None
        if self.cleanup.package in self.packages:
            index = self.packages.index(self.cleanup.package)
            return (index + 1) % len(self.packages)
        return min(self.package_index, len(self.packages) - 1)

    def load_versions(self) -> None:
        """Show ``Loading ...``, fetch, and move the pair to its next state.

        A successful fetch replaces the rows.
        A failure depends on whether this pair has ever
        loaded: a pair that has keeps the old table,
        becomes ``STALE`` and shows the modal alert; a pair that never loaded keeps no rows,
        becomes ``ERROR`` and shows the error in the body instead.
        The pair's state is durable,
        so switching away and back restores whichever result this produced.
        """
        state = self.state
        previous_status = state.status
        previous_pick = self.win.pick_pos
        self.loading = True
        self.load_failed = False
        self.cleanup.versions = []
        self.win.pick_pos = 0
        self._draw_current_screen()
        self.win.render()
        state.last_attempt_at = self.clock()
        try:
            self.cleanup.fetch_versions()
        except Exception as exc:
            self.load_failed = True
            self._handle_load_failure(
                state, previous_status, previous_pick, exc)
            return
        finally:
            self.loading = False
        self.cleanup.sort_versions(self.sort)
        state.releases = self.cleanup.versions
        state.error_message = ''
        state.no_package = False
        state.status = LOADED
        self._settle_hidden_versions()
        state.releases = self.cleanup.versions

    def _load_error_message(self, exc: BaseException) -> str:
        """The alert text a failed fetch has always used."""
        return (
            f'Could not load {self.cleanup.package!r} from '
            f'{self.cleanup.host}.\n\n'
            f'{type(exc).__name__}: {exc}'
        )

    def _handle_load_failure(
        self,
        state: PackageState,
        previous_status: str,
        previous_pick: int,
        exc: BaseException,
    ) -> None:
        """Record a failed fetch and choose the alert or the body error.

        A pair that has loaded before is considered stale.
        A pair that has never loaded is an error.
        """
        message = self._load_error_message(exc)
        state.error_message = message
        state.no_package = is_missing_package_error(exc)
        if previous_status in (LOADED, STALE):
            state.status = STALE
            self.cleanup.versions = state.releases
            self.cleanup.sort_versions(self.sort)
            count = len(self.visible_versions())
            self.win.pick_pos = min(previous_pick, count - 1) if count else 0
            self.win.alert(message, title='LOAD ERROR')
            return
        state.status = ERROR
        state.releases = []
        self.cleanup.versions = []

    def _draw_current_screen(self) -> None:
        """Clear and draw the screen on top: one content pass, start to finish."""
        screen = self.stack.get_curr_obj()
        if screen is not None:
            screen.clear()
            screen.draw_screen()

    def main_loop(self) -> None:
        """Load the first history, then draw until an action clears running."""
        # Entering the TUI before the fetch is what lets the
        # loading frame and the failure alert use the real terminal.
        self.load_versions()
        while self.running:
            self._draw_current_screen()
            self.win.render()
            key = self.win.prompt(seconds=1.0)
            if key is not None:
                self.handle_key(key)
            self.stack.perform_actions(self.spin)

    def run(self) -> int:
        """Run the application and always leave the terminal usable."""
        try:
            self.main_loop()
        finally:
            self.win.stop_curses()
        return 0


class CleanupScreen(Screen):
    """Base screen: every screen can receive the global quit/back actions.

    ``ESC`` needs no handler of its own: ``Screen.escape_ACTION``
    already pops one screen and is a no-op on the home screen,
    which is exactly the table's meaning of the key.
    Quitting ends the loop instead of raising,
    so the window's teardown in :meth:`CleanupApp.run` always runs.
    """

    app: CleanupApp

    def quit_ACTION(self) -> None:
        self.app.running = False

    def help_screen_ACTION(self) -> None:
        """Push the help screen, remembering the pick to return to."""
        self.app.stack.push(HELP_ST, self.app.win.pick_pos)

    def theme_screen_ACTION(self) -> None:
        """Push the theme picker; ESC returns to the screen that pushed it."""
        self.app.stack.push(THEME_ST, self.app.win.pick_pos)


class MainScreen(CleanupScreen):
    """The release table."""

    def draw_screen(self) -> None:
        # While the pattern is being typed the bar is the focus; suppressing
        # the row highlight keeps the cursor in the header unambiguous.
        self.set_pick_mode(not self.app.search_bar.is_active)
        self._draw_headers()
        self._draw_body()

    def _time_mode(self) -> str:
        """The ``D`` spinner's current value; UTC until the spinner is read."""
        return self.app.spin.get_value('time_zone') or UTC_MODE

    def _gap_days(self) -> int:
        """The stability gap the spinner holds, in days."""
        return int(self.app.spin.get_value('gap') or DEFAULT_GAP)

    def _hint_line(self) -> HeaderLine:
        """The first header line: one fixed-width block per key."""
        hints = HeaderLine()
        if self.app.read_only:
            hints.text(READ_ONLY_HINT)
        elif self._deletion_offered():
            hints.bracket_key('d').text(DEL_HINT[1:])
        else:
            hints.text(' ' * len(DEL_HINT))
        hints.text(' ')
        picked = self._release_at_pick()
        if picked is not None and picked.delete:
            hints.bracket_key('u').text('nmark ')
            hints.bracket_key('U').text(f'nmark{DOWN_MARK} ')
        else:
            hints.bracket_key('x').text(':mark ')
            hints.bracket_key('X').text(f':mark{DOWN_MARK} ')

        hints.bracket_key('s').text('ort ')
        hints.bracket_key('z').text('one ')
        hints.bracket_key('g').text(f'ap{self._gap_days():<{GAP_HINT_WIDTH}} ')
        hints.bracket_key('f').text('resh ')
        hints.bracket_key('q').text('uit ')
        hints.bracket_key('?').text(':help')
        hints.extend(self._search_header_line())
        return hints

    def _draw_headers(self) -> None:
        self.add_fancy_header(self._hint_line(), line_attr=curses.A_DIM)

        cleanup = self.app.cleanup
        summary = HeaderLine()
        summary.text(f'User={cleanup_user(cleanup) or "n/a"} ')
        summary.bracket_key('p').text(f'ack={cleanup.package} ')
        summary.bracket_key('h').text(f'ost={cleanup.host_key}')
        state = self.app.state
        if state.status == STALE:
            now = self.app.clock()
            start = state.last_attempt_at
            age = compact_delta_time(now if start is None else start, now)
            summary.label(f' STALE [{age}]')
        self.add_fancy_header(summary)
        self.add_header(
            column_header(self._time_mode(), cleanup.sort),
            attr=curses.A_DIM,
        )

    def _search_header_line(self) -> HeaderLine:
        """The ``/pattern`` field at the end of the hint line.

        ``IncrementalSearchBar.as_header_line()`` hides itself while
        idle with an empty buffer; we keep the bare ``/`` visible when empty.
        """
        line = self.app.search_bar.as_header_line(prefix='/')
        if not line:
            line.search('', prefix='/')
        display = HeaderLine()
        display.text(' ')
        display.extend(line)
        return display

    def _marked_count(self) -> int:
        """How many releases are currently marked for deletion."""
        return sum(1 for release in self.app.cleanup.versions if release.delete)

    def _deletion_offered(self) -> bool:
        """Whether ``d`` may fire: something is marked and nothing is filtered
        and not read-only.
        """
        return (
            not self.app.read_only
            and self._marked_count() > 0
            and self.app.search_re is None
        )

    def _release_at_pick(self) -> Release | None:
        """The visible release under the pick, or ``None`` when there is none.

        Unlike :meth:`_picked` this answers while the search bar is
        active: the hint line describes the row the pick sits on,
        although the bar steals all the keys and none act while the pattern is read.
        """
        visible = self.app.visible_versions()
        position = self.app.win.pick_pos
        if 0 <= position < len(visible):
            return visible[position]
        return None

    def _draw_body(self) -> None:
        # The loading frame is drawn by load_versions(); it deliberately shows no releases,
        # so the old package's rows cannot be mistaken for new.
        if self.app.loading:
            self.add_body(
                'Loading ...',
                attr=semantic_attr(Theme.HOTSWAP),
                context=Context(genre='DECOR'),
            )
            return
        state = self.app.state
        if state.status == ERROR:
            self._draw_error_body(state)
            return
        versions = self.app.visible_versions()
        if not versions:
            self.add_body(
                ('No matching releases.' if self.app.search_text
                 else 'No releases found.'),
                attr=curses.A_DIM,
                context=Context(genre='DECOR'),
            )
            return
        now = datetime.now(UTC)
        mode = self._time_mode()
        # Once anything is marked, the surviving releases colored SUCCESS.
        # A marked row keeps its DEL cell plain and dims the rest of the line.
        keep_attr = semantic_attr(Theme.SUCCESS) if self._marked_count() else None
        for index, release in enumerate(versions):
            row = format_row(release, now, mode)
            context = Context(genre='item', release=release, index=index)
            if release.delete:
                self.add_body(row[:DEL_WIDTH], context=context)
                self.add_body(row[DEL_WIDTH:], attr=curses.A_DIM, resume=True)
            else:
                self.add_body(row, attr=keep_attr, context=context)

    def _draw_error_body(self, state: PackageState) -> None:
        """Draw a never-loaded pair's failure instead of a release table.

        The body is the only explanation for an ``ERROR``
        pair: no popup interrupts the first load.
        A missing package answers with one line; anything else shows the age, a blank line,
        and the wrapped description an alert would have contained.
        Every line carries the same HOTSWAP color the block connotes state, not rows.
        """
        attr = semantic_attr(Theme.HOTSWAP)
        context = Context(genre='DECOR')
        now = self.app.clock()
        start = state.last_attempt_at
        age = compact_delta_time(now if start is None else start, now)
        if state.no_package:
            self.add_body(f'NO PACKAGE [{age}]', attr=attr, context=context)
            return
        self.add_body(f'ERROR [{age}]', attr=attr, context=context)
        self.add_body('', attr=attr, context=context)
        width = max(ERROR_TEXT_WIDTH, min(self.win.get_pad_width(), 78))
        for index, paragraph in enumerate(state.error_message.split('\n\n')):
            if index:
                self.add_body('', attr=attr, context=context)
            for line in textwrap.wrap(
                paragraph, width=width, break_on_hyphens=False
            ):
                self.add_body(line, attr=attr, context=context)

    # --- selection -------------------------------------------------------
    #
    # Every body row is a release,
    # so the release with visible-row index *i* is body row *i*;
    # the column titles live in the header and can never be picked.
    # The model index may differ while a search is filtering the table,
    # which is why the actions slice the visible list.

    def _picked(self) -> Context | None:
        """The context of the release under the pick, or None off the rows."""
        ctx = self.app.win.get_picked_context()
        if ctx is None or not hasattr(ctx, 'release'):
            return None
        return ctx

    def _pick_release(self, index: int) -> None:
        """Point the pick at the visible row *index*."""
        self.app.win.pick_pos = index

    def mark_ACTION(self) -> None:
        """Mark the picked release and advance to the next visible one."""
        ctx = self._picked()
        if ctx is None:
            return
        visible = self.app.visible_versions()
        ctx.release.delete = True
        if ctx.index + 1 < len(visible):
            self._pick_release(ctx.index + 1)

    def mark_from_here_ACTION(self) -> None:
        """Mark the picked visible row and every visible row below it."""
        ctx = self._picked()
        if ctx is None or ctx.release.delete:
            return
        visible = self.app.visible_versions()
        for release in visible[ctx.index:]:
            release.delete = True
        # The row above the block is the last release the cut keeps: parking
        # the pick there (and never above the first release) shows the boundary.
        self._pick_release(max(ctx.index - 1, 0))

    def unmark_ACTION(self) -> None:
        """Unmark the picked visible row, then step down like ``x`` does."""
        ctx = self._picked()
        if ctx is None:
            return
        visible = self.app.visible_versions()
        ctx.release.delete = False
        if ctx.index + 1 < len(visible):
            self._pick_release(ctx.index + 1)

    def unmark_from_here_ACTION(self) -> None:
        """Unmark the picked visible row and every visible row below it."""
        ctx = self._picked()
        if ctx is None or not ctx.release.delete:
            return
        visible = self.app.visible_versions()
        for release in visible[ctx.index:]:
            release.delete = False
        self._pick_release(max(ctx.index - 1, 0))

    def delete_ACTION(self) -> None:
        """Hand the marked releases to ``pypi-cleanup`` and wait to come back.

        The key is inert whenever its block is blank -- nothing marked,
        a pattern filtering the table, or a read-only run.
        The marked versions are read in table order,
        so the dry run and the deletion name exactly the rows that were on screen.
        """
        if not self._deletion_offered():
            return
        releases = self.app.cleanup.versions
        notice = None
        given_back = unmark_newest_marked(releases)
        if given_back is not None:
            if not any(release.delete for release in releases):
                self.win.flash(
                    LAST_VERSION_MESSAGE,
                    duration=LAST_VERSION_FLASH_SECONDS,
                )
                return
            notice = UNMARKED_NEWEST_NOTICE.format(version=given_back.version)
        self.app.hand_off_to_cleanup(
            [release.version for release in releases if release.delete],
            notice=notice,
        )

    def apply_gap_ACTION(self) -> None:
        """Keep the marked releases that stayed current for the stability gap."""
        app = self.app
        gap = self._gap_days()
        marked = self._marked_count()
        stable = stable_releases(
            app.cleanup.versions, gap, self._time_mode())
        for release in stable:
            release.delete = False
        self.win.status(
            f'Kept {len(stable)} of {marked} marked versions, gap {gap} days',
            timeout=2.0,
        )

    def sort_ACTION(self) -> None:
        """Flip the table between version order and upload-date order."""
        cleanup = self.app.cleanup
        order = (SORT_BY_DATE if cleanup.sort == SORT_BY_VERSION
                 else SORT_BY_VERSION)
        cleanup.sort_versions(order)
        self.app.persist(sort=cleanup.sort)

    def search_ACTION(self) -> None:
        """Open the incremental search bar at the end of the hint line."""
        self.app.start_search()

    def packages_screen_ACTION(self) -> None:
        """Open the working package list, ready to open the next package."""
        app = self.app
        app.packages_pick = app.next_package_index()
        app.stack.push(PACKAGES_ST, app.win.pick_pos)

    def refresh_ACTION(self) -> None:
        """Fetch the current package again, carrying the marks onto the new rows."""
        app = self.app
        was_stale = app.state.status == STALE
        marked = {release.version for release in app.cleanup.versions
                  if release.delete}
        app.load_versions()
        if app.load_failed:
            return
        for release in app.cleanup.versions:
            if release.version in marked:
                release.delete = True
        if was_stale and app.state.status == LOADED:
            self.win.status('Fresh', timeout=2.0)

    def package_next_ACTION(self) -> None:
        """Show the next package in the remembered list and reload it.

        A list holding only the current package has no next package and does not reload.
        """
        app = self.app
        next_index = app.next_package_index()
        if next_index is None or app.packages[next_index] == app.cleanup.package:
            return
        app.package_index = next_index
        app.switch_to(app.packages[next_index], app.cleanup.host_key)

    def host_next_ACTION(self) -> None:
        """Switch between pypi.org and test.pypi.org and reload."""
        cleanup = self.app.cleanup
        target = HOST_TEST if cleanup.host_key == HOST_PYPI else HOST_PYPI
        self.app.persist(host=target)
        self.app.switch_to(cleanup.package, target)


class HelpScreen(CleanupScreen, BasicHelpScreen):
    """The key-help screen; ESC returns to the screen that opened it."""

    def extra_help_paragraphs(self) -> Iterable[str]:
        """The less obvious bits under the option list, one short bullet each."""
        bullets = [
            '/ filters the version column only, as a case-insensitive regular '
                'expression; only the visible rows can be marked.',
            'f refetches the package but marks; a failed fetch shows the '
                'the list as STALE, as does fetch having deleted versions.',
            'g is the stability gap: here it rotates allowed values; '
                'on the table it unmarks releases superseded within the gap',
        ]
        ini = self.app.ini
        if ini is not None:
            stored = ', '.join(
                f'{key}={getattr(ini.vals, key)!r}' for key in vars(ini.vals)
            )
            bullets.append(f'Saved options ({ini.config_file_path}): {stored}')
        return tuple(bullets)


class PackagesScreen(CleanupScreen):
    """The working package list, with a VERs/DELs pair for each index.

    The list is what ``p`` rotates through and what the command line remembers.
    Each row carries one ``VERs``/``DELs`` pair per host;
    ``x`` removes the picked name from the list.
    ``ESC`` returns to main screen or exits if no packages remain.
    """

    def draw_screen(self) -> None:
        self.set_pick_mode(True)
        width = package_width(self.app.packages)
        hosts = package_host_order(self.app.cleanup.host_key)
        self.add_fancy_header(PACKAGES_HINT, line_attr=curses.A_DIM)
        self.add_header(package_host_header(width, hosts), attr=curses.A_DIM)
        self.add_header(package_header(width, hosts), attr=curses.A_DIM)
        self._draw_body(width, hosts)
        self._place_pick()

    def _place_pick(self) -> None:
        """Consume the pending start row, scrolling it into view.

        ``P`` determines the row the pick starts, but placement awaits this Screen.
        """
        start = self.app.packages_pick
        if start is None:
            return
        self.app.packages_pick = None
        win = self.app.win
        win.pick_pos = start
        win.scroll_pos = 0
        # fix_positions() clamps the row to the body and scrolls
        # the viewport down when the start row is below the fold.
        win.fix_positions()

    def _draw_body(self, width: int, hosts: Sequence[str]) -> None:
        if not self.app.packages:
            self.add_body(
                'No packages in the list.',
                attr=curses.A_DIM,
                context=Context(genre='DECOR'),
            )
            return
        for name in self.app.packages:
            states = {
                host: self.app.state_for(name, host)
                for host in hosts
            }
            row = format_package_row(name, states, width, hosts)
            self.add_body(row, context=Context(genre='item', package=name))

    def _picked_package(self) -> str | None:
        """The package under the pick, or ``None`` off the rows."""
        ctx = self.app.win.get_picked_context()
        if ctx is None or not hasattr(ctx, 'package'):
            return None
        return ctx.package

    def escape_ACTION(self) -> None:
        """Open the picked package in the table, or leave when there is none."""
        app = self.app
        package = self._picked_package()
        if package is None:
            app.running = False
            return
        app.stack.pop()
        app.select_package(package)

    def package_remove_ACTION(self) -> None:
        """Remove the picked name from the list, keeping the pick on a row."""
        package = self._picked_package()
        if package is None:
            return
        self.app.remove_package(package)
        count = len(self.app.packages)
        self.app.win.pick_pos = min(self.app.win.pick_pos, count - 1) if count else 0

ThemeScreen = Theme.create_picker_screen(CleanupScreen, cycle_key='t')

def run_tui(
    cleanup: CleanupTui,
    backend: RenderBackend | None = None,
    singleton: bool = True,
    ini: IniManager | None = None,
    zone: str = UTC_MODE,
    theme: str | None = None,
    no_color: bool | None = None,
    sort: str = SORT_BY_VERSION,
    gap: int = DEFAULT_GAP,
    read_only: bool = False,
    packages: Sequence[str] | None = None,
    totp_method: str = DEFAULT_TOTP_METHOD,
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
        gap=gap,
        read_only=read_only,
        packages=packages,
        totp_method=totp_method,
    ).run()
