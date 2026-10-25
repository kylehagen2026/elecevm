"""Domain model: disciplines, activities, budgets, cost transactions, quantities."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Dict, List, Optional, Tuple


class CostType(str, Enum):
    """The five cost classes every ledger cost type is mapped to (RP §4.1)."""

    LABOR = "L"
    MATERIAL = "M"
    SUBCONTRACT = "S"
    EQUIPMENT = "E"
    OTHER = "O"

    @classmethod
    def parse(cls, value) -> "CostType":
        if isinstance(value, CostType):
            return value
        v = str(value).strip().upper()
        aliases = {
            "L": "L", "LAB": "L", "LABOR": "L", "LABOUR": "L",
            "M": "M", "MAT": "M", "MATERIAL": "M", "MATERIALS": "M",
            "S": "S", "SUB": "S", "SUBCONTRACT": "S", "SUBCONTRACTOR": "S",
            "E": "E", "EQ": "E", "EQUIP": "E", "EQUIPMENT": "E",
            "O": "O", "OTH": "O", "OTHER": "O",
        }
        if v in aliases:
            return cls(aliases[v])
        raise ValueError(f"unknown cost type: {value!r}")

    @property
    def label(self) -> str:
        return self.name.capitalize()


class EVMethod(str, Enum):
    """Earned value measurement tiers (RP §6.1)."""

    QUANTITY = "quantity"      # Tier 1 — installed quantities
    MILESTONE = "milestone"    # Tier 2 — weighted milestones
    PERCENT = "percent"        # Tier 2b — field-reported physical percent
    INVOICED = "invoiced"      # Tier 3 — invoiced percent, interim only
    LOE = "loe"                # level of effort: EV = PV
    APPORTIONED = "apportioned"  # earned at the fraction of a base activity

    @classmethod
    def parse(cls, value) -> "EVMethod":
        if isinstance(value, EVMethod):
            return value
        v = str(value).strip().lower()
        if not v:
            return cls.QUANTITY
        aliases = {"qty": "quantity", "ms": "milestone", "pct": "percent", "%": "percent",
                   "billed": "invoiced", "invoice": "invoiced", "level_of_effort": "loe"}
        v = aliases.get(v, v)
        return cls(v)


@dataclass
class Discipline:
    """A craft/system scope with its own labor budget and composite rate."""

    code: str
    name: str
    composite_rate: float = 0.0  # burdened labor $/hr
    std_hours_per_week: Optional[float] = None


@dataclass
class Activity:
    """A schedule activity carrying a share of one discipline's labor budget."""

    id: str
    name: str
    discipline: str
    start: date
    finish: date
    area: str = ""
    actual_start: Optional[date] = None
    actual_finish: Optional[date] = None
    forecast_finish: Optional[date] = None
    original_duration: Optional[int] = None  # workdays
    percent_complete: float = 0.0             # field-reported physical % (0–1)
    budget_hours: Optional[float] = None      # from a resource-loaded schedule
    hours_per_day: float = 10.0
    area_weight: float = 1.0
    activity_factor: float = 1.0
    ev_method: EVMethod = EVMethod.QUANTITY
    commodity: Optional[str] = None
    base_activity: Optional[str] = None       # for apportioned effort

    @property
    def is_started(self) -> bool:
        return self.actual_start is not None or self.percent_complete > 0

    @property
    def is_complete(self) -> bool:
        return self.actual_finish is not None or self.percent_complete >= 1.0

    @property
    def status_text(self) -> str:
        if self.is_complete:
            return "Completed"
        if self.is_started:
            return "In Progress"
        return "Not Started"

    @property
    def current_start(self) -> date:
        return self.actual_start or self.start

    @property
    def current_finish(self) -> date:
        return self.actual_finish or self.forecast_finish or self.finish


BudgetKey = Tuple[str, str]  # (discipline code, CostType value)


@dataclass
class ChangeOrder:
    """A change order carried in the project's CO log (RP §4.2, §10)."""

    id: str
    description: str
    date: date
    status: str = "approved"  # proposed | pending | approved | rejected
    amounts: Dict[str, float] = field(default_factory=dict)  # "DISC:CT" -> $
    hours: Dict[str, float] = field(default_factory=dict)    # discipline -> labor hours

    @property
    def counts_toward_estimate(self) -> bool:
        return self.status.lower() in {"approved", "pending"}

    @property
    def total(self) -> float:
        return sum(self.amounts.values())


