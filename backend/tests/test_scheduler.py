from datetime import datetime, timezone

from app.scheduler import seconds_until


def at(h, m=0, s=0):
    return datetime(2026, 10, 7, h, m, s, tzinfo=timezone.utc)


def test_later_today():
    assert seconds_until(3, at(1)) == 2 * 3600


def test_already_past_waits_for_tomorrow():
    assert seconds_until(3, at(4)) == 23 * 3600


def test_exactly_on_the_hour_waits_a_full_day():
    assert seconds_until(3, at(3)) == 24 * 3600


def test_never_negative_or_zero():
    for h in range(24):
        assert 0 < seconds_until(h, at(h, 59, 59)) <= 24 * 3600
