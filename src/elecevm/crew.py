"""Crew (headcount) analysis (RP §8.4)."""
from __future__ import annotations

from typing import List, Optional, Sequence


def headcount(hours: float, std_hours_per_week: float) -> float:
    """Equivalent heads for a week's hours at the standard hours-per-head."""
    if std_hours_per_week <= 0:
        return 0.0
    return hours / std_hours_per_week


def smooth(series: Sequence[Optional[float]], window: int = 4) -> List[Optional[float]]:
    """Trailing mean over ``window`` periods, skipping missing values."""
    out: List[Optional[float]] = []
    for i in range(len(series)):
        vals = [v for v in series[max(0, i - window + 1): i + 1] if v is not None]
        out.append(sum(vals) / len(vals) if vals else None)
    return out


def peak(series: Sequence[Optional[float]]) -> Optional[int]:
    """1-based index of the peak value, or None if the series is empty."""
    best, best_i = None, None
    for i, v in enumerate(series):
        if v is not None and (best is None or v > best):
            best, best_i = v, i + 1
    return best_i
