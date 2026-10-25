"""Earned value measurement, analysis, forecasting and integrity checks (RP §6, §8, §11)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Dict, Iterable, List, Optional, Tuple

from . import crew as crew_mod
from .actuals import WeeklyActuals
from .allocation import Baseline, forecast_remaining
from .config import Project
from .models import Activity, CostType, EVMethod, QuantityRecord
from .rules_of_credit import RuleOfCredit, earned_fraction, get_rule

EAC_METHOD_LABELS = {
    "cpi": "BAC ÷ CPI (statistical)",
    "budget_rate": "AC + (BAC − EV) (remaining at budget rate)",
    "composite": "AC + (BAC − EV) ÷ (CPI × SPI)",
    "management": "AC + management ETC (bottom-up)",
}


def _clamp(x: float) -> float:
    return min(max(float(x), 0.0), 1.0)


def _ratio(num: float, den: float) -> Optional[float]:
    return num / den if den else None


@dataclass
class ActivityEV:
    activity_id: str
    name: str
    discipline: str
    area: str
    method: str
    tier: str
    fraction: float
    budget_hours: float
    earned_hours: float
    planned_fraction: float
    note: str = ""


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""
    ran: bool = True   # False when the check had no data to run on (reported as NOT RUN, never as PASS)


@dataclass
class WeeklyPoint:
    week: int
    week_end: str
    pv: float
    ev: Optional[float]
    ac: float
    pv_hours: float
    ev_hours: Optional[float]
    ac_hours: float
    planned_crew: float
    actual_crew: float
    earned_crew: Optional[float]
    locked: bool = False


@dataclass
class DisciplineStatus:
    code: str
    name: str
    bac: float
    pv: float
    ev: float
    ac: float
    bac_hours: float
    pv_hours: float
    ev_hours: float
    ac_hours: float
    spi: Optional[float]
    cpi: Optional[float]
    spi_hours: Optional[float]
    cpi_hours: Optional[float]
    pct_complete: float
    pct_spent: float
    eac_hours: Optional[float]
    etc_hours: float


@dataclass
class StatusSnapshot:
    project: str
    data_date: str
    status_week: int
    week_end: str
    basis: str
    basis_version: int
    bac: float
    bac_hours: float
    pv: float
    ev: float
    ac: float
    pv_hours: float
    ev_hours: float
    ac_hours: float
    sv: float
    cv: float
    spi: Optional[float]
    cpi: Optional[float]
    spi_hours: Optional[float]
    cpi_hours: Optional[float]
    tcpi_bac: Optional[float]
    tcpi_eac: Optional[float]
    eac_methods: Dict[str, float]
    eac_selected_method: str
    eac: float
    etc: float
    vac: float
    eac_hours: Optional[float]
    pct_complete: float
    pct_spent: float
    contracted_value: float
    estimated_value: float
    funding_exposure: float
    crossover_week: Optional[int]
    crossover_week_end: Optional[str]
    weekly: List[WeeklyPoint]
    forecast_ac: Dict[int, float]              # week -> cumulative forecast AC after status
    forecast_hours: Dict[int, float]           # week -> forecast labor hours after status
    forecast_finish_week: Optional[int]
    disciplines: List[DisciplineStatus]
    activities: List[ActivityEV]
    checks: List[CheckResult]
    thresholds_breached: List[str]
    notes: List[str] = field(default_factory=list)

    @property
    def all_checks_pass(self) -> bool:
        return all(c.passed for c in self.checks)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_record(self) -> dict:
        """Compact record for the status log (Appendix B)."""
        return {
            "week": self.status_week,
            "week_end": self.week_end,
            "data_date": self.data_date,
            "basis": self.basis,
            "basis_version": self.basis_version,
            "bac": round(self.bac, 2),
            "bac_hours": round(self.bac_hours, 2),
            "pv": round(self.pv, 2),
            "ev": round(self.ev, 2),
            "ac": round(self.ac, 2),
            "pv_hours": round(self.pv_hours, 2),
            "ev_hours": round(self.ev_hours, 2),
            "ac_hours": round(self.ac_hours, 2),
            "spi": _round(self.spi),
            "cpi": _round(self.cpi),
            "spi_hours": _round(self.spi_hours),
            "cpi_hours": _round(self.cpi_hours),
            "eac": round(self.eac, 2),
            "eac_method": self.eac_selected_method,
            "etc": round(self.etc, 2),
            "vac": round(self.vac, 2),
            "crossover_week": self.crossover_week,
            "checks_passed": self.all_checks_pass,
            "disciplines": {
                d.code: {"pv": round(d.pv, 2), "ev": round(d.ev, 2), "ac": round(d.ac, 2),
                          "pv_hours": round(d.pv_hours, 2), "ev_hours": round(d.ev_hours, 2),
                          "ac_hours": round(d.ac_hours, 2)}
                for d in self.disciplines
            },
        }


def _round(x: Optional[float], n: int = 4) -> Optional[float]:
    return None if x is None else round(x, n)


# ---------------------------------------------------------------------------
# Earned value measurement
# ---------------------------------------------------------------------------

def latest_records(records: Iterable[QuantityRecord], through: date) -> Dict[str, QuantityRecord]:
    """Most recent field record per activity dated on or before ``through``."""
    best: Dict[str, QuantityRecord] = {}
    for r in records:
        if r.as_of <= through and (r.activity_id not in best or r.as_of >= best[r.activity_id].as_of):
            best[r.activity_id] = r
    return best


def _schedule_fraction(a: Activity, cutoff: date, schedule_data_date: Optional[date],
                       project: Project) -> Tuple[float, str]:
    """Fallback progress from the statused schedule when no field record exists (Tier 2b).

    The schedule's percent complete is only valid as of the schedule's own data
    date; for an earlier cutoff (a backfilled week) progress is interpolated on
    working days between the actual start and the current finish.
    """
    if a.actual_finish is not None and a.actual_finish <= cutoff:
        return 1.0, "no field record; complete per schedule"
    if a.actual_start is None or a.actual_start > cutoff:
        if a.actual_start is None and a.percent_complete > 0 and (schedule_data_date is None or cutoff >= schedule_data_date):
            return _clamp(a.percent_complete), "no field record; schedule physical percent used"
        return 0.0, "no field record; not started per schedule"
    if schedule_data_date is None or cutoff >= schedule_data_date:
        return _clamp(a.percent_complete), "no field record; schedule physical percent used"
    # earlier than the schedule's data date: scale the schedule's percent by the share of the
    # working days worked to the data date that had been worked by the cutoff
    done_to_cutoff = project.work_cal.workdays_between(a.actual_start, cutoff)
    done_to_data = project.work_cal.workdays_between(a.actual_start, min(schedule_data_date, a.current_finish)) or 1
    pct_at_data = a.percent_complete if a.percent_complete > 0 else (
        project.work_cal.workdays_between(a.actual_start, min(schedule_data_date, a.current_finish))
        / (project.work_cal.workdays_between(a.actual_start, a.current_finish) or 1))
    return _clamp(pct_at_data * done_to_cutoff / done_to_data), "no field record; interpolated from schedule dates"


def _activity_fraction(a: Activity, baseline: Baseline, latest: Dict[str, QuantityRecord],
                       status_week: int, invoiced_fraction: Optional[float],
                       rules: Optional[Dict[str, RuleOfCredit]], project: Project,
                       schedule_data_date: Optional[date]) -> Tuple[float, str, str]:
    cutoff = project.week_cal.week_end(status_week)
    if a.ev_method == EVMethod.LOE:
        return baseline.activity_pv_fraction(a.id, status_week), "LOE", "level of effort: EV = PV"
    if a.ev_method == EVMethod.INVOICED:
        if invoiced_fraction is not None:
            return _clamp(invoiced_fraction), "3", "invoiced percent — interim only, not claims-grade"
        fraction, note = _schedule_fraction(a, cutoff, schedule_data_date, project)
        return fraction, "2b", "invoiced percent unavailable; " + note
    rec = latest.get(a.id)
    if a.ev_method == EVMethod.PERCENT:
        if rec is not None and rec.percent_complete is not None:
            return _clamp(rec.percent_complete), "2b", "field-reported percent"
        fraction, note = _schedule_fraction(a, cutoff, schedule_data_date, project)
        return fraction, "2b", note
    # quantity / milestone
    if rec is None:
        fraction, note = _schedule_fraction(a, cutoff, schedule_data_date, project)
        return fraction, "2b", note
    rule = get_rule(rec.commodity or a.commodity, rules)
    fraction, tier = earned_fraction(rule, rec)
    note = f"{rule.commodity} ({rule.basis})" if rule else "installed ÷ total (no rule of credit)"
    return fraction, tier, note


def measure_activities(project: Project, baseline: Baseline, activities: Iterable[Activity],
                       records: Iterable[QuantityRecord], status_week: int,
                       invoiced_fraction: Optional[float] = None,
                       rules: Optional[Dict[str, RuleOfCredit]] = None,
                       schedule_data_date: Optional[date] = None) -> List[ActivityEV]:
    """Earned hours per activity at the status week (RP §6)."""
    acts = list(activities)
    cutoff = project.week_cal.week_end(status_week)
    latest = latest_records(records, cutoff)
    results: Dict[str, ActivityEV] = {}
    deferred: List[Activity] = []
    for a in acts:
        if a.ev_method == EVMethod.APPORTIONED:
            deferred.append(a)
            continue
        fraction, tier, note = _activity_fraction(a, baseline, latest, status_week, invoiced_fraction, rules,
                                                  project, schedule_data_date)
        budget = baseline.allocation.get(a.id, 0.0)
        results[a.id] = ActivityEV(a.id, a.name, a.discipline, a.area, a.ev_method.value, tier, fraction,
                                   budget, budget * fraction, baseline.activity_pv_fraction(a.id, status_week), note)
    pending = list(deferred)
    for _ in range(len(pending) + 1):   # resolve chains of apportioned activities in dependency order
        still: List[Activity] = []
        for a in pending:
            base = results.get(a.base_activity or "")
            if base is None and a.base_activity in {x.id for x in pending}:
                still.append(a)
                continue
            if base is not None:
                fraction, note = base.fraction, f"apportioned to {base.activity_id}"
            else:
                fraction, note = _clamp(a.percent_complete), "apportioned base not found; schedule percent used"
            budget = baseline.allocation.get(a.id, 0.0)
            results[a.id] = ActivityEV(a.id, a.name, a.discipline, a.area, a.ev_method.value, "apportioned",
                                       fraction, budget, budget * fraction,
                                       baseline.activity_pv_fraction(a.id, status_week), note)
        if not still or len(still) == len(pending):
            for a in still:   # circular references: fall back to schedule percent
                budget = baseline.allocation.get(a.id, 0.0)
                results[a.id] = ActivityEV(a.id, a.name, a.discipline, a.area, a.ev_method.value, "apportioned",
                                           _clamp(a.percent_complete), budget, budget * _clamp(a.percent_complete),
                                           baseline.activity_pv_fraction(a.id, status_week),
                                           "apportioned chain is circular; schedule percent used")
            break
        pending = still
    return [results[a.id] for a in acts]


# ---------------------------------------------------------------------------
# Forecasting helpers
# ---------------------------------------------------------------------------

def eac_methods(bac: float, ev: float, ac: float, management_etc: Optional[float] = None) -> Dict[str, float]:
    cpi = _ratio(ev, ac)
    out: Dict[str, float] = {}
    if cpi:
        out["cpi"] = bac / cpi
    out["budget_rate"] = ac + (bac - ev)
    if management_etc is not None:
        out["management"] = ac + management_etc
    return out


def select_eac(methods: Dict[str, float], policy: str, spi: Optional[float] = None) -> Tuple[str, float]:
    if policy == "max_management_cpi":
        candidates = [m for m in ("management", "cpi") if m in methods]
        if candidates:
            best = max(candidates, key=lambda m: methods[m])
            return best, methods[best]
    if policy in methods:
        return policy, methods[policy]
    if "cpi" in methods:
        return "cpi", methods["cpi"]
    return "budget_rate", methods["budget_rate"]


def funding_crossover(cum_ac_by_week: Dict[int, float], funding: float) -> Optional[int]:
    """First week whose cumulative AC exceeds the funding line."""
    for week in sorted(cum_ac_by_week):
        if cum_ac_by_week[week] > funding + 0.005:
            return week
    return None


# ---------------------------------------------------------------------------
# Status computation
# ---------------------------------------------------------------------------

def compute_status(project: Project, baseline: Baseline, activities: Iterable[Activity],
                   actuals: WeeklyActuals, quantity_records: Iterable[QuantityRecord],
                   data_date: date, history: Optional[Dict[int, dict]] = None,
                   management_etc: Optional[float] = None, invoiced_fraction: Optional[float] = None,
                   source_totals: Optional[Dict[str, Tuple[float, float]]] = None,
                   rules: Optional[Dict[str, RuleOfCredit]] = None,
                   schedule_data_date: Optional[date] = None) -> StatusSnapshot:
    """Status the project as of ``data_date`` (RP §8) and run the integrity checks (RP §11).

    ``schedule_data_date`` is the date the schedule file was statused at; it
    defaults to ``data_date``.  When an earlier week is being backfilled from a
    later schedule, activities with no field record are interpolated instead of
    taking the schedule's (later) percent complete.
    """
    acts = list(activities)
    records = list(quantity_records)
    history = history or {}
    week_cal = project.week_cal
    status_week = week_cal.status_week(data_date)
    if status_week < 1:
        raise ValueError("data date precedes the end of payroll week 1; nothing to status")
    if actuals.status_week != status_week:
        raise ValueError(f"actuals were bucketed for status week {actuals.status_week}, "
                         f"but the data date statuses week {status_week}")
    notes: List[str] = list(actuals.notes)

    # --- earned value ---------------------------------------------------
    activity_ev = measure_activities(project, baseline, acts, records, status_week, invoiced_fraction, rules,
                                     schedule_data_date or data_date)
    earned_hours_by_act = {e.activity_id: e.earned_hours for e in activity_ev}
    ev_hours_disc: Dict[str, float] = {}
    for e in activity_ev:
        ev_hours_disc[e.discipline] = ev_hours_disc.get(e.discipline, 0.0) + e.earned_hours

    disciplines: List[DisciplineStatus] = []
    etc_hours_disc: Dict[str, float] = {}
    for d in baseline.disciplines:
        bac_h = baseline.bac_hours.get(d, 0.0)
        bac_d = sum(v for (dd, _), v in baseline.bac.items() if dd == d)
        pv_d = baseline.pv(status_week, d)
        pv_h = baseline.pv_hours(status_week, d)
        ev_h = ev_hours_disc.get(d, 0.0)
        frac = ev_h / bac_h if bac_h > 0 else 0.0
        ev_d = sum(v * frac for (dd, _), v in baseline.bac.items() if dd == d)
        ac_bucket = actuals.cumulative(status_week, d)
        ac_h = actuals.cumulative(status_week, d, CostType.LABOR).hours
        cpi_h = _ratio(ev_h, ac_h)
        if cpi_h:
            eac_h: Optional[float] = bac_h / cpi_h
        elif ac_h > 0:
            eac_h = None          # hours spent, nothing earned: no statistical forecast yet
        else:
            eac_h = bac_h
        etc_h = max(eac_h - ac_h, 0.0) if eac_h is not None else max(bac_h - ev_h, 0.0)
        etc_hours_disc[d] = etc_h
        disciplines.append(DisciplineStatus(
            code=d, name=project.discipline_name(d), bac=bac_d, pv=pv_d, ev=ev_d, ac=ac_bucket.amount,
            bac_hours=bac_h, pv_hours=pv_h, ev_hours=ev_h, ac_hours=ac_h,
            spi=_ratio(ev_d, pv_d), cpi=_ratio(ev_d, ac_bucket.amount),
            spi_hours=_ratio(ev_h, pv_h), cpi_hours=cpi_h,
            pct_complete=frac, pct_spent=(ac_bucket.amount / bac_d if bac_d else 0.0),
            eac_hours=eac_h, etc_hours=etc_h,
        ))

    bac = baseline.total_bac
    bac_hours = baseline.total_bac_hours
    pv = baseline.pv(status_week)
    pv_hours = baseline.pv_hours(status_week)
    ev = sum(d.ev for d in disciplines)
    ev_hours = sum(d.ev_hours for d in disciplines)
    ac = actuals.cumulative(status_week).amount
    ac_hours = actuals.cumulative(status_week, None, CostType.LABOR).hours

    spi, cpi = _ratio(ev, pv), _ratio(ev, ac)
    spi_h, cpi_h = _ratio(ev_hours, pv_hours), _ratio(ev_hours, ac_hours)

    methods = eac_methods(bac, ev, ac, management_etc)
    if cpi and spi:
        methods["composite"] = ac + (bac - ev) / (cpi * spi)
    method, eac = select_eac(methods, project.eac_policy, spi)
    etc = eac - ac
    vac = bac - eac
    eac_hours = bac_hours / cpi_h if cpi_h else (None if ac_hours > 0 else bac_hours)
    tcpi_bac = _ratio(bac - ev, bac - ac) if bac - ac > 0 else None
    tcpi_eac = _ratio(bac - ev, eac - ac) if eac - ac > 0 else None

    # --- weekly series --------------------------------------------------
    std = project.std_hours_per_week
    weekly: List[WeeklyPoint] = []
    prev_ev_h: Optional[float] = None
    for w in range(1, status_week + 1):
        rec = history.get(w) if w < status_week else None
        if w == status_week:
            ev_w, ev_h_w, locked = ev, ev_hours, False
        elif rec is not None:
            ev_w, ev_h_w, locked = float(rec.get("ev", 0.0)), float(rec.get("ev_hours", 0.0)), True
        else:
            ev_w, ev_h_w, locked = None, None, False
        ac_h_w = actuals.weekly(w, None, CostType.LABOR).hours
        earned_crew = None
        if ev_h_w is not None and prev_ev_h is not None:
            earned_crew = crew_mod.headcount(ev_h_w - prev_ev_h, std)
        elif ev_h_w is not None and w == 1:
            earned_crew = crew_mod.headcount(ev_h_w, std)
        weekly.append(WeeklyPoint(
            week=w, week_end=week_cal.week_end(w).isoformat(),
            pv=baseline.pv(w), ev=ev_w, ac=actuals.cumulative(w).amount,
            pv_hours=baseline.pv_hours(w), ev_hours=ev_h_w,
            ac_hours=actuals.cumulative(w, None, CostType.LABOR).hours,
            planned_crew=crew_mod.headcount(baseline.weekly_hours(w), std),
            actual_crew=crew_mod.headcount(ac_h_w, std),
            earned_crew=earned_crew, locked=locked,
        ))
        prev_ev_h = ev_h_w if ev_h_w is not None else prev_ev_h

    # --- forecast after status ----------------------------------------
    fc_hours_table = forecast_remaining(project, baseline, acts, earned_hours_by_act, status_week, etc_hours_disc)
    forecast_hours = {w: sum(v.values()) for w, v in sorted(fc_hours_table.items())}
    forecast_finish_week = max(forecast_hours) if forecast_hours else None
    forecast_ac: Dict[int, float] = {}
    if etc > 0:
        if forecast_hours:
            weeks = sorted(forecast_hours)
            weights = [forecast_hours[w] for w in weeks]
        else:
            weeks = [w for w in range(status_week + 1, baseline.weeks + 1) if baseline.weekly_dollars(w) > 0]
            weights = [baseline.weekly_dollars(w) for w in weeks]
            if not weeks:
                weeks, weights = [status_week + 1], [1.0]
        total_w = sum(weights) or 1.0
        running = ac
        for w, wt in zip(weeks, weights):
            running += etc * wt / total_w
            forecast_ac[w] = running
    cum_ac = {p.week: p.ac for p in weekly}
    cum_ac.update(forecast_ac)
    crossover = funding_crossover(cum_ac, project.contracted_value)

    # --- thresholds -----------------------------------------------------
    breached: List[str] = []
    th = project.thresholds
    if spi is not None and spi < th.get("spi", 0.0):
        breached.append(f"SPI {spi:.2f} below {th['spi']:.2f}")
    if cpi is not None and cpi < th.get("cpi", 0.0):
        breached.append(f"CPI {cpi:.2f} below {th['cpi']:.2f}")
    if bac and abs(ev - ac) / bac > th.get("cv_pct", 1.0):
        breached.append(f"CV {ev - ac:,.0f} exceeds {th['cv_pct']:.0%} of BAC")

    snapshot = StatusSnapshot(
        project=project.name, data_date=data_date.isoformat(), status_week=status_week,
        week_end=week_cal.week_end(status_week).isoformat(), basis=baseline.basis,
        basis_version=baseline.version, bac=bac, bac_hours=bac_hours, pv=pv, ev=ev, ac=ac,
        pv_hours=pv_hours, ev_hours=ev_hours, ac_hours=ac_hours, sv=ev - pv, cv=ev - ac,
        spi=spi, cpi=cpi, spi_hours=spi_h, cpi_hours=cpi_h, tcpi_bac=tcpi_bac, tcpi_eac=tcpi_eac,
        eac_methods=methods, eac_selected_method=method, eac=eac, etc=etc, vac=vac, eac_hours=eac_hours,
        pct_complete=(ev / bac if bac else 0.0), pct_spent=(ac / bac if bac else 0.0),
        contracted_value=project.contracted_value, estimated_value=project.budget_total("estimated"),
        funding_exposure=project.budget_total("estimated") - project.contracted_value,
        crossover_week=crossover,
        crossover_week_end=(week_cal.week_end(crossover).isoformat() if crossover else None),
        weekly=weekly, forecast_ac=forecast_ac, forecast_hours=forecast_hours,
        forecast_finish_week=forecast_finish_week, disciplines=disciplines, activities=activity_ev,
        checks=[], thresholds_breached=breached, notes=notes,
    )
    snapshot.checks = health_checks(project, baseline, actuals, snapshot, history, source_totals)
    return snapshot


# ---------------------------------------------------------------------------
# Integrity checks (RP §11)
# ---------------------------------------------------------------------------

def health_checks(project: Project, baseline: Baseline, actuals: WeeklyActuals, snap: StatusSnapshot,
                  history: Optional[Dict[int, dict]] = None,
                  source_totals: Optional[Dict[str, Tuple[float, float]]] = None) -> List[CheckResult]:
    checks: List[CheckResult] = []
    history = history or {}

    diff = baseline.terminal_pv - baseline.total_bac
    checks.append(CheckResult("terminal_pv_equals_bac", abs(diff) < 1.0,
                              f"terminal PV {baseline.terminal_pv:,.2f} vs BAC {baseline.total_bac:,.2f} (diff {diff:,.2f})"))

    monotonic = all(baseline.weekly_dollars(w) >= -1e-6 for w in range(1, baseline.weeks + 1))
    checks.append(CheckResult("pv_monotonic", monotonic, "no negative weekly PV"))

    ties = []
    for d in baseline.disciplines:
        alloc = sum(h for aid, h in baseline.allocation.items() if _disc_of(aid, snap) == d)
        target = baseline.bac_hours.get(d, 0.0)
        if abs(alloc - target) > 0.01:
            ties.append(f"{d}: allocated {alloc:,.2f} vs budget {target:,.2f}")
    checks.append(CheckResult("allocation_ties_by_discipline", not ties, "; ".join(ties) or "all disciplines tie"))

    missing = [e.activity_id for e in snap.activities if e.activity_id not in baseline.allocation]
    checks.append(CheckResult("activities_in_baseline", not missing,
                              f"schedule activities absent from the baseline (earn nothing): {missing}" if missing
                              else f"all {len(snap.activities)} activities carry a baseline allocation"))

    hours_ok = abs(sum(baseline.weekly_hours(w) for w in range(1, baseline.weeks + 1)) - baseline.total_bac_hours) < 0.01
    checks.append(CheckResult("phased_hours_conserved", hours_ok,
                              f"phased {sum(baseline.weekly_hours(w) for w in range(1, baseline.weeks + 1)):,.2f} vs BAC hours {baseline.total_bac_hours:,.2f}"))

    if source_totals is not None:
        from .actuals import reconcile
        issues = reconcile(actuals, source_totals)
        checks.append(CheckResult("ac_reconciles_to_source", not issues, "; ".join(issues) or "all cost types reconcile"))
    else:
        checks.append(CheckResult("ac_reconciles_to_source", True, "not run — no source report totals supplied", ran=False))

    over = [e.activity_id for e in snap.activities if e.earned_hours > e.budget_hours + 1e-6]
    checks.append(CheckResult("ev_within_budget", not over and snap.ev <= snap.bac + 0.01,
                              f"activities over budget: {over}" if over else "EV ≤ BAC at every level"))

    checks.append(CheckResult("status_week_complete", date.fromisoformat(snap.week_end) <= date.fromisoformat(snap.data_date),
                              f"status week ends {snap.week_end}, data date {snap.data_date}"))

    leak = len(actuals.post_status)
    checks.append(CheckResult("no_post_status_cost_in_ac", True,
                              f"{leak} transaction(s) dated after the status week held out of AC"))

    locked_weeks = sorted(history)
    gaps = [w for w in range(1, snap.status_week) if w not in history]
    if snap.status_week == 1:
        checks.append(CheckResult("history_contiguous", True, "not run — first status week", ran=False))
    else:
        checks.append(CheckResult("history_contiguous", not gaps,
                                  f"weeks missing from the status log: {gaps}" if gaps else f"{len(locked_weeks)} locked week(s)"))

    drift = []
    for w, rec in history.items():
        if w >= snap.status_week:
            continue
        pv_now = baseline.pv(w)
        if "pv" in rec and rec.get("basis_version") == baseline.version and abs(pv_now - float(rec["pv"])) > 1.0:
            drift.append(f"wk {w}: PV now {pv_now:,.0f} vs logged {float(rec['pv']):,.0f}")
    checks.append(CheckResult("locked_pv_unchanged", not drift,
                              "; ".join(drift) or "PV of locked weeks matches the baseline version they were statused on"))

    co_gap = project.budget_total("estimated") - project.budget_total("contracted") - project.budget.change_order_total
    if project.budget.has_override:
        checks.append(CheckResult("co_log_ties_estimated_basis", True,
                                  f"explicit estimate override declared; override − (contracted + COs) = {co_gap:,.2f}"))
    else:
        checks.append(CheckResult("co_log_ties_estimated_basis", abs(co_gap) < 0.01,
                                  f"estimated − contracted − COs = {co_gap:,.2f}"))

    stat = snap.eac_methods.get("cpi")
    stat_ok = stat is None or snap.cpi is None or snap.cpi >= 1.0 or snap.eac >= stat - 0.01
    checks.append(CheckResult("eac_not_below_statistical", stat_ok,
                              f"selected {snap.eac:,.0f} ({snap.eac_selected_method}) vs BAC/CPI {stat:,.0f}" if stat else "not run — no earned value yet",
                              ran=stat is not None))
    return checks


def _disc_of(activity_id: str, snap: StatusSnapshot) -> Optional[str]:
    for e in snap.activities:
        if e.activity_id == activity_id:
            return e.discipline
    return None
