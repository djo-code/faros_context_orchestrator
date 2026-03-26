---
rule_id: context-aware-metrics-dora
principle: Context-Aware Metrics
category: engineering-metrics, correctness, calendar-arithmetic
tags: [DORA, working-time, calendar, holidays, weekends, org_settings, lead-time, MTTR, deployment-frequency, change-failure-rate, timezone]
severity: high
language: python
---

# Rule: DORA Metrics Must Exclude Weekends and Holidays via OrgSettings

## Core Constraint

All duration-based DORA metrics (Lead Time for Changes, MTTR) **must count only working time** as defined by a single authoritative `OrgSettings` object. Wall-clock hours are never acceptable for human-centric engineering metrics. Every calendar rule — working days, holidays, shift hours — must derive exclusively from `OrgSettings`; no metric calculator may hard-code weekend or holiday logic independently. Additionally, the authoritative `is_working_moment()` method defined in `OrgSettings` must be the single function called by all calendar consumers — divergent inline re-implementations create silent context drift.

---

## Negative Patterns — What to Avoid

### ❌ Anti-Pattern 1: Wall-clock duration for DORA metrics
```python
# VIOLATION: uses raw timedelta — counts nights, weekends, and holidays
def calculate_lead_time(commit_time: datetime, deployed_at: datetime) -> float:
    return (deployed_at - commit_time).total_seconds() / 3600.0

# A Friday 4:45 pm commit deployed Monday 9:30 am reports ~64 hours.
# Actual working hours: 0.25 h (Fri) + 0.5 h (Mon) = 0.75 h.
# The metric is meaningless for engineering decision-making.
```

### ❌ Anti-Pattern 2: Hard-coded weekend/holiday knowledge outside OrgSettings
```python
# VIOLATION: calendar rules duplicated outside the authoritative source
def count_working_days(start: date, end: date) -> int:
    count = 0
    current = start
    while current <= end:
        if current.weekday() < 5:   # ← hard-coded Mon–Fri assumption
            count += 1
        current += timedelta(days=1)
    return count
# No holiday awareness. Cannot adapt to 4-day work weeks or regional calendars.
```

### ❌ Anti-Pattern 3: `is_working_moment` defined but not called — context divergence
```python
# VIOLATION: OrgSettings defines the authoritative working-moment predicate,
# but WorkingCalendar reimplements the same logic inline and ignores it.
class OrgSettings:
    def is_working_moment(self, dt: datetime) -> bool:
        return (
            self.is_working_day(dt.date())
            and self.work_day_start_hour <= dt.hour < self.work_day_end_hour
        )

class WorkingCalendar:
    def working_hours_between(self, start: datetime, end: datetime) -> float:
        # ← Never calls self._settings.is_working_moment()
        # Duplicates boundary logic inline — will silently diverge if
        # OrgSettings gains shift-based or partial-holiday rules.
        if cursor.hour >= settings.work_day_end_hour: ...
        elif cursor.hour < settings.work_day_start_hour: ...
```

### ❌ Anti-Pattern 4: Fragile `+timedelta(seconds=1)` loop-escape cursor advance
```python
# VIOLATION: nudging by one second to escape the working-period loop is fragile.
# Correctness depends on the second pushing the cursor past work_day_end_hour,
# which breaks for non-integer-hour boundaries and obscures the true intent.
cursor = cursor.replace(
    hour=settings.work_day_end_hour, minute=0, second=0, microsecond=0
) + timedelta(seconds=1)   # ← hack: relies on seconds > end_hour comparison
```

### ❌ Anti-Pattern 5: End-hour boundary inconsistency between methods
```python
# VIOLATION: is_working_moment excludes the end hour (strict <),
# but working_hours_between accumulates UP TO end hour (inclusive endpoint).
# A timestamp at exactly 17:00:00 is handled differently by each method.
def is_working_moment(self, dt: datetime) -> bool:
    return self.work_day_start_hour <= dt.hour < self.work_day_end_hour  # 17:00 → False

# But the calendar accumulates:
working_period_end = cursor.replace(hour=settings.work_day_end_hour, ...)  # 17:00 included
```

### ❌ Anti-Pattern 6: Window-boundary filtering silently excludes cross-boundary incidents
```python
# VIOLATION: incidents opened before window_start are excluded entirely,
# understating MTTR when long-running incidents span the measurement boundary.
incidents_in_window = [
    i for i in incidents
    if window_start <= i.opened_at.date() <= window_end and i.is_resolved
]
# An incident opened Nov 29, resolved Dec 3, in a Dec 1–31 window → excluded.
# True MTTR is understated.
```

