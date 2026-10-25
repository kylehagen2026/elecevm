# Changelog

## 0.1.0 — 2026-10-25

First public release (alpha).

- Payroll-week and working-day calendars with the last-complete-week status rule
- Two-basis budget (contracted / estimated) with a change-order log
- Cost-loaded schedule allocation (resource-loaded hours or score basis), exact ties per discipline, delay-only crew-cap leveling, taper-to-floor phasing
- Default electrical rules of credit for 22 commodities; measurement tiers 1, 2, 2b, 3, LOE, apportioned
- Actual-cost bucketing by transaction date, per-cost-type basis rules (raw / markup / billed with residual week), reconciliation to printed report totals, late postings detected between pulls and annotated in the log
- Indices on dollars and labor hours, TCPI, all EAC methods with a selection policy, funding-crossover forecast, crew curves
- Append-only locked status log with BCR-referenced restatements and annotations
- Weekly Status Report (HTML) with colorblind-safe cost and crew charts
- P6 XER and activity-CSV schedule ingest; Vista-style job-cost CSV/XLSX ingest; field quantity CSV ingest
- Thirteen integrity checks run on every status
- Synthetic example project and a test suite
