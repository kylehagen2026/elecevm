"""Job-cost ingest for Vista-style JC Detail exports (CSV or XLSX) (RP §7, §12).

The expected export is one row per ledger transaction.  Column names are
matched case-insensitively against the defaults below and can be overridden
with ``columns={"date": "Trans Date", ...}``.  Discipline comes from a
``Discipline`` column when present, otherwise from the project's
``[phase_map]`` (longest prefix match on the phase/cost code).  The ledger
cost type is mapped through ``[cost_type_map]``.

Vista prints JC Detail as a Crystal report; export it to Excel/CSV with the
detail rows, or convert the PDF with a table extractor before ingest.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from ..config import Project, to_date
from ..models import CostTransaction

DEFAULT_COLUMNS = {
    "phase": ["phase", "phase code", "cost code", "costcode", "phasecode"],
    "cost_type": ["costtype", "cost type", "ct"],
    "date": ["date", "trans date", "transdate", "transaction date", "actual date", "actualdate"],
    "posted": ["posteddate", "posted date", "post date", "postdate", "posted"],
    "hours": ["hours", "actual hours", "actualhours", "hrs"],
    "amount": ["amount", "actual cost", "actualcost", "cost", "actual $"],
    "description": ["description", "desc", "memo"],
    "discipline": ["discipline", "disc"],
    "source": ["source", "src", "jcsource"],
}


def _resolve_columns(header: List[str], overrides: Optional[Dict[str, str]]) -> Dict[str, Optional[str]]:
    lower = {h.strip().lower(): h for h in header}
    out: Dict[str, Optional[str]] = {}
    for key, candidates in DEFAULT_COLUMNS.items():
        chosen = None
        if overrides and key in overrides:
            chosen = overrides[key]
        else:
            for c in candidates:
                if c in lower:
                    chosen = lower[c]
                    break
        out[key] = chosen
    return out


def _to_float(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("$", "")
    if not text or text in {"-", "—"}:
        return 0.0
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    return float(text)


def rows_to_transactions(rows: Iterable[dict], project: Project,
                         columns: Optional[Dict[str, str]] = None,
                         strict: bool = True) -> List[CostTransaction]:
    rows = list(rows)
    if not rows:
        return []
    cols = _resolve_columns(list(rows[0].keys()), columns)
    for required in ("phase", "cost_type", "date", "amount"):
        if cols[required] is None:
            raise ValueError(f"job-cost export is missing a '{required}' column; pass columns={{'{required}': '<name>'}}")
    out: List[CostTransaction] = []
    unmapped: set = set()
    undated = 0
    for row in rows:
        phase = str(row.get(cols["phase"], "")).strip()
        if not phase and not str(row.get(cols["amount"], "")).strip():
            continue
        disc = str(row.get(cols["discipline"], "")).strip() if cols["discipline"] else ""
        if not disc:
            disc = project.map_phase(phase) or ""
        if not disc:
            unmapped.add(phase)
            if strict:
                continue
            disc = "UNMAPPED"
        try:
            trans_date = to_date(row.get(cols["date"]))
        except ValueError:
            trans_date = None
        if trans_date is None:
            undated += 1
            continue
        out.append(CostTransaction(
            trans_date=trans_date,
            cost_type=project.map_cost_type(row.get(cols["cost_type"])),
            discipline=disc,
            hours=_to_float(row.get(cols["hours"])) if cols["hours"] else 0.0,
            amount=_to_float(row.get(cols["amount"])),
            phase=phase,
            posted_date=to_date(row.get(cols["posted"])) if cols["posted"] else None,
            description=str(row.get(cols["description"], "")) if cols["description"] else "",
            source=str(row.get(cols["source"], "")) if cols["source"] else "",
        ))
    if unmapped and strict:
        raise ValueError(f"ledger phases with no discipline mapping (add them to [phase_map]): {sorted(unmapped)}")
    if undated and strict:
        raise ValueError(f"{undated} ledger row(s) have a missing or unreadable transaction date; "
                         f"fix the export or pass strict=False to drop them")
    return out


def read_jobcost_csv(path, project: Project, columns: Optional[Dict[str, str]] = None,
                     strict: bool = True) -> List[CostTransaction]:
    with Path(path).open("r", newline="", encoding="utf-8-sig") as fh:
        return rows_to_transactions(csv.DictReader(fh), project, columns, strict)


def read_jobcost_xlsx(path, project: Project, sheet: Optional[str] = None,
                      columns: Optional[Dict[str, str]] = None, strict: bool = True) -> List[CostTransaction]:
    try:
        import openpyxl  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise ImportError("reading .xlsx needs openpyxl: pip install 'elecevm[xlsx]'") from exc
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet] if sheet else wb.active
    rows_iter = ws.iter_rows(values_only=True)
    header = [str(h).strip() if h is not None else "" for h in next(rows_iter)]
    rows = [dict(zip(header, r)) for r in rows_iter if any(v not in (None, "") for v in r)]
    return rows_to_transactions(rows, project, columns, strict)


def source_totals(transactions: Iterable[CostTransaction]) -> Dict[str, Tuple[float, float]]:
    """Totals by cost type value, as a job-cost report would print them."""
    out: Dict[str, List[float]] = {}
    for t in transactions:
        ct = t.cost_type.value
        out.setdefault(ct, [0.0, 0.0])
        out[ct][0] += float(t.hours)
        out[ct][1] += float(t.amount)
    return {ct: (v[0], v[1]) for ct, v in out.items()}


def write_jobcost_csv(path, transactions: Iterable[CostTransaction], cost_type_codes: Optional[Dict[str, str]] = None) -> None:
    """Write transactions in the default export layout (used by the example generator)."""
    codes = cost_type_codes or {}
    with Path(path).open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Phase", "CostType", "Date", "PostedDate", "Hours", "Amount", "Description", "Source"])
        for t in transactions:
            w.writerow([t.phase, codes.get(t.cost_type.value, t.cost_type.value), t.trans_date.isoformat(),
                        t.posted_date.isoformat() if t.posted_date else "", f"{t.hours:.2f}", f"{t.amount:.2f}",
                        t.description, t.source])
