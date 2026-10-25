"""Electrical rules of credit (RP §6.2, Appendix A).

A rule of credit converts a field observation into an earned fraction for
one commodity.  Two bases exist:

* ``quantity`` — earned fraction = installed quantity ÷ total quantity
  (Tier 1); the milestones listed are informational.
* ``milestone`` — earned fraction = Σ weight × progress for each milestone,
  where progress is 1.0 for an achieved milestone or a partial 0–1 fraction
  when the field reports quantities per milestone (Tier 2).

The default weights below are a published starting point.  Each contractor
should calibrate them to its own labor-unit distribution and record the
calibrated set in the project configuration (RP §6.2).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from .models import QuantityRecord


@dataclass(frozen=True)
class Milestone:
    name: str
    weight: float


@dataclass(frozen=True)
class RuleOfCredit:
    commodity: str
    description: str
    uom: str
    basis: str                       # "quantity" | "milestone"
    milestones: Tuple[Milestone, ...] = ()

    def __post_init__(self) -> None:
        if self.basis not in {"quantity", "milestone"}:
            raise ValueError("basis must be 'quantity' or 'milestone'")
        if self.basis == "milestone":
            total = sum(m.weight for m in self.milestones)
            if abs(total - 1.0) > 1e-9:
                raise ValueError(f"{self.commodity}: milestone weights sum to {total}, not 1.0")

    @property
    def tier(self) -> str:
        return "1" if self.basis == "quantity" else "2"


def _ms(*pairs) -> Tuple[Milestone, ...]:
    return tuple(Milestone(n, w) for n, w in pairs)


DEFAULT_RULES: Dict[str, RuleOfCredit] = {
    # --- raceway ---------------------------------------------------------
    "conduit": RuleOfCredit(
        "conduit", "Conduit and raceway (EMT/RMC/PVC) incl. supports, boxes and fittings", "LF", "milestone",
        _ms(("layout", 0.05), ("supports", 0.15), ("conduit_installed", 0.65),
            ("boxes_fittings", 0.10), ("labeled_inspected", 0.05))),
    "cable_tray": RuleOfCredit(
        "cable_tray", "Cable tray and ladder rack incl. supports, covers and bonding", "LF", "milestone",
        _ms(("supports", 0.30), ("tray_installed", 0.55), ("covers_bonding_labeled", 0.15))),
    "underground": RuleOfCredit(
        "underground", "Underground duct bank and direct-buried conduit", "LF", "milestone",
        _ms(("trench_open", 0.20), ("conduit_set", 0.45), ("concrete_backfill", 0.25), ("mandrel_labeled", 0.10))),
    # --- conductors ------------------------------------------------------
    "wire_feeder": RuleOfCredit(
        "wire_feeder", "Feeder conductors — pull, terminate, test", "LF", "milestone",
        _ms(("pulled", 0.60), ("terminated", 0.25), ("tested", 0.15))),
    "wire_branch": RuleOfCredit(
        "wire_branch", "Branch-circuit conductors — pull and make-up", "LF", "milestone",
        _ms(("pulled", 0.65), ("made_up", 0.35))),
    "mc_cable": RuleOfCredit(
        "mc_cable", "MC cable — install and terminate", "LF", "milestone",
        _ms(("installed", 0.75), ("terminated", 0.25))),
    "terminations": RuleOfCredit("terminations", "Conductor terminations", "EA", "quantity"),
    "grounding": RuleOfCredit("grounding", "Grounding electrode and bonding system", "LF", "quantity"),
    # --- equipment -------------------------------------------------------
    "switchgear": RuleOfCredit(
        "switchgear", "Switchgear, switchboards and MCCs", "EA", "milestone",
        _ms(("set_anchored", 0.40), ("bus_sections_connected", 0.20), ("terminated", 0.20),
            ("tested", 0.10), ("energized", 0.10))),
    "panelboard": RuleOfCredit(
        "panelboard", "Panelboards and distribution panels", "EA", "milestone",
        _ms(("set", 0.40), ("fed_terminated", 0.35), ("circuits_made_up", 0.15), ("energized_labeled", 0.10))),
    "transformer": RuleOfCredit(
        "transformer", "Dry-type and pad-mount transformers", "EA", "milestone",
        _ms(("set", 0.50), ("connected", 0.35), ("energized", 0.15))),
    "equipment_connection": RuleOfCredit(
        "equipment_connection", "Motor and mechanical equipment connections", "EA", "milestone",
        _ms(("rough_in", 0.40), ("connected", 0.45), ("checked", 0.15))),
    "vfd_starter": RuleOfCredit(
        "vfd_starter", "VFDs, starters and disconnects", "EA", "milestone",
        _ms(("set", 0.45), ("wired", 0.40), ("checked", 0.15))),
    # --- devices and lighting -------------------------------------------
    "wiring_device": RuleOfCredit("wiring_device", "Wiring devices — make-up and trim", "EA", "quantity"),
    "lighting_fixture": RuleOfCredit(
        "lighting_fixture", "Lighting fixtures", "EA", "milestone",
        _ms(("hung", 0.55), ("wired", 0.30), ("lamped_energized", 0.15))),
    "lighting_control": RuleOfCredit(
        "lighting_control", "Lighting control devices and panels", "EA", "milestone",
        _ms(("installed", 0.60), ("wired", 0.25), ("programmed", 0.15))),
    # --- fire, security, telecom, instrumentation ------------------------
    "fire_alarm_device": RuleOfCredit(
        "fire_alarm_device", "Fire alarm devices and appliances", "EA", "milestone",
        _ms(("rough_in", 0.30), ("device_installed", 0.45), ("tested_programmed", 0.25))),
    "security_device": RuleOfCredit(
        "security_device", "Access control, CCTV and intrusion devices", "EA", "milestone",
        _ms(("rough_in", 0.30), ("device_installed", 0.45), ("commissioned", 0.25))),
    "telecom_drop": RuleOfCredit(
        "telecom_drop", "Structured cabling drops — pull, terminate, certify", "EA", "milestone",
        _ms(("pulled", 0.50), ("terminated", 0.35), ("tested_certified", 0.15))),
    "fiber": RuleOfCredit(
        "fiber", "Fiber optic backbone — pull, terminate, test", "STRAND", "milestone",
        _ms(("pulled", 0.45), ("terminated", 0.35), ("tested", 0.20))),
    "instrument": RuleOfCredit(
        "instrument", "Field instruments — mount, tube/wire, loop check", "EA", "milestone",
        _ms(("mounted", 0.40), ("tubed_wired", 0.40), ("loop_checked", 0.20))),
    # --- other -------------------------------------------------------------
    "demolition": RuleOfCredit("demolition", "Demolition and removals", "UNIT", "quantity"),
}


def get_rule(commodity: Optional[str], rules: Optional[Dict[str, RuleOfCredit]] = None) -> Optional[RuleOfCredit]:
    if not commodity:
        return None
    table = rules or DEFAULT_RULES
    return table.get(str(commodity).strip().lower())


def earned_fraction(rule: Optional[RuleOfCredit], record: QuantityRecord) -> Tuple[float, str]:
    """Return (earned fraction 0–1, tier label) for a field record.

    Precedence: a field-reported percent on the record (Tier 2b) → the rule's
    basis → a plain installed ÷ total quantity when no rule is known.
    """
    if record.percent_complete is not None:
        return _clamp(record.percent_complete), "2b"
    if rule is None:
        if record.total_qty > 0:
            return _clamp(record.installed_qty / record.total_qty), "1"
        return 0.0, "none"
    if rule.basis == "quantity":
        if record.total_qty > 0:
            return _clamp(record.installed_qty / record.total_qty), "1"
        return 0.0, "1"
    achieved = {m.strip().lower() for m in record.milestones}
    progress = {k.strip().lower(): _clamp(v) for k, v in record.milestone_progress.items()}
    fraction = 0.0
    for m in rule.milestones:
        if m.name in achieved:
            fraction += m.weight
        elif m.name in progress:
            fraction += m.weight * progress[m.name]
    return _clamp(fraction), "2"


def _clamp(x: float) -> float:
    return min(max(float(x), 0.0), 1.0)
