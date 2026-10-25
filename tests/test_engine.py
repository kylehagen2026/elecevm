"""Engine tests on a small hand-built project plus the packaged example."""
from datetime import date

import pytest

from elecevm import (Activity, CostTransaction, CostType, EVMethod, LockedWeekError, QuantityRecord, StatusLog,
                     apply_basis, bucket_transactions, build_baseline, compute_status, project_from_dict, reconcile)
from elecevm.actuals import restatements
from elecevm.config import ACBasisRule
from elecevm.evm import eac_methods, funding_crossover, select_eac
from elecevm.rules_of_credit import DEFAULT_RULES, earned_fraction, get_rule


def small_project(basis="contracted"):
    data = {
        "project": {"name": "Unit", "start": date(2026, 3, 9), "week_ending": "saturday",
                    "std_hours_per_week": 50, "contracted_value": 150000.0, "basis": basis},
        "disciplines": [{"code": "FE", "name": "Facility Electrical", "composite_rate": 90.0},
                        {"code": "TEL", "name": "Telecom", "composite_rate": 70.0}],
        "budget": {"contracted": {"FE": {"labor_hours": 1000, "labor": 90000.0, "material": 40000.0},
                                  "TEL": {"labor_hours": 200, "labor": 14000.0, "subcontract": 6000.0}}},
        "change_orders": [{"id": "CO-1", "description": "adds", "date": date(2026, 4, 1), "status": "approved",
                           "amounts": {"FE:L": 9000.0}, "hours": {"FE": 100}}],
        "ac_basis": {"subcontract": "markup", "subcontract_markup": 1.05},
    }
    return project_from_dict(data)


def small_activities():
    return [
        Activity("FE-A-1", "Rough-in", "FE", date(2026, 3, 9), date(2026, 3, 21), budget_hours=600, commodity="conduit",
                 ev_method=EVMethod.MILESTONE),
        Activity("FE-A-2", "Wire", "FE", date(2026, 3, 16), date(2026, 4, 4), budget_hours=400, commodity="wire_branch",
                 ev_method=EVMethod.MILESTONE),
        Activity("TEL-A-1", "Drops", "TEL", date(2026, 3, 23), date(2026, 4, 4), budget_hours=200, commodity="telecom_drop",
                 ev_method=EVMethod.MILESTONE),
    ]


def test_budget_bases_and_change_orders():
    p = small_project()
    assert p.budget.contracted_total == 150000.0
    assert p.budget.estimated_total == 159000.0
    assert p.budget.bac_hours("FE", basis="estimated") == 1100.0
    assert p.budget.bac("FE", CostType.LABOR, basis="contracted") == 90000.0
    assert p.rate("FE") == 90.0


def test_baseline_ties_and_terminal_pv_equals_bac():
    p = small_project("estimated")
    b = build_baseline(p, small_activities(), created=date(2026, 3, 9))
    assert abs(sum(b.allocation[a] for a in ("FE-A-1", "FE-A-2")) - 1100.0) < 1e-9   # CO hours included
    assert abs(b.allocation["TEL-A-1"] - 200.0) < 1e-9
    assert abs(b.terminal_pv - b.total_bac) < 1e-6
    assert abs(b.total_bac - 159000.0) < 1e-6
    # PV is cumulative and non-decreasing
    pvs = [b.pv(w) for w in range(1, b.weeks + 1)]
    assert all(y >= x for x, y in zip(pvs, pvs[1:]))
    assert abs(sum(b.weekly_hours(w) for w in range(1, b.weeks + 1)) - 1300.0) < 1e-9
    # allocation basis recorded
    assert b.allocation_basis["FE-A-1"] == "budget_hours"


def test_score_allocation_when_schedule_is_not_loaded():
    p = small_project()
    acts = [Activity("FE-1", "a", "FE", date(2026, 3, 9), date(2026, 3, 14), hours_per_day=10),      # 6 workdays
            Activity("FE-2", "b", "FE", date(2026, 3, 16), date(2026, 3, 28), hours_per_day=10, area_weight=2.0)]  # 12 wd × 2
    b = build_baseline(p, [a for a in acts] + [Activity("TEL-1", "t", "TEL", date(2026, 3, 9), date(2026, 3, 14))])
    assert abs(b.allocation["FE-1"] - 1000 * 60 / (60 + 240)) < 1e-9
    assert abs(b.allocation["FE-2"] - 1000 * 240 / (60 + 240)) < 1e-9


