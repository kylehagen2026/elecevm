"""Cost-loaded schedule, allocation and the time-phased baseline (RP §5).

The baseline is built in four steps:

1. **Allocate** each discipline's budget labor hours to its schedule activities,
   by resource-loaded budget hours when the schedule carries them, otherwise by
   a *score* (original duration × hours/day × area weight × activity factor).
   The allocation ties to the discipline budget exactly (RP §5.2).
2. **Spread** each activity's hours evenly over its working days and sum them
   into payroll weeks (RP §5.3).
3. **Level** (optional) the total labor curve under a crew cap, delay-only (RP §5.4).
4. **Price** the weekly hours at the effective discipline rate and phase
   material, subcontract, equipment and other budgets on the configured
   profile so that terminal PV equals BAC (RP §5.5).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from . import curves
from .calendar import WeekCalendar, WorkCalendar
from .config import Project
from .models import Activity, BudgetKey, CostType

ALLOCATION_TOLERANCE = 1e-6


def activity_score(a: Activity, work_cal: WorkCalendar) -> Tuple[float, str]:
    """Return (score, basis) for an activity: budget hours if loaded, else duration-based."""
    if a.budget_hours is not None and a.budget_hours > 0:
        return float(a.budget_hours), "budget_hours"
    od = a.original_duration if a.original_duration else work_cal.workdays_between(a.start, a.finish)
    od = max(od, 1)
    return od * a.hours_per_day * a.area_weight * a.activity_factor, "score"


def allocate_hours(activities: Iterable[Activity], bac_hours: Dict[str, float],
                   work_cal: WorkCalendar) -> Dict[str, float]:
    """Allocate discipline budget hours to activities; ties exactly per discipline."""
    acts = list(activities)
    by_disc: Dict[str, List[Activity]] = {}
    for a in acts:
        by_disc.setdefault(a.discipline, []).append(a)

    allocation: Dict[str, float] = {}
    for disc, group in by_disc.items():
        target = float(bac_hours.get(disc, 0.0))
        scored = {a.id: activity_score(a, work_cal) for a in group}
        bases = {basis for _, basis in scored.values()}
        if len(bases) > 1:
            unloaded = sorted(aid for aid, (_, basis) in scored.items() if basis == "score")
            raise ValueError(
                f"discipline {disc} mixes resource-loaded and unloaded activities; "
                f"activities with no budget hours: {unloaded} (RP §5.1: a data error, not a zero allocation)")
        scores = {aid: s for aid, (s, _) in scored.items()}
        total_score = sum(scores.values())
        if total_score <= 0:
            for a in group:
                allocation[a.id] = 0.0
            continue
        running = 0.0
        for a in group:
            allocation[a.id] = target * scores[a.id] / total_score
            running += allocation[a.id]
        # absorb floating-point residual on the largest activity so the tie is exact
        residual = target - running
        if group and abs(residual) > 0:
            biggest = max(group, key=lambda x: scores[x.id])
            allocation[biggest.id] += residual
    return allocation


def spread_hours(hours: float, start: date, finish: date, work_cal: WorkCalendar,
                 week_cal: WeekCalendar) -> Dict[int, float]:
    """Spread ``hours`` evenly over the working days in [start, finish], by payroll week."""
    days = work_cal.workday_dates(start, finish)
    out: Dict[int, float] = {}
    if hours == 0:
        return out
    if not days:
        out[week_cal.week_of(start)] = hours
        return out
    per_day = hours / len(days)
    for d in days:
        w = week_cal.week_of(d)
        out[w] = out.get(w, 0.0) + per_day
    # exact conservation
    residual = hours - sum(out.values())
    if residual:
        last = max(out)
        out[last] += residual
    return out


@dataclass
class Baseline:
    """A versioned time-phased plan: allocation, weekly hours and dollars, BAC."""

    version: int
    created: date
    note: str
    basis: str
    allocation: Dict[str, float]
    allocation_basis: Dict[str, str]
    activity_weeks: Dict[str, Dict[int, float]]
    hours: Dict[int, Dict[str, float]]                 # week -> discipline -> labor hours
    dollars: Dict[int, Dict[BudgetKey, float]]         # week -> (disc, ct) -> $
    bac: Dict[BudgetKey, float]
    bac_hours: Dict[str, float]
    rates: Dict[str, float]
    leveled: bool = False
    bcr_log: List[dict] = field(default_factory=list)
    unleveled_hours: Dict[int, Dict[str, float]] = field(default_factory=dict)  # schedule demand before leveling

    # -- shape -----------------------------------------------------------
    @property
    def weeks(self) -> int:
        candidates = [w for w, v in self.hours.items() if sum(v.values()) > 0]
        candidates += [w for w, v in self.dollars.items() if sum(v.values()) > 0]
        return max(candidates) if candidates else 0

    @property
    def disciplines(self) -> List[str]:
        seen: List[str] = []
        for d in list(self.bac_hours) + [k[0] for k in self.bac]:
            if d not in seen:
                seen.append(d)
        return seen

    # -- weekly values ---------------------------------------------------
    def weekly_hours(self, week: int, discipline: Optional[str] = None) -> float:
        row = self.hours.get(week, {})
        if discipline is None:
            return sum(row.values())
        return row.get(discipline, 0.0)

    def weekly_demand(self, week: int, discipline: Optional[str] = None) -> float:
        """Unleveled schedule demand for the week (equals weekly_hours when not leveled)."""
        table = self.unleveled_hours if self.leveled and self.unleveled_hours else self.hours
        row = table.get(week, {})
        return sum(row.values()) if discipline is None else row.get(discipline, 0.0)

    def weekly_dollars(self, week: int, discipline: Optional[str] = None,
                       cost_type: Optional[CostType] = None) -> float:
        total = 0.0
        for (disc, ct), amount in self.dollars.get(week, {}).items():
            if discipline is not None and disc != discipline:
                continue
            if cost_type is not None and ct != cost_type.value:
                continue
            total += amount
        return total

    # -- cumulative values -----------------------------------------------
    def pv(self, through: int, discipline: Optional[str] = None,
           cost_type: Optional[CostType] = None) -> float:
        return sum(self.weekly_dollars(w, discipline, cost_type) for w in range(1, through + 1))

    def pv_hours(self, through: int, discipline: Optional[str] = None) -> float:
        return sum(self.weekly_hours(w, discipline) for w in range(1, through + 1))

    def activity_pv_fraction(self, activity_id: str, through: int) -> float:
        total = self.allocation.get(activity_id, 0.0)
        if total <= 0:
            return 0.0
        done = sum(h for w, h in self.activity_weeks.get(activity_id, {}).items() if w <= through)
        return min(max(done / total, 0.0), 1.0)

    @property
    def terminal_pv(self) -> float:
        return self.pv(self.weeks)

    @property
    def total_bac(self) -> float:
        return sum(self.bac.values())

    @property
    def total_bac_hours(self) -> float:
        return sum(self.bac_hours.values())

    # -- persistence -----------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "created": self.created.isoformat(),
            "note": self.note,
            "basis": self.basis,
            "leveled": self.leveled,
            "allocation": self.allocation,
            "allocation_basis": self.allocation_basis,
            "activity_weeks": {k: {str(w): h for w, h in v.items()} for k, v in self.activity_weeks.items()},
            "hours": {str(w): v for w, v in self.hours.items()},
            "dollars": {str(w): {f"{d}:{ct}": amt for (d, ct), amt in v.items()} for w, v in self.dollars.items()},
            "bac": {f"{d}:{ct}": amt for (d, ct), amt in self.bac.items()},
            "bac_hours": self.bac_hours,
            "rates": self.rates,
            "bcr_log": self.bcr_log,
            "unleveled_hours": {str(w): v for w, v in self.unleveled_hours.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Baseline":
        def split(key: str) -> BudgetKey:
            d, ct = key.rsplit(":", 1)
            return (d, ct)

        return cls(
            version=int(data["version"]),
            created=date.fromisoformat(data["created"]),
            note=str(data.get("note", "")),
            basis=str(data.get("basis", "estimated")),
            allocation={k: float(v) for k, v in data["allocation"].items()},
            allocation_basis={k: str(v) for k, v in data.get("allocation_basis", {}).items()},
            activity_weeks={k: {int(w): float(h) for w, h in v.items()} for k, v in data["activity_weeks"].items()},
            hours={int(w): {d: float(h) for d, h in v.items()} for w, v in data["hours"].items()},
            dollars={int(w): {split(k): float(a) for k, a in v.items()} for w, v in data["dollars"].items()},
            bac={split(k): float(v) for k, v in data["bac"].items()},
            bac_hours={k: float(v) for k, v in data["bac_hours"].items()},
            rates={k: float(v) for k, v in data.get("rates", {}).items()},
            leveled=bool(data.get("leveled", False)),
            bcr_log=list(data.get("bcr_log", [])),
            unleveled_hours={int(w): {d: float(h) for d, h in v.items()} for w, v in data.get("unleveled_hours", {}).items()},
        )

    def save(self, path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path) -> "Baseline":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def _phase_dollars(total: float, weights_by_week: Dict[int, float]) -> Dict[int, float]:
    if total == 0 or not weights_by_week:
        return {}
    weeks = sorted(weights_by_week)
    values = curves.scale_to_total([weights_by_week[w] for w in weeks], total)
    return {w: v for w, v in zip(weeks, values) if v != 0}


def build_baseline(project: Project, activities: Iterable[Activity], version: int = 1,
                   note: str = "Initial baseline", created: Optional[date] = None,
                   level: Optional[bool] = None) -> Baseline:
    """Build the time-phased baseline for ``project`` from its schedule activities."""
    acts = list(activities)
    if not acts:
        raise ValueError("no activities to build a baseline from")
    budget = project.budget
    work_cal, week_cal = project.work_cal, project.week_cal

    discs_with_acts = sorted({a.discipline for a in acts})
    bac_hours = {d: budget.bac_hours(d) for d in discs_with_acts}
    missing = [d for d in budget.disciplines() if d not in discs_with_acts and (budget.bac(d) > 0 or budget.bac_hours(d) > 0)]
    if missing:
        raise ValueError(f"budget carries disciplines with no schedule activities to phase against: {missing}")

    allocation = allocate_hours(acts, bac_hours, work_cal)
    allocation_basis = {a.id: activity_score(a, work_cal)[1] for a in acts}

    activity_weeks: Dict[str, Dict[int, float]] = {}
    hours: Dict[int, Dict[str, float]] = {}
    for a in acts:
        weekly = spread_hours(allocation[a.id], a.start, a.finish, work_cal, week_cal)
        activity_weeks[a.id] = weekly
        for w, h in weekly.items():
            hours.setdefault(w, {})
            hours[w][a.discipline] = hours[w].get(a.discipline, 0.0) + h

    leveled = False
    unleveled: Dict[int, Dict[str, float]] = {}
    do_level = project.crew_cap_hours is not None if level is None else level
    if do_level and project.crew_cap_hours:
        unleveled = {w: dict(v) for w, v in hours.items()}
        # level every activity's own curve under the shared cap, then rebuild the discipline table
        by_activity: Dict[int, Dict[str, float]] = {}
        for aid, weekly in activity_weeks.items():
            for w, h in weekly.items():
                by_activity.setdefault(w, {})[aid] = h
        leveled_acts = curves.level_by_group(by_activity, project.crew_cap_hours)
        disc_of = {a.id: a.discipline for a in acts}
        activity_weeks = {aid: {} for aid in activity_weeks}
        hours = {}
        for w, row in leveled_acts.items():
            for aid, h in row.items():
                activity_weeks[aid][w] = h
                hours.setdefault(w, {})
                hours[w][disc_of[aid]] = hours[w].get(disc_of[aid], 0.0) + h
        leveled = True

    rates = {d: project.rate(d) for d in discs_with_acts}
    dollars: Dict[int, Dict[BudgetKey, float]] = {}
    bac: Dict[BudgetKey, float] = {}

    for d in discs_with_acts:
        # labor $ = hours × effective rate (ties to budget labor $ when both are budgeted)
        labor_bac = budget.bac(d, CostType.LABOR)
        if labor_bac <= 0 and bac_hours[d] > 0:
            labor_bac = bac_hours[d] * rates[d]
        if labor_bac > 0:
            weights = {w: hours[w].get(d, 0.0) for w in hours if hours[w].get(d, 0.0) > 0}
            for w, amt in _phase_dollars(labor_bac, weights).items():
                dollars.setdefault(w, {})[(d, CostType.LABOR.value)] = amt
            bac[(d, CostType.LABOR.value)] = labor_bac

        for ct in (CostType.MATERIAL, CostType.SUBCONTRACT, CostType.EQUIPMENT, CostType.OTHER):
            total = budget.bac(d, ct)
            if total <= 0:
                continue
            bac[(d, ct.value)] = total
            span = [w for w in sorted(hours) if hours[w].get(d, 0.0) > 0]
            if not span:
                continue
            if project.material_phasing == "follow_labor":
                weights = {w: hours[w][d] for w in span}
            else:
                first, last = span[0], span[-1]
                n = last - first + 1
                shape = curves.bell(n) if project.material_phasing == "bell" else curves.linear(n)
                weights = {first + i: shape[i] for i in range(n)}
            for w, amt in _phase_dollars(total, weights).items():
                dollars.setdefault(w, {})[(d, ct.value)] = amt

    return Baseline(
        version=version,
        created=created or date.today(),
        note=note,
        basis=budget.basis,
        allocation=allocation,
        allocation_basis=allocation_basis,
        activity_weeks=activity_weeks,
        hours=hours,
        dollars=dollars,
        bac=bac,
        bac_hours=bac_hours,
        rates=rates,
        leveled=leveled,
        bcr_log=[{"version": version, "date": (created or date.today()).isoformat(), "note": note}],
        unleveled_hours=unleveled,
    )


def forecast_remaining(project: Project, baseline: Baseline, activities: Iterable[Activity],
                       earned_hours: Dict[str, float], status_week: int,
                       etc_hours: Optional[Dict[str, float]] = None) -> Dict[int, Dict[str, float]]:
    """Phase the estimate-to-complete hours after the status week (RP §8.4).

    Each activity's remaining hours (allocation − earned, or a supplied ETC by
    discipline shared by remaining allocation) are spread over the working days
    from the week after status through the activity's current finish.  Finished
    or exhausted activities contribute nothing; activities whose finish is
    already past are pushed into the week after status.
    """
    week_cal, work_cal = project.week_cal, project.work_cal
    cutoff = week_cal.week_end(status_week)
    acts = list(activities)
    remaining_by_act = {a.id: max(baseline.allocation.get(a.id, 0.0) - earned_hours.get(a.id, 0.0), 0.0) for a in acts}
    if etc_hours:
        by_disc: Dict[str, float] = {}
        for a in acts:
            by_disc[a.discipline] = by_disc.get(a.discipline, 0.0) + remaining_by_act[a.id]
        for a in acts:
            share = by_disc.get(a.discipline, 0.0)
            if share > 0 and a.discipline in etc_hours:
                remaining_by_act[a.id] = etc_hours[a.discipline] * remaining_by_act[a.id] / share
    out: Dict[int, Dict[str, float]] = {}
    for a in acts:
        rem = remaining_by_act[a.id]
        if rem <= 0:
            continue
        # a schedule-complete activity with unearned hours still owes them: next week
        start = max(a.current_start, cutoff + timedelta(days=1))
        finish = max(a.current_finish, start)
        weekly = spread_hours(rem, start, finish, work_cal, week_cal)
        for w, h in weekly.items():
            out.setdefault(w, {})
            out[w][a.discipline] = out[w].get(a.discipline, 0.0) + h
    return out
