"""Weekly Status Report rendering (RP §9.2).

Produces a self-contained HTML report with embedded PNG charts (matplotlib,
optional).  Colors are validated colorblind-safe defaults: PV blue, EV green,
AC orange; line style and direct labels carry identity as well as color.
"""
from __future__ import annotations

import base64
import html
import io
from datetime import date
from typing import Dict, List, Optional

from . import __version__
from .crew import smooth
from .evm import EAC_METHOD_LABELS, StatusSnapshot

COLORS = {
    "pv": "#2b5c9e",
    "ev": "#1b9e77",
    "ac": "#d95f02",
    "ink": "#1f2933",
    "muted": "#6b7280",
    "grid": "#e5e7eb",
    "surface": "#fcfcfb",
    "good": "#1b7f3b",
    "bad": "#b42318",
}


def _fmt_money(x: Optional[float]) -> str:
    if x is None:
        return "—"
    return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


def _fmt_hours(x: Optional[float]) -> str:
    return "—" if x is None else f"{x:,.0f}"


def _fmt_idx(x: Optional[float]) -> str:
    return "—" if x is None else f"{x:.2f}"


def _fmt_pct(x: Optional[float]) -> str:
    return "—" if x is None else f"{x:.1%}"


def _idx_class(x: Optional[float], threshold: float) -> str:
    if x is None:
        return ""
    return "bad" if x < threshold else "good"


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def _png(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight", facecolor=COLORS["surface"])
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _style(ax):
    ax.set_facecolor(COLORS["surface"])
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(COLORS["grid"])
    ax.tick_params(colors=COLORS["muted"], labelsize=8)
    ax.yaxis.grid(True, color=COLORS["grid"], linewidth=0.8)
    ax.set_axisbelow(True)


def cost_curve_png(snap: StatusSnapshot, baseline_pv_by_week: Dict[int, float], bac: float) -> Optional[str]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.ticker import FuncFormatter
    except ImportError:
        return None
    fig, ax = plt.subplots(figsize=(9, 4.2))
    _style(ax)
    weeks = sorted(baseline_pv_by_week)
    ax.plot(weeks, [baseline_pv_by_week[w] / 1e6 for w in weeks], color=COLORS["pv"], linewidth=2, label="PV (baseline)")
    ev_pts = [(p.week, p.ev / 1e6) for p in snap.weekly if p.ev is not None]
    if ev_pts:
        ax.plot([w for w, _ in ev_pts], [v for _, v in ev_pts], color=COLORS["ev"], linewidth=2,
                linestyle="--", marker="o", markersize=3, label="EV")
    ax.plot([p.week for p in snap.weekly], [p.ac / 1e6 for p in snap.weekly], color=COLORS["ac"],
            linewidth=2, linestyle="-.", label="AC")
    if snap.forecast_ac:
        fw = sorted(snap.forecast_ac)
        ax.plot([snap.status_week] + fw, [snap.ac / 1e6] + [snap.forecast_ac[w] / 1e6 for w in fw],
                color=COLORS["ac"], linewidth=1.5, linestyle=":", label="AC forecast")
    ax.axhline(snap.contracted_value / 1e6, color=COLORS["muted"], linewidth=1, linestyle=(0, (4, 3)))
    ax.text(weeks[0] if weeks else 1, snap.contracted_value / 1e6, f"  funding {_fmt_money(snap.contracted_value)}",
            fontsize=8, color=COLORS["muted"], va="bottom")
    ax.axvline(snap.status_week, color=COLORS["muted"], linewidth=1)
    ax.text(snap.status_week, ax.get_ylim()[1] * 0.98, f" status wk {snap.status_week}", fontsize=8,
            color=COLORS["muted"], va="top")
    if snap.crossover_week:
        ax.plot([snap.crossover_week], [snap.contracted_value / 1e6], marker="D", color=COLORS["ac"], markersize=7)
        ax.annotate(f"crossover wk {snap.crossover_week}", (snap.crossover_week, snap.contracted_value / 1e6),
                    xytext=(6, -14), textcoords="offset points", fontsize=8, color=COLORS["ac"])
    ax.set_xlabel("Payroll week", fontsize=9, color=COLORS["muted"])
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:,.1f}M"))
    ax.set_title("Cumulative cost performance", fontsize=11, color=COLORS["ink"], loc="left")
    ax.legend(frameon=False, fontsize=8, loc="upper left", bbox_to_anchor=(0.0, -0.12), ncol=4)
    out = _png(fig)
    plt.close(fig)
    return out


