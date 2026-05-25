"""Fake-lead detection for request_quote.

AI agents probing the MCP server tend to submit lead-creation calls with
placeholder identities. We classify those at the boundary so the operator
chat does not get spammed.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

_TEST_EMAIL_RE = re.compile(
    r"@(example|test|invalid|localhost)\.(com|ru|org|net|io)$|"
    r"(yagentinbox|mailinator|10minutemail|tempmail|guerrillamail|throwaway|fakeinbox|sharklasers|trashmail|getnada)",
    re.IGNORECASE,
)
_TEST_PHONE_RE = re.compile(r"555-?[0-9]{2,}")
_TEST_NAME_RE = re.compile(
    r"^(test|john\s+doe|jane\s+doe|ivan\s+petrov|john\s+smith)$",
    re.IGNORECASE,
)


def looks_like_test(
    email: Optional[str],
    phone: Optional[str],
    name: Optional[str],
) -> Tuple[bool, Optional[str]]:
    """Classify an inbound lead as a placeholder / AI-test or a real contact.

    Returns (is_test, reason). Reasons used (stored in leads.test_reason):
      - example_domain: @example.* or @test.* domains
      - disposable_email: mailinator, 10minutemail, agentinbox, tempmail, etc
      - placeholder_phone: 555-prefixed phone (US convention)
      - empty_contact: neither email nor phone supplied
      - test_name: well-known canonical test names (Ivan Petrov, John Doe, ...)
    """
    if email and _TEST_EMAIL_RE.search(email):
        if "@example." in email.lower() or "@test." in email.lower():
            return True, "example_domain"
        return True, "disposable_email"
    if phone and _TEST_PHONE_RE.search(phone):
        return True, "placeholder_phone"
    if not email and not phone:
        return True, "empty_contact"
    if name and _TEST_NAME_RE.match(name.strip()):
        return True, "test_name"
    return False, None