def test_rules_of_credit_defaults_are_consistent():
    for rule in DEFAULT_RULES.values():
        if rule.basis == "milestone":
            assert abs(sum(m.weight for m in rule.milestones) - 1.0) < 1e-9
    conduit = get_rule("conduit")
    rec = QuantityRecord("x", date(2026, 3, 14), "conduit", total_qty=1000, installed_qty=500,
                         milestones=["layout", "supports"], milestone_progress={"conduit_installed": 0.5})
    frac, tier = earned_fraction(conduit, rec)
    assert tier == "2"
    assert abs(frac - (0.05 + 0.15 + 0.65 * 0.5)) < 1e-9
    qty_rec = QuantityRecord("y", date(2026, 3, 14), "terminations", total_qty=200, installed_qty=50)
    assert earned_fraction(get_rule("terminations"), qty_rec) == (0.25, "1")
    pct_rec = QuantityRecord("z", date(2026, 3, 14), percent_complete=0.4)
    assert earned_fraction(None, pct_rec) == (0.4, "2b")


def test_actuals_bucketing_basis_and_reconciliation():
    p = small_project()
    cal = p.week_cal
    txns = [
        CostTransaction(date(2026, 3, 2), CostType.LABOR, "FE", 10, 900.0, "200001"),      # pre-start -> week 1
        CostTransaction(date(2026, 3, 12), CostType.LABOR, "FE", 40, 3600.0, "200001"),
        CostTransaction(date(2026, 3, 17), CostType.MATERIAL, "FE", 0, 5000.0, "200001"),
        CostTransaction(date(2026, 3, 18), CostType.SUBCONTRACT, "TEL", 0, 1000.0, "200003"),
        CostTransaction(date(2026, 3, 23), CostType.LABOR, "FE", 40, 3600.0, "200001"),     # after status week 2
    ]
    raw = bucket_transactions(txns, cal, status_week=2)
    assert raw.weekly(1, "FE", CostType.LABOR).hours == 50
    assert len(raw.post_status) == 1
    assert raw.cumulative(2).amount == 900 + 3600 + 5000 + 1000
    # source totals include the post-status line (as the report would) and reconcile exactly
    assert reconcile(raw, {"L": (90, 8100.0), "M": (0, 5000.0), "S": (0, 1000.0)}) == []
    assert reconcile(raw, {"L": (90, 8000.0), "M": (0, 5000.0), "S": (0, 1000.0)}) != []
    # subcontract markup
    based = apply_basis(raw, p.ac_basis)
    assert abs(based.weekly(2, "TEL", CostType.SUBCONTRACT).amount - 1050.0) < 1e-9
    assert raw.weekly(2, "TEL", CostType.SUBCONTRACT).amount == 1000.0   # original untouched
    # billed basis: status week carries the residual to billed-to-date
    rules = dict(p.ac_basis)
    rules[CostType.LABOR] = ACBasisRule("billed", 1.0)
    billed = apply_basis(raw, rules, {CostType.LABOR: 6000.0})
    assert abs(billed.cumulative(2, None, CostType.LABOR).amount - 6000.0) < 1e-9
    assert abs(billed.weekly(1, None, CostType.LABOR).amount - 4500.0) < 1e-9
    assert billed.notes


def test_restatements_detect_late_postings():
    p = small_project()
    t1 = [CostTransaction(date(2026, 3, 12), CostType.LABOR, "FE", 40, 3600.0)]
    t2 = t1 + [CostTransaction(date(2026, 3, 12), CostType.LABOR, "FE", 2, 180.0)]  # late posting into week 1
    a1 = bucket_transactions(t1, p.week_cal, 3)
    a2 = bucket_transactions(t2, p.week_cal, 3)
    out = restatements(a1, a2, locked_through=2)
    assert len(out) == 1 and out[0].week == 1 and abs(out[0].delta_amount - 180.0) < 1e-9


def test_eac_methods_and_selection_rule():
    m = eac_methods(bac=1000.0, ev=400.0, ac=500.0, management_etc=450.0)
    assert abs(m["cpi"] - 1250.0) < 1e-9
    assert abs(m["budget_rate"] - 1100.0) < 1e-9
    assert abs(m["management"] - 950.0) < 1e-9
    # max rule: the reported EAC never drops below the statistical one
    assert select_eac(m, "max_management_cpi") == ("cpi", 1250.0)
    assert select_eac(m, "management") == ("management", 950.0)
    assert funding_crossover({1: 100.0, 2: 900.0, 3: 1200.0}, 1000.0) == 3
    assert funding_crossover({1: 100.0, 2: 900.0}, 1000.0) is None


