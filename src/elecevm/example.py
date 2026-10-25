"""A synthetic example project: a distribution-center electrical package.

Everything here is generated from a seeded random process.  No real project,
client, contractor or ledger data is used.  ``elecevm example --out DIR``
writes the inputs (``elecevm.toml``, ``schedule.csv``, ``jobcost.csv``,
``quantities.csv``), builds the baseline, statuses every payroll week through
the data date into a locked status log, and renders a Weekly Status Report.
"""
from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .allocation import Baseline, build_baseline
from .config import load_project, template_toml
from .ingest import (activities_from_csv, read_jobcost_csv, read_quantities_csv,
                     write_activities_csv, write_jobcost_csv, write_quantities_csv)
from .models import Activity, CostTransaction, CostType, EVMethod, QuantityRecord
from .rules_of_credit import DEFAULT_RULES

DATA_DATE = date(2026, 9, 5)
PHASES = {"FE": "200001", "FSS": "200002", "TEL": "200003"}
COST_TYPE_CODES = {"L": "1", "M": "3", "S": "7"}

# id, name, discipline, area, start, finish, budget hours, ev method, commodity, total qty, uom
SCHEDULE: List[Tuple] = [
    ("FE-ER-010", "Electrical room rough-in", "FE", "ER", "2026-03-09", "2026-04-18", 1800, "milestone", "conduit", 2400, "LF"),
    ("FE-ER-020", "Set switchgear and distribution", "FE", "ER", "2026-04-13", "2026-05-16", 1600, "milestone", "switchgear", 6, "EA"),
    ("FE-ER-030", "Feeders — pull and terminate", "FE", "ER", "2026-05-11", "2026-06-27", 2800, "milestone", "wire_feeder", 18000, "LF"),
    ("FE-A1-010", "Area 1 overhead rough-in", "FE", "A1", "2026-03-23", "2026-05-30", 5000, "milestone", "conduit", 9500, "LF"),
    ("FE-A1-020", "Area 1 branch wire and devices", "FE", "A1", "2026-05-18", "2026-07-18", 3400, "milestone", "wire_branch", 42000, "LF"),
    ("FE-A1-030", "Area 1 lighting", "FE", "A1", "2026-06-22", "2026-08-08", 2200, "milestone", "lighting_fixture", 420, "EA"),
    ("FE-A2-010", "Area 2 overhead rough-in", "FE", "A2", "2026-05-04", "2026-07-11", 4600, "milestone", "conduit", 8800, "LF"),
    ("FE-A2-020", "Area 2 branch wire and devices", "FE", "A2", "2026-06-29", "2026-08-22", 3000, "milestone", "wire_branch", 36000, "LF"),
    ("FE-A2-030", "Area 2 lighting", "FE", "A2", "2026-07-27", "2026-09-05", 2000, "milestone", "lighting_fixture", 380, "EA"),
    ("FE-A3-010", "Area 3 overhead rough-in", "FE", "A3", "2026-06-15", "2026-08-15", 3600, "milestone", "conduit", 6900, "LF"),
    ("FE-A3-020", "Area 3 branch wire and devices", "FE", "A3", "2026-08-03", "2026-09-26", 2400, "milestone", "wire_branch", 28000, "LF"),
    ("FE-A3-030", "Area 3 lighting", "FE", "A3", "2026-09-01", "2026-10-10", 1500, "milestone", "lighting_fixture", 290, "EA"),
    ("FE-SITE-010", "Site lighting and feeders", "FE", "SITE", "2026-08-17", "2026-10-03", 1400, "milestone", "underground", 1800, "LF"),
    ("FE-ALL-090", "Equipment connections and testing", "FE", "ALL", "2026-09-14", "2026-11-07", 1800, "milestone", "equipment_connection", 64, "EA"),
    ("FE-ALL-095", "Temporary power maintenance", "FE", "ALL", "2026-03-09", "2026-11-14", 1000, "loe", None, 0, ""),
    ("FSS-ALL-010", "Fire alarm rough-in", "FSS", "ALL", "2026-04-20", "2026-07-25", 2400, "milestone", "conduit", 5200, "LF"),
    ("FSS-ALL-020", "Fire alarm devices and cabling", "FSS", "ALL", "2026-07-13", "2026-09-26", 2600, "milestone", "fire_alarm_device", 410, "EA"),
    ("FSS-ALL-030", "Fire alarm programming and test", "FSS", "ALL", "2026-09-28", "2026-11-07", 800, "percent", None, 0, ""),
    ("TEL-ALL-010", "Telecom pathways", "TEL", "ALL", "2026-05-04", "2026-07-18", 2000, "milestone", "cable_tray", 2600, "LF"),
    ("TEL-ALL-020", "Structured cabling — pull and terminate", "TEL", "ALL", "2026-07-20", "2026-10-03", 3400, "milestone", "telecom_drop", 1150, "EA"),
    ("TEL-ALL-030", "Fiber backbone", "TEL", "ALL", "2026-08-24", "2026-10-17", 900, "milestone", "fiber", 288, "STRAND"),
    ("TEL-ALL-040", "Test and certify", "TEL", "ALL", "2026-10-05", "2026-11-07", 600, "percent", None, 0, ""),
]

