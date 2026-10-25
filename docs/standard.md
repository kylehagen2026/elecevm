# Earned Value Management for Electrical Construction

## A Recommended Practice for Specialty Contractors

**Revision 0 — Draft for Comment · 2026-10-25 · Author: Kyle Hagen**

Reference implementation: the `elecevm` Python package in this repository.

---

## 1. Purpose and scope

This practice defines how an electrical specialty contractor measures earned value so that planned value, earned value and actual cost tie to the schedule, the estimate and the job-cost ledger every status week. It adapts ANSI/EIA-748 earned value management to the realities of trade contracting: labor-hour-driven scope, payroll-week statusing, a CPM schedule owned by someone else, and a job-cost system that was never designed to feed one.

**Applies to** electrical, fire and security systems, telecommunications and instrumentation scope performed under a subcontract or a direct contract, on any project the contractor chooses to status weekly. It assumes a CPM schedule (Primavera P6 or equivalent) and a transactional job-cost ledger (Viewpoint Vista, Spectrum, Sage, CMiC or equivalent).

**Covers**

- Control structure, budget bases and calendars (§4)
- Building and controlling the time-phased baseline (§5)
- Measuring earned value, including electrical rules of credit (§6)
- Bucketing and reconciling actual cost (§7)
- Indices, estimate at completion and funding analysis (§8)
- Locked status history and reporting (§9)
- Change control (§10) and data integrity checks (§11)

**Does not cover** estimating method or labor-unit libraries, schedule logic quality, contractual entitlement to delay or productivity-loss recovery (this practice produces the quantification inputs only), or earned value at the general contractor or owner level.

**Conformance.** *Shall* marks a requirement, *should* a recommendation, *may* a permitted option. A conforming implementation shall pass every check in §11 on every status run and shall keep the status history described in §9. The reference implementation is the open-source `elecevm` engine (§12); conformance does not require it.

## 2. Definitions and abbreviations

Terms carry their ANSI/EIA-748 meaning unless a row below narrows it for trade-contractor use.

| Term | Meaning in this practice |
| --- | --- |
| PV (planned value) | Budgeted labor hours and dollars time-phased by payroll week from the cost-loaded schedule; cumulative PV at the last week equals BAC |
| EV (earned value) | Budget earned for work physically complete, measured by the tier rules in §6; never exceeds the activity budget |
| AC (actual cost) | Cost bucketed by transaction date to payroll weeks and reconciled to the job-cost source (§7) |
| BAC | Budget at completion on the selected basis (contracted or estimated) |
| EAC / ETC / VAC | Estimate at completion, estimate to complete (EAC − AC), variance at completion (BAC − EAC) |
| SPI / CPI | EV ÷ PV and EV ÷ AC, reported on dollars and, for labor, on hours |
| TCPI | (BAC − EV) ÷ (BAC − AC) or ÷ (EAC − AC): the efficiency needed from here to hit the target |
| Control account | The intersection of discipline, area and cost type at which budget, EV and AC are compared |
| Discipline | A craft or system scope with its own labor budget and composite rate: facility electrical, process electrical, fire/security systems, telecom, instrumentation |
| Cost type | Labor, material, subcontract, equipment, other — the ledger's cost classes mapped to these five |
| Basis | Which budget the metrics report against: *contracted* (executed contract value) or *estimated* (contract plus approved and pending-approved change orders) |
| Funding line | Cumulative contracted value available to be billed; the AC curve crossing it is the *crossover week* |
| Payroll week | The contractor's timesheet week, named by its week-ending date (Saturday by default); week 1 contains the project start and absorbs pre-start cost |
| Data date | The date through which the schedule and ledger were pulled |
| Status week | The last complete payroll week on or before the data date; metrics are reported as of its week-ending date |
| Residual week | The status week when AC for a cost type is set to a billed value: it carries the difference between billed-to-date and the sum of earlier weeks |
| Late posting | A ledger transaction dated in an earlier week but posted after that week was statused; it is restated into its transaction week and logged |
| Measurement tier | The class of evidence behind EV: Tier 1 installed quantities, Tier 2 weighted milestones or field percent, Tier 3 invoiced percent (interim only), LOE, apportioned (§6.1) |
| Rule of credit | For one commodity, the milestones and weights that convert field observation into an earned fraction (§6.2, Appendix A) |
| LOE | Level of effort: support scope with no measurable product (temporary power maintenance, supervision); EV equals PV by definition |
| Apportioned effort | Scope earned at the same fraction as a base activity (QA/QC on an installation activity) |
| Composite rate | Burdened labor dollars per hour for a discipline; when the budget carries both labor dollars and hours, the effective rate is dollars ÷ hours |
| Allocation | Distribution of a discipline's budget hours to its schedule activities (§5.1) |
| Baseline | A versioned, time-phased PV with its allocation and BAC; changed only through a baseline change request |
| BCR | Baseline change request: the logged record of any change to BAC, allocation or phasing (§10) |