def manpower_png(snap: StatusSnapshot, std_hours: float, baseline_hours_by_week: Dict[int, float],
                 demand_by_week: Optional[Dict[int, float]] = None) -> Optional[str]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    fig, ax = plt.subplots(figsize=(9, 3.8))
    _style(ax)
    weeks = sorted(baseline_hours_by_week)
    planned = [baseline_hours_by_week[w] / std_hours for w in weeks]
    ax.bar(weeks, planned, color=COLORS["pv"], alpha=0.25, width=0.8, label="Planned crew (baseline)")
    if demand_by_week:
        dw = sorted(demand_by_week)
        ax.step(dw, [demand_by_week[w] / std_hours for w in dw], where="mid", color=COLORS["pv"], linewidth=1.2,
                linestyle="--", label="Schedule demand (unleveled)")
    actual = [p.actual_crew for p in snap.weekly]
    aw = [p.week for p in snap.weekly]
    ax.plot(aw, actual, color=COLORS["ac"], linewidth=1, alpha=0.6, label="Actual crew (weekly)")
    sm = smooth(actual, 4)
    ax.plot(aw, sm, color=COLORS["ac"], linewidth=2, label="Actual crew (4-wk avg)")
    earned = [(p.week, p.earned_crew) for p in snap.weekly if p.earned_crew is not None]
    if earned:
        ax.plot([w for w, _ in earned], [v for _, v in earned], color=COLORS["ev"], linewidth=0,
                marker="o", markersize=4, label="Earned crew")
    if snap.forecast_hours:
        fw = sorted(snap.forecast_hours)
        ax.plot(fw, [snap.forecast_hours[w] / std_hours for w in fw], color=COLORS["ac"], linewidth=1.5,
                linestyle=":", label="Forecast crew")
    ax.axvline(snap.status_week, color=COLORS["muted"], linewidth=1)
    ax.set_xlabel("Payroll week", fontsize=9, color=COLORS["muted"])
    ax.set_ylabel(f"Heads at {std_hours:g} hr/wk", fontsize=9, color=COLORS["muted"])
    ax.set_title("Field crew — planned, actual, earned", fontsize=11, color=COLORS["ink"], loc="left")
    ax.legend(frameon=False, fontsize=8, loc="upper left", bbox_to_anchor=(0.0, -0.16), ncol=3)
    out = _png(fig)
    plt.close(fig)
    return out


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

CSS = """
:root { --ink:#1f2933; --muted:#6b7280; --grid:#e5e7eb; --surface:#fcfcfb; --pv:#2b5c9e; --ev:#1b9e77; --ac:#d95f02;
        --good:#1b7f3b; --bad:#b42318; --band:#eef2f7; }
* { box-sizing: border-box; }
body { font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; color: var(--ink); background: var(--surface);
       margin: 0; padding: 24px; font-size: 13px; line-height: 1.4; }
h1 { font-size: 20px; margin: 0 0 4px; }
h2 { font-size: 14px; margin: 28px 0 8px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); }
.strip { display:flex; flex-wrap: wrap; gap: 18px; color: var(--muted); font-size: 12px; margin-bottom: 18px; }
.strip b { color: var(--ink); }
.tiles { display:grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }
.tile { background: var(--band); border-radius: 8px; padding: 10px 12px; }
.tile .l { font-size: 11px; color: var(--muted); }
.tile .v { font-size: 20px; font-weight: 600; margin-top: 2px; }
.tile .s { font-size: 11px; color: var(--muted); }
table { border-collapse: collapse; width: 100%; margin-top: 6px; }
th, td { padding: 6px 8px; border-bottom: 1px solid var(--grid); text-align: right; white-space: nowrap; }
th { font-weight: 600; color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .03em; }
td:first-child, th:first-child { text-align: left; }
td.text { text-align: left; white-space: normal; }
.good { color: var(--good); font-weight: 600; } .bad { color: var(--bad); font-weight: 600; }
.pass { color: var(--good); } .fail { color: var(--bad); font-weight: 600; }
img.chart { width: 100%; max-width: 980px; display: block; margin: 8px 0; }
.note { color: var(--muted); font-size: 12px; }
.small { font-size: 11px; }
footer { margin-top: 32px; color: var(--muted); font-size: 11px; border-top: 1px solid var(--grid); padding-top: 8px; }
@media print { body { padding: 12px; } h2 { page-break-after: avoid; } table { page-break-inside: auto; } }
"""


