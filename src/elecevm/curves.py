"""Time-phasing shapes and leveling (RP §5.3–§5.4).

Every function here conserves its total exactly: shapes sum to 1.0 and
leveling or tapering never creates or loses an hour.
"""
from __future__ import annotations

from typing import Dict, List, Sequence


def normalize(weights: Sequence[float]) -> List[float]:
    total = float(sum(weights))
    if total <= 0:
        n = len(weights)
        return [1.0 / n] * n if n else []
    return [float(w) / total for w in weights]


def linear(n: int) -> List[float]:
    """Flat loading over ``n`` periods."""
    return [1.0 / n] * n if n > 0 else []


def bell(n: int, peak: float = 0.5, spread: float = 4.0) -> List[float]:
    """Bell-shaped loading over ``n`` periods (beta-distribution kernel).

    ``peak`` is the position of the peak in (0, 1); ``spread`` controls how
    concentrated the curve is (larger = more peaked).  This approximates the
    classic manpower-loading curve used in electrical estimating.
    """
    if n <= 0:
        return []
    if n == 1:
        return [1.0]
    peak = min(max(peak, 0.01), 0.99)
    a = 1.0 + spread * peak
    b = 1.0 + spread * (1.0 - peak)
    raw = []
    for k in range(n):
        x = (k + 0.5) / n
        raw.append((x ** (a - 1.0)) * ((1.0 - x) ** (b - 1.0)))
    return normalize(raw)


def trapezoid(n: int, ramp_up: float = 0.25, ramp_down: float = 0.25) -> List[float]:
    """Classic manpower trapezoid: linear ramp up, plateau, linear ramp down."""
    if n <= 0:
        return []
    if n == 1:
        return [1.0]
    up = max(0.0, min(ramp_up, 1.0))
    down = max(0.0, min(ramp_down, 1.0 - up))
    raw = []
    for k in range(n):
        x = (k + 0.5) / n
        if up > 0 and x < up:
            raw.append(x / up)
        elif down > 0 and x > 1.0 - down:
            raw.append((1.0 - x) / down)
        else:
            raw.append(1.0)
    return normalize(raw)


def scale_to_total(weights: Sequence[float], total: float) -> List[float]:
    """Scale ``weights`` so they sum to ``total`` exactly (residual on the last non-zero)."""
    w = normalize(weights)
    out = [x * total for x in w]
    if out:
        residual = total - sum(out)
        for i in range(len(out) - 1, -1, -1):
            if out[i] != 0 or i == 0:
                out[i] += residual
                break
    return out


def level_delay_only(series: Sequence[float], cap: float) -> List[float]:
    """Cap each period at ``cap`` and push the excess into later periods only.

    Work is never pulled earlier.  The series grows at the end until the carried
    excess is exhausted, so the total is conserved exactly.
    """
    if cap <= 0:
        raise ValueError("cap must be positive")
    out: List[float] = []
    carry = 0.0
    for value in series:
        avail = float(value) + carry
        take = min(avail, cap)
        out.append(take)
        carry = avail - take
    while carry > 1e-9:
        take = min(carry, cap)
        out.append(take)
        carry -= take
    return out


def level_by_group(weekly: Dict[int, Dict[str, float]], cap: float) -> Dict[int, Dict[str, float]]:
    """Delay-only leveling of a week → group → hours table under one shared cap.

    Each week's excess is carried forward *per group* in proportion to that
    group's share of the week, so every group's total is conserved.
    """
    if cap <= 0:
        raise ValueError("cap must be positive")
    if not weekly:
        return {}
    groups = sorted({g for w in weekly.values() for g in w})
    first, last = min(weekly), max(weekly)
    carry = {g: 0.0 for g in groups}
    out: Dict[int, Dict[str, float]] = {}
    week = first
    while week <= last or any(c > 1e-9 for c in carry.values()):
        demand = weekly.get(week, {})
        avail = {g: float(demand.get(g, 0.0)) + carry[g] for g in groups}
        total = sum(avail.values())
        if total <= cap:
            out[week] = {g: v for g, v in avail.items() if v > 0}
            carry = {g: 0.0 for g in groups}
        else:
            scale = cap / total
            out[week] = {g: v * scale for g, v in avail.items() if v > 0}
            carry = {g: avail[g] - avail[g] * scale for g in groups}
        week += 1
    return out


def taper_to_floor(total: float, n: int, start_rate: float, floor_rate: float) -> List[float]:
    """Spread ``total`` over ``n`` periods as an exponential taper from
    ``start_rate`` per period down to a ``floor_rate`` per period.

    The decay rate is solved so the periods sum to ``total`` exactly.  If
    ``total`` cannot be fitted between a flat ``floor_rate`` and a flat
    ``start_rate`` the function falls back to a flat ``total / n`` and the caller
    should treat that as a planning flag.
    """
    if n <= 0:
        return []
    if total <= 0:
        return [0.0] * n
    if floor_rate < 0 or start_rate <= 0:
        raise ValueError("rates must be non-negative, start_rate positive")
    if total <= n * floor_rate or total >= n * start_rate:
        return scale_to_total([1.0] * n, total)

    def series_for(rho: float) -> List[float]:
        return [max(start_rate * (rho ** k), floor_rate) for k in range(n)]

    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if sum(series_for(mid)) < total:
            lo = mid
        else:
            hi = mid
    return scale_to_total(series_for((lo + hi) / 2.0), total)


def cumulative(series: Sequence[float]) -> List[float]:
    out: List[float] = []
    running = 0.0
    for v in series:
        running += float(v)
        out.append(running)
    return out