# per-activity execution: (start delay in workdays, duration factor, hours factor, progress factor)
EXECUTION: Dict[str, Tuple[int, float, float, float]] = {
    "FE-ER-010": (0, 1.05, 1.08, 1.00), "FE-ER-020": (2, 1.10, 1.12, 0.97), "FE-ER-030": (3, 1.10, 1.15, 0.96),
    "FE-A1-010": (0, 1.10, 1.12, 0.96), "FE-A1-020": (4, 1.15, 1.14, 0.95), "FE-A1-030": (4, 1.10, 1.10, 0.97),
    "FE-A2-010": (8, 1.15, 1.16, 0.94), "FE-A2-020": (10, 1.20, 1.15, 0.94), "FE-A2-030": (10, 1.15, 1.12, 0.95),
    "FE-A3-010": (10, 1.20, 1.18, 0.93), "FE-A3-020": (12, 1.20, 1.16, 0.93), "FE-A3-030": (12, 1.15, 1.12, 0.95),
    "FE-SITE-010": (5, 1.10, 1.10, 0.96), "FE-ALL-090": (10, 1.15, 1.12, 0.95), "FE-ALL-095": (0, 1.00, 1.05, 1.00),
    "FSS-ALL-010": (0, 1.00, 0.95, 1.00), "FSS-ALL-020": (3, 1.05, 0.96, 1.00), "FSS-ALL-030": (5, 1.05, 0.97, 1.00),
    "TEL-ALL-010": (0, 1.00, 1.02, 1.00), "TEL-ALL-020": (6, 1.08, 1.03, 0.99), "TEL-ALL-030": (4, 1.05, 1.02, 1.00),
    "TEL-ALL-040": (6, 1.05, 1.00, 1.00),
}

SUBCONTRACTS = {  # activity -> (discipline, raw cost before markup, number of invoices)
    "FE-SITE-010": ("FE", 120000.0 / 1.065, 3),
    "TEL-ALL-030": ("TEL", 45000.0 / 1.065, 2),
}


def _activities() -> List[Activity]:
    out = []
    for (aid, name, disc, area, start, finish, hours, method, commodity, _qty, _uom) in SCHEDULE:
        out.append(Activity(
            id=aid, name=name, discipline=disc, area=area,
            start=date.fromisoformat(start), finish=date.fromisoformat(finish),
            budget_hours=float(hours), hours_per_day=10.0,
            ev_method=EVMethod.parse(method), commodity=commodity,
        ))
    return out


def _milestone_progress(commodity: str, p: float) -> Tuple[List[str], Dict[str, float]]:
    """Fill a commodity's milestones in order until cumulative weight reaches ``p``."""
    rule = DEFAULT_RULES[commodity]
    achieved, partial = [], {}
    remaining = p
    for m in rule.milestones:
        if remaining >= m.weight - 1e-9:
            achieved.append(m.name)
            remaining -= m.weight
        elif remaining > 1e-9:
            partial[m.name] = remaining / m.weight
            remaining = 0.0
        else:
            break
    return achieved, partial


