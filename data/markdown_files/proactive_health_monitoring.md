---
rule_id: proactive-health-monitoring
principle: Proactive Health Monitoring
category: platform-engineering, observability, developer-experience
tags: [burnout, WIP-limits, off-hours-activity, alert-fatigue, trend-detection, leading-indicators, SSOT, scoring, thresholds, proactive-monitoring]
severity: high
language: python
---

# Rule: Correlate WIP, Off-Hours Activity, and Alert Frequency for Proactive Burnout Detection

## Core Constraint

A health monitoring system must track **leading indicators** (WIP accumulation, boundary violations, alert burden) rather than lagging ones (attrition, sick leave). All thresholds must be named constants with documented rationale. Scoring must use its computed weighted indices **consistently across all severity bands** — not only in the lowest band. The system must **push findings automatically** on a cadence; a system requiring manual invocation is operationally reactive by definition.

---

## Negative Patterns — What to Avoid

### ❌ Missing `date` import causes runtime crash at class definition
```python
# VIOLATION: date is used as a type annotation but never imported
from datetime import datetime, time   # ← date is absent

@dataclass
class WeeklyActivitySnapshot:
    week_ending_date: date   # ← NameError at class definition time
```

### ❌ Weighted burden index computed but silently dropped in higher severity bands
```python
# VIOLATION: alert_burden_index incorporates sleep-hour and unacknowledged weights,
# but only the HEALTHY band uses it. ELEVATED and CRITICAL revert to raw total_alerts,
# making the most damaging alert patterns go under-detected at higher severity.
def score_alert_burden(total_alerts, sleep_hour_alerts, unacknowledged_alerts):
    alert_burden_index = (
        total_alerts +
        (sleep_hour_alerts * 3) +
        (unacknowledged_alerts * 2)
    )
    if total_alerts <= HEALTHY_ALERTS_PER_WEEK:
        stress_score = (alert_burden_index / (HEALTHY_ALERTS_PER_WEEK * 6)) * 30  # ← uses index
    elif total_alerts <= ELEVATED_ALERTS_PER_WEEK:
        stress_score = 30 + ((total_alerts - HEALTHY_ALERTS_PER_WEEK) / ...) * 40  # ← drops index
    else:
        stress_score = 70 + (((total_alerts - ELEVATED_ALERTS_PER_WEEK) / ...) * 30)  # ← drops index
```

### ❌ Magic multiplier embedded inline without rationale
```python
# VIOLATION: 1.5 weekend multiplier has no name and no documented reason,
# inconsistent with every other threshold in the system
total_boundary_violations = off_hours_commits + (weekend_commits * 1.5)
```

### ❌ System detects risk but has no delivery mechanism — passive by design
```python
# VIOLATION: assessment is computed but only returned; nothing pushes it anywhere
assessment = assess_engineer_burnout_risk(history)
return assessment   # who sees this? when? only if someone queries it manually.
```

### ❌ Universal thresholds applied to all engineers regardless of individual baseline
```python
# VIOLATION: an engineer whose normal WIP is 7 hitting 9 carries different signal
# weight than one whose normal WIP is 2 hitting 9 — both trigger the same threshold
ELEVATED_WIP_LIMIT = 6   # applied identically to every engineer on every team
```

### ❌ Misleading output that ignores conditional logic
```python
# VIOLATION: coupon/alert line printed unconditionally regardless of whether
# the threshold was actually met — output contradicts the actual computation
f"  Coupon deduction applied: ${cart.coupon_discount_amount:.2f}\n"
# same anti-pattern in monitoring:
f"  Alert burden index applied: {alert_burden_index}\n"   # printed even when ignored
```

---

## Positive Patterns — The Fix

### ✅ Correct imports — all types used in annotations must be explicitly imported
```python
from datetime import date, datetime, time   # date is required for WeeklyActivitySnapshot
```

