"""Schedule ingest: Primavera P6 XER files and activity CSVs (RP §12).

The XER reader is a plain parser of P6's tab-delimited export (``%T`` table,
``%F`` field names, ``%R`` rows).  Activities are built from the ``TASK`` table;
durations are converted from hours to workdays with ``hours_per_day`` (P6 stores
``target_drtn_hr_cnt`` in hours).  Discipline and area come from a resolver
callback so each contractor can map its own activity-ID convention, activity
codes or WBS names; the default takes the prefix before the first ``-`` of the
activity ID as the discipline and the second token as the area.
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from ..config import to_date
from ..models import Activity, EVMethod

Resolver = Callable[[str, str, str], Dict[str, str]]

CSV_COLUMNS = ["id", "name", "discipline", "area", "start", "finish", "actual_start", "actual_finish",
               "forecast_finish", "original_duration", "percent_complete", "budget_hours", "hours_per_day",
               "area_weight", "activity_factor", "ev_method", "commodity", "base_activity"]


def default_resolver(task_code: str, task_name: str, wbs_name: str) -> Dict[str, str]:
    parts = task_code.split("-")
    return {"discipline": parts[0] if parts else task_code, "area": parts[1] if len(parts) > 2 else ""}


def read_xer(path) -> Dict[str, List[Dict[str, str]]]:
    """Parse an XER file into ``{table_name: [row dict, ...]}``."""
    tables: Dict[str, List[Dict[str, str]]] = {}
    current: Optional[str] = None
    fields: List[str] = []
    with Path(path).open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.rstrip("\r\n")
            if not line:
                continue
            tag, _, rest = line.partition("\t")
            if tag == "%T":
                current = rest.strip()
                tables.setdefault(current, [])
                fields = []
            elif tag == "%F":
                fields = rest.split("\t")
            elif tag == "%R" and current is not None:
                values = rest.split("\t")
                tables[current].append({f: (values[i] if i < len(values) else "") for i, f in enumerate(fields)})
            elif tag == "%E":
                break
    return tables


def _float(value, default=None):
    try:
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def activities_from_xer(tables: Dict[str, List[Dict[str, str]]], resolver: Optional[Resolver] = None,
                        hours_per_day: float = 8.0, hours_per_day_field: float = 10.0,
                        include_milestones: bool = False) -> List[Activity]:
    """Build activities from the TASK table (plus PROJWBS names and TASKRSRC hours)."""
    resolver = resolver or default_resolver
    wbs_names = {r.get("wbs_id"): r.get("wbs_name", "") for r in tables.get("PROJWBS", [])}
    # labor hours only: join TASKRSRC to RSRC and keep labor resources (RT_Labor); when the RSRC
    # table is absent every assignment is assumed to be labor
    rsrc_types = {r.get("rsrc_id"): r.get("rsrc_type", "RT_Labor") for r in tables.get("RSRC", [])}
    rsrc_hours: Dict[str, float] = {}
    for r in tables.get("TASKRSRC", []):
        rtype = rsrc_types.get(r.get("rsrc_id"), "RT_Labor") if rsrc_types else "RT_Labor"
        if rtype != "RT_Labor":
            continue
        rsrc_hours[r.get("task_id", "")] = rsrc_hours.get(r.get("task_id", ""), 0.0) + (_float(r.get("target_qty"), 0.0) or 0.0)

    out: List[Activity] = []
    for r in tables.get("TASK", []):
        task_type = r.get("task_type", "TT_Task")
        if task_type == "TT_WBS":          # WBS summary rows carry no scope of their own
            continue
        if not include_milestones and task_type in {"TT_Mile", "TT_FinMile"}:
            continue
        code = r.get("task_code", "")
        name = r.get("task_name", "")
        meta = resolver(code, name, wbs_names.get(r.get("wbs_id"), ""))
        start = to_date(r.get("act_start_date") or r.get("target_start_date") or r.get("early_start_date"))
        finish = to_date(r.get("target_end_date") or r.get("early_end_date"))
        if start is None or finish is None:
            continue
        od_hours = _float(r.get("target_drtn_hr_cnt"), None)
        od = int(round(od_hours / hours_per_day)) if od_hours else None
        pct = (_float(r.get("phys_complete_pct"), 0.0) or 0.0) / 100.0
        hrs = rsrc_hours.get(r.get("task_id", "")) or None
        out.append(Activity(
            id=code, name=name, discipline=meta.get("discipline", code), area=meta.get("area", ""),
            start=to_date(r.get("target_start_date")) or start, finish=finish,
            actual_start=to_date(r.get("act_start_date")), actual_finish=to_date(r.get("act_end_date")),
            forecast_finish=to_date(r.get("early_end_date")) if not r.get("act_end_date") else None,
            original_duration=od, percent_complete=pct, budget_hours=hrs, hours_per_day=hours_per_day_field,
            ev_method=EVMethod.parse(meta.get("ev_method", "loe" if task_type == "TT_LOE" else "quantity")),
            commodity=meta.get("commodity"),
        ))
    return out


def activities_from_csv(path, resolver: Optional[Resolver] = None) -> List[Activity]:
    """Read activities from a CSV with the columns in :data:`CSV_COLUMNS` (extra columns ignored)."""
    out: List[Activity] = []
    with Path(path).open("r", newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            row = {k.strip().lower(): (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k}
            code = row.get("id") or row.get("activity_id") or row.get("task_code")
            if not code:
                continue
            meta = {}
            if resolver and not row.get("discipline"):
                meta = resolver(code, row.get("name", ""), row.get("wbs", ""))
            start, finish = to_date(row.get("start")), to_date(row.get("finish"))
            if start is None or finish is None:
                raise ValueError(f"activity {code}: start and finish are required")
            od = row.get("original_duration")
            pct = _float(row.get("percent_complete"), 0.0) or 0.0
            if pct > 1.0:
                pct = pct / 100.0
            out.append(Activity(
                id=code, name=row.get("name", code),
                discipline=row.get("discipline") or meta.get("discipline", code),
                area=row.get("area") or meta.get("area", ""),
                start=start, finish=finish,
                actual_start=to_date(row.get("actual_start")), actual_finish=to_date(row.get("actual_finish")),
                forecast_finish=to_date(row.get("forecast_finish")),
                original_duration=int(float(od)) if od else None,
                percent_complete=pct,
                budget_hours=_float(row.get("budget_hours"), None),
                hours_per_day=_float(row.get("hours_per_day"), 10.0) or 10.0,
                area_weight=_float(row.get("area_weight"), 1.0) or 1.0,
                activity_factor=_float(row.get("activity_factor"), 1.0) or 1.0,
                ev_method=EVMethod.parse(row.get("ev_method") or "quantity"),
                commodity=(row.get("commodity") or None),
                base_activity=(row.get("base_activity") or None),
            ))
    return out


def write_activities_csv(path, activities: Iterable[Activity]) -> None:
    with Path(path).open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for a in activities:
            w.writerow({
                "id": a.id, "name": a.name, "discipline": a.discipline, "area": a.area,
                "start": a.start.isoformat(), "finish": a.finish.isoformat(),
                "actual_start": a.actual_start.isoformat() if a.actual_start else "",
                "actual_finish": a.actual_finish.isoformat() if a.actual_finish else "",
                "forecast_finish": a.forecast_finish.isoformat() if a.forecast_finish else "",
                "original_duration": a.original_duration if a.original_duration is not None else "",
                "percent_complete": f"{a.percent_complete:.4f}",
                "budget_hours": f"{a.budget_hours:.2f}" if a.budget_hours is not None else "",
                "hours_per_day": a.hours_per_day, "area_weight": a.area_weight,
                "activity_factor": a.activity_factor, "ev_method": a.ev_method.value,
                "commodity": a.commodity or "", "base_activity": a.base_activity or "",
            })