def test_compute_status_metrics_and_checks(tmp_path):
    p = small_project("estimated")
    acts = small_activities()
    b = build_baseline(p, acts, created=date(2026, 3, 9))
    data_date = date(2026, 3, 21)  # status week 2
    txns = [CostTransaction(date(2026, 3, 10), CostType.LABOR, "FE", 100, 9000.0, "200001"),
            CostTransaction(date(2026, 3, 17), CostType.LABOR, "FE", 150, 13500.0, "200001"),
            CostTransaction(date(2026, 3, 18), CostType.MATERIAL, "FE", 0, 6000.0, "200001")]
    actuals = apply_basis(bucket_transactions(txns, p.week_cal, 2), p.ac_basis)
    records = [QuantityRecord("FE-A-1", date(2026, 3, 21), "conduit", total_qty=1000, installed_qty=400,
                              milestones=["layout", "supports"], milestone_progress={"conduit_installed": 0.3})]
    snap = compute_status(p, b, acts, actuals, records, data_date)
    assert snap.status_week == 2
    frac = 0.05 + 0.15 + 0.65 * 0.3
    assert abs(snap.ev_hours - b.allocation["FE-A-1"] * frac) < 1e-6   # FE-A-2 not started, no record -> 0
    assert abs(snap.ac_hours - 250.0) < 1e-9
    assert snap.cpi_hours == pytest.approx(snap.ev_hours / 250.0)
    assert snap.spi == pytest.approx(snap.ev / snap.pv)
    # material EV follows the discipline's earned labor fraction
    fe = next(d for d in snap.disciplines if d.code == "FE")
    assert fe.ev == pytest.approx((99000.0 + 40000.0) * fe.ev_hours / 1100.0)
    assert snap.eac >= snap.eac_methods["cpi"] - 1e-6
    names = {c.name: c.passed for c in snap.checks}
    assert names["terminal_pv_equals_bac"] and names["allocation_ties_by_discipline"] and names["ev_within_budget"]
    assert names["co_log_ties_estimated_basis"]
    # EV is capped: an over-installed quantity cannot earn beyond the budget
    over = [QuantityRecord("FE-A-1", date(2026, 3, 21), "terminations", total_qty=100, installed_qty=150)]
    snap2 = compute_status(p, b, acts, actuals, over, data_date)
    assert abs(next(e for e in snap2.activities if e.activity_id == "FE-A-1").earned_hours - b.allocation["FE-A-1"]) < 1e-6


def test_status_log_locks_weeks(tmp_path):
    log = StatusLog(tmp_path / "log.jsonl")
    log.append({"week": 1, "pv": 10, "ev": 9, "ac": 11})
    with pytest.raises(LockedWeekError):
        log.append({"week": 1, "pv": 12, "ev": 9, "ac": 11})
    log.append({"week": 1, "pv": 12, "ev": 9, "ac": 11}, restate=True, bcr="BCR-002")
    assert log.get(1)["pv"] == 12 and log.get(1)["restates"] is True
    assert len(log.records) == 2                       # history retained, nothing overwritten
    log.annotate(1, "basis change")
    assert log.annotations(1)[0]["note"] == "basis change"
    reloaded = StatusLog(tmp_path / "log.jsonl")
    assert reloaded.weeks() == [1]


def test_example_end_to_end(tmp_path):
    from elecevm import example
    example.generate(tmp_path)
    result = example.run(tmp_path, charts=False)
    snap = result["snapshot"]
    assert snap.all_checks_pass, [c for c in snap.checks if not c.passed]
    assert snap.status_week == 26
    assert 0.8 < snap.spi < 1.0 and 0.8 < snap.cpi < 1.0
    ev = [pt.ev for pt in snap.weekly]
    assert all(y >= x - 1e-6 for x, y in zip(ev, ev[1:]))     # EV never goes backwards
    assert result["log"].weeks() == list(range(1, 27))
    assert (tmp_path / "wsr_wk26.html").exists()