@dataclass
class Budget:
    """Budget at completion on two bases: contracted and estimated (RP §4.2).

    ``estimated`` defaults to ``contracted`` plus every change order whose
    status counts toward the estimate (approved or pending).
    """

    contracted: Dict[BudgetKey, float] = field(default_factory=dict)
    contracted_hours: Dict[str, float] = field(default_factory=dict)
    estimated_override: Dict[BudgetKey, float] = field(default_factory=dict)
    estimated_hours_override: Dict[str, float] = field(default_factory=dict)
    change_orders: List[ChangeOrder] = field(default_factory=list)
    basis: str = "estimated"

    # -- derived tables -------------------------------------------------
    @property
    def has_override(self) -> bool:
        """True when an explicit estimated budget was declared (it then supersedes contracted + COs)."""
        return bool(self.estimated_override) or bool(self.estimated_hours_override)

    @property
    def estimated(self) -> Dict[BudgetKey, float]:
        if self.estimated_override:
            return dict(self.estimated_override)
        table = dict(self.contracted)
        for co in self.change_orders:
            if not co.counts_toward_estimate:
                continue
            for key, amount in co.amounts.items():
                disc, ct = key.split(":")
                k = (disc, CostType.parse(ct).value)
                table[k] = table.get(k, 0.0) + float(amount)
        return table

    @property
    def estimated_hours(self) -> Dict[str, float]:
        if self.estimated_hours_override:
            return dict(self.estimated_hours_override)
        table = dict(self.contracted_hours)
        for co in self.change_orders:
            if not co.counts_toward_estimate:
                continue
            for disc, hrs in co.hours.items():
                table[disc] = table.get(disc, 0.0) + float(hrs)
        return table

    def contracted_plus_change_orders(self) -> float:
        total = sum(self.contracted.values())
        return total + self.change_order_total

    def table(self, basis: Optional[str] = None) -> Dict[BudgetKey, float]:
        return self.estimated if (basis or self.basis) == "estimated" else dict(self.contracted)

    def hours_table(self, basis: Optional[str] = None) -> Dict[str, float]:
        return self.estimated_hours if (basis or self.basis) == "estimated" else dict(self.contracted_hours)

    # -- queries ---------------------------------------------------------
    def bac(self, discipline: Optional[str] = None, cost_type: Optional[CostType] = None,
            basis: Optional[str] = None) -> float:
        total = 0.0
        for (disc, ct), amount in self.table(basis).items():
            if discipline is not None and disc != discipline:
                continue
            if cost_type is not None and ct != cost_type.value:
                continue
            total += amount
        return total

    def bac_hours(self, discipline: Optional[str] = None, basis: Optional[str] = None) -> float:
        table = self.hours_table(basis)
        if discipline is None:
            return sum(table.values())
        return table.get(discipline, 0.0)

    def disciplines(self) -> List[str]:
        seen: List[str] = []
        for disc, _ in list(self.contracted) + list(self.estimated):
            if disc not in seen:
                seen.append(disc)
        for disc in list(self.contracted_hours) + list(self.estimated_hours):
            if disc not in seen:
                seen.append(disc)
        return seen

    @property
    def contracted_total(self) -> float:
        return sum(self.contracted.values())

    @property
    def estimated_total(self) -> float:
        return sum(self.estimated.values())

    @property
    def change_order_total(self) -> float:
        return sum(co.total for co in self.change_orders if co.counts_toward_estimate)


@dataclass
class CostTransaction:
    """One job-cost ledger line, already mapped to a discipline and cost type."""

    trans_date: date
    cost_type: CostType
    discipline: str
    hours: float = 0.0
    amount: float = 0.0
    phase: str = ""
    posted_date: Optional[date] = None
    description: str = ""
    source: str = ""


@dataclass
class QuantityRecord:
    """A field progress observation for one activity as of a date (RP §6.3)."""

    activity_id: str
    as_of: date
    commodity: Optional[str] = None
    item: str = ""
    uom: str = ""
    total_qty: float = 0.0
    installed_qty: float = 0.0
    milestones: List[str] = field(default_factory=list)           # fully achieved
    milestone_progress: Dict[str, float] = field(default_factory=dict)  # partial, 0–1
    percent_complete: Optional[float] = None                        # field-reported %
    reported_by: str = ""
