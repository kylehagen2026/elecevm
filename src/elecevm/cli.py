"""Command-line interface: ``elecevm init | baseline | status | backfill | report | check | example``."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import __version__
from .actuals import WeeklyActuals, apply_basis, bucket_transactions, restatements
from .allocation import Baseline, build_baseline
from .config import load_project, template_toml, to_date
from .evm import compute_status
from .ingest import activities_from_csv, activities_from_xer, read_jobcost_csv, read_jobcost_xlsx, read_quantities_csv, read_xer
from .models import CostType
from .report import render_html
from .status_log import LockedWeekError, StatusLog


# ---------------------------------------------------------------------------
# input helpers
# ---------------------------------------------------------------------------

def _load_inputs(args):
    project = load_project(args.project)
    schedule = Path(args.schedule)
    if schedule.suffix.lower() == ".xer":
        activities = activities_from_xer(read_xer(schedule))
    else:
        activities = activities_from_csv(schedule)
    return project, activities


def _load_jobcost(args, project):
    path = Path(args.jobcost)
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        return read_jobcost_xlsx(path, project)
    return read_jobcost_csv(path, project)


def _billed(args) -> Optional[Dict[CostType, float]]:
    billed = {}
    if getattr(args, "billed_labor", None) is not None:
        billed[CostType.LABOR] = float(args.billed_labor)
    if getattr(args, "billed_material", None) is not None:
        billed[CostType.MATERIAL] = float(args.billed_material)
    return billed or None


def parse_source_totals(text: Optional[str]) -> Optional[Dict[str, Tuple[float, float]]]:
    """``"L=43701.73:5884177.17,M=0:1200000"`` or a path to a JSON file ``{"L": [hours, amount], ...}``."""
    if not text:
        return None
    path = Path(text)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(k): (float(v[0]), float(v[1])) for k, v in data.items()}
    out: Dict[str, Tuple[float, float]] = {}
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        key, _, val = part.partition("=")
        hours, _, amount = val.partition(":")
        out[CostType.parse(key).value] = (float(hours or 0), float(amount or 0))
    return out or None


def _baseline_for(args, project, activities) -> Baseline:
    if getattr(args, "baseline", None):
        return Baseline.load(args.baseline)
    return build_baseline(project, activities, created=project.week_cal.start)


def _status_once(project, baseline, activities, transactions, records, data_date, log, args,
                 schedule_data_date=None, billed=None, source_totals=None):
    """Bucket the whole pull (post-status lines are held out), apply the AC basis and status."""
    status_week = project.week_cal.status_week(data_date)
    raw = bucket_transactions(transactions, project.week_cal, status_week)
    actuals = apply_basis(raw, project.ac_basis, billed)
    snapshot = compute_status(
        project, baseline, activities, actuals, records, data_date,
        history=log.history() if log else None,
        management_etc=(float(args.management_etc) if getattr(args, "management_etc", None) is not None else None),
        invoiced_fraction=(float(args.invoiced_pct) if getattr(args, "invoiced_pct", None) is not None else None),
        source_totals=source_totals, schedule_data_date=schedule_data_date)
    return snapshot, raw


def _print_summary(snap) -> None:
    def idx(x):
        return "—" if x is None else f"{x:.2f}"
    print(f"{snap.project} — status week {snap.status_week} (w/e {snap.week_end}), basis {snap.basis} v{snap.basis_version}")
    print(f"  PV {snap.pv:,.0f}  EV {snap.ev:,.0f}  AC {snap.ac:,.0f}   SPI {idx(snap.spi)}  CPI {idx(snap.cpi)}")
    print(f"  hours: PV {snap.pv_hours:,.0f}  EV {snap.ev_hours:,.0f}  AC {snap.ac_hours:,.0f}   SPI {idx(snap.spi_hours)}  CPI {idx(snap.cpi_hours)}")
    print(f"  EAC {snap.eac:,.0f} ({snap.eac_selected_method})  VAC {snap.vac:,.0f}  crossover wk {snap.crossover_week}")
    ran = [c for c in snap.checks if c.ran]
    failed = [c for c in ran if not c.passed]
    skipped = len(snap.checks) - len(ran)
    print(f"  checks: {len(ran) - len(failed)}/{len(ran)} pass" + (f", {skipped} not run" if skipped else "")
          + (f" — FAILED: {[c.name for c in failed]}" if failed else ""))
    for b in snap.thresholds_breached:
        print(f"  threshold: {b}")
    for n in snap.notes:
        print(f"  note: {n}")


def _pulls_dir(log_path) -> Path:
    d = Path(log_path).parent / "pulls"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _detect_late_postings(log: StatusLog, raw: WeeklyActuals, status_week: int) -> int:
    """Compare this pull with the most recent saved pull; log every restated locked week (RP §7.2)."""
    pulls = _pulls_dir(log.path)
    previous = sorted(pulls.glob("pull_wk*.json"))
    count = 0
    if previous:
        prev = WeeklyActuals.from_dict(json.loads(previous[-1].read_text(encoding="utf-8")))
        locked_through = min(prev.status_week, status_week - 1)
        for r in restatements(prev, raw, locked_through):
            log.annotate(r.week, f"late posting restated into week {r.week}: {r.discipline} {r.cost_type} "
                                 f"{r.delta_hours:+,.2f} h / {r.delta_amount:+,.2f}",
                         kind_detail="late_posting", discipline=r.discipline, cost_type=r.cost_type,
                         delta_hours=round(r.delta_hours, 2), delta_amount=round(r.delta_amount, 2))
            count += 1
    (pulls / f"pull_wk{status_week:02d}.json").write_text(json.dumps(raw.to_dict()), encoding="utf-8")
    return count


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def cmd_init(args) -> int:
    out = Path(args.dir)
    out.mkdir(parents=True, exist_ok=True)
    target = out / "elecevm.toml"
    if target.exists() and not args.force:
        print(f"{target} exists; use --force to overwrite", file=sys.stderr)
        return 1
    target.write_text(template_toml(), encoding="utf-8")
    print(f"wrote {target}\nnext: put schedule.csv (or .xer), jobcost.csv and quantities.csv beside it, then `elecevm baseline`")
    return 0


def cmd_baseline(args) -> int:
    project, activities = _load_inputs(args)
    baseline = build_baseline(project, activities, version=args.version, note=args.note, created=project.week_cal.start)
    baseline.save(args.out)
    print(f"baseline v{baseline.version} written to {args.out}: {len(baseline.allocation)} activities, "
          f"{baseline.total_bac_hours:,.0f} hrs, BAC {baseline.total_bac:,.0f}, {baseline.weeks} weeks, "
          f"terminal PV {baseline.terminal_pv:,.2f}" + (", leveled" if baseline.leveled else ""))
    return 0


def cmd_status(args) -> int:
    project, activities = _load_inputs(args)
    baseline = _baseline_for(args, project, activities)
    transactions = _load_jobcost(args, project)
    records = read_quantities_csv(args.quantities) if args.quantities else []
    data_date = to_date(args.data_date) or date.today()
    log = StatusLog(args.log) if args.log else None
    snapshot, raw = _status_once(project, baseline, activities, transactions, records, data_date, log, args,
                                 schedule_data_date=to_date(args.schedule_data_date), billed=_billed(args),
                                 source_totals=parse_source_totals(args.source_totals))
    if log is not None:
        if log.is_locked(snapshot.status_week) and not (args.restate and args.bcr):
            raise LockedWeekError(f"week {snapshot.status_week} is already statused; "
                                  f"restating it requires --restate and --bcr <reference>")
        if not snapshot.all_checks_pass and not args.allow_failed_checks:
            print("integrity checks failed; the week was NOT written to the log "
                  "(fix the data, or pass --allow-failed-checks to lock it with the failures recorded)", file=sys.stderr)
        else:
            late = _detect_late_postings(log, raw, snapshot.status_week)
            log.append(snapshot.to_record(), restate=args.restate, bcr=args.bcr)
            if late:
                print(f"  {late} late posting(s) restated into locked weeks and annotated in the log")
    if args.out:
        Path(args.out).write_text(json.dumps(snapshot.to_dict(), indent=2), encoding="utf-8")
    _print_summary(snapshot)
    return 0 if snapshot.all_checks_pass else 2


def cmd_backfill(args) -> int:
    project, activities = _load_inputs(args)
    baseline = _baseline_for(args, project, activities)
    transactions = _load_jobcost(args, project)
    records = read_quantities_csv(args.quantities) if args.quantities else []
    through = to_date(args.through) or date.today()
    log = StatusLog(args.log)
    last = project.week_cal.status_week(through)
    billed = _billed(args)
    totals = parse_source_totals(args.source_totals)
    done = 0
    snapshot = None
    for w in range(1, last + 1):
        if log.is_locked(w):
            continue
        week_end = project.week_cal.week_end(w)
        # billed-to-date figures and report totals describe the final pull only
        final = w == last
        snapshot, raw = _status_once(project, baseline, activities, transactions, records, week_end, log, args,
                                     schedule_data_date=to_date(args.schedule_data_date) or through,
                                     billed=billed if final else None, source_totals=totals if final else None)
        if not snapshot.all_checks_pass and not args.allow_failed_checks:
            print(f"week {w}: integrity checks failed; stopping before the log is written "
                  f"({[c.name for c in snapshot.checks if c.ran and not c.passed]})", file=sys.stderr)
            _print_summary(snapshot)
            return 2
        log.append(snapshot.to_record())
        if final:
            (_pulls_dir(log.path) / f"pull_wk{w:02d}.json").write_text(json.dumps(raw.to_dict()), encoding="utf-8")
        done += 1
    weeks = log.weeks()
    print(f"statused {done} week(s); log holds weeks {weeks[0] if weeks else '-'}..{weeks[-1] if weeks else '-'}")
    if snapshot is not None:
        _print_summary(snapshot)
    return 0


def cmd_report(args) -> int:
    project, activities = _load_inputs(args)
    baseline = _baseline_for(args, project, activities)
    transactions = _load_jobcost(args, project)
    records = read_quantities_csv(args.quantities) if args.quantities else []
    log = StatusLog(args.log) if args.log else None
    data_date = to_date(args.data_date) if args.data_date else None
    if data_date is None:
        if log is None or log.latest_week() is None:
            print("give --data-date or a --log with statused weeks", file=sys.stderr)
            return 1
        data_date = project.week_cal.week_end(log.latest_week())
    status_week = project.week_cal.status_week(data_date)

    class _History:  # the report week is recomputed; only earlier locked rows are history
        def history(self_inner):
            return {w: r for w, r in (log.history() if log else {}).items() if w < status_week}

    snapshot, _ = _status_once(project, baseline, activities, transactions, records, data_date, _History(), args,
                               schedule_data_date=to_date(args.schedule_data_date), billed=_billed(args),
                               source_totals=parse_source_totals(args.source_totals))
    html = render_html(snapshot, project.std_hours_per_week,
                       {w: baseline.pv(w) for w in range(1, baseline.weeks + 1)},
                       {w: baseline.weekly_hours(w) for w in range(1, baseline.weeks + 1)},
                       project.thresholds, report_no=args.number, charts=not args.no_charts,
                       demand_by_week=({w: baseline.weekly_demand(w) for w in range(1, baseline.weeks + 1)}
                                       if baseline.leveled else None))
    Path(args.out).write_text(html, encoding="utf-8")
    print(f"wrote {args.out}")
    _print_summary(snapshot)
    return 0


def cmd_check(args) -> int:
    """Run the integrity checks for a data date without writing to the log."""
    project, activities = _load_inputs(args)
    baseline = _baseline_for(args, project, activities)
    transactions = _load_jobcost(args, project)
    records = read_quantities_csv(args.quantities) if args.quantities else []
    data_date = to_date(args.data_date) or date.today()
    log = StatusLog(args.log) if args.log else None
    snapshot, _ = _status_once(project, baseline, activities, transactions, records, data_date, log, args,
                               schedule_data_date=to_date(args.schedule_data_date), billed=_billed(args),
                               source_totals=parse_source_totals(args.source_totals))
    if args.out:
        Path(args.out).write_text(json.dumps(snapshot.to_dict(), indent=2), encoding="utf-8")
    for c in snapshot.checks:
        state = "NOT RUN" if not c.ran else ("PASS" if c.passed else "FAIL")
        print(f"  [{state}] {c.name}: {c.detail}")
    _print_summary(snapshot)
    return 0 if snapshot.all_checks_pass else 2


def cmd_example(args) -> int:
    from . import example
    paths = example.generate(args.out, seed=args.seed)
    result = example.run(args.out, charts=not args.no_charts)
    snap = result["snapshot"]
    print(f"example written to {Path(args.out).resolve()}")
    print("  inputs: " + ", ".join(p.name for p in paths.values()))
    print(f"  outputs: baseline.json, status_log.jsonl, status_log.csv, {Path(result['report']).name}")
    _print_summary(snap)
    return 0


# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="elecevm", description="Earned value management engine for electrical construction")
    p.add_argument("--version", action="version", version=f"elecevm {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init", help="write an elecevm.toml template")
    s.add_argument("dir", nargs="?", default=".")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_init)

    def common(sp, jobcost=True, quantities=True, baseline=True):
        sp.add_argument("--project", required=True, help="elecevm.toml")
        sp.add_argument("--schedule", required=True, help="activities .csv or P6 .xer")
        if baseline:
            sp.add_argument("--baseline", help="baseline.json (default: build from the schedule)")
        if jobcost:
            sp.add_argument("--jobcost", required=True, help="job-cost detail export (.csv or .xlsx)")
            sp.add_argument("--source-totals", help="report totals to reconcile to: 'L=hours:amount,M=...' or a JSON file")
            sp.add_argument("--billed-labor", type=float, help="billed labor $ to date (billed AC basis)")
            sp.add_argument("--billed-material", type=float, help="billed material $ to date (billed AC basis)")
            sp.add_argument("--management-etc", type=float, help="bottom-up estimate to complete, $")
            sp.add_argument("--invoiced-pct", type=float, help="invoiced fraction 0–1 for Tier 3 activities")
            sp.add_argument("--schedule-data-date", help="date the schedule file was statused at (default: the data date)")
        if quantities:
            sp.add_argument("--quantities", help="field quantity tracker .csv")

    s = sub.add_parser("baseline", help="build and save the time-phased baseline")
    common(s, jobcost=False, quantities=False, baseline=False)
    s.add_argument("--out", default="baseline.json")
    s.add_argument("--version", dest="version", type=int, default=1)
    s.add_argument("--note", default="Initial baseline")
    s.set_defaults(func=cmd_baseline)

    s = sub.add_parser("status", help="status one week and append it to the log")
    common(s)
    s.add_argument("--data-date", required=True)
    s.add_argument("--log", help="status_log.jsonl (append)")
    s.add_argument("--out", help="write the full snapshot as JSON")
    s.add_argument("--restate", action="store_true", help="allow restating a locked week (needs --bcr)")
    s.add_argument("--bcr", help="baseline change request reference for a restatement")
    s.add_argument("--allow-failed-checks", action="store_true", help="lock the week even if integrity checks fail")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("backfill", help="status every unstatused week through a date")
    common(s)
    s.add_argument("--through", required=True, help="data date to status through")
    s.add_argument("--log", required=True)
    s.add_argument("--allow-failed-checks", action="store_true")
    s.set_defaults(func=cmd_backfill)

    s = sub.add_parser("report", help="render the Weekly Status Report (HTML)")
    common(s)
    s.add_argument("--log", help="status_log.jsonl for locked history")
    s.add_argument("--data-date", help="defaults to the latest week in the log")
    s.add_argument("--out", default="wsr.html")
    s.add_argument("--number", type=int, help="report number (default: status week)")
    s.add_argument("--no-charts", action="store_true")
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("check", help="run the integrity checks for a data date (exit 2 on failure)")
    common(s)
    s.add_argument("--data-date", required=True)
    s.add_argument("--log")
    s.add_argument("--out")
    s.set_defaults(func=cmd_check)

    s = sub.add_parser("example", help="generate and run the synthetic example project")
    s.add_argument("--out", default="elecevm-example")
    s.add_argument("--seed", type=int, default=7)
    s.add_argument("--no-charts", action="store_true")
    s.set_defaults(func=cmd_example)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except LockedWeekError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 3
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