def test_xer_reader_builds_activities(tmp_path):
    from elecevm.ingest import activities_from_xer, read_xer
    xer = "\n".join([
        "ERMHDR\t19.12\t2026-09-05",
        "%T\tPROJWBS",
        "%F\twbs_id\twbs_name",
        "%R\t10\tArea 1",
        "%T\tTASK",
        "%F\ttask_id\ttask_code\ttask_name\ttask_type\twbs_id\ttarget_start_date\ttarget_end_date\tact_start_date\tact_end_date\tearly_end_date\ttarget_drtn_hr_cnt\tphys_complete_pct\tstatus_code",
        "%R\t1\tFE-A1-010\tArea 1 rough-in\tTT_Task\t10\t2026-03-23 07:00\t2026-05-30 17:00\t2026-03-23 07:00\t\t2026-06-06 17:00\t480\t80\tTK_Active",
        "%R\t2\tFE-M-001\tMilestone\tTT_Mile\t10\t2026-05-30 17:00\t2026-05-30 17:00\t\t\t\t0\t0\tTK_NotStart",
        "%T\tTASKRSRC",
        "%F\ttask_id\ttarget_qty",
        "%R\t1\t5000",
        "%E",
    ])
    (tmp_path / "s.xer").write_text(xer, encoding="utf-8")
    tables = read_xer(tmp_path / "s.xer")
    acts = activities_from_xer(tables)
    assert len(acts) == 1
    a = acts[0]
    assert a.id == "FE-A1-010" and a.discipline == "FE" and a.area == "A1"
    assert a.start == date(2026, 3, 23) and a.finish == date(2026, 5, 30)
    assert a.actual_start == date(2026, 3, 23) and a.forecast_finish == date(2026, 6, 6)
    assert a.original_duration == 60 and a.budget_hours == 5000 and a.percent_complete == 0.8


def test_cli_round_trip(tmp_path):
    from elecevm import example
    from elecevm.cli import main
    example.generate(tmp_path)
    p = str(tmp_path / "elecevm.toml"); s = str(tmp_path / "schedule.csv")
    j = str(tmp_path / "jobcost.csv"); q = str(tmp_path / "quantities.csv")
    log = str(tmp_path / "log.jsonl")
    assert main(["baseline", "--project", p, "--schedule", s, "--out", str(tmp_path / "b.json")]) == 0
    assert main(["backfill", "--project", p, "--schedule", s, "--baseline", str(tmp_path / "b.json"), "--jobcost", j,
                 "--quantities", q, "--through", "2026-09-05", "--log", log]) == 0
    assert main(["status", "--project", p, "--schedule", s, "--jobcost", j, "--quantities", q,
                 "--data-date", "2026-09-05", "--log", log]) == 3      # locked week refused
    assert main(["report", "--project", p, "--schedule", s, "--baseline", str(tmp_path / "b.json"), "--jobcost", j,
                 "--quantities", q, "--log", log, "--out", str(tmp_path / "wsr.html"), "--no-charts"]) == 0
    assert (tmp_path / "wsr.html").read_text().count("<table>") >= 5


# ---------------------------------------------------------------------------
# audit follow-ups: paths the example does not exercise
# ---------------------------------------------------------------------------

def test_mixed_allocation_basis_is_an_error():
    p = small_project()
    acts = small_activities()
    acts[1].budget_hours = None  # FE-A-2 unloaded while FE-A-1 is loaded
    with pytest.raises(ValueError, match="mixes resource-loaded"):
        build_baseline(p, acts)