def generate(out_dir, seed: int = 7, data_date: date = DATA_DATE) -> Dict[str, Path]:
    """Write the example inputs into ``out_dir`` and return their paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)

    toml_path = out / "elecevm.toml"
    toml_path.write_text(template_toml(), encoding="utf-8")
    project = load_project(toml_path)
    work_cal, week_cal = project.work_cal, project.week_cal

    activities = _activities()
    schedule_path = out / "schedule.csv"
    baseline = build_baseline(project, activities)

    disc_hours = {d: sum(baseline.allocation[a.id] for a in activities if a.discipline == d) for d in project.disciplines}
    txns: List[CostTransaction] = []
    records: List[QuantityRecord] = []
    statused: List[Activity] = []

    for a in activities:
        delay, dur_factor, hrs_factor, prog_factor = EXECUTION[a.id]
        od = work_cal.workdays_between(a.start, a.finish)
        actual_start = work_cal.add_workdays(a.start, delay + 1) if delay else work_cal.roll_forward(a.start)
        actual_days = max(int(round(od * dur_factor)), 1)
        actual_finish = work_cal.add_workdays(actual_start, actual_days)
        days = work_cal.workday_dates(actual_start, actual_finish)
        total_hours = baseline.allocation[a.id] * hrs_factor
        rate = project.rate(a.discipline) * (1.03 if a.discipline == "FE" else 1.0)
        phase = PHASES[a.discipline]
        worked = [d for d in days if d <= data_date]

        # --- labor ---------------------------------------------------------
        for d in worked:
            hours = total_hours / len(days) * rng.uniform(0.85, 1.15)
            hours = round(hours, 2)
            amount = round(hours * rate * rng.uniform(0.98, 1.02), 2)
            txns.append(CostTransaction(d, CostType.LABOR, a.discipline, hours, amount, phase,
                                        posted_date=d + timedelta(days=rng.randint(0, 3)),
                                        description=f"Timesheet {a.id}", source="PR"))

        # --- material (three deliveries at 15/45/75% of the actual span) -----
        mat_bac = project.budget.bac(a.discipline, CostType.MATERIAL)
        share = baseline.allocation[a.id] / disc_hours[a.discipline] if disc_hours[a.discipline] else 0.0
        if a.ev_method is EVMethod.LOE:
            # temp power: small monthly consumables
            month_days = [d for d in days if d.day <= 6 and d.weekday() == 0 and d <= data_date]
            for d in month_days:
                txns.append(CostTransaction(d, CostType.MATERIAL, a.discipline, 0.0, round(mat_bac * share / 9 * rng.uniform(0.8, 1.2), 2),
                                            phase, posted_date=d + timedelta(days=2), description="Temp power consumables", source="AP"))
        else:
            for frac, portion in ((0.15, 0.35), (0.45, 0.35), (0.75, 0.30)):
                d = days[min(int(len(days) * frac), len(days) - 1)]
                if d <= data_date:
                    txns.append(CostTransaction(d, CostType.MATERIAL, a.discipline, 0.0,
                                                round(mat_bac * share * portion * rng.uniform(0.95, 1.08), 2), phase,
                                                posted_date=d + timedelta(days=rng.randint(1, 6)),
                                                description=f"Material delivery {a.id}", source="AP"))

        # --- subcontract --------------------------------------------------
        if a.id in SUBCONTRACTS:
            _disc, raw_total, n_inv = SUBCONTRACTS[a.id]
            for i in range(n_inv):
                d = days[min(int(len(days) * (i + 1) / (n_inv + 1)), len(days) - 1)]
                if d <= data_date:
                    txns.append(CostTransaction(d, CostType.SUBCONTRACT, a.discipline, 0.0, round(raw_total / n_inv, 2), phase,
                                                posted_date=d + timedelta(days=5), description=f"Sub invoice {i + 1} {a.id}", source="AP"))

        # --- weekly field quantities --------------------------------------
        total_qty = next(s[9] for s in SCHEDULE if s[0] == a.id)
        uom = next(s[10] for s in SCHEDULE if s[0] == a.id)
        status_week = week_cal.status_week(data_date)
        for w in range(1, status_week + 1):
            cutoff = week_cal.week_end(w)
            elapsed = len([d for d in days if d <= cutoff])
            if elapsed == 0:
                continue
            p = min(elapsed / len(days), 1.0) * prog_factor
            if elapsed >= len(days):
                p = 1.0
            if a.ev_method is EVMethod.LOE:
                continue
            if a.ev_method is EVMethod.PERCENT or not a.commodity:
                records.append(QuantityRecord(a.id, cutoff, None, a.name, uom, total_qty, total_qty * p,
                                              percent_complete=round(p, 4), reported_by="GF"))
            else:
                achieved, partial = _milestone_progress(a.commodity, p)
                records.append(QuantityRecord(a.id, cutoff, a.commodity, a.name, uom, total_qty,
                                              round(total_qty * p, 1), achieved, partial, reported_by="GF"))

        # --- statused schedule row ------------------------------------------
        statused.append(Activity(
            id=a.id, name=a.name, discipline=a.discipline, area=a.area, start=a.start, finish=a.finish,
            actual_start=(actual_start if worked else None),
            actual_finish=(actual_finish if actual_finish <= data_date else None),
            forecast_finish=(actual_finish if actual_finish > data_date else None),
            percent_complete=(1.0 if actual_finish <= data_date else (len(worked) / len(days) if worked else 0.0)),
            budget_hours=a.budget_hours, hours_per_day=a.hours_per_day, ev_method=a.ev_method, commodity=a.commodity,
        ))

    txns.sort(key=lambda t: (t.trans_date, t.phase, t.cost_type.value))
    write_activities_csv(schedule_path, statused)
    jobcost_path = out / "jobcost.csv"
    write_jobcost_csv(jobcost_path, txns, COST_TYPE_CODES)
    # the totals "as printed on the job-cost report", written independently of the engine's bucketing
    totals_path = out / "jobcost_totals.json"
    printed = {}
    for t in txns:
        printed.setdefault(t.cost_type.value, [0.0, 0.0])
        printed[t.cost_type.value][0] += t.hours
        printed[t.cost_type.value][1] += t.amount
    totals_path.write_text(json.dumps({k: [round(v[0], 2), round(v[1], 2)] for k, v in printed.items()}, indent=2),
                           encoding="utf-8")
    qty_path = out / "quantities.csv"
    write_quantities_csv(qty_path, records)
    return {"project": toml_path, "schedule": schedule_path, "jobcost": jobcost_path,
            "jobcost_totals": totals_path, "quantities": qty_path}


def run(out_dir, data_date: date = DATA_DATE, charts: bool = True) -> Dict[str, object]:
    """Build the baseline, backfill the status log through ``data_date`` and render the WSR."""
    from .actuals import apply_basis, bucket_transactions
    from .evm import compute_status
    from .report import render_html
    from .status_log import StatusLog
    out = Path(out_dir)
    project = load_project(out / "elecevm.toml")
    activities = activities_from_csv(out / "schedule.csv")
    transactions = read_jobcost_csv(out / "jobcost.csv", project)
    records = read_quantities_csv(out / "quantities.csv")

    baseline = build_baseline(project, activities, created=project.week_cal.start)
    baseline.save(out / "baseline.json")

    log_path = out / "status_log.jsonl"
    if log_path.exists():
        log_path.unlink()
    log = StatusLog(log_path)
    status_week = project.week_cal.status_week(data_date)
    snapshot = None
    printed_totals = {k: (v[0], v[1]) for k, v in json.loads((out / "jobcost_totals.json").read_text(encoding="utf-8")).items()}
    for w in range(1, status_week + 1):
        week_end = project.week_cal.week_end(w)
        # the whole pull is bucketed every week; lines after the week-end are held out of AC
        actuals = apply_basis(bucket_transactions(transactions, project.week_cal, w), project.ac_basis)
        snapshot = compute_status(project, baseline, activities, actuals, records, week_end,
                                  history=log.history(), source_totals=printed_totals,
                                  schedule_data_date=data_date)
        log.append(snapshot.to_record())
    assert snapshot is not None
    log.to_csv(out / "status_log.csv")
    (out / f"snapshot_wk{status_week:02d}.json").write_text(json.dumps(snapshot.to_dict(), indent=2), encoding="utf-8")
    html = render_html(
        snapshot, project.std_hours_per_week,
        {w: baseline.pv(w) for w in range(1, baseline.weeks + 1)},
        {w: baseline.weekly_hours(w) for w in range(1, baseline.weeks + 1)},
        project.thresholds, charts=charts)
    report_path = out / f"wsr_wk{status_week:02d}.html"
    report_path.write_text(html, encoding="utf-8")
    return {"project": project, "baseline": baseline, "snapshot": snapshot, "log": log, "report": report_path}