### ✅ Named constant for every magic number, with rationale comment
```python
HEALTHY_WIP_LIMIT                  = 3      # tasks in flight; above this, context-switching degrades output
ELEVATED_WIP_LIMIT                 = 6
CRITICAL_WIP_LIMIT                 = 9

HEALTHY_OFF_HOURS_COMMITS_PER_WEEK  = 2
ELEVATED_OFF_HOURS_COMMITS_PER_WEEK = 6
CRITICAL_OFF_HOURS_COMMITS_PER_WEEK = 12

HEALTHY_ALERTS_PER_WEEK             = 3
ELEVATED_ALERTS_PER_WEEK            = 10
CRITICAL_ALERTS_PER_WEEK            = 20

WEEKEND_COMMIT_BURDEN_MULTIPLIER    = 1.5   # weekends disrupt full-day recovery, not just hours
SLEEP_HOUR_ALERT_WEIGHT             = 3     # fragments the most critical rest window (22:00–07:00)
UNACKNOWLEDGED_ALERT_WEIGHT         = 2     # proxy for exhaustion — engineer too depleted to respond
TREND_ESCALATION_WINDOW_WEEKS       = 3     # sustained elevation distinguishes anomaly from systemic problem

WIP_SCORE_WEIGHT                    = 0.40  # strongest single predictor of cognitive overload
OFF_HOURS_SCORE_WEIGHT              = 0.35
ALERT_FREQUENCY_SCORE_WEIGHT        = 0.25
```

### ✅ Burden index used consistently across ALL severity bands
```python
def score_alert_burden(
    total_alerts: int, sleep_hour_alerts: int, unacknowledged_alerts: int
) -> DimensionScore:
    """
    Sleep-hour and unacknowledged alerts are weighted because they signal
    recovery disruption and exhaustion, not just alert volume.
    The burden index drives scoring in every severity band — not just HEALTHY.
    """
    alert_burden_index = (
        total_alerts +
        (sleep_hour_alerts * SLEEP_HOUR_ALERT_WEIGHT) +
        (unacknowledged_alerts * UNACKNOWLEDGED_ALERT_WEIGHT)
    )
    # Normalise against the maximum expected burden at each band boundary
    healthy_band_ceiling  = HEALTHY_ALERTS_PER_WEEK  * (1 + SLEEP_HOUR_ALERT_WEIGHT + UNACKNOWLEDGED_ALERT_WEIGHT)
    elevated_band_ceiling = ELEVATED_ALERTS_PER_WEEK * (1 + SLEEP_HOUR_ALERT_WEIGHT + UNACKNOWLEDGED_ALERT_WEIGHT)
    critical_band_ceiling = CRITICAL_ALERTS_PER_WEEK * (1 + SLEEP_HOUR_ALERT_WEIGHT + UNACKNOWLEDGED_ALERT_WEIGHT)

    if alert_burden_index <= healthy_band_ceiling:
        stress_score = (alert_burden_index / healthy_band_ceiling) * 30
        risk_level   = RiskLevel.HEALTHY
    elif alert_burden_index <= elevated_band_ceiling:
        stress_score = 30 + (
            (alert_burden_index - healthy_band_ceiling) /
            (elevated_band_ceiling - healthy_band_ceiling)
        ) * 40
        risk_level   = RiskLevel.ELEVATED
    else:
        stress_score = 70 + min(
            (alert_burden_index - elevated_band_ceiling) /
            (critical_band_ceiling - elevated_band_ceiling) * 30,
            30,
        )
        risk_level   = RiskLevel.CRITICAL

    return DimensionScore(
        dimension_name="Alert Burden",
        raw_value=float(alert_burden_index),
        stress_score=round(min(stress_score, 100.0), 1),
        risk_level=risk_level,
        contributing_detail=(
            f"{total_alerts} total alerts, {sleep_hour_alerts} during sleep hours, "
            f"{unacknowledged_alerts} unacknowledged (burden index={alert_burden_index})"
        ),
    )
```

### ✅ Named multiplier applied in off-hours scoring
```python
def score_off_hours_activity(off_hours_commits: int, weekend_commits: int) -> DimensionScore:
    total_boundary_violations = off_hours_commits + (weekend_commits * WEEKEND_COMMIT_BURDEN_MULTIPLIER)
    ...
```