def test_leveling_keeps_activities_consistent_and_retains_demand():
    data = {
        "project": {"name": "Lev", "start": date(2026, 3, 9), "std_hours_per_week": 50, "contracted_value": 200000.0,
                    "basis": "contracted"},
        "disciplines": [{"code": "FE", "name": "FE", "composite_rate": 90.0}],
        "budget": {"contracted": {"FE": {"labor_hours": 2000, "labor": 180000.0, "material": 20000.0}}},
        "leveling": {"crew_cap_headcount": 5},   # 250 h/week
    }
    p = project_from_dict(data)
    acts = [Activity("FE-1", "a", "FE", date(2026, 3, 9), date(2026, 3, 21), budget_hours=1500, commodity="conduit",
                     ev_method=EVMethod.MILESTONE),
            Activity("FE-2", "temp", "FE", date(2026, 3, 9), date(2026, 3, 28), budget_hours=500, ev_method=EVMethod.LOE)]
    b = build_baseline(p, acts, created=date(2026, 3, 9))
    assert b.leveled and b.unleveled_hours
    assert all(b.weekly_hours(w) <= 250.0 + 1e-9 for w in range(1, b.weeks + 1))
    # each activity's own curve is conserved and sums to the discipline table
    for aid in ("FE-1", "FE-2"):
        assert abs(sum(b.activity_weeks[aid].values()) - b.allocation[aid]) < 1e-9
    for w in range(1, b.weeks + 1):
        assert abs(sum(b.activity_weeks[a].get(w, 0.0) for a in b.activity_weeks) - b.weekly_hours(w)) < 1e-9
    assert sum(b.weekly_demand(w) for w in range(1, b.weeks + 1)) == pytest.approx(2000.0)
    assert b.weekly_demand(1) > b.weekly_hours(1)          # demand above the cap in week 1
    # LOE earns exactly its (leveled) planned value
    status_week = 2
    txns = [CostTransaction(date(2026, 3, 10), CostType.LABOR, "FE", 100, 9000.0)]
    actuals = apply_basis(bucket_transactions(txns, p.week_cal, status_week), p.ac_basis)
    snap = compute_status(p, b, acts, actuals, [], date(2026, 3, 21))
    loe = next(e for e in snap.activities if e.activity_id == "FE-2")
    assert loe.earned_hours == pytest.approx(sum(h for w, h in b.activity_weeks["FE-2"].items() if w <= status_week))


def test_estimate_override_is_not_increased_by_change_orders():
    data = {
        "project": {"name": "O", "start": date(2026, 3, 9), "contracted_value": 100.0, "basis": "estimated"},
        "disciplines": [{"code": "FE", "name": "FE", "composite_rate": 1.0}],
        "budget": {"contracted": {"FE": {"labor_hours": 100, "labor": 100.0}},
                   "estimated": {"FE": {"labor_hours": 150, "labor": 150.0}}},
        "change_orders": [{"id": "CO-1", "description": "x", "date": date(2026, 4, 1), "status": "approved",
                           "amounts": {"FE:L": 50.0}, "hours": {"FE": 50}}],
    }
    p = project_from_dict(data)
    assert p.budget.estimated_total == 150.0 and p.budget.bac_hours("FE") == 150.0
    assert p.budget.has_override


def test_budget_total_includes_derived_labor_dollars():
    data = {
        "project": {"name": "D", "start": date(2026, 3, 9), "basis": "contracted"},
        "disciplines": [{"code": "FE", "name": "FE", "composite_rate": 80.0}],
        "budget": {"contracted": {"FE": {"labor_hours": 100, "material": 500.0}}},   # hours only, no labor $
    }
    p = project_from_dict(data)
    assert p.budget_total("contracted") == pytest.approx(8500.0)
    assert p.contracted_value == pytest.approx(8500.0)        # default funding line uses the derived total
    b = build_baseline(p, [Activity("FE-1", "a", "FE", date(2026, 3, 9), date(2026, 3, 14))])
    assert b.total_bac == pytest.approx(8500.0)


def test_forecast_keeps_unearned_hours_of_schedule_complete_activity():
    from elecevm import forecast_remaining
    p = small_project("estimated")
    acts = small_activities()
    acts[0].actual_start, acts[0].actual_finish = date(2026, 3, 9), date(2026, 3, 20)   # complete per schedule
    b = build_baseline(p, acts, created=date(2026, 3, 9))
    earned = {"FE-A-1": b.allocation["FE-A-1"] * 0.9}                                  # field says 90 %
    fc = forecast_remaining(p, b, acts, earned, status_week=2)
    total = sum(sum(v.values()) for v in fc.values())
    expected = sum(b.allocation[a.id] for a in acts) - earned["FE-A-1"]
    assert total == pytest.approx(expected)
    assert min(fc) == 3                                                               # nothing before the week after status