def render_html(snap: StatusSnapshot, std_hours: float, baseline_pv_by_week: Dict[int, float],
                baseline_hours_by_week: Dict[int, float], thresholds: Dict[str, float],
                report_no: Optional[int] = None, charts: bool = True,
                demand_by_week: Optional[Dict[int, float]] = None) -> str:
    esc = html.escape
    report_no = report_no or snap.status_week
    thr_spi, thr_cpi = thresholds.get("spi", 0.9), thresholds.get("cpi", 0.9)

    cost_png = cost_curve_png(snap, baseline_pv_by_week, snap.bac) if charts else None
    crew_png = manpower_png(snap, std_hours, baseline_hours_by_week, demand_by_week) if charts else None

    tiles = [
        ("% complete (EV ÷ BAC)", _fmt_pct(snap.pct_complete), f"spent {_fmt_pct(snap.pct_spent)}"),
        ("SPI / CPI ($)", f"<span class='{_idx_class(snap.spi, thr_spi)}'>{_fmt_idx(snap.spi)}</span> / "
                          f"<span class='{_idx_class(snap.cpi, thr_cpi)}'>{_fmt_idx(snap.cpi)}</span>", "dollars, cumulative"),
        ("Labor SPI / CPI (hrs)", f"<span class='{_idx_class(snap.spi_hours, thr_spi)}'>{_fmt_idx(snap.spi_hours)}</span> / "
                                  f"<span class='{_idx_class(snap.cpi_hours, thr_cpi)}'>{_fmt_idx(snap.cpi_hours)}</span>", "hours, cumulative"),
        ("EAC", _fmt_money(snap.eac), esc(EAC_METHOD_LABELS.get(snap.eac_selected_method, snap.eac_selected_method))),
        ("VAC (BAC − EAC)", f"<span class='{'bad' if snap.vac < 0 else 'good'}'>{_fmt_money(snap.vac)}</span>", f"ETC {_fmt_money(snap.etc)}"),
        ("Funding crossover", f"Wk {snap.crossover_week}" if snap.crossover_week else "none forecast",
         esc(f"w/e {snap.crossover_week_end}") if snap.crossover_week_end else f"exposure {_fmt_money(snap.funding_exposure)}"),
    ]
    tiles_html = "".join(f"<div class='tile'><div class='l'>{esc(l)}</div><div class='v'>{v}</div><div class='s'>{s}</div></div>"
                         for l, v, s in tiles)

    def evm_row(label, bac, pv, ev, ac, spi, cpi, money=True):
        f = _fmt_money if money else _fmt_hours
        return (f"<tr><td>{esc(label)}</td><td>{f(bac)}</td><td>{f(pv)}</td><td>{f(ev)}</td><td>{f(ac)}</td>"
                f"<td>{f(ev - pv)}</td><td>{f(ev - ac)}</td>"
                f"<td class='{_idx_class(spi, thr_spi)}'>{_fmt_idx(spi)}</td><td class='{_idx_class(cpi, thr_cpi)}'>{_fmt_idx(cpi)}</td></tr>")

    labor = [d for d in snap.disciplines]
    labor_bac = sum(d.bac for d in labor)
    evm_rows = evm_row("Total ($)", snap.bac, snap.pv, snap.ev, snap.ac, snap.spi, snap.cpi)
    evm_rows += evm_row("Labor (hours)", snap.bac_hours, snap.pv_hours, snap.ev_hours, snap.ac_hours,
                        snap.spi_hours, snap.cpi_hours, money=False)

    disc_rows = "".join(
        f"<tr><td>{esc(d.code)} — {esc(d.name)}</td><td>{_fmt_money(d.bac)}</td><td>{_fmt_pct(d.pct_complete)}</td>"
        f"<td>{_fmt_pct(d.pct_spent)}</td><td class='{_idx_class(d.spi, thr_spi)}'>{_fmt_idx(d.spi)}</td>"
        f"<td class='{_idx_class(d.cpi, thr_cpi)}'>{_fmt_idx(d.cpi)}</td>"
        f"<td>{_fmt_hours(d.bac_hours)}</td><td>{_fmt_hours(d.ev_hours)}</td><td>{_fmt_hours(d.ac_hours)}</td>"
        f"<td class='{_idx_class(d.spi_hours, thr_spi)}'>{_fmt_idx(d.spi_hours)}</td>"
        f"<td class='{_idx_class(d.cpi_hours, thr_cpi)}'>{_fmt_idx(d.cpi_hours)}</td>"
        f"<td>{_fmt_hours(d.eac_hours)}</td></tr>"
        for d in snap.disciplines)

    eac_rows = "".join(
        f"<tr><td>{esc(EAC_METHOD_LABELS.get(m, m))}{' <b>(reported)</b>' if m == snap.eac_selected_method else ''}</td>"
        f"<td>{_fmt_money(v)}</td><td>{_fmt_money(snap.bac - v)}</td></tr>"
        for m, v in snap.eac_methods.items())

    act_rows = "".join(
        f"<tr><td>{esc(e.activity_id)}</td><td class='text'>{esc(e.name)}</td><td>{esc(e.discipline)}</td><td>{esc(e.area)}</td>"
        f"<td>{esc(e.method)} / {esc('T' + e.tier if e.tier[:1].isdigit() else e.tier)}</td><td>{_fmt_pct(e.planned_fraction)}</td><td>{_fmt_pct(e.fraction)}</td>"
        f"<td>{_fmt_hours(e.budget_hours)}</td><td>{_fmt_hours(e.earned_hours)}</td><td class='text small'>{esc(e.note)}</td></tr>"
        for e in snap.activities)

    def _check_cell(c):
        if not c.ran:
            return "<td class='note'>NOT RUN</td>"
        return f"<td class='{'pass' if c.passed else 'fail'}'>{'PASS' if c.passed else 'FAIL'}</td>"
    check_rows = "".join(
        f"<tr><td>{esc(c.name)}</td>{_check_cell(c)}<td class='text small'>{esc(c.detail)}</td></tr>" for c in snap.checks)

    breaches = "".join(f"<li>{esc(b)}</li>" for b in snap.thresholds_breached) or "<li>None — all indices within thresholds</li>"
    notes = "".join(f"<li>{esc(n)}</li>" for n in snap.notes)

    charts_html = ""
    if cost_png:
        charts_html += f"<h2>Cost curve</h2><img class='chart' alt='Cumulative PV, EV, AC with funding line and forecast' src='data:image/png;base64,{cost_png}'>"
    if crew_png:
        charts_html += f"<h2>Manpower</h2><img class='chart' alt='Planned, actual and earned crew by week' src='data:image/png;base64,{crew_png}'>"

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>WSR {report_no} — {esc(snap.project)}</title><style>{CSS}</style></head>
<body>
<h1>Weekly Status Report No. {report_no}</h1>
<div class="strip">
  <span><b>{esc(snap.project)}</b></span>
  <span>Status week <b>{snap.status_week}</b> (w/e {esc(snap.week_end)})</span>
  <span>Data date <b>{esc(snap.data_date)}</b></span>
  <span>Basis <b>{esc(snap.basis)}</b> · baseline v{snap.basis_version}</span>
  <span>BAC <b>{_fmt_money(snap.bac)}</b> · contracted {_fmt_money(snap.contracted_value)}</span>
