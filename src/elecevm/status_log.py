"""Locked status history (RP §9.1, Appendix B).

The status log is an append-only JSON-lines file.  Each line is one statused
week.  A week that has been statused is never rewritten in place: a restatement
appends a new record that names the baseline change request that justified it
and marks the earlier record as superseded.  Annotations (basis changes, pull
dates, notes) are appended as their own records and never alter numbers.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


class LockedWeekError(RuntimeError):
    """Raised when a statused week would be overwritten without a BCR."""


class StatusLog:
    def __init__(self, path) -> None:
        self.path = Path(path)
        self.records: List[dict] = []
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    self.records.append(json.loads(line))

    # -- queries ---------------------------------------------------------
    def status_records(self) -> List[dict]:
        return [r for r in self.records if r.get("kind", "status") == "status"]

    def history(self) -> Dict[int, dict]:
        """Latest effective record per week (superseded records excluded)."""
        out: Dict[int, dict] = {}
        for r in self.status_records():
            out[int(r["week"])] = r
        return out

    def weeks(self) -> List[int]:
        return sorted(self.history())

    def latest_week(self) -> Optional[int]:
        weeks = self.weeks()
        return weeks[-1] if weeks else None

    def get(self, week: int) -> Optional[dict]:
        return self.history().get(int(week))

    def is_locked(self, week: int) -> bool:
        return int(week) in self.history()

    def annotations(self, week: Optional[int] = None) -> List[dict]:
        return [r for r in self.records if r.get("kind") == "annotation" and (week is None or r.get("week") == week)]

    # -- writes ----------------------------------------------------------
    def _write(self, record: dict) -> None:
        record = dict(record)
        record.setdefault("logged_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
        self.records.append(record)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")

    def append(self, record: dict, restate: bool = False, bcr: Optional[str] = None) -> dict:
        """Append a week's status record.

        A week already in the log is locked: appending it again raises
        :class:`LockedWeekError` unless ``restate=True`` and a ``bcr`` reference
        is supplied, in which case the new record carries ``restates`` and the
        old one stays in the file as history.
        """
        week = int(record["week"])
        record = dict(record)
        record["kind"] = "status"
        if self.is_locked(week):
            if not restate or not bcr:
                raise LockedWeekError(
                    f"week {week} is already statused; restating it requires restate=True and a BCR reference")
            record["restates"] = True
            record["bcr"] = bcr
        self._write(record)
        return record

    def annotate(self, week: Optional[int], note: str, **extra) -> dict:
        record = {"kind": "annotation", "week": week, "note": note}
        record.update(extra)
        self._write(record)
        return record

    # -- export ----------------------------------------------------------
    def to_csv(self, path, fields: Optional[List[str]] = None) -> None:
        import csv

        fields = fields or ["week", "week_end", "data_date", "basis_version", "pv", "ev", "ac",
                            "pv_hours", "ev_hours", "ac_hours", "spi", "cpi", "spi_hours", "cpi_hours",
                            "bac", "eac", "etc", "vac", "crossover_week"]
        with Path(path).open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for week in self.weeks():
                writer.writerow(self.history()[week])
