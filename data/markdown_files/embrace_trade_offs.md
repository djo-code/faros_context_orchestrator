---
rule_id: embrace-tradeoffs-no-perfect-architecture
principle: Embrace Trade-offs
category: architecture, decision-making, system-design
tags: [trade-offs, architecture, SSOT, context-driven-design, weighted-scoring, sensitivity-analysis, decision-records, maintainability, scalability, performance]
severity: high
language: python
---

# Rule: Embrace Trade-offs — No Architecture Is Universally Correct

## Core Constraint

Every structural decision **balances competing characteristics** (scalability, maintainability, cost, performance, operational complexity, time-to-market). There is no universally optimal architecture. The correct choice is always **context-dependent**: the same architecture that is right for an early-stage startup is wrong for a regulated enterprise. Trade-offs must be made **explicit, documented, and revisitable** — not buried or pretended away.

---

## Negative Patterns — What to Avoid

### ❌ Anti-Pattern 1: Declaring a universal winner without acknowledging context
```python
# VIOLATION: asserts microservices are "best" with no context, no acknowledged costs
def choose_architecture():
    return "Microservices — industry standard, always scalable, best practice."

# Problems:
# - Ignores team size, budget, ops maturity, and current traffic
# - Does not surface known costs (network latency, distributed failures, DevOps burden)
# - Cannot be revisited when context changes because no context was ever recorded
```

### ❌ Anti-Pattern 2: Scoring without exposing the scoring model's own trade-offs
```python
# VIOLATION: uses a linear weighted sum but never acknowledges model assumptions
def score(candidate, weights):
    return sum(candidate.scores[c] * weights[c] for c in weights)
    # Assumes: characteristic independence, cardinal scores, precise weights.
    # Interactions (e.g., microservices structurally constrain performance ceiling
    # regardless of weight values) are invisible to this model.
    # No comment explains WHY this model was chosen over TOPSIS or AHP.
```

### ❌ Anti-Pattern 3: Sensitivity analysis that varies context but not scores
```python
# VIOLATION: perturbs weights across contexts but treats scores as ground truth
for context in ALL_CONTEXTS:
    ranked = rank_candidates_for_context(candidates, context)
    # If MICROSERVICES.MAINTAINABILITY is 5 ± 2 (scores are opinions!),
    # does the winner change? This is never tested.
    # Real architectural debates live in score uncertainty, not just weight variation.
```

### ❌ Anti-Pattern 4: Reporting only the winner's breakdown — hiding how close the decision was
```python
# VIOLATION: only the winner's score decomposition is shown
lines.append(f"  Score breakdown for recommended architecture: {winner.name}")
# A reader cannot see:
# - How far behind the runner-up was
# - Which specific characteristics drove the gap
# - Whether a small context shift would flip the result
# Showing only the winner conceals the trade-off structure the framework exists to reveal.
```

### ❌ Anti-Pattern 5: No input validation on the scoring model's own inputs
```python
# VIOLATION: accepts any integer for scores, any float for weights
@dataclass
class ArchitectureCandidate:
    scores: dict[ArchitecturalCharacteristic, int]   # accepts -999 or 999 silently

@dataclass
class ProjectContext:
    weights: dict[ArchitecturalCharacteristic, float]  # negative weights accepted
    # A framework for careful trade-off reasoning should guard its own inputs.
```

### ❌ Anti-Pattern 6: No audit trail for decisions over time
```python
# VIOLATION: context and scores are modelled statically; no record of what was
# chosen, when, and why — so future engineers must reconstruct reasoning from scratch
# rather than revisiting a recorded decision.
ALL_CONTEXTS = [EARLY_STAGE_STARTUP, GROWTH_STAGE_SCALEUP, REGULATED_ENTERPRISE]
# Missing: DecisionRecord(chosen_architecture, context_snapshot, timestamp, rationale)
```

---

## Positive Patterns — The Fix