</div>
<div class="tiles">{tiles_html}</div>

<h2>Earned value summary</h2>
<table><thead><tr><th>Measure</th><th>BAC</th><th>PV</th><th>EV</th><th>AC</th><th>SV</th><th>CV</th><th>SPI</th><th>CPI</th></tr></thead>
<tbody>{evm_rows}</tbody></table>
<p class="note">TCPI to BAC {_fmt_idx(snap.tcpi_bac)} · TCPI to EAC {_fmt_idx(snap.tcpi_eac)} · indices below {thr_spi:.2f} / {thr_cpi:.2f} are flagged.</p>

{charts_html}

<h2>By discipline</h2>
<table><thead><tr><th>Discipline</th><th>BAC $</th><th>% complete</th><th>% spent</th><th>SPI $</th><th>CPI $</th>
<th>BAC hrs</th><th>Earned hrs</th><th>Actual hrs</th><th>SPI hrs</th><th>CPI hrs</th><th>EAC hrs</th></tr></thead>
<tbody>{disc_rows}</tbody></table>

<h2>Estimate at completion</h2>
<table><thead><tr><th>Method</th><th>EAC</th><th>VAC</th></tr></thead><tbody>{eac_rows}</tbody></table>
<p class="note">Reported EAC follows the project's selection rule; the statistical EAC (BAC ÷ CPI) is always shown alongside.</p>

<h2>Variance thresholds</h2><ul>{breaches}</ul>
{'<h2>Notes</h2><ul>' + notes + '</ul>' if notes else ''}

<h2>Activity earned value</h2>
<table><thead><tr><th>ID</th><th>Activity</th><th>Disc.</th><th>Area</th><th>Method / tier</th><th>Planned %</th><th>Earned %</th>
<th>Budget hrs</th><th>Earned hrs</th><th>Basis</th></tr></thead><tbody>{act_rows}</tbody></table>

<h2>Integrity checks</h2>
<table><thead><tr><th>Check</th><th>Result</th><th>Detail</th></tr></thead><tbody>{check_rows}</tbody></table>

<footer>Generated by elecevm {esc(__version__)} on {date.today().isoformat()} · Earned Value Management for Electrical Construction — Recommended Practice, Rev. 0</footer>
</body></html>
"""
