"""Turn the stored authenticator secret into the code ``pypi-cleanup`` asks for.

``pypi-cleanup`` does not read ``PYPI_CLEANUP_TOTP_SECRET`` from the
environment: every run prompts ``Authentication code:`` for the current
six-digit value.  The TUI therefore keeps the secret itself -- the plain
variable or its ``4PYPI``/``4TEST`` scoped form -- and computes the value that
prompt expects with :mod:`pyotp`, the usual Python implementation of RFC 6238.

Only the computation lives here.  Which secret applies to the index in use is
the host-scoped choice in :mod:`pypi_cleanup_tui.tui`, next to the password
mapping.  The code is printed above the command; a code about to expire is
slept out first so the user has room to type it, and handing it to the prompt
is a later step.
"""

from __future__ import annotations

import binascii
import time
from collections.abc import Callable

import pyotp

#: The variable holding the authenticator secret, before any index suffix.
TOTP_SECRET_ENV_VAR = 'PYPI_CLEANUP_TOTP_SECRET'

#: Seconds one code stays valid.  pyotp's default, and the interval every
#: mainstream authenticator uses; the report needs it to say what is left.
TOTP_INTERVAL = 30

#: A code with this little time left is not worth printing: the user could not
#: reach the prompt before it rolls over, so the wait below takes the next one.
MIN_TOTP_SECONDS = 10


def normalize_secret(secret: str) -> str:
    """Strip what authenticator apps display but base32 does not contain.

    Secrets are shown in groups of four and sometimes in lower case; the spaces
    are display noise and base32 is case-insensitive, so both are normalised
    here.  pyotp restores any missing ``=`` padding itself.
    """
    return ''.join(secret.split()).upper()


def code_and_remaining(secret: str,
                       now: float | None = None) -> tuple[str, int]:
    """Return the current six-digit code and the seconds until it expires.

    *now* is Unix time and exists for tests; the default is the current clock.
    A secret that is empty or not valid base32 raises :class:`ValueError`, so
    the caller can warn instead of crashing the hand-off.
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
    """Return a code that has more than :data:`MIN_TOTP_SECONDS` left.

    Printing a code about to expire would only send the user to a prompt that
    rejects it, so a short window is slept out first.  The loop repeats if the
    clock still reports too little time after waking.  *clock* and *sleep*
    exist for tests and default to the real ones.
    """
    code, remaining = code_and_remaining(secret, clock())
    while remaining <= MIN_TOTP_SECONDS:
        sleep(remaining)
        code, remaining = code_and_remaining(secret, clock())
    return code, remaining
