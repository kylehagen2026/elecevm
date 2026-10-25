from datetime import date

import pytest

from elecevm import curves
from elecevm.calendar import WeekCalendar, WorkCalendar, parse_weekday


def test_week_numbering_saturday_weeks():
    cal = WeekCalendar(date(2026, 3, 9))  # Monday start, Saturday week-ending
    assert cal.week1_end == date(2026, 3, 14)
    assert cal.week_of(date(2026, 3, 1)) == 1          # pre-start cost lands in week 1
    assert cal.week_of(date(2026, 3, 14)) == 1
    assert cal.week_of(date(2026, 3, 15)) == 2         # Sunday starts week 2
    assert cal.week_of(date(2026, 3, 21)) == 2
    assert cal.week_of(date(2026, 3, 22)) == 3
    assert cal.week_start(2) == date(2026, 3, 15)
    assert cal.week_end(33) == date(2026, 10, 24)


def test_status_week_is_last_complete_week():
    cal = WeekCalendar(date(2026, 3, 9))
    assert cal.status_week(date(2026, 3, 13)) == 0     # week 1 not yet complete
    assert cal.status_week(date(2026, 3, 14)) == 1
    assert cal.status_week(date(2026, 3, 18)) == 1     # mid-week pull statuses the prior week
    assert cal.status_week(date(2026, 3, 21)) == 2


def test_parse_weekday():
    assert parse_weekday("saturday") == 5
    assert parse_weekday("Sat") == 5
    assert parse_weekday("thu") == 3
    assert parse_weekday(6) == 6
    with pytest.raises(ValueError):
        parse_weekday("xx")


def test_work_calendar_skips_sundays_and_holidays():
    cal = WorkCalendar(holidays=frozenset({date(2026, 5, 25)}))
    days = cal.workday_dates(date(2026, 5, 23), date(2026, 5, 27))  # Sat..Wed with Memorial Day
    assert days == [date(2026, 5, 23), date(2026, 5, 26), date(2026, 5, 27)]
    assert cal.add_workdays(date(2026, 5, 23), 3) == date(2026, 5, 27)
    assert cal.roll_forward(date(2026, 5, 24)) == date(2026, 5, 26)


def test_shapes_sum_to_one():
    for n in (1, 2, 7, 40):
        assert abs(sum(curves.bell(n)) - 1.0) < 1e-9
        assert abs(sum(curves.trapezoid(n)) - 1.0) < 1e-9
        assert abs(sum(curves.linear(n)) - 1.0) < 1e-9
    b = curves.bell(21)
    assert max(b) == b[10]  # symmetric peak in the middle


def test_level_delay_only_conserves_and_caps():
    series = [100, 300, 500, 50, 0]
    out = curves.level_delay_only(series, 200)
    assert abs(sum(out) - sum(series)) < 1e-9
    assert all(v <= 200 + 1e-9 for v in out)
    assert out[:3] == [100, 200, 200]          # excess pushed later, never earlier
    assert len(out) > len(series)


def test_level_by_group_conserves_each_group():
    weekly = {1: {"FE": 300.0, "TEL": 100.0}, 2: {"FE": 300.0, "TEL": 300.0}, 3: {"FE": 50.0}}
    out = curves.level_by_group(weekly, 250.0)
    for g in ("FE", "TEL"):
        before = sum(w.get(g, 0.0) for w in weekly.values())
        after = sum(w.get(g, 0.0) for w in out.values())
        assert abs(before - after) < 1e-9
    assert all(sum(w.values()) <= 250.0 + 1e-9 for w in out.values())


def test_taper_to_floor_conserves_and_respects_floor():
    out = curves.taper_to_floor(1000.0, 10, 300.0, 40.0)
    assert abs(sum(out) - 1000.0) < 1e-9
    assert all(v >= 40.0 - 1e-9 for v in out)
    assert out[0] >= out[1] >= out[2]
    flat = curves.taper_to_floor(100.0, 5, 300.0, 40.0)  # below the floor total: flat fallback
    assert abs(sum(flat) - 100.0) < 1e-9