def test_xer_labor_only_and_task_types(tmp_path):
    from elecevm.ingest import activities_from_xer, read_xer
    xer = "\n".join([
        "ERMHDR\t19.12",
        "%T\tRSRC", "%F\trsrc_id\trsrc_type", "%R\t1\tRT_Labor", "%R\t2\tRT_Mat",
        "%T\tTASK",
        "%F\ttask_id\ttask_code\ttask_name\ttask_type\twbs_id\ttarget_start_date\ttarget_end_date\ttarget_drtn_hr_cnt\tphys_complete_pct",
        "%R\t1\tFE-A1-010\tRough-in\tTT_Task\t10\t2026-03-23\t2026-05-30\t480\t0",
        "%R\t2\tFE-A1-000\tArea 1\tTT_WBS\t10\t2026-03-23\t2026-05-30\t480\t0",
        "%R\t3\tFE-ALL-095\tTemp power\tTT_LOE\t10\t2026-03-23\t2026-05-30\t480\t0",
        "%T\tTASKRSRC", "%F\ttask_id\trsrc_id\ttarget_qty", "%R\t1\t1\t5000", "%R\t1\t2\t9500",
        "%E"])
    (tmp_path / "s.xer").write_text(xer, encoding="utf-8")
    acts = {a.id: a for a in activities_from_xer(read_xer(tmp_path / "s.xer"))}
    assert set(acts) == {"FE-A1-010", "FE-ALL-095"}          # WBS summary excluded
    assert acts["FE-A1-010"].budget_hours == 5000              # material quantity ignored
    assert acts["FE-ALL-095"].ev_method is EVMethod.LOE


def test_source_totals_not_run_or_fail():
    p = small_project("estimated")
    acts = small_activities()
    b = build_baseline(p, acts, created=date(2026, 3, 9))
    txns = [CostTransaction(date(2026, 3, 10), CostType.LABOR, "FE", 100, 9000.0, "200001")]
    actuals = apply_basis(bucket_transactions(txns, p.week_cal, 1), p.ac_basis)
    snap = compute_status(p, b, acts, actuals, [], date(2026, 3, 14))
    c = next(c for c in snap.checks if c.name == "ac_reconciles_to_source")
    assert c.ran is False and c.passed
    snap2 = compute_status(p, b, acts, actuals, [], date(2026, 3, 14), source_totals={"L": (100, 9999.0)})
    assert not next(c for c in snap2.checks if c.name == "ac_reconciles_to_source").passed
    assert not snap2.all_checks_pass


def test_vista_rejects_undated_rows(tmp_path):
    from elecevm.ingest import read_jobcost_csv
    p = small_project()
    p.phase_map["200001"] = "FE"
    p.cost_type_map["1"] = "L"
    (tmp_path / "jc.csv").write_text("Phase,CostType,Date,Hours,Amount\n200001,1,2026-03-10,8,700\n200001,1,,8,99999\n")
    with pytest.raises(ValueError, match="transaction date"):
        read_jobcost_csv(tmp_path / "jc.csv", p)
    assert len(read_jobcost_csv(tmp_path / "jc.csv", p, strict=False)) == 1


def test_cli_refuses_failed_checks_and_logs_late_postings(tmp_path):
    from elecevm import example
    from elecevm.cli import main
    from elecevm.status_log import StatusLog
    example.generate(tmp_path)
    p = str(tmp_path / "elecevm.toml"); s = str(tmp_path / "schedule.csv")
    j = str(tmp_path / "jobcost.csv"); q = str(tmp_path / "quantities.csv")
    totals = str(tmp_path / "jobcost_totals.json")
    log = str(tmp_path / "log.jsonl")
    base = ["--project", p, "--schedule", s, "--jobcost", j, "--quantities", q, "--schedule-data-date", "2026-09-05"]
    assert main(["backfill", *base, "--through", "2026-08-22", "--log", log, "--source-totals", totals]) == 0
    assert StatusLog(log).weeks() == list(range(1, 25))
    # a wrong report total fails check 5 and the week is not locked
    assert main(["status", *base, "--data-date", "2026-08-29", "--log", log, "--source-totals", "L=1:1"]) == 2
    assert StatusLog(log).weeks() == list(range(1, 25))
    assert main(["status", *base, "--data-date", "2026-08-29", "--log", log, "--source-totals", totals]) == 0
    assert StatusLog(log).weeks() == list(range(1, 26))
    # a late posting into week 20 shows up on the next status as an annotation, not a rewritten row
    with open(j, "a") as fh:
        fh.write("200001,1,2026-07-20,2026-09-01,2.00,180.00,Late timesheet,PR\n")
    import json as _json
    t = _json.loads(open(totals).read()); t["L"][0] += 2.0; t["L"][1] += 180.0
    open(totals, "w").write(_json.dumps(t))
    assert main(["status", *base, "--data-date", "2026-09-05", "--log", log, "--source-totals", totals]) == 0
    lg = StatusLog(log)
    assert lg.weeks() == list(range(1, 27))
    notes = lg.annotations(20)
    assert len(notes) == 1 and "late posting" in notes[0]["note"]
    assert lg.get(25)["ac"] == pytest.approx(lg.get(25)["ac"])      # locked row untouched
