# elecevm — earned value for electrical construction

**elecevm** is an open earned-value management (EVM) engine for electrical specialty
contractors. It is the reference implementation of
[*Earned Value Management for Electrical Construction — A Recommended Practice for
Specialty Contractors*](docs/standard.md), which adapts ANSI/EIA-748 to how trade
contractors actually run work: labor-hour-driven scope, weekly payroll statusing,
a CPM schedule owned by the CM, and a job-cost ledger that was never designed to
feed an EVM system.

It takes three things every contractor already has — the schedule, the job-cost
detail, and what the foremen installed this week — and produces defensible
planned value, earned value, actual cost, indices, estimates at completion, a
funding-crossover forecast and a Weekly Status Report, with every number tied
back to its source and every statused week locked.

Pure Python 3.11+, no required dependencies. Charts and `.xlsx` ingest are optional extras.

## Why

Electrical contractors keep cost in Vista, Spectrum or Sage and schedules in P6,
and the two never meet. EVM practice lives at the owner/CM level and in defense
work; specialty trades get a percent-complete column and a gut feel. This engine
makes the connection reproducible:

- **Planned value** from a cost-loaded copy of your own activities, allocated from
  the estimate so that every discipline ties exactly and terminal PV equals BAC.
- **Earned value** from field quantities through published electrical rules of
  credit (conduit, feeders, gear, fixtures, fire alarm, telecom, instrumentation …),
  with measurement tiers so an invoiced percent is never mistaken for a physical one.
- **Actual cost** bucketed by transaction date to payroll weeks, reconciled to the
  job-cost report to the cent, with declared basis rules per cost type (raw,
  marked-up, or billed with a residual week).
- **Analysis** on dollars *and* labor hours — the hours indices are what the field
  can act on — plus every EAC method with one selected by rule, TCPI, thresholds,
  crew curves and the week the AC curve crosses the funding line.
- **A locked status log.** Statused weeks are never rewritten; restatements carry a
  baseline change request and the old record stays in the file.
- **Thirteen integrity checks** on every run (terminal PV = BAC, allocation ties,
  hours conserved, AC reconciles, EV ≤ BAC, history contiguous, CO log ties, EAC
  not below statistical, every activity in the baseline …). A run that fails a check says so and exits non-zero.

## Install

```bash
pip install elecevm              # core
pip install "elecevm[charts]"    # + matplotlib for the report charts
pip install "elecevm[xlsx]"      # + openpyxl for .xlsx job-cost exports
```

From a checkout: `pip install -e ".[dev]"` then `pytest`.

## Try it in one command

```bash
elecevm example --out elecevm-example
```

This writes a synthetic distribution-center electrical project (22 activities,
three disciplines, ~960 ledger lines, weekly field quantities), builds the
baseline, statuses 26 payroll weeks into a locked log and renders
`wsr_wk26.html` — a Weekly Status Report with the cost curve, crew chart,
discipline table, EAC methods, activity earned value and the integrity checks.
The same inputs and outputs are committed under [`examples/distribution-center`](examples/distribution-center).

## Using it on a project

```text
project/
├── elecevm.toml      # calendars, disciplines, budget on two bases, CO log, AC basis rules
├── schedule.csv      # or a P6 .xer export
├── jobcost.csv       # Vista-style JC Detail export (.csv or .xlsx)
└── quantities.csv    # weekly field progress by activity
```

```bash
elecevm init project/                     # writes a commented elecevm.toml
elecevm baseline --project elecevm.toml --schedule schedule.csv --out baseline.json
elecevm status   --project elecevm.toml --schedule schedule.csv --baseline baseline.json \
                 --jobcost jobcost.csv --quantities quantities.csv \
                 --data-date 2026-09-05 --log status_log.jsonl --out snapshot.json
elecevm report   --project elecevm.toml --schedule schedule.csv --baseline baseline.json \
                 --jobcost jobcost.csv --quantities quantities.csv --log status_log.jsonl --out wsr.html
elecevm check    ...                      # integrity checks only, exit 2 on failure
elecevm backfill ... --through 2026-09-05 # status every unstatused week into the log
```

Options worth knowing: `--source-totals "L=hours:amount,M=...,S=..."` (or a JSON
file) gives the totals printed on the job-cost report so check 5 can reconcile the
pull against something independent — without it the check is reported as NOT RUN;
`--billed-labor` / `--billed-material` supply billed-to-date values for the
*billed* AC basis; `--management-etc` supplies a bottom-up estimate to complete so
the reported EAC can follow the `max(management, BAC/CPI)` rule; `--invoiced-pct`
feeds Tier 3 activities; `--schedule-data-date` tells a backfill when the schedule
file was statused so earlier weeks are interpolated rather than taking a later
percent complete.

A week whose checks fail is **not** written to the log (pass
`--allow-failed-checks` to lock it with the failures recorded). Each `status`
saves the raw pull under `pulls/` beside the log; the next status compares the
two and annotates any late posting into a locked week (RP §7.2) instead of
rewriting that week's row.