### ✅ Pattern 1: Context as a first-class, validated, weight-bearing object
```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

@dataclass(frozen=True)
class ArchitecturalCharacteristic:
    """A single quality axis on which an architecture can be evaluated."""
    name:        str
    description: str

# Define the universe of characteristics once — used everywhere
SCALABILITY            = ArchitecturalCharacteristic("scalability",             "Ability to handle growing load")
MAINTAINABILITY        = ArchitecturalCharacteristic("maintainability",         "Ease of understanding and modifying the system")
OPERATIONAL_COMPLEXITY = ArchitecturalCharacteristic("operational_complexity",  "Infrastructure burden on the team (lower is better)")
COST_EFFICIENCY        = ArchitecturalCharacteristic("cost_efficiency",         "Value delivered per dollar spent")
PERFORMANCE            = ArchitecturalCharacteristic("performance",             "Raw speed and latency")
TIME_TO_MARKET         = ArchitecturalCharacteristic("time_to_market",          "How quickly features can be shipped")

ALL_CHARACTERISTICS = [
    SCALABILITY, MAINTAINABILITY, OPERATIONAL_COMPLEXITY,
    COST_EFFICIENCY, PERFORMANCE, TIME_TO_MARKET,
]

VALID_SCORE_RANGE = range(0, 11)   # 0–10 inclusive


@dataclass
class ProjectContext:
    """
    The weights that reflect the team's current priorities.
    These WILL change as the product, team, and business evolve —
    and when they do, the recommended architecture should be revisited.

    Weights must sum to 1.0 and be non-negative.
    """
    name:      str
    weights:   dict[ArchitecturalCharacteristic, float]
    rationale: str = ""

    def __post_init__(self) -> None:
        # Guard: no negative weights
        for char, w in self.weights.items():
            if w < 0:
                raise ValueError(
                    f"Context '{self.name}': weight for '{char.name}' "
                    f"must be non-negative, got {w}"
                )
        # Guard: weights must sum to 1.0
        total = sum(self.weights.values())
        if not (0.99 < total < 1.01):
            raise ValueError(
                f"Context '{self.name}': weights must sum to 1.0, got {total:.3f}"
            )


EARLY_STAGE_STARTUP = ProjectContext(
    name = "Early-Stage Startup",
    rationale = (
        "Two engineers, no customers yet. Speed and simplicity are everything. "
        "We can re-architect when we have real scale problems — a luxury problem."
    ),
    weights = {
        SCALABILITY:             0.05,
        MAINTAINABILITY:         0.20,
        OPERATIONAL_COMPLEXITY:  0.15,
        COST_EFFICIENCY:         0.25,
        PERFORMANCE:             0.05,
        TIME_TO_MARKET:          0.30,
    },
)

GROWTH_STAGE_SCALEUP = ProjectContext(
    name = "Growth-Stage Scale-up",
    rationale = (
        "Product-market fit found. Traffic is spiking. 15 engineers, "
        "dedicated platform team. Scalability and team autonomy now outweigh "
        "simplicity."
    ),
    weights = {
        SCALABILITY:             0.30,
        MAINTAINABILITY:         0.20,
        OPERATIONAL_COMPLEXITY:  0.10,
        COST_EFFICIENCY:         0.15,
        PERFORMANCE:             0.15,
        TIME_TO_MARKET:          0.10,
    },
)

REGULATED_ENTERPRISE = ProjectContext(
    name = "Regulated Enterprise",
    rationale = (
        "Large bank. Auditors demand traceability. Ops team of 50. "
        "Outages cost millions. Maintainability and predictable performance "
        "trump speed and cost."
    ),
    weights = {
        SCALABILITY:             0.15,
        MAINTAINABILITY:         0.30,
        OPERATIONAL_COMPLEXITY:  0.10,
        COST_EFFICIENCY:         0.05,
        PERFORMANCE:             0.30,
        TIME_TO_MARKET:          0.10,
    },
)

ALL_CONTEXTS = [EARLY_STAGE_STARTUP, GROWTH_STAGE_SCALEUP, REGULATED_ENTERPRISE]
```

### ✅ Pattern 2: Architecture candidates with validated scores and explicit known risks
```python
@dataclass
class ArchitectureCandidate:
    """
    One structural option being considered.
    Scores are 0 (terrible) – 10 (excellent) for each characteristic.
    Scores are OPINIONS — they should be challenged and revised.
    """
    name:        str
    description: str
    scores:      dict[ArchitecturalCharacteristic, int]
    known_risks: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        for char, score in self.scores.items():
            if score not in VALID_SCORE_RANGE:
                raise ValueError(
                    f"Candidate '{self.name}': score for '{char.name}' "
                    f"must be 0–10, got {score}"
                )

    def score_for(self, characteristic: ArchitecturalCharacteristic) -> int:
        return self.scores.get(characteristic, 0)


MONOLITH = ArchitectureCandidate(
    name        = "Modular Monolith",
    description = "Single deployable unit with internal module boundaries",
    scores = {
        SCALABILITY:             5,
        MAINTAINABILITY:         8,
        OPERATIONAL_COMPLEXITY:  9,   # low ops burden → high score
        COST_EFFICIENCY:         9,
        PERFORMANCE:             8,
        TIME_TO_MARKET:          9,
    },
    known_risks = [
        "Vertical scaling ceiling may be hit under extreme load",
        "Module boundaries can erode over time without discipline",
        "Full redeployment required for any change",
    ],
)

MICROSERVICES = ArchitectureCandidate(
    name        = "Microservices",
    description = "Fine-grained independently deployable services over a network",
    scores = {
        SCALABILITY:             10,
        MAINTAINABILITY:          5,   # each service is simple; the system is complex
        OPERATIONAL_COMPLEXITY:   3,   # high ops burden → low score
        COST_EFFICIENCY:          4,
        PERFORMANCE:              6,   # network overhead hurts latency
        TIME_TO_MARKET:           4,   # coordination cost slows delivery
    },
    known_risks = [
        "Distributed system failures are hard to diagnose",
        "Network latency accumulates across service call chains",
        "Requires mature DevOps, CI/CD, and observability tooling",
        "Team coordination overhead grows with number of services",
    ],
)

SERVERLESS = ArchitectureCandidate(
    name        = "Serverless (FaaS)",
    description = "Event-driven functions managed entirely by a cloud provider",
    scores = {
        SCALABILITY:             9,
        MAINTAINABILITY:         6,
        OPERATIONAL_COMPLEXITY:  8,   # provider handles infrastructure
        COST_EFFICIENCY:         7,   # cheap at low volume, expensive at scale
        PERFORMANCE:             5,   # cold-start latency is real
        TIME_TO_MARKET:          8,
    },
    known_risks = [
        "Cold-start latency unacceptable for latency-sensitive workloads",
        "Vendor lock-in limits portability",
        "Cost per invocation escalates unpredictably at high throughput",
        "Long-running workloads are awkward to model as functions",
    ],
)

ALL_CANDIDATES = [MONOLITH, MICROSERVICES, SERVERLESS]
```

