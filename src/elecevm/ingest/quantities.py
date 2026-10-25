"""Field quantity tracker ingest (RP §6.3).

CSV columns: ``activity_id, as_of, commodity, item, uom, total_qty, installed_qty,
milestones, milestone_progress, percent_complete, reported_by``.

* ``milestones`` — semicolon-separated names of fully achieved milestones
  (``supports;conduit_installed``)
* ``milestone_progress`` — ``name=fraction`` pairs for partially complete
  milestones (``pulled=0.6;terminated=0.2``)
* ``percent_complete`` — a field-reported percent (0–1 or 0–100) that
  overrides the quantity/milestone calculation (Tier 2b)
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, List

from ..config import to_date
from ..models import QuantityRecord

COLUMNS = ["activity_id", "as_of", "commodity", "item", "uom", "total_qty", "installed_qty",
           "milestones", "milestone_progress", "percent_complete", "reported_by"]


def _parse_progress(text: str) -> dict:
    out = {}
    for part in (text or "").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        try:
            out[name.strip().lower()] = float(value)
        except ValueError:
            continue
    return out


def read_quantities_csv(path) -> List[QuantityRecord]:
    out: List[QuantityRecord] = []
    with Path(path).open("r", newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            row = {k.strip().lower(): (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k}
            as_of = to_date(row.get("as_of"))
            if not row.get("activity_id") or as_of is None:
                continue
            pct = row.get("percent_complete")
            pct_value = None
            if pct not in (None, ""):
                pct_value = float(pct)
                if pct_value > 1.0:
                    pct_value /= 100.0
            out.append(QuantityRecord(
                activity_id=row["activity_id"], as_of=as_of,
                commodity=(row.get("commodity") or None), item=row.get("item", ""), uom=row.get("uom", ""),
                total_qty=float(row.get("total_qty") or 0.0), installed_qty=float(row.get("installed_qty") or 0.0),
                milestones=[m.strip() for m in (row.get("milestones") or "").split(";") if m.strip()],
                milestone_progress=_parse_progress(row.get("milestone_progress", "")),
                percent_complete=pct_value, reported_by=row.get("reported_by", ""),
            ))
    return out


def write_quantities_csv(path, records: Iterable[QuantityRecord]) -> None:
    with Path(path).open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for r in records:
            w.writerow({
                "activity_id": r.activity_id, "as_of": r.as_of.isoformat(), "commodity": r.commodity or "",
                "item": r.item, "uom": r.uom, "total_qty": f"{r.total_qty:g}", "installed_qty": f"{r.installed_qty:g}",
                "milestones": ";".join(r.milestones),
                "milestone_progress": ";".join(f"{k}={v:.4f}" for k, v in r.milestone_progress.items()),
                "percent_complete": "" if r.percent_complete is None else f"{r.percent_complete:.4f}",
                "reported_by": r.reported_by,
            })
