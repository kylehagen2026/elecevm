"""Payroll-week and working-day calendars (Recommended Practice §4.3).

Two calendars drive everything in the engine:

* :class:`WeekCalendar` numbers *payroll weeks* from the project start.  Week 1
  is the week containing the start date and absorbs any cost dated before it
  (pre-NTP cost).  Weeks are named by their week-ending date (Saturday by
  default, i.e. Sunday–Saturday timesheet weeks).  The *status week* is the last
  complete payroll week on or before the data date: a mid-week data pull
  statuses to the previous complete week, never the week in progress.
* :class:`WorkCalendar` counts working days for schedule durations and spreads
  activity hours across the days an activity is actually open.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import FrozenSet, List, Union

WEEKDAY_NAMES = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def parse_weekday(value: Union[str, int]) -> int:
    """Accept 0–6 (Monday = 0), full weekday names or 3-letter abbreviations."""
    if isinstance(value, int):
        if 0 <= value <= 6:
            return value
        raise ValueError(f"weekday index out of range: {value}")
    key = str(value).strip().lower()
    if len(key) < 3:
        raise ValueError(f"unknown weekday: {value!r}")
    for name, idx in WEEKDAY_NAMES.items():
        if key == name or name.startswith(key[:3]):
            return idx
    raise ValueError(f"unknown weekday: {value!r}")


@dataclass(frozen=True)
class WeekCalendar:
    """Payroll-week numbering anchored on the project start date."""

    start: date
    week_ending: int = 5  # Saturday

    @property
    def week1_end(self) -> date:
        """Week-ending date of week 1 (the first week-ending day on/after start)."""
        return self.start + timedelta(days=(self.week_ending - self.start.weekday()) % 7)

    def week_end(self, week: int) -> date:
        return self.week1_end + timedelta(weeks=week - 1)

    def week_start(self, week: int) -> date:
        return self.week_end(week) - timedelta(days=6)

    def week_of(self, d: date) -> int:
        """Payroll week containing ``d``; dates before the start fall in week 1."""
        if d <= self.week1_end:
            return 1
        return ((d - self.week1_end).days + 6) // 7 + 1

    def status_week(self, data_date: date) -> int:
        """Last complete payroll week on or before ``data_date`` (0 if none)."""
        if data_date < self.week1_end:
            return 0
        return (data_date - self.week1_end).days // 7 + 1

    def weeks_in(self, start: date, finish: date) -> List[int]:
        return list(range(self.week_of(start), self.week_of(finish) + 1))

    def label(self, week: int) -> str:
        return f"Wk {week} (w/e {self.week_end(week).isoformat()})"


@dataclass(frozen=True)
class WorkCalendar:
    """Working-day calendar for schedule durations (default Monday–Saturday)."""

    workdays: FrozenSet[int] = frozenset({0, 1, 2, 3, 4, 5})
    holidays: FrozenSet[date] = frozenset()

    def is_workday(self, d: date) -> bool:
        return d.weekday() in self.workdays and d not in self.holidays

    def workday_dates(self, start: date, finish: date) -> List[date]:
        """Every working day from ``start`` through ``finish`` inclusive."""
        if finish < start:
            return []
        out: List[date] = []
        d = start
        while d <= finish:
            if self.is_workday(d):
                out.append(d)
            d += timedelta(days=1)
        return out

    def workdays_between(self, start: date, finish: date) -> int:
        return len(self.workday_dates(start, finish))

    def roll_forward(self, d: date) -> date:
        while not self.is_workday(d):
            d += timedelta(days=1)
        return d

    def roll_back(self, d: date) -> date:
        while not self.is_workday(d):
            d -= timedelta(days=1)
        return d

    def add_workdays(self, d: date, n: int) -> date:
        """Finish date of an ``n``-workday activity starting on ``d`` (n >= 1)."""
        d = self.roll_forward(d)
        if n <= 1:
            return d
        count = 1
        while count < n:
            d += timedelta(days=1)
            if self.is_workday(d):
                count += 1
        return d