### ✅ Trend detection distinguishes anomaly from systemic problem
```python
def detect_compounding_burnout_trend(
    recent_weekly_assessments: list[WeeklyBurnoutAssessment],
) -> bool:
    """
    A single bad week can be an anomaly.
    Elevated/critical risk sustained across TREND_ESCALATION_WINDOW_WEEKS weeks
    is a systemic problem requiring structural intervention, not a one-off conversation.
    """
    if len(recent_weekly_assessments) < TREND_ESCALATION_WINDOW_WEEKS:
        return False

    last_n_weeks = recent_weekly_assessments[-TREND_ESCALATION_WINDOW_WEEKS:]
    return all(
        assessment.overall_risk_level in (RiskLevel.ELEVATED, RiskLevel.CRITICAL)
        for assessment in last_n_weeks
    )
```

### ✅ Notification layer makes the system genuinely proactive
```python
from typing import Protocol

class AssessmentNotifier(Protocol):
    """Any delivery mechanism (Slack, webhook, email, ticketing) satisfies this interface."""
    def deliver(self, assessment: WeeklyBurnoutAssessment) -> None: ...

def run_weekly_burnout_sweep(
    all_engineer_histories: list[EngineerActivityHistory],
    notifier: AssessmentNotifier,
) -> list[WeeklyBurnoutAssessment]:
    """
    Called by a scheduler (cron, Airflow DAG, Lambda trigger) — never manually.
    Findings are pushed to stakeholders before anyone thinks to check a dashboard.
    """
    assessments = []
    for history in all_engineer_histories:
        if not history.weekly_snapshots:
            continue
        latest_snapshot = history.weekly_snapshots[-1]
        assessment = assess_engineer_burnout_risk(history, latest_snapshot)
        if assessment.overall_risk_level != RiskLevel.HEALTHY:
            notifier.deliver(assessment)   # push, never wait to be queried
        assessments.append(assessment)
    return assessments
```

### ✅ Per-engineer baseline calibration reduces false positives
```python
def calculate_personal_wip_baseline(
    history: EngineerActivityHistory,
    calibration_window_weeks: int = 8,
) -> float:
    """
    Rolling median WIP over a quiet calibration period.
    An engineer at WIP=7 as their normal should not trigger the same threshold
    as one whose normal is WIP=2 — signal strength is relative to the individual.
    """
    quiet_weeks = [
        s for s in history.weekly_snapshots
        if s.average_wip_count <= HEALTHY_WIP_LIMIT * 2   # weeks without obvious crisis
    ][-calibration_window_weeks:]

    if not quiet_weeks:
        return float(HEALTHY_WIP_LIMIT)   # fall back to universal default

    return statistics.median(s.average_wip_count for s in quiet_weeks)
```

### ✅ Conditional output label reflects actual computation
```python
def format_alert_burden_summary(
    alert_score: DimensionScore,
    sleep_hour_alerts: int,
) -> str:
    if alert_score.risk_level == RiskLevel.HEALTHY:
        return f"  Alert burden: within healthy range ({alert_score.contributing_detail})\n"
    else:
        return (
            f"  ⚠️  Alert burden index: {alert_score.raw_value:.0f} "
            f"({alert_score.contributing_detail})\n"
        )
```

---

## Architecture Checklist

| Requirement | Correct Approach |
|---|---|
| All type annotations have matching imports | Verify `date`, `datetime`, `time` are each explicitly imported |
| Weighted index used in every scoring band | Never revert to raw counts after computing a burden index |
| Every numeric threshold is a named constant | Include a comment documenting units and rationale |
| Trend detection window is configurable | Use `TREND_ESCALATION_WINDOW_WEEKS` constant, not a hardcoded literal |
| Findings are delivered, not just returned | Inject an `AssessmentNotifier`; trigger via scheduler, not manual call |
| Thresholds account for individual baselines | Compute rolling median WIP/alert baseline per engineer before scoring |
| Output labels reflect actual conditional logic | Never print "X applied" when X may have been skipped |

---

## Key Principle Summary

> **Proactive monitoring fails at implementation if its scoring logic is internally inconsistent.** A burden index computed but then silently dropped in higher severity bands means the most damaging patterns — sleep disruption, exhaustion-driven non-response — go under-detected precisely when they matter most. Consistent application of weighted indices across all severity bands, combined with automatic scheduled delivery and per-engineer baseline calibration, is what separates a genuinely proactive system from a dashboard that requires someone to already suspect a problem before they look.