## 3. Relationship to ANSI/EIA-748

This practice is a trade-contractor profile of ANSI/EIA-748, not a replacement for it: every 748 guideline has a home in §4–§11, and Appendix C maps each one. Where 748 leaves a choice open, this practice makes it; where the owner's or CM's system already covers a guideline, the contractor's implementation defers to it and says so.

| 748 guideline category | How a trade contractor implements it here |
| --- | --- |
| Organization (guidelines 1–5) | Control accounts are discipline × area × cost type (§4.1); the contractor's own cost codes and the CM's WBS are both mapped to them, so the same account answers the estimate, the ledger and the master schedule |
| Planning, scheduling and budgeting (6–15) | PV comes from a cost-loaded copy of the contractor's schedule activities, allocated from the estimate and phased by payroll week (§5); the baseline is versioned and locked (§5.5) |
| Accounting considerations (16–21) | AC is the job-cost ledger bucketed by transaction date and reconciled to source totals; cost-type basis rules are declared, not improvised (§7) |
| Analysis and management reports (22–27) | Weekly indices on dollars and labor hours, all EAC methods reported with one selected by rule, thresholds that trigger variance analysis (§8), and a weekly status report with minimum contents (§9.2) |
| Revisions and data maintenance (28–32) | Every change to BAC, allocation or phasing is a logged baseline change request (§10); statused weeks are never restated (§9.1) |

**Deliberate departures from common 748 practice**

- Status cadence is weekly, on payroll weeks, because trade labor is managed and paid weekly; monthly roll-ups are derived from the weekly log, never statused separately.
- Two budget bases coexist: contracted and estimated. Metrics are reported on one declared basis, and the gap between the bases is reported as the funding exposure (§4.2).
- Labor-hour indices are first-class. Dollar indices are distorted by material timing and billing basis; the hours-based SPI and CPI are what the field can act on.
- Actual cost may be carried on a billed-value basis for labor and material when the contract is time-and-material or the owner reconciles to billings; the choice is declared per cost type and the raw ledger is retained alongside (§7.3).
- A Tier 3 (invoiced percent) measure of EV is permitted as an interim fallback only, must be labeled, and is not acceptable for change-order or claim quantification (§6.1).

## 4. Project control structure

Every number in the system lives in a control account defined by discipline × area × cost type, reported against one declared budget basis, on a payroll-week calendar.

**4.1 Control accounts.** A *discipline* is a scope with its own labor budget and composite rate (facility electrical, process electrical, fire and security systems, telecom, instrumentation, demolition, temporary power). An *area* is the physical zone the schedule and the foremen already use. The five cost types are labor, material, subcontract, equipment and other; every ledger cost type shall be mapped to exactly one of them. Every ledger phase or cost code shall map to exactly one discipline by exact code or longest prefix. A status run that meets an unmapped phase shall stop, not guess.

**4.2 Budget bases.** Two budgets at completion are maintained for every discipline and cost type:

- *Contracted* — the executed contract value, including executed change orders. Its total is the funding line.
- *Estimated* — the contracted budget plus the change-order log (approved and pending-approved change orders), or an explicit NTP-committed estimate where the owner has authorized work ahead of contract.

Metrics are reported on one declared basis, stated on every report. Both totals are shown, and their difference is reported as the funding exposure. The change-order log carries, for each change order, its id, date, status, dollars by discipline and cost type, and labor hours by discipline; the estimated basis shall equal the contracted basis plus the log (§11, check 11). Rejected change orders stay in the log and count toward nothing.

**4.3 Calendars.**

- *Payroll week.* Weeks are named by their week-ending date (Saturday by default). Week 1 is the week containing the project start and absorbs any cost dated before it.
- *Status week.* The last complete payroll week on or before the data date. A pull taken mid-week statuses the previous complete week; the week in progress is never statused from a partial week of cost.
- *Work calendar.* Working days (Monday–Saturday by default) less the project holiday list. Durations are in working days; a start on a non-working day rolls forward, a finish rolls back.

**4.4 Standard hours.** One standard hours-per-head-per-week value (40, 50 or 60 with planned overtime) converts hours to headcount everywhere: planned crew, actual crew, earned crew and crew caps. A discipline may carry its own value. The number is a reporting convention, not a productivity assumption, and shall be stated on the manpower chart.

