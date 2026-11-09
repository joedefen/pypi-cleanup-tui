"""Tests for the authenticator code the TUI computes for pypi-cleanup.

``pypi-cleanup`` never reads a TOTP secret from the environment; it prompts for
the six-digit code.  These tests pin the value the TUI prints for that prompt.
"""

from __future__ import annotations

import pytest

from pypi_cleanup_tui import totp

#: RFC 6238's SHA-1 seed is the ASCII string "12345678901234567890", written
#: here in base32.  Its six-digit code at T=59 is 287082, which is the RFC's
#: 94287082 truncated the way authenticator prompts show it.
RFC_SECRET = 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'


def test_the_code_matches_the_rfc_6238_vector():
    assert totp.code_and_remaining(RFC_SECRET, now=59) == ('287082', 1)


def test_the_remaining_seconds_count_down_to_the_next_boundary():
    assert totp.code_and_remaining(RFC_SECRET, now=60)[1] == 30
    assert totp.code_and_remaining(RFC_SECRET, now=89)[1] == 1


def test_spaces_and_case_do_not_change_the_code():
    spaced = 'gezd gnbv gy3t qojq gezd gnbv gy3t qojq'
    assert totp.normalize_secret(spaced) == RFC_SECRET
    assert totp.code_and_remaining(spaced, now=59)[0] == '287082'


def test_describe_names_the_code_and_the_seconds_left():
    assert totp.describe(RFC_SECRET, now=59) == (
        'Authentication code: 287082 (expires in 1s)')


def test_a_code_with_enough_room_is_used_immediately():
    slept = []

    code, remaining = totp.code_with_room(
        RFC_SECRET, clock=lambda: 61.0, sleep=slept.append)

    assert slept == []
    assert (code, remaining) == totp.code_and_remaining(RFC_SECRET, now=61)


def test_a_code_with_ten_seconds_left_waits_for_the_next_window():
    moments = iter([80.0, 90.0])
    slept = []

    code, remaining = totp.code_with_room(
        RFC_SECRET, clock=lambda: next(moments), sleep=slept.append)

    assert slept == [10]
    assert (code, remaining) == totp.code_and_remaining(RFC_SECRET, now=90)
    assert remaining > totp.MIN_TOTP_SECONDS


def test_the_wait_repeats_until_the_new_code_has_room():
    moments = iter([89.0, 89.5, 90.0])
    slept = []

    code, remaining = totp.code_with_room(
        RFC_SECRET, clock=lambda: next(moments), sleep=slept.append)

    # The first wait lands just before the boundary, so a second one is needed.
    assert slept == [1, 1]
    assert remaining == 30


def test_an_empty_secret_is_rejected_instead_of_computed():
    with pytest.raises(ValueError):
        totp.code_and_remaining('   ', now=59)


def test_a_secret_that_is_not_base32_is_a_value_error():
    with pytest.raises(ValueError):
        totp.code_and_remaining('not base 32!', now=59)