### Inputs

**`elecevm.toml`** — see [`src/elecevm/config.py`](src/elecevm/config.py) (`template_toml()`)
for the commented schema: project start and payroll week-ending day, work calendar
and holidays, standard hours per head per week, contracted value (the funding line),
reporting basis (`contracted` or `estimated`), disciplines with composite rates,
budget by discipline × cost type on each basis, the change-order log, AC basis per
cost type, EAC policy and thresholds, optional crew-cap leveling, and the
phase → discipline and cost-type maps for the ledger.

**Schedule** — a CSV with `id, name, discipline, area, start, finish, actual_start,
actual_finish, forecast_finish, original_duration, percent_complete, budget_hours,
hours_per_day, area_weight, activity_factor, ev_method, commodity, base_activity`,
or a P6 `.xer` (TASK/PROJWBS/TASKRSRC tables; discipline and area resolved from the
activity ID by default, pluggable).

**Job cost** — one row per ledger transaction with phase/cost code, cost type,
transaction date, posted date, hours, amount. Column names are matched
case-insensitively; disciplines come from `[phase_map]`, cost classes from
`[cost_type_map]`.

**Quantities** — `activity_id, as_of, commodity, item, uom, total_qty,
installed_qty, milestones, milestone_progress, percent_complete, reported_by`.
Milestones are the names in the rule of credit (`layout;supports`), partial
progress is `name=fraction` (`conduit_installed=0.4`).

### Python API

```python
from datetime import date
from elecevm import load_project, build_baseline, bucket_transactions, apply_basis, compute_status, StatusLog
from elecevm.ingest import activities_from_csv, read_jobcost_csv, read_quantities_csv, source_totals

project    = load_project("elecevm.toml")
activities = activities_from_csv("schedule.csv")
baseline   = build_baseline(project, activities, created=project.week_cal.start)
txns       = read_jobcost_csv("jobcost.csv", project)
records    = read_quantities_csv("quantities.csv")

data_date = date(2026, 9, 5)
week      = project.week_cal.status_week(data_date)
actuals   = apply_basis(bucket_transactions(txns, project.week_cal, week), project.ac_basis)
log       = StatusLog("status_log.jsonl")
snap      = compute_status(project, baseline, activities, actuals, records, data_date,
                           history=log.history(), source_totals=source_totals(txns))
log.append(snap.to_record())
print(snap.spi_hours, snap.cpi_hours, snap.eac, snap.crossover_week, snap.all_checks_pass)
```

## How the engine maps to the Recommended Practice

| RP section | Module |
| --- | --- |
| §4 Control structure, bases, calendars | `config.py`, `models.py`, `calendar.py` |
| §5 Cost-loaded schedule and PV, leveling, baseline control | `allocation.py`, `curves.py` |
| §6 EV measurement tiers and electrical rules of credit | `rules_of_credit.py`, `evm.py` |
| §7 Actual cost bucketing, basis rules, reconciliation, late postings | `actuals.py` |
| §8 Indices, EAC selection, funding crossover, crew | `evm.py`, `crew.py` |
| §9 Locked status log and the WSR | `status_log.py`, `report.py` |
| §11 Integrity checks | `evm.health_checks` |
| §12 Data pulls | `ingest/` |

## Calibrate, don't copy

The rules of credit ship with default milestone weights. They are a reasonable
published starting point, not your labor-unit distribution. The practice asks
each contractor to calibrate the weights to its own estimating data and record
the calibrated set with the project; a future release will accept a custom
rules table in `elecevm.toml`.

## Known limitations in 0.1.0

- Rules of credit are the shipped defaults; a custom table in `elecevm.toml` is the next release.
- The billed AC basis takes one billed-to-date figure per cost type for the status week; a backfill applies it to the final week only and carries earlier weeks at ledger × markup (noted on the report).
- `curves.taper_to_floor` is implemented and tested but not yet wired into baseline building; a long commissioning tail is phased by the activity dates for now.
- Check 7 (status week complete) is satisfied by construction in this engine and is kept for conformance reporting.
- A Vista JC Detail **PDF** is not parsed; export the detail to Excel/CSV first.

## Status and roadmap

`0.1.0` is an alpha: the engine, the example and the test suite are complete;
the report is HTML. Planned: custom rules-of-credit tables in the configuration,
a PDF export of the WSR, a Vista JC Detail PDF text extractor, restatement
tooling for late postings, and a labor-unit calibration module that turns
quantity-tracked actuals into condition-adjusted productivity rates.

Contributions, field data corrections and challenges to the default weights are
welcome — open an issue with the commodity, the proposed weights and the basis
for them.

## License

Apache-2.0. Copyright 2026 Kyle Hagen. Not affiliated with or endorsed by NECA,
AACE International, Oracle (Primavera) or Trimble (Viewpoint).