**4.5 Effective labor rate.** Where a discipline's budget carries both labor dollars and labor hours, the rate used to price hours is dollars ÷ hours. Where only hours are budgeted, the composite rate from the configuration applies. The rate is recorded with the baseline so later rate changes are visible as baseline changes (§10), not silent drift.

## 5. Cost-loaded schedule and planned value

Planned value is the discipline budget, allocated to the contractor's own schedule activities and spread over the working days each activity is open, so that the last week's cumulative PV equals BAC to the dollar.

**5.1 Activities and allocation basis.** The baseline is built from the contractor's working-level activities, each belonging to one discipline and one area. A discipline's budget labor hours are allocated to its activities in proportion to a score:

- resource-loaded budget hours from the schedule, when the schedule carries them (preferred); otherwise
- original duration × planned hours per day × area weight × activity factor, where the weights express the estimator's judgment of relative density and difficulty and are recorded with the baseline.

The basis used for each activity is recorded. Mixing bases within a discipline is permitted only when every loaded activity carries hours; an activity with zero loaded hours in a loaded discipline is a data error, not a zero allocation.

**5.2 Tie rule.** For every discipline the allocated hours shall equal the budget labor hours within 0.01 hour, and the phased labor dollars shall equal the budget labor dollars. Terminal PV shall equal BAC within $1 (§11, check 1). Floating-point residue is absorbed by the largest activity, never spread.

**5.3 Time-phasing.**

