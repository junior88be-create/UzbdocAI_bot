"""Tests for the free-tier request quota decision logic (documents and
voice/audio transcription share one monthly counter - see
app/bot/quota.py and app.database.repositories.UserRepository
.check_and_consume_quota). _quota_decision is pure (no DB session), so it
is tested directly here rather than through a live database.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.database.models import UserRole
from app.database.repositories import _quota_decision

_PERIOD = timedelta(days=30)
_NOW = datetime(2026, 9, 15, tzinfo=UTC)


def test_admin_always_allowed_without_consuming_quota():
    allowed, period_start, used = _quota_decision(
        role=UserRole.ADMIN,
        subscription_expires_at=None,
        usage_period_start=_NOW,
        free_requests_used=999,
        free_limit=3,
        period=_PERIOD,
        now=_NOW,
    )
    assert allowed is True
    assert used == 999  # unchanged - admins never consume the counter


def test_active_subscription_allowed_without_consuming_quota():
    allowed, period_start, used = _quota_decision(
        role=UserRole.USER,
        subscription_expires_at=_NOW + timedelta(days=5),
        usage_period_start=_NOW,
        free_requests_used=3,
        free_limit=3,
        period=_PERIOD,
        now=_NOW,
    )
    assert allowed is True
    assert used == 3  # unchanged - a subscription bypasses the counter entirely


def test_expired_subscription_does_not_bypass_quota():
    allowed, _period_start, used = _quota_decision(
        role=UserRole.USER,
        subscription_expires_at=_NOW - timedelta(days=1),  # expired yesterday
        usage_period_start=_NOW,
        free_requests_used=3,
        free_limit=3,
        period=_PERIOD,
        now=_NOW,
    )
    assert allowed is False
    assert used == 3


def test_request_allowed_and_consumed_when_under_limit():
    allowed, period_start, used = _quota_decision(
        role=UserRole.USER,
        subscription_expires_at=None,
        usage_period_start=_NOW,
        free_requests_used=1,
        free_limit=3,
        period=_PERIOD,
        now=_NOW,
    )
    assert allowed is True
    assert used == 2
    assert period_start == _NOW  # untouched - period hasn't elapsed


def test_request_blocked_at_limit():
    allowed, _period_start, used = _quota_decision(
        role=UserRole.USER,
        subscription_expires_at=None,
        usage_period_start=_NOW,
        free_requests_used=3,
        free_limit=3,
        period=_PERIOD,
        now=_NOW,
    )
    assert allowed is False
    assert used == 3  # not incremented - the blocked request doesn't count


def test_quota_resets_after_period_elapses():
    # Regression: a user who exhausted their quota last month must get a
    # fresh allowance this month, not stay blocked forever.
    period_start = _NOW - timedelta(days=31)
    allowed, new_period_start, used = _quota_decision(
        role=UserRole.USER,
        subscription_expires_at=None,
        usage_period_start=period_start,
        free_requests_used=3,
        free_limit=3,
        period=_PERIOD,
        now=_NOW,
    )
    assert allowed is True
    assert used == 1  # counter reset to 0, then this request consumed one
    assert new_period_start == _NOW


def test_quota_does_not_reset_before_period_elapses():
    period_start = _NOW - timedelta(days=29)
    allowed, new_period_start, used = _quota_decision(
        role=UserRole.USER,
        subscription_expires_at=None,
        usage_period_start=period_start,
        free_requests_used=3,
        free_limit=3,
        period=_PERIOD,
        now=_NOW,
    )
    assert allowed is False
    assert used == 3
    assert new_period_start == period_start  # not reset yet
