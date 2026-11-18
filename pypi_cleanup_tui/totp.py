"""Turn the stored authenticator secret into the code ``pypi-cleanup`` asks for.

``pypi-cleanup`` does not read ``PYPI_CLEANUP_TOTP_SECRET`` from the environment:
every run prompts ``Authentication code:`` for the current six-digit value.
The TUI therefore keeps the secret itself -- the plain variable or its ``4PYPI``/``4TEST``
scoped form -- and computes the value that prompt expects with :mod:`pyotp`,
the usual Python implementation of RFC 6238.

Only the computation lives here.  Which secret applies to the index in use is the
scoped elsewhere.
"""

from __future__ import annotations

import binascii
import time
from collections.abc import Callable

import pyotp

TOTP_SECRET_ENV_VAR = 'PYPI_CLEANUP_TOTP_SECRET'
TOTP_INTERVAL = 30
MIN_TOTP_SECONDS = 10


def normalize_secret(secret: str) -> str:
    """Strip what authenticator apps display but base32 does not contain.

    Secrets are shown in groups of four and sometimes in lower case;
    the spaces are display noise and base32 is case-insensitive,
    so both are normalized here.  pyotp restores any missing ``=`` padding itself.
    """
    return ''.join(secret.split()).upper()


def code_and_remaining(secret: str,
                       now: float | None = None) -> tuple[str, int]:
    """Return the current six-digit code and the seconds until it expires.

    *now* is Unix time; the default (typical use) is the current clock.
    A secret that is empty or not valid base32 raises :class:`ValueError`.
    """
    normalized = normalize_secret(secret)
    if not normalized:
        raise ValueError('the TOTP secret is empty')
    otp = pyotp.TOTP(normalized, interval=TOTP_INTERVAL)
    moment = time.time() if now is None else now
    try:
        code = otp.at(moment)
    except (binascii.Error, ValueError, TypeError) as error:
        raise ValueError(f'could not compute a TOTP code: {error}') from error
    remaining = TOTP_INTERVAL - int(moment) % TOTP_INTERVAL
    return code, remaining


def format_code(code: str, remaining: int) -> str:
    """The line printed before a run: the code and how long it still lasts."""
    return f'Authentication code: {code} (expires in {remaining}s)'


def describe(secret: str, now: float | None = None) -> str:
    """Format the code at *now* without waiting; the tests pin this form."""
    code, remaining = code_and_remaining(secret, now)
    return format_code(code, remaining)


def code_with_room(secret: str,
                   clock: Callable[[], float] = time.time,
                   sleep: Callable[[float], None] = time.sleep,
                   ) -> tuple[str, int]:
    """Return a code that has more than :data:`MIN_TOTP_SECONDS` left. """
    code, remaining = code_and_remaining(secret, clock())
    while remaining <= MIN_TOTP_SECONDS:
        sleep(remaining)
        code, remaining = code_and_remaining(secret, clock())
    return code, remaining
