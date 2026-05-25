"""Unit tests for the fake-lead detector (looks_like_test).

We import the function directly from app.main without spinning up FastAPI.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make `import app.main` work when pytest runs from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.lead_detector import looks_like_test  # noqa: E402


@pytest.mark.parametrize(
    "email, phone, name, reason",
    [
        ("alice@example.com", "+7 999 123-45-67", "Alice", "example_domain"),
        ("foo@example.ru", None, None, "example_domain"),
        ("bar@test.com", None, None, "example_domain"),
        ("x@mailinator.com", None, None, "disposable_email"),
        ("y@nyagentinbox.com", None, None, "disposable_email"),
        ("z@10minutemail.com", None, None, "disposable_email"),
        ("real@gmail.com", "+7 916 555-12-34", None, "placeholder_phone"),
        (None, None, None, "empty_contact"),
        ("", "", "", "empty_contact"),
        ("real@gmail.com", "+1 222 333 4444", "Ivan Petrov", "test_name"),
        ("real@gmail.com", "+1 222 333 4444", "John Doe", "test_name"),
    ],
)
def test_detects_placeholder(email, phone, name, reason):
    is_test, got_reason = looks_like_test(email, phone, name)
    assert is_test is True, f"expected test for {email}/{phone}/{name}"
    assert got_reason == reason


@pytest.mark.parametrize(
    "email, phone, name",
    [
        ("yuri@mcp-market.ru", "+7 921 800-12-34", "Юрий"),
        ("contact@stroy-kompaniya.ru", "+7 812 200-30-40", "Ольга Николаевна"),
        ("buyer@gmail.com", "+49 30 12345678", "Hans Müller"),
        ("sales@some-real-builder.ru", "+7 495 123-00-99", None),
    ],
)
def test_does_not_flag_real_contacts(email, phone, name):
    is_test, reason = looks_like_test(email, phone, name)
    assert is_test is False, f"unexpected flag {reason!r} for {email}/{phone}/{name}"
    assert reason is None


def test_email_only_no_phone_real():
    is_test, reason = looks_like_test("client@gmail.com", None, None)
    assert is_test is False
    assert reason is None


def test_phone_only_no_email_real():
    is_test, reason = looks_like_test(None, "+7 800 200-00-00", None)
    assert is_test is False
    assert reason is None