### ✅ Pattern 3: Transparent evaluation engine with documented model assumptions
```python
@dataclass
class EvaluatedCandidate:
    candidate:       ArchitectureCandidate
    weighted_score:  float
    score_breakdown: dict[str, float]   # characteristic name → weighted contribution


def evaluate_candidate(
    candidate: ArchitectureCandidate,
    context:   ProjectContext,
) -> EvaluatedCandidate:
    """
    Score a candidate using a linear weighted sum.

    Model trade-off acknowledged: this approach assumes characteristic
    independence and cardinal (not ordinal) score values. It does not
    model interactions between characteristics (e.g., microservices
    architecturally constrain the performance ceiling regardless of weights).
    A simple weighted sum was chosen over MCDA methods (TOPSIS, AHP) because
    transparency and inspectability outweigh modelling precision here.
    """
    breakdown: dict[str, float] = {}
    total_weighted_score = 0.0
    for characteristic, weight in context.weights.items():
        raw_score             = candidate.score_for(characteristic)
        weighted_contribution = raw_score * weight
        breakdown[characteristic.name] = round(weighted_contribution, 3)
        total_weighted_score          += weighted_contribution
    return EvaluatedCandidate(
        candidate       = candidate,
        weighted_score  = round(total_weighted_score, 3),
        score_breakdown = breakdown,
    )


def rank_candidates_for_context(
    candidates: list[ArchitectureCandidate],
    context:    ProjectContext,
) -> list[EvaluatedCandidate]:
    evaluations = [evaluate_candidate(c, context) for c in candidates]
    return sorted(evaluations, key=lambda e: e.weighted_score, reverse=True)
```

### ✅ Pattern 4: Report that exposes ALL candidates and the delta between them
```python
def format_trade_off_report(
    context:    ProjectContext,
    candidates: list[ArchitectureCandidate],
) -> str:
    """
    Show all candidates' breakdowns and the gap to the winner — so the
    trade-off structure is visible, not hidden behind a single recommendation.
    """
    ranked = rank_candidates_for_context(candidates, context)
    winner = ranked[0]
    lines  = [
        f"╔{'═' * 62}╗",
        f"║  Context: {context.name:<51}║",
        f"╚{'═' * 62}╝",
        f"  Rationale: {context.rationale}",
        "",
        f"  {'Architecture':<26} {'Weighted Score':>16}   {'Gap to Winner':>13}  Rank",
        f"  {'─' * 26} {'─' * 16}   {'─' * 13}  {'─' * 4}",
    ]
    for rank, evaluation in enumerate(ranked, start=1):
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, "  ")
        gap   = winner.weighted_score - evaluation.weighted_score
        gap_str = f"-{gap:.3f}" if gap > 0 else "  —"
        lines.append(
            f"  {evaluation.candidate.name:<26} "
            f"{evaluation.weighted_score:>16.3f}   "
            f"{gap_str:>13}  {medal} #{rank}"
        )

    # Show ALL candidates' breakdowns so the reader can see what drove each score
    lines += ["", f"  Score breakdown by characteristic across all candidates:"]
    header = f"  {'Characteristic':<26} {'Weight':>8}"
    for evaluation in ranked:
        header += f"  {evaluation.candidate.name[:12]:>12}"
    lines.append(header)
    lines.append(f"  {'─' * 26} {'─' * 8}" + ("  " + "─" * 12) * len(ranked))
    for characteristic, weight in context.weights.items():
        row = f"  {characteristic.name:<26} {weight:>8.0%}"
        for evaluation in ranked:
            contrib = evaluation.score_breakdown[characteristic