---

## Positive Patterns — The Fix

### ✅ Pattern 1: OrgSettings as the single source of calendar truth
```python
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import IntEnum
from typing import Sequence

class Weekday(IntEnum):
    MONDAY=0; TUESDAY=1; WEDNESDAY=2; THURSDAY=3
    FRIDAY=4; SATURDAY=5; SUNDAY=6

@dataclass(frozen=True)
class OrgSettings:
    """
    Single authoritative source for all working-time rules.
    No metric calculator may declare its own weekend or holiday logic.
    """
    working_days: frozenset[Weekday] = frozenset({
        Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY,
        Weekday.THURSDAY, Weekday.FRIDAY,
    })
    holidays: frozenset[date] = frozenset()
    work_day_start_hour: int = 9
    work_day_end_hour:   int = 17  # exclusive upper boundary

    @property
    def working_hours_per_day(self) -> int:
        return self.work_day_end_hour - self.work_day_start_hour

    def is_working_day(self, d: date) -> bool:
        return Weekday(d.weekday()) in self.working_days and d not in self.holidays

    def is_working_moment(self, dt: datetime) -> bool:
        """
        Authoritative predicate — ALL calendar consumers must call this.
        Never re-implement inline in WorkingCalendar or metric calculators.
        """
        return (
            self.is_working_day(dt.date())
            and self.work_day_start_hour <= dt.hour < self.work_day_end_hour
        )
```

### ✅ Pattern 2: WorkingCalendar delegates exclusively to `OrgSettings.is_working_moment`
```python
class WorkingCalendar:
    """
    All calendar arithmetic derives from OrgSettings.
    No hard-coded weekend, holiday, or hour-boundary knowledge lives here.
    """
    def __init__(self, org_settings: OrgSettings) -> None:
        self._settings = org_settings

    def working_hours_between(self, start: datetime, end: datetime) -> float:
        """Count only working hours — delegates boundary logic to OrgSettings."""
        if end <= start:
            return 0.0

        settings = self._settings
        total_working_seconds = 0.0
        cursor = self._advance_to_next_working_moment(start)

        while cursor < end:
            # Compute the end of the current working period
            working_period_end = min(
                end,
                cursor.replace(
                    hour=settings.work_day_end_hour,
                    minute=0, second=0, microsecond=0,
                ),
            )
            total_working_seconds += (working_period_end - cursor).total_seconds()

            # Advance explicitly to next day's start — no +timedelta(seconds=1) hack
            next_day_start = (cursor + timedelta(days=1)).replace(
                hour=settings.work_day_start_hour,
                minute=0, second=0, microsecond=0,
            )
            cursor = self._advance_to_next_working_moment(next_day_start)

        return total_working_seconds / 3600.0

    def count_working_days_in_range(self, range_start: date, range_end: date) -> int:
        count = 0
        current = range_start
        while current <= range_end:
            if self._settings.is_working_day(current):
                count += 1
            current += timedelta(days=1)
        return count

    def _advance_to_next_working_moment(self, dt: datetime) -> datetime:
        """
        Advance `dt` to the next working moment.
        Delegates the working-moment predicate to OrgSettings — single source.
        """
        settings = self._settings

        # Normalise to working-hour boundaries before day-skipping
        if dt.hour >= settings.work_day_end_hour:
            dt = (dt + timedelta(days=1)).replace(
                hour=settings.work_day_start_hour,
                minute=0, second=0, microsecond=0,
            )
        elif dt.hour < settings.work_day_start_hour:
            dt = dt.replace(
                hour=settings.work_day_start_hour,
                minute=0, second=0, microsecond=0,
            )

        # Skip non-working days — calls is_working_day which honours holidays
        while not settings.is_working_day(dt.date()):
            dt = (dt + timedelta(days=1)).replace(
                hour=settings.work_day_start_hour,
                minute=0, second=0, microsecond=0,
            )
        return dt
```

### ✅ Pattern 3: MTTR window includes cross-boundary incidents
```python
# CORRECT: include incidents that were still open at window_start,
# so long-running incidents do not silently vanish from the metric.
def _incidents_relevant_to_window(
    incidents: Sequence[Incident],
    window_start: date,
    window_end: date,
) -> list[Incident]:
    """
    Include an incident if ANY part of its duration overlaps the window.
    Opened-before/resolved-within incidents are no longer silently excluded.
    """
    return [
        i for i in incidents
        if i.is_resolved
        and i.opened_at.date() <= window_end          # opened before window closes
        and i.resolved_at.date() >= window_start      # resolved after window opens
    ]
```