- Labor hours are spread evenly over the working days between an activity's planned start and planned finish and summed into payroll weeks. Level-of-effort activities are spread over their full span.
- Labor dollars are the weekly hours at the effective rate (§4.5).
- Material, subcontract, equipment and other dollars are phased per a declared policy: *follow labor* (default; the discipline's weekly labor profile, since electrical material is installed as labor is expended), *bell* or *linear* over the discipline's span. A delivery-based material curve may be substituted when supplier milestones are known; the policy is recorded with the baseline.

**5.4 Leveling.** A crew cap may be applied to the total labor curve. Leveling is delay-only: hours above the cap move to later weeks, never earlier, per discipline in proportion to that discipline's share of the week, and every discipline's total is conserved. Where a long low-intensity tail (commissioning support, warranty) must be phased, an exponential taper to a stated floor is used and its decay solved so the hours sum exactly. The leveled curve is the baseline; the unleveled schedule demand is retained and shown against it in crew analysis (§8.4) because the gap between the two is the staffing conversation.

**5.5 Baseline control.** The baseline is versioned. Version 1 is set before the first status. Each version carries its allocation, its weekly hours and dollars, its BAC by discipline and cost type, the effective rates, the phasing policy and a change log. A version changes only through a baseline change request (§10), takes effect from the next status week, and never alters the PV recorded for already-statused weeks (§9.1). Re-leveling, re-allocation, change-order incorporation and rate changes are all baseline changes.

## 6. Earned value measurement

Earned value is measured per activity from what the field installed, through a declared rule of credit, and never from what was spent or billed except as a labeled interim fallback.

**6.1 Measurement tiers.** Each activity declares one method. The tier is carried on every earned-value record and summarized in the status report so a reader can see how much of the EV rests on each kind of evidence.

| Tier | Method | Earned fraction | Use |
| --- | --- | --- | --- |
| 1 | Quantity | installed quantity ÷ total quantity | Countable commodities with uniform labor per unit: terminations, devices, grounding, demolition units |
| 2 | Weighted milestones | Σ milestone weight × milestone progress | The standard for electrical installation (Appendix A); partial progress on the open milestone is proportional to its quantity |
| 2b | Field percent | foreman-reported physical percent | Scope with no countable product (programming, testing, punch); must be reported weekly, not left to the schedule |
| 3 | Invoiced percent | invoiced ÷ contract value for the activity | Interim fallback only: labeled on every report, never used for change-order or claim quantification |
| LOE | Level of effort | earned fraction = planned fraction (EV = PV) | Temporary power maintenance, supervision, safety; should not exceed 10 % of a discipline's labor hours |
| Apportioned | Fraction of a base activity | earned fraction of the named base activity | QA/QC or commissioning support tied to an installation activity |

**6.2 Rules of credit.** A rule of credit names a commodity, its unit of measure, its basis (quantity or milestone) and, for milestones, the ordered milestones with weights that sum to 1.000. Appendix A gives the default rules. Before the first status the contractor shall adopt a rule table for the project: the defaults, or weights calibrated to its own labor-unit distribution for that commodity, and record the table with the baseline. One rule applies to every activity of that commodity on the project; a change of rule is a baseline change (§10). Weights represent labor distribution, not schedule duration; a milestone that consumes little labor gets little weight however long it takes.

**6.3 Field quantity tracking.** Progress is recorded weekly, per activity, by the foreman or general foreman responsible, as of the week-ending date. A record carries the activity, the as-of date, the commodity, total and installed quantity, the milestones fully achieved, partial progress on the open milestone, an optional field percent for Tier 2b scope, and who reported it. Records are append-only; the latest record dated on or before the status week-ending date governs. Totals come from the estimate take-off and change only through a baseline change. Where an activity has no field record for the status week the engine falls back to the schedule — complete if the schedule shows an actual finish, zero if not started, otherwise the schedule's physical percent (or, for a backfilled week, an interpolation on working days) — and labels the result Tier 2b with a note, so that an unreported week is visible, not silent.

**6.4 Caps, decreases and rework.** Earned value never exceeds the activity's allocated budget, in hours or dollars (§11, check 6). An earned fraction may decrease between weeks when a prior report was overstated or installed work was removed; the decrease is real progress information and is recorded, not smoothed. Rework earns nothing: hours spent on it raise AC and leave EV where it was, which is exactly the signal a CPI is for. Material, subcontract, equipment and other dollars are earned at the discipline's earned labor fraction unless the activity carries its own measure for them.

**6.5 Discipline and project EV.** Discipline earned hours are the sum over its activities; discipline earned dollars are each cost-type budget times the discipline's earned hours fraction (labor dollars therefore equal earned hours at the effective rate). Project EV is the sum over disciplines. No EV is computed at a level the field did not report.

## 7. Actual cost

Actual cost is the job-cost ledger, bucketed by transaction date into payroll weeks and reconciled to the source report to the cent before anything is computed from it.

**7.1 Bucketing and reconciliation.** Each ledger line is placed in the payroll week of its *transaction* date (the date the labor was worked or the material received), never its posted date. Lines dated before the project start fall in week 1. Lines dated after the status week-ending date are real cost that belongs to the next period: they are held out of AC, counted, and reported (§11, check 8). The totals of the whole pull — held-out lines included, because the source report includes them — shall reconcile to the job-cost report by cost type, hours to 0.01 and dollars to $0.01 (check 5). A pull that does not reconcile is not statused.

**7.2 Late postings.** When a new pull changes the bucket of a week that has already been statused — a timesheet corrected, an invoice posted late — the bucket is restated into its transaction week and each restatement is logged with the week, discipline, cost type and the change in hours and dollars. The status-log record for the affected week is not changed (§9.1): it shows what was known when the week was statused, and the cumulative AC in the current week shows the restated truth. The two are reconciled by the restatement log.

**7.3 Basis per cost type.** The contractor declares, per cost type, how AC is carried:

| Basis | AC carried as | Typical use |
| --- | --- | --- |
| Raw | the ledger amount | labor and material on lump-sum work |
| Markup | ledger amount × a stated factor | subcontract cost at its billed markup, so AC and the funding line are on the same footing |
| Billed | weeks before status at ledger × factor; the status week carries the residual to a supplied billed-to-date value | labor and material on time-and-material or cost-plus work where the owner reconciles to billings, including stored and committed material |

Under the billed basis the status week is the *residual week*: it absorbs the difference between billed-to-date and the sum of earlier weeks, so its weekly AC is not a clean week of cost and is never used alone for crew or run-rate analysis. Hours are never marked up or replaced. The raw ledger is retained beside the carried values on every basis.

**7.4 Accruals.** Incurred but unposted cost that would distort CPI if ignored — a subcontractor's work performed but not yet invoiced, a received but un-vouchered delivery — may be entered as an accrual line dated in the status week, described as such, and reversed in the following week. Accruals are ledger lines like any other and are logged.

**7.5 Hours.** Labor hours follow the same bucketing and reconciliation as dollars and are the basis of the hours indices (§8.1). Overtime hours count once; the premium is in the dollars.

## 8. Analysis and forecasting

Indices are computed on dollars and on labor hours, every estimate-at-completion method is reported, one is selected by a stated rule, and the week the cost curve crosses the funding line is forecast from the same numbers.

**8.1 Indices.** At the status week, for the project and for each discipline: SV = EV − PV, CV = EV − AC, SPI = EV ÷ PV, CPI = EV ÷ AC, on cumulative dollars; and SPI and CPI on cumulative labor hours. TCPI to BAC = (BAC − EV) ÷ (BAC − AC) and TCPI to EAC = (BAC − EV) ÷ (EAC − AC). The hours indices are the primary field-management signal: they are free of material timing, billing basis and rate mix. Dollar indices are the owner-reporting signal. A report shows both and says which one it is arguing from.

**8.2 Estimate at completion.** Every method below is computed and shown on the report:

| Method | Formula | Reads as |
| --- | --- | --- |
| Statistical | BAC ÷ CPI | performance to date continues |
| Budget rate | AC + (BAC − EV) | the rest goes to plan |
| Composite | AC + (BAC − EV) ÷ (CPI × SPI) | cost and schedule pressure both continue |
| Management | AC + bottom-up ETC | the field's own estimate of what is left |

The reported EAC follows the project's selection policy. The default policy is max(management, statistical): a bottom-up estimate may raise the forecast above the statistical one, never lower it, until performance improves. Where no management ETC exists the statistical EAC is reported. A reported EAC below the statistical EAC while CPI < 1 is a check failure (§11, check 12) unless a justification is logged. ETC = EAC − AC and VAC = BAC − EAC are reported with it; the hours EAC is BAC hours ÷ hours CPI.

**8.3 Funding crossover.** The remaining cost (ETC) is phased over the forecast labor profile — each unfinished activity's remaining hours, scaled to the discipline's hours ETC, spread from the week after status to the activity's current finish — and added to cumulative AC. The crossover week is the first week, historical or forecast, in which cumulative AC exceeds the contracted value. It is reported with the funding exposure (§4.2) so the reader sees both how far the estimate exceeds the contract and when the spend will show it.

**8.4 Crew analysis.** Planned crew is the baseline's weekly labor hours ÷ standard hours; actual crew is the week's ledger labor hours ÷ standard hours, shown weekly and as a four-week trailing average; earned crew is the week's increase in earned hours ÷ standard hours; forecast crew is the ETC phasing ÷ standard hours. Crew is always computed from hours, never from dollars, so a billed-basis residual week cannot distort it. The unleveled schedule demand (§5.4) is shown against the leveled plan when the two differ: a plan the schedule cannot be executed within is a finding, not a formatting choice.

**8.5 Variance thresholds.** A project declares its thresholds; the defaults are SPI or CPI below 0.90 on dollars, or cumulative CV beyond 5 % of BAC. A breached threshold obliges a variance analysis in the status report: cause, impact on EAC and finish, corrective action, and who owns it. Thresholds are checked at the project level and should also be checked per discipline.

## 9. Status log and reporting

Every statused week is written once to an append-only log and never rewritten; every report is generated from that log and the current status, so a figure in any report can be traced to one record.

**9.1 Locked history.** The status log holds one record per statused week (Appendix B): the data date, basis and baseline version, PV, EV and AC in dollars and hours, the indices, the EAC and its method, the crossover week, and the discipline split. A week present in the log is locked. A later run that recomputes the week — because of a late posting, a corrected quantity or a baseline change — does not overwrite it. Where a restatement is warranted, a new record is appended that cites the baseline change request, and the superseded record stays in the file. Annotations (pull dates, basis changes, notes to the reader) are appended as their own records and change no numbers. Monthly or period reports are derived from the weekly log, never statused separately.

**9.2 Weekly status report.** A report shall contain, in this order:

1. Header: project, report number, status week and week-ending date, data date, basis and baseline version, BAC and contracted value.
2. Summary: percent complete (EV ÷ BAC), percent spent, SPI and CPI on dollars and on hours, reported EAC and its method, VAC, funding crossover week or exposure.
3. Earned value table: BAC, PV, EV, AC, SV, CV, SPI and CPI for the total in dollars and for labor in hours.
4. Cost curve: cumulative PV for the full baseline, EV and AC through status, the AC forecast, the funding line and the crossover marker, the status week marked.
5. Discipline table: BAC, percent complete and spent, dollar and hours indices, hours earned and spent, hours EAC.
6. Estimate at completion: every method and the reported one.
7. Variance threshold items with their analyses (§8.5).
8. Manpower: planned, actual (weekly and smoothed), earned and forecast crew.
9. Activity earned value: method and tier, planned and earned fraction, budget and earned hours, and the basis note.
10. Integrity checks (§11) with their results.

Milestones, change-order status, a manpower look-ahead and safety indicators may be added; nothing above may be removed.

**9.3 Owner-facing and internal reports.** Internal and owner-facing reports for a week carry the same figures, taken from the same log record; narrative framing may differ, numbers may not. A forecast the contractor has not yet adopted may be withheld from an owner-facing report but shall not be replaced by a different number, and the report shall state the basis (contracted or estimated) its figures are on. An owner-facing report that omits the hours indices shall still carry them in the log.

## 10. Change control

Anything that changes BAC, the allocation, the phasing, a rate, a rule of credit or a locked week is a baseline change request, logged before it takes effect.

**10.1 Types.**

| Type | Trigger | Changes |
| --- | --- | --- |
| Change-order incorporation | a change order enters or leaves the estimated basis | BAC dollars and hours by discipline and cost type; allocation to the activities that carry the scope |
| Re-allocation | estimate re-work, scope moved between activities | allocation within a discipline; discipline totals unchanged unless combined with the above |
| Re-phasing or re-leveling | schedule re-baseline, crew cap change | weekly hours and dollars for weeks after status; prior weeks unchanged |
| Rate change | a wage-schedule step not already in the composite rate | effective rate and labor dollars for weeks after status |
| Measurement rule change | a rule of credit recalibrated or an activity's method changed | earned fractions from the next status; prior weeks unchanged |
| Restatement | a locked week must be re-expressed (a material error, not a late posting) | a new log record for that week citing this request; the old record retained |

**10.2 Required fields.** Identifier, date raised, type, description, the authority (change-order number, estimate revision, management approval), BAC dollars and hours before and after by discipline, the first status week affected, the baseline version it produces, and who approved it.

**10.3 Rules.** A request takes effect from the next status week; it is never applied to a week already in the log. Every request increments the baseline version, and the version is recorded on every status record from then on. The change-order log and the estimated basis are reconciled on every status run (§11, check 11). Late postings (§7.2) are not baseline changes and need no request; restatements of locked weeks are.

## 11. Data integrity checks

Every status run executes the thirteen checks below and prints the result of each on the report; a run with a failed check is not issued until the failure is resolved or annotated.

| # | Check | Passes when |
| --- | --- | --- |
| 1 | Terminal PV equals BAC | cumulative PV at the last baseline week equals BAC within $1 |
| 2 | PV monotonic | no payroll week carries negative planned value |
| 3 | Allocation ties by discipline | allocated hours equal budget labor hours within 0.01 h for every discipline |
| 4 | Phased hours conserved | the weekly labor curve sums to total budget hours within 0.01 h (leveling and tapering lose nothing) |
| 5 | AC reconciles to source | the pull's raw totals by cost type equal the job-cost report, hours to 0.01 and dollars to $0.01 |
| 6 | EV within budget | no activity earns more than its allocation; project EV ≤ BAC |
| 7 | Status week complete | the status week-ending date is on or before the data date |
| 8 | No post-status cost in AC | lines dated after the status week are held out and counted |
| 9 | History contiguous | every week before the status week has a record in the log |
| 10 | Locked PV unchanged | for each locked week statused on the current baseline version, the baseline's PV for that week equals the logged PV within $1 |
| 11 | CO log ties estimated basis | estimated BAC − contracted BAC − counted change orders = 0 within $0.01 (or an explicit estimate override is declared, in which case the difference is reported) |
| 12 | EAC not below statistical | while CPI < 1, the reported EAC is at least BAC ÷ CPI, or a justification is logged |
| 13 | Activities in baseline | every activity in the statused schedule carries an allocation in the baseline in force; a new activity with none earns nothing and is a baseline change (§10) |

Checks 1–4 are properties of the baseline and are run again whenever a baseline version is created. Checks 5 and 8 are properties of the pull. Checks 9 and 10 are properties of the log. A check that cannot run (no source totals supplied, no history yet) is reported as not run, not as passed.

## 12. Implementation notes

The practice can be run on a spreadsheet; the reference implementation exists because a 40,000-formula workbook cannot prove it is following the practice, and code with tests can.

**12.1 Schedule pulls (Primavera P6).** Export the contractor's own activities as an XER with resource-loaded labor hours where the schedule has them. Put the discipline and area in the activity ID (`FE-A2-010`) or in activity codes the resolver can read. Record the schedule's data date with every pull; a baseline is built from planned dates, a status uses actual starts, actual finishes, forecast finishes and physical percent. Milestones carry no budget and are excluded from allocation.

**12.2 Job-cost pulls (Viewpoint Vista and similar).** Export the JC Detail at transaction level with phase or cost code, cost type, transaction date, posted date, hours and amount; a Crystal-report PDF must be converted to rows before ingest. Map every phase to a discipline and every ledger cost type to labor, material, subcontract, equipment or other in the project configuration. Reconcile the pull to the report's printed totals before statusing (§7.1); the first failed reconciliation is usually a cost type that was never mapped.

**12.3 Field quantities.** A one-sheet tracker per general foreman is enough: one row per activity per week, with the milestone names from the rule table. Totals come from the take-off. The engine reads the sheet as CSV; a form on a tablet that writes the same columns is better.

**12.4 Reference implementation.** `elecevm` is an open-source Python package licensed under Apache-2.0. It implements §4–§11 as tested functions, ships the default rules of credit (Appendix A), reads XER, CSV and XLSX inputs, keeps the locked status log (Appendix B), renders the weekly status report (§9.2) and runs the thirteen checks (§11) on every status. The command sequence is `elecevm init`, `elecevm baseline`, then `elecevm status` each week (or `elecevm backfill` to build history) and `elecevm report`. A synthetic example project is included so the full cycle can be run in one command with no real data.

**12.5 Adoption path.** Start with labor only: a cost-loaded baseline on hours, Tier 2 milestones for the three or four commodities that carry most of the hours, and the hours indices. Add material phasing and the dollar indices once the labor loop runs clean for a month. Adopt the billed basis only where owner reporting reconciles to billings. Calibrate the milestone weights after two or three projects' worth of quantity-tracked actuals, and record the calibrated table as the company standard.

**12.6 Limits of this revision.** Revision 0 covers single-contract projects with a weekly cadence. Multi-project portfolio roll-ups, indirect-cost accounting beyond the composite rate, and the productivity-loss quantification that builds on quantity-tracked actuals (measured-mile and factor methods) are reserved for later revisions.

## Appendix A — Default electrical rules of credit

These 22 rules are the published starting point (§6.2). Weights are labor-distribution weights for the milestone in that commodity; milestone names are the identifiers the field tracker uses. Calibrate to your own labor units and record the calibrated table with the baseline.

| Commodity | Scope | Unit | Basis | Milestones (weight) |
| --- | --- | --- | --- | --- |
| `conduit` | Conduit and raceway (EMT/RMC/PVC) incl. supports, boxes and fittings | LF | milestone | layout (0.05), supports (0.15), conduit installed (0.65), boxes fittings (0.10), labeled inspected (0.05) |
| `cable_tray` | Cable tray and ladder rack incl. supports, covers and bonding | LF | milestone | supports (0.30), tray installed (0.55), covers bonding labeled (0.15) |
| `underground` | Underground duct bank and direct-buried conduit | LF | milestone | trench open (0.20), conduit set (0.45), concrete backfill (0.25), mandrel labeled (0.10) |
| `wire_feeder` | Feeder conductors — pull, terminate, test | LF | milestone | pulled (0.60), terminated (0.25), tested (0.15) |
| `wire_branch` | Branch-circuit conductors — pull and make-up | LF | milestone | pulled (0.65), made up (0.35) |
| `mc_cable` | MC cable — install and terminate | LF | milestone | installed (0.75), terminated (0.25) |
| `terminations` | Conductor terminations | EA | quantity | installed ÷ total |
| `grounding` | Grounding electrode and bonding system | LF | quantity | installed ÷ total |
| `switchgear` | Switchgear, switchboards and MCCs | EA | milestone | set anchored (0.40), bus sections connected (0.20), terminated (0.20), tested (0.10), energized (0.10) |
| `panelboard` | Panelboards and distribution panels | EA | milestone | set (0.40), fed terminated (0.35), circuits made up (0.15), energized labeled (0.10) |
| `transformer` | Dry-type and pad-mount transformers | EA | milestone | set (0.50), connected (0.35), energized (0.15) |
| `equipment_connection` | Motor and mechanical equipment connections | EA | milestone | rough in (0.40), connected (0.45), checked (0.15) |
| `vfd_starter` | VFDs, starters and disconnects | EA | milestone | set (0.45), wired (0.40), checked (0.15) |
| `wiring_device` | Wiring devices — make-up and trim | EA | quantity | installed ÷ total |
| `lighting_fixture` | Lighting fixtures | EA | milestone | hung (0.55), wired (0.30), lamped energized (0.15) |
| `lighting_control` | Lighting control devices and panels | EA | milestone | installed (0.60), wired (0.25), programmed (0.15) |
| `fire_alarm_device` | Fire alarm devices and appliances | EA | milestone | rough in (0.30), device installed (0.45), tested programmed (0.25) |
| `security_device` | Access control, CCTV and intrusion devices | EA | milestone | rough in (0.30), device installed (0.45), commissioned (0.25) |
| `telecom_drop` | Structured cabling drops — pull, terminate, certify | EA | milestone | pulled (0.50), terminated (0.35), tested certified (0.15) |
| `fiber` | Fiber optic backbone — pull, terminate, test | STRAND | milestone | pulled (0.45), terminated (0.35), tested (0.20) |
| `instrument` | Field instruments — mount, tube/wire, loop check | EA | milestone | mounted (0.40), tubed wired (0.40), loop checked (0.20) |
| `demolition` | Demolition and removals | UNIT | quantity | installed ÷ total |

Scope with no entry above (temporary power maintenance, supervision, programming and test, punch) is measured as level of effort, field percent (Tier 2b) or apportioned effort per §6.1. Partial progress on an open milestone is reported as a fraction of that milestone's quantity (pulled 60 % of the feeder footage → `pulled = 0.60`).

## Appendix B — Status log record

One record per statused week, appended as a line of JSON; a restatement is a second record for the same week carrying the change request that justified it. Field names below are those the reference implementation writes.

| Field | Type | Meaning |
| --- | --- | --- |
| `kind` | text | `status` for a week record, `annotation` for a note that changes no numbers |
| `week`, `week_end` | integer, date | payroll week number and its week-ending date |
| `data_date` | date | the pull date the week was statused from |
| `basis`, `basis_version` | text, integer | `contracted` or `estimated`; the baseline version in force |
| `bac`, `bac_hours` | $, hours | budget at completion on the stated basis |
| `pv`, `ev`, `ac` | $ | cumulative planned, earned and actual cost through the week |
| `pv_hours`, `ev_hours`, `ac_hours` | hours | cumulative labor hours planned, earned and worked |
| `spi`, `cpi`, `spi_hours`, `cpi_hours` | ratio | indices on dollars and on hours |
| `eac`, `eac_method`, `etc`, `vac` | $, text, $, $ | reported estimate at completion, the method that produced it, estimate to complete, variance at completion |
| `crossover_week` | integer or null | first week cumulative AC exceeds the contracted value, historical or forecast |
| `checks_passed` | boolean | whether all §11 checks passed when the week was statused |
| `disciplines` | map | per discipline: `pv`, `ev`, `ac`, `pv_hours`, `ev_hours`, `ac_hours` |
| `restates`, `bcr` | boolean, text | present on a restatement: the request that authorized it |
| `logged_at` | timestamp | when the record was written (UTC) |
| `note` | text | annotation records only |

The full status snapshot — activity earned value, every EAC method, the forecast curve, the check details — is written beside the log as a JSON file per week and is not part of the locked record. A CSV view of the log (one row per week, newest last) is derived from it for spreadsheets.

## Appendix C — ANSI/EIA-748 cross-reference

The 32 guidelines of EIA-748 fall in five groups; the table maps each group's intent to the section of this practice that carries it, and names what is deferred to the owner's or construction manager's system. Guideline numbering follows the current edition of EIA-748; verify against the licensed text before any formal conformance claim.

| EIA-748 group and intent | This practice | Notes |
| --- | --- | --- |
| Organization (1–5): define the work, the responsible organization and the control-account level where they meet | §4.1 control accounts = discipline × area × cost type; the CM's WBS and the contractor's cost codes are both mapped to them | The contractor is one organization in the owner's OBS; the discipline is its internal organization |
| Planning, scheduling and budgeting (6–15): a logic-driven schedule, progress indicators, a time-phased budget baseline at control-account level, work and planning packages, level of effort, overhead, reserves, reconciliation to the target | §5 cost-loaded baseline and tie rule; §6.1 measurement methods per activity; §6.1 LOE limited and time-phased; §4.2 two bases reconciled through the CO log | Schedule logic quality is the CM's; this practice consumes the contractor's activities. Overhead is in the composite rate; management reserve, where the contractor holds one, is outside BAC and reported with the funding exposure |
| Accounting (16–21): record direct cost in the books of account, summarize through the structures, account for indirect cost, unit costs, material at the right point in time | §7 ledger bucketing by transaction date, reconciliation to source, basis per cost type; §5.3 material phasing policy; §7.4 accruals | Material is earned with labor by default (§6.4); a delivery-based measure may be declared |
| Analysis and management reports (22–27): variances at control-account level at least monthly, indirect variances, summarized reporting, management action, estimates at completion | §8 weekly indices on dollars and hours, every EAC method with a selection rule, thresholds obliging variance analysis; §9.2 report contents | Weekly cadence exceeds the monthly minimum; monthly reports are derived from the log (§9.1) |
| Revisions and data maintenance (28–32): timely incorporation of authorized changes, reconciliation of budgets, control of retroactive changes, no unauthorized baseline revision, documented changes | §10 baseline change requests; §9.1 locked history; §11 checks 10 and 11 | Retroactive change is prevented structurally: a locked week can only be superseded by an appended record citing a request |

---

*ANSI/EIA-748 is a standard of SAE International / the Electronic Industries Alliance; NECA, AACE International, Oracle Primavera and Trimble Viewpoint are the marks of their owners. This practice is independent of all of them.*
