"""Project configuration loaded from ``elecevm.toml`` (RP §4)."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Union

from .calendar import WeekCalendar, WorkCalendar, parse_weekday
from .models import Budget, ChangeOrder, CostType, Discipline, EVMethod

AC_METHODS = {"raw", "markup", "billed"}
EAC_POLICIES = {"max_management_cpi", "management", "cpi", "budget_rate", "composite"}
MATERIAL_PHASING = {"follow_labor", "bell", "linear"}


def to_date(value: Union[str, date, datetime, None]) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d-%b-%y", "%d-%b-%Y", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date: {value!r}")


@dataclass
class ACBasisRule:
    """How a cost type's actual cost is carried (RP §7.3).

    * ``raw``     — ledger amount as posted
    * ``markup``  — ledger amount × ``markup`` (e.g. subcontract cost at billed markup)
    * ``billed``  — weeks before status at ledger × markup; the status week carries the
      residual to a supplied billed-to-date value (the *residual week*)
    """

    method: str = "raw"
    markup: float = 1.0

    def __post_init__(self) -> None:
        if self.method not in AC_METHODS:
            raise ValueError(f"ac_basis method must be one of {sorted(AC_METHODS)}, got {self.method!r}")


@dataclass
class Project:
    name: str
    week_cal: WeekCalendar
    work_cal: WorkCalendar
    std_hours_per_week: float
    disciplines: Dict[str, Discipline]
    budget: Budget
    contracted_value: float
    ac_basis: Dict[CostType, ACBasisRule] = field(default_factory=dict)
    ev_default: EVMethod = EVMethod.QUANTITY
    eac_policy: str = "max_management_cpi"
    thresholds: Dict[str, float] = field(default_factory=lambda: {"spi": 0.90, "cpi": 0.90, "cv_pct": 0.05})
    crew_cap_headcount: Optional[float] = None
    taper_floor_headcount: float = 0.0
    material_phasing: str = "follow_labor"
    phase_map: Dict[str, str] = field(default_factory=dict)
    cost_type_map: Dict[str, str] = field(default_factory=dict)
    source_path: Optional[Path] = None

    # -- helpers ----------------------------------------------------------
    def rate(self, discipline: str) -> float:
        """Effective labor $/hr: budget labor $ ÷ budget hours when both exist, else the composite rate."""
        dollars = self.budget.bac(discipline, CostType.LABOR)
        hours = self.budget.bac_hours(discipline)
        if dollars > 0 and hours > 0:
            return dollars / hours
        disc = self.disciplines.get(discipline)
        return disc.composite_rate if disc else 0.0

    def std_hours(self, discipline: Optional[str] = None) -> float:
        if discipline and discipline in self.disciplines and self.disciplines[discipline].std_hours_per_week:
            return float(self.disciplines[discipline].std_hours_per_week)
        return float(self.std_hours_per_week)

    @property
    def crew_cap_hours(self) -> Optional[float]:
        if self.crew_cap_headcount is None:
            return None
        return float(self.crew_cap_headcount) * self.std_hours_per_week

    @property
    def taper_floor_hours(self) -> float:
        return float(self.taper_floor_headcount) * self.std_hours_per_week

    def budget_total(self, basis: Optional[str] = None) -> float:
        """BAC in dollars on a basis, including labor dollars derived from hours × composite rate
        for disciplines budgeted in hours only (the same derivation the baseline uses)."""
        table = self.budget.table(basis)
        total = sum(table.values())
        for disc, hours in self.budget.hours_table(basis).items():
            if table.get((disc, CostType.LABOR.value), 0.0) <= 0 and hours > 0:
                d = self.disciplines.get(disc)
                total += hours * (d.composite_rate if d else 0.0)
        return total

    def discipline_name(self, code: str) -> str:
        d = self.disciplines.get(code)
        return d.name if d else code

    def map_cost_type(self, raw) -> CostType:
        key = str(raw).strip()
        if key in self.cost_type_map:
            return CostType.parse(self.cost_type_map[key])
        return CostType.parse(key)

    def map_phase(self, phase: str) -> Optional[str]:
        """Discipline for a ledger phase/cost code: exact match, then longest prefix."""
        phase = str(phase).strip()
        if phase in self.phase_map:
            return self.phase_map[phase]
        best = None
        for prefix, disc in self.phase_map.items():
            if phase.startswith(prefix) and (best is None or len(prefix) > len(best[0])):
                best = (prefix, disc)
        return best[1] if best else None


def _parse_budget(section: dict, basis: str, change_orders: List[ChangeOrder]) -> Budget:
    def table(name: str):
        amounts: Dict[tuple, float] = {}
        hours: Dict[str, float] = {}
        for disc, vals in section.get(name, {}).items():
            if "labor_hours" in vals:
                hours[disc] = float(vals["labor_hours"])
            for ct in CostType:
                key = ct.name.lower()
                if key in vals:
                    amounts[(disc, ct.value)] = float(vals[key])
        return amounts, hours

    c_amt, c_hrs = table("contracted")
    e_amt, e_hrs = table("estimated")
    if basis not in {"contracted", "estimated"}:
        raise ValueError("project.basis must be 'contracted' or 'estimated'")
    return Budget(c_amt, c_hrs, e_amt, e_hrs, change_orders, basis)


def _parse_change_orders(items: list) -> List[ChangeOrder]:
    out: List[ChangeOrder] = []
    for item in items:
        amounts = {str(k): float(v) for k, v in item.get("amounts", {}).items()}
        hours = {str(k): float(v) for k, v in item.get("hours", {}).items()}
        out.append(ChangeOrder(
            id=str(item["id"]),
            description=str(item.get("description", "")),
            date=to_date(item.get("date")) or date.today(),
            status=str(item.get("status", "approved")),
            amounts=amounts,
            hours=hours,
        ))
    return out


def load_project(path: Union[str, Path]) -> Project:
    """Load ``elecevm.toml``.  See :func:`template_toml` for the schema."""
    p = Path(path)
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    return project_from_dict(data, source_path=p)


def project_from_dict(data: dict, source_path: Optional[Path] = None) -> Project:
    proj = data["project"]
    start = to_date(proj["start"])
    if start is None:
        raise ValueError("project.start is required")
    week_cal = WeekCalendar(start, parse_weekday(proj.get("week_ending", "saturday")))
    workdays = frozenset(parse_weekday(w) for w in proj.get("workdays", ["mon", "tue", "wed", "thu", "fri", "sat"]))
    holidays = frozenset(h for h in (to_date(x) for x in proj.get("holidays", [])) if h is not None)
    work_cal = WorkCalendar(workdays, holidays)

    disciplines = {}
    for d in data.get("disciplines", []):
        disciplines[str(d["code"])] = Discipline(
            code=str(d["code"]),
            name=str(d.get("name", d["code"])),
            composite_rate=float(d.get("composite_rate", 0.0)),
            std_hours_per_week=d.get("std_hours_per_week"),
        )

    change_orders = _parse_change_orders(data.get("change_orders", []))
    budget = _parse_budget(data.get("budget", {}), str(proj.get("basis", "estimated")), change_orders)

    ac_section = data.get("ac_basis", {})
    ac_basis = {}
    for ct in CostType:
        key = ct.name.lower()
        ac_basis[ct] = ACBasisRule(
            method=str(ac_section.get(key, "raw")),
            markup=float(ac_section.get(f"{key}_markup", 1.0)),
        )

    ev_section = data.get("ev", {})
    eac_section = data.get("eac", {})
    policy = str(eac_section.get("policy", "max_management_cpi"))
    if policy not in EAC_POLICIES:
        raise ValueError(f"eac.policy must be one of {sorted(EAC_POLICIES)}")
    thresholds = {"spi": 0.90, "cpi": 0.90, "cv_pct": 0.05}
    thresholds.update({k: float(v) for k, v in eac_section.get("thresholds", {}).items()})

    lev = data.get("leveling", {})
    phasing = str(data.get("phasing", {}).get("material", "follow_labor"))
    if phasing not in MATERIAL_PHASING:
        raise ValueError(f"phasing.material must be one of {sorted(MATERIAL_PHASING)}")

    project = Project(
        name=str(proj.get("name", "Project")),
        week_cal=week_cal,
        work_cal=work_cal,
        std_hours_per_week=float(proj.get("std_hours_per_week", 40)),
        disciplines=disciplines,
        budget=budget,
        contracted_value=float(proj["contracted_value"]) if "contracted_value" in proj else -1.0,
        ac_basis=ac_basis,
        ev_default=EVMethod.parse(ev_section.get("default_method", "quantity")),
        eac_policy=policy,
        thresholds=thresholds,
        crew_cap_headcount=(float(lev["crew_cap_headcount"]) if "crew_cap_headcount" in lev else None),
        taper_floor_headcount=float(lev.get("taper_floor_headcount", 0.0)),
        material_phasing=phasing,
        phase_map={str(k): str(v) for k, v in data.get("phase_map", {}).items()},
        cost_type_map={str(k): str(v) for k, v in data.get("cost_type_map", {}).items()},
        source_path=source_path,
    )
    if project.contracted_value < 0:
        project.contracted_value = project.budget_total("contracted")
    return project


def template_toml() -> str:
    """A commented ``elecevm.toml`` template written by ``elecevm init``."""
    return '''# elecevm project configuration — see docs/standard.md (Recommended Practice §4)

[project]
name = "Example Project — Electrical Package"
start = 2026-03-09                 # project start / NTP; payroll week 1 contains this date
week_ending = "saturday"           # payroll week-ending day (Sunday–Saturday weeks)
workdays = ["mon", "tue", "wed", "thu", "fri", "sat"]
holidays = [2026-05-25, 2026-07-03, 2026-09-07, 2026-11-26, 2026-12-25]
std_hours_per_week = 50            # hours per head per week used for headcount conversions
contracted_value = 6887050.0       # funding line: executed contract value
basis = "estimated"                # metrics basis: "contracted" or "estimated" (contract + COs)

[[disciplines]]
code = "FE"
name = "Facility Electrical"
composite_rate = 92.50             # burdened labor $/hr (used when the budget has hours but no $)

[[disciplines]]
code = "FSS"
name = "Fire & Security Systems"
composite_rate = 98.00

[[disciplines]]
code = "TEL"
name = "Telecommunications"
composite_rate = 76.00

# Budget at completion by discipline and cost type. Keys: labor_hours, labor, material,
# subcontract, equipment, other. The estimated basis = contracted + change orders below
# unless a [budget.estimated.<DISC>] table is given explicitly.
[budget.contracted.FE]
labor_hours = 38100
labor = 3524250.0
material = 1480000.0
subcontract = 120000.0

[budget.contracted.FSS]
labor_hours = 5800
labor = 568400.0
material = 360000.0

[budget.contracted.TEL]
labor_hours = 6900
labor = 524400.0
material = 265000.0
subcontract = 45000.0

[[change_orders]]
id = "CO-001"
description = "Added receptacle circuits, Area 2 mezzanine"
date = 2026-07-20
status = "approved"                # proposed | pending | approved | rejected
amounts = { "FE:L" = 101750.0, "FE:M" = 68000.0 }
hours = { FE = 1100 }

# Actual-cost basis per cost type: raw | markup | billed (RP §7.3)
[ac_basis]
labor = "raw"
material = "raw"
subcontract = "markup"
subcontract_markup = 1.065

[ev]
default_method = "quantity"        # quantity | milestone | percent | invoiced | loe | apportioned

[eac]
policy = "max_management_cpi"      # reported EAC = max(management estimate, BAC/CPI)
thresholds = { spi = 0.90, cpi = 0.90, cv_pct = 0.05 }

[leveling]
# crew_cap_headcount = 45          # optional: delay-only leveling cap on the labor curve (RP §5.4)

[phasing]
material = "follow_labor"          # follow_labor | bell | linear

# Ledger phase (cost code) → discipline. Longest matching prefix wins.
[phase_map]
"200001" = "FE"
"200002" = "FSS"
"200003" = "TEL"

# Ledger cost type → L/M/S/E/O
[cost_type_map]
"1" = "L"
"3" = "M"
"7" = "S"
'''