### ✅ Pattern 4: Full DORA calculator — working-time-aware, context-driven
```python
@dataclass
class DoraMetrics:
    deployment_frequency_per_working_day: float
    average_lead_time_for_changes_hours:  float
    mean_time_to_restore_hours:           float
    change_failure_rate_percent:          float
    working_days_in_window:               int
    total_deployments:                    int
    failed_deployments:                   int

def calculate_dora_metrics(
    deployments:  Sequence[Deployment],
    incidents:    Sequence[Incident],
    window_start: date,
    window_end:   date,
    org_settings: OrgSettings,       # ← sole source of calendar context
) -> DoraMetrics:
    calendar = WorkingCalendar(org_settings)
    working_days = calendar.count_working_days_in_range(window_start, window_end)

    deployments_in_window = [
        d for d in deployments
        if window_start <= d.deployed_at.date() <= window_end
    ]
    failed_count = sum(1 for d in deployments_in_window if d.caused_incident)

    lead_times = [
        calendar.working_hours_between(d.commit_time, d.deployed_at)
        for d in deployments_in_window
    ]
    avg_lead_time = sum(lead_times) / len(lead_times) if lead_times else 0.0

    relevant_incidents = _incidents_relevant_to_window(incidents, window_start, window_end)
    restore_times = [
        calendar.working_hours_between(i.opened_at, i.resolved_at)
        for i in relevant_incidents
    ]
    mttr = sum(restore_times) / len(restore_times) if restore_times else 0.0

    return DoraMetrics(
        deployment_frequency_per_working_day=round(
            len(deployments_in_window) / working_days if working_days else 0.0, 3
        ),
        average_lead_time_for_changes_hours=round(avg_lead_time, 2),
        mean_time_to_restore_hours=round(mttr, 2),
        change_failure_rate_percent=round(
            (failed_count / len(deployments_in_window) * 100)
            if deployments_in_window else 0.0, 2
        ),
        working_days_in_window=working_days,
        total_deployments=len(deployments_in_window),
        failed_deployments=failed_count,
    )
```

### ✅ Pattern 5: OrgSettings declaration — the only place working-time rules live
```python
# Declare ONCE. All calculators receive this object; none duplicate its knowledge.
thanksgiving      = date(2024, 11, 28)
day_after_holiday = date(2024, 11, 29)

standard_us_eng_org = OrgSettings(
    working_days=frozenset({
        Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY,
        Weekday.THURSDAY, Weekday.FRIDAY,
    }),
    holidays=frozenset({thanksgiving, day_after_holiday}),
    work_day_start_hour=9,
    work_day_end_hour=17,
)
# A Friday-EOD commit deployed Monday morning correctly reports ~0.75 working
# hours of lead time — not 64 wall-clock hours.
```

---

## Decision Checklist

| Question | Required Answer |
|---|---|
| Do all duration metrics call `WorkingCalendar.working_hours_between`, not `timedelta`? | ✅ Yes |
| Does `WorkingCalendar` call `OrgSettings.is_working_moment` / `is_working_day` exclusively? | ✅ Yes — no inline re-implementation |
| Is there exactly one `OrgSettings` instance passed to all calculators? | ✅ Yes |
| Does cursor advancement use explicit next-day replacement, not `+timedelta(seconds=1)`? | ✅ Yes |
| Are end-hour boundary semantics identical across `is_working_moment` and `working_hours_between`? | ✅ Yes — exclusive upper bound in both |
| Does the MTTR window include incidents that *overlap* the window, not just those *opened within* it? | ✅ Yes |
| Are `datetime` objects timezone-aware for multi-timezone orgs? | ✅ Required for production; naive datetimes only acceptable for single-tz demos |

---

## Key Principle Summary

> **Wall-clock time is the wrong unit for human-centric engineering metrics.** A Friday-evening incident resolved Monday morning is not a 64-hour failure — it is a few working hours. `OrgSettings` is the single contractual definition of what "working time" means for an organisation. Every calendar consumer must delegate to it; any inline re-implementation creates silent divergence the moment org policy changes. Correctness at the boundary (explicit cursor advancement, consistent end-hour semantics, cross-window incident inclusion) is what separates a metric that drives decisions from one that misleads them.