"""elecevm — an earned value management engine for electrical construction.

Reference implementation of *Earned Value Management for Electrical
Construction — A Recommended Practice for Specialty Contractors*
(``docs/standard.md``).  Pure Python; charts and .xlsx ingest are optional extras.
"""

__version__ = "0.1.0"

from .calendar import WeekCalendar, WorkCalendar  # noqa: E402
from .models import (Activity, Budget, ChangeOrder, CostTransaction, CostType, Discipline,  # noqa: E402
                     EVMethod, QuantityRecord)
from .config import ACBasisRule, Project, load_project, project_from_dict  # noqa: E402
from .allocation import Baseline, allocate_hours, build_baseline, forecast_remaining  # noqa: E402
from .actuals import WeeklyActuals, apply_basis, bucket_transactions, reconcile, restatements  # noqa: E402
from .rules_of_credit import DEFAULT_RULES, RuleOfCredit, earned_fraction, get_rule  # noqa: E402
from .evm import StatusSnapshot, compute_status, health_checks, measure_activities  # noqa: E402
from .status_log import LockedWeekError, StatusLog  # noqa: E402

__all__ = [
    "__version__",
    "WeekCalendar", "WorkCalendar",
    "Activity", "Budget", "ChangeOrder", "CostTransaction", "CostType", "Discipline", "EVMethod", "QuantityRecord",
    "ACBasisRule", "Project", "load_project", "project_from_dict",
    "Baseline", "allocate_hours", "build_baseline", "forecast_remaining",
    "WeeklyActuals", "apply_basis", "bucket_transactions", "reconcile", "restatements",
    "DEFAULT_RULES", "RuleOfCredit", "earned_fraction", "get_rule",
    "StatusSnapshot", "compute_status", "health_checks", "measure_activities",
    "LockedWeekError", "StatusLog",
]
