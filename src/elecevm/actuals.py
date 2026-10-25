"""Actual cost: transaction-date bucketing, basis rules, reconciliation (RP §7)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from .calendar import WeekCalendar
from .config import ACBasisRule
from .models import CostTransaction, CostType

Key = Tuple[str, str]  # (discipline, CostType value)


@dataclass
class ACBucket:
    hours: float = 0.0
    amount: float = 0.0

    def add(self, hours: float, amount: float) -> None:
        self.hours += hours
        self.amount += amount

    def copy(self) -> "ACBucket":
        return ACBucket(self.hours, self.amount)


@dataclass
class WeeklyActuals:
    """Actual cost by payroll week, discipline and cost type through the status week."""

    status_week: int
    buckets: Dict[int, Dict[Key, ACBucket]] = field(default_factory=dict)
    post_status: List[CostTransaction] = field(default_factory=list)
    source_totals: Dict[str, ACBucket] = field(default_factory=dict)  # by cost type value
    notes: List[str] = field(default_factory=list)

    def _iter(self, week: int, discipline: Optional[str], cost_type: Optional[CostType]):
        for (disc, ct), b in self.buckets.get(week, {}).items():
            if discipline is not None and disc != discipline:
                continue
            if cost_type is not None and ct != cost_type.value:
                continue
            yield b

    def weekly(self, week: int, discipline: Optional[str] = None,
               cost_type: Optional[CostType] = None) -> ACBucket:
        out = ACBucket()
        for b in self._iter(week, discipline, cost_type):
            out.add(b.hours, b.amount)
        return out

    def cumulative(self, through: int, discipline: Optional[str] = None,
                   cost_type: Optional[CostType] = None) -> ACBucket:
        out = ACBucket()
        for w in range(1, through + 1):
            b = self.weekly(w, discipline, cost_type)
            out.add(b.hours, b.amount)
        return out

    def totals_by_cost_type(self) -> Dict[str, ACBucket]:
        out: Dict[str, ACBucket] = {}
        for week in self.buckets.values():
            for (_, ct), b in week.items():
                out.setdefault(ct, ACBucket()).add(b.hours, b.amount)
        return out

    def disciplines(self) -> List[str]:
        seen: List[str] = []
        for week in self.buckets.values():
            for (disc, _) in week:
                if disc not in seen:
                    seen.append(disc)
        return seen

    def to_dict(self) -> dict:
        return {
            "status_week": self.status_week,
            "buckets": {str(w): {f"{d}:{ct}": [b.hours, b.amount] for (d, ct), b in row.items()} for w, row in self.buckets.items()},
            "source_totals": {ct: [b.hours, b.amount] for ct, b in self.source_totals.items()},
            "post_status_count": len(self.post_status),
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WeeklyActuals":
        out = cls(int(data["status_week"]))
        for w, row in data.get("buckets", {}).items():
            for key, (h, amt) in row.items():
                d, ct = key.rsplit(":", 1)
                out.buckets.setdefault(int(w), {})[(d, ct)] = ACBucket(float(h), float(amt))
        out.source_totals = {ct: ACBucket(float(h), float(amt)) for ct, (h, amt) in data.get("source_totals", {}).items()}
        out.notes = list(data.get("notes", []))
        return out

    def copy(self) -> "WeeklyActuals":
        return WeeklyActuals(
            self.status_week,
            {w: {k: b.copy() for k, b in row.items()} for w, row in self.buckets.items()},
            list(self.post_status),
            {k: b.copy() for k, b in self.source_totals.items()},
            list(self.notes),
        )


def bucket_transactions(transactions: Iterable[CostTransaction], week_cal: WeekCalendar,
                        status_week: int) -> WeeklyActuals:
    """Bucket ledger lines by *transaction date* into payroll weeks (RP §7.1).

    Lines dated after the status week-ending date are kept aside in
    ``post_status`` — they are real cost, but they belong to the next status
    period and must not leak into this one.  Lines dated before the project
    start land in week 1.
    """
    actuals = WeeklyActuals(status_week=status_week)
    for t in transactions:
        week = week_cal.week_of(t.trans_date)
        key = (t.discipline, CostType.parse(t.cost_type).value)
        # raw totals of the whole pull, post-status lines included — what the source report prints
        actuals.source_totals.setdefault(key[1], ACBucket()).add(float(t.hours), float(t.amount))
        if week > status_week:
            actuals.post_status.append(t)
            continue
        actuals.buckets.setdefault(week, {}).setdefault(key, ACBucket()).add(float(t.hours), float(t.amount))
    return actuals


def reconcile(actuals: WeeklyActuals, expected: Dict[str, Tuple[float, float]],
              tolerance: float = 0.01) -> List[str]:
    """Compare the raw totals of the pull with the source report's totals by cost type.

    ``expected`` maps a cost type value (``"L"``, ``"M"`` …) to ``(hours, amount)``
    as printed on the job-cost report.  The comparison uses the raw ledger
    amounts captured at bucketing time (before any AC basis rule is applied)
    and includes lines dated after the status week, because the report
    includes them too.  Returns a list of mismatch messages; empty means the
    pull reconciles exactly (RP §7.1).
    """
    issues: List[str] = []
    totals = actuals.source_totals
    for ct, (hours, amount) in expected.items():
        got = totals.get(ct, ACBucket())
        if abs(got.hours - hours) > tolerance:
            issues.append(f"{ct}: hours {got.hours:,.2f} vs source {hours:,.2f}")
        if abs(got.amount - amount) > tolerance:
            issues.append(f"{ct}: amount {got.amount:,.2f} vs source {amount:,.2f}")
    for ct in totals:
        if ct not in expected:
            issues.append(f"{ct}: in the pull but absent from source totals")
    return issues


def apply_basis(actuals: WeeklyActuals, rules: Dict[CostType, ACBasisRule],
                billed_to_date: Optional[Dict[CostType, float]] = None) -> WeeklyActuals:
    """Apply the per-cost-type AC basis (RP §7.3) and return a new table.

    * ``raw``: unchanged.
    * ``markup``: every week's amount × markup.
    * ``billed``: weeks before status at ledger × markup; the status week is
      replaced so the cumulative equals the supplied billed-to-date value.
      The residual is shared across the status week's disciplines in
      proportion to their status-week ledger amounts (or their cumulative
      amounts if the status week is empty).  Hours are never adjusted.
    """
    out = actuals.copy()
    billed_to_date = billed_to_date or {}
    status = out.status_week
    for ct, rule in rules.items():
        if rule.method == "raw":
            continue
        factor = rule.markup
        for week, row in out.buckets.items():
            for key, b in row.items():
                if key[1] == ct.value:
                    b.amount *= factor
        if rule.method == "billed" and ct not in billed_to_date:
            out.notes.append(f"{ct.label}: billed basis declared but no billed-to-date value supplied; "
                             f"carried at ledger × {factor:g}")
        if rule.method == "billed" and ct in billed_to_date and status >= 1:
            billed = float(billed_to_date[ct])
            prior = sum(out.weekly(w, None, ct).amount for w in range(1, status))
            residual = billed - prior
            status_row = out.buckets.setdefault(status, {})
            shares = {k: b.amount for k, b in status_row.items() if k[1] == ct.value}
            if sum(shares.values()) <= 0:
                shares = {}
                for w in range(1, status + 1):
                    for k, b in out.buckets.get(w, {}).items():
                        if k[1] == ct.value:
                            shares[k] = shares.get(k, 0.0) + b.amount
            total_share = sum(shares.values())
            if total_share <= 0:
                disc = out.disciplines()[0] if out.disciplines() else "ALL"
                shares = {(disc, ct.value): 1.0}
                total_share = 1.0
            for k, share in shares.items():
                b = status_row.setdefault(k, ACBucket())
                b.amount = residual * share / total_share
            out.notes.append(
                f"{ct.label}: status week {status} carries the billed-basis residual "
                f"{residual:,.2f} (billed-to-date {billed:,.2f} − prior weeks {prior:,.2f})")
    return out


@dataclass
class Restatement:
    week: int
    discipline: str
    cost_type: str
    delta_hours: float
    delta_amount: float


def restatements(previous: WeeklyActuals, current: WeeklyActuals, locked_through: int,
                 tolerance: float = 0.005) -> List[Restatement]:
    """Late postings: differences in weeks already statused (RP §7.2).

    These are logged, and the affected weeks' AC buckets are restated to the
    transaction week; the locked status-log rows for those weeks are *not*
    changed (RP §9.1).
    """
    out: List[Restatement] = []
    for week in range(1, locked_through + 1):
        keys = set(previous.buckets.get(week, {})) | set(current.buckets.get(week, {}))
        for key in sorted(keys):
            before = previous.buckets.get(week, {}).get(key, ACBucket())
            after = current.buckets.get(week, {}).get(key, ACBucket())
            dh, da = after.hours - before.hours, after.amount - before.amount
            if abs(dh) > tolerance or abs(da) > tolerance:
                out.append(Restatement(week, key[0], key[1], dh, da))
    return out
