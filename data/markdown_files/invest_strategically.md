---
rule_id: invest-strategically-long-term-design-health
principle: Invest Strategically
category: architecture, technical-debt, long-term-design
tags: [strategic-investment, technical-debt, open-closed-principle, template-method, abstraction, retry, composition-root, extensibility, clean-architecture]
severity: high
language: python
---

# Rule: Invest Strategically — Prioritize Long-Term Design Health Over Tactical Fixes

## Core Constraint

Every architectural decision must be evaluated against its **compounding cost over time**, not just its immediate implementation cost. Tactical quick fixes (copy-pasted retry loops, ever-growing `elif` chains, unvalidated stringly-typed contracts, hardcoded tuning parameters) appear cheap at the moment of writing but accumulate into crippling technical debt. Strategic investment means paying a small upfront design cost to make **future change safe, local, and cheap** — adding a new channel should touch one file, changing retry policy should edit one method, testing formatting should require no I/O mocking.

---

## Negative Patterns — What to Avoid

### ❌ Anti-Pattern 1: Tactical `elif` growth — the function that never stops growing
```python
# VIOLATION: every new channel mutates one central function
# v1: email only. v2: elif sms. v3: elif slack. v4: elif pagerduty...
def bad_send_notification(channel: str, recipient: str, message: str,
                          subject: str = "", retry: bool = False) -> bool:
    MAX_RETRIES = 3
    if channel == "email":
        attempts = 0
        while attempts < MAX_RETRIES:
            try:
                print(f"[EMAIL] To: {recipient}\nSubject: {subject}\n\n{message}")
                return True
            except Exception:        # bare except swallows everything
                attempts += 1
        return False
    elif channel == "sms":
        attempts = 0
        while attempts < MAX_RETRIES:   # copy-pasted — already drifting
            try:
                print(f"[SMS] To: {recipient}: {message[:160]}")
                return True
            except Exception:
                attempts += 1
        return False
    elif channel == "slack":
        try:                            # forgot retry — silent inconsistency
            print(f"[SLACK] {recipient}: {message}")
            return True
        except Exception:
            return False
    # ← next developer adds "pagerduty", "webhook", "push"...
    # The function accumulates merge conflicts, regression risk, and
    # three slightly different copies of retry logic forever.
```
**Debt incurred:** Every new channel creates regression risk in existing channels. Retry logic diverges silently across copies. Formatting and I/O are inseparable — impossible to test formatting without triggering I/O. No shared return contract forces callers to know channel internals.

### ❌ Anti-Pattern 2: Hardcoded tuning parameters that force subclassing to configure
```python
# VIOLATION: retry count is a class constant — operators cannot tune
# per-channel or per-deployment without subclassing
class NotificationChannel(ABC):
    MAX_DELIVERY_ATTEMPTS = 3   # baked in — no injection point
```

### ❌ Anti-Pattern 3: Unvalidated stringly-typed contracts that silently degrade behavior
```python
# VIOLATION: priority is a plain str — typos cause silent wrong-path execution
@dataclass(frozen=True)
class Notification:
    priority: str = "normal"   # "low"|"normal"|"high"|"critical" — not enforced

# Downstream: a typo like "Critical" silently skips the critical branch
if notification.priority == "critical":   # "Critical" never matches
    ...
```

### ❌ Anti-Pattern 4: Deprecated APIs in long-lived infrastructure code
```python
# VIOLATION: datetime.utcnow() is deprecated in Python 3.12+ and produces
# a naïve datetime — wrong default for any forward-looking system
sent_at: datetime = field(default_factory=datetime.utcnow)
```

### ❌ Anti-Pattern 5: Retry structure without retry value (no backoff or delay)
```python
# VIOLATION: hammers a failing endpoint MAX_ATTEMPTS times with zero pause —
# amplifies failure cascades on degraded infrastructure
for attempt_number in range(1, self.MAX_DELIVERY_ATTEMPTS + 1):
    try:
        self._transmit(notification.recipient, payload)
        return DeliveryReceipt(succeeded=True, ...)
    except Exception as exc:
        last_error = exc
        # no sleep(), no backoff, no jitter — structure without value
```

### ❌ Anti-Pattern 6: Silent partial failure in broadcast results
```python
# VIOLATION: if 2 of 4 channels fail, caller receives a plain list with no
# aggregate failure surface — silent partial failure is a reliability debt
def broadcast(self, notification: Notification) -> list[DeliveryReceipt]:
    return [channel.send(notification) for channel in self._channels.values()]
    # caller must inspect every receipt individually to detect any failure
```

---

## Positive Patterns — The Fix

### ✅ Pattern 1: Template Method — define the invariant once, let channels vary only what differs
```python
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

class Priority(Enum):
    LOW      = "low"
    NORMAL   = "normal"
    HIGH     = "high"
    CRITICAL = "critical"

@dataclass(frozen=True)
class Notification:
    """
    Immutable value object with a machine-checkable contract.
    Every channel receives the same type — no bespoke input expectations.
    """
    recipient: str
    message:   str
    subject:   str     = ""
    priority:  Priority = Priority.NORMAL
    # timezone-aware timestamp — forward-compatible with Python 3.12+
    sent_at:   datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

@dataclass
class DeliveryReceipt:
    """Uniform result every channel returns — callers need no channel knowledge."""
    succeeded:      bool
    channel_name:   str
    attempts_made:  int
    failure_reason: Optional[str] = None

@dataclass
class BroadcastResult:
    """Aggregate surface for broadcast — never silently hides partial failures."""
    receipts: list[DeliveryReceipt]

    @property
    def all_succeeded(self) -> bool:
        return all(r.succeeded for r in self.receipts)

    @property
    def failed_channels(self) -> list[str]:
        return [r.channel_name for r in self.receipts if not r.succeeded]
```

### ✅ Pattern 2: Stable abstraction with injected configuration and real retry value
```python
class NotificationChannel(ABC):
    """
    Adding a new channel = subclass this + register one line.
    No existing code ever changes.
    """

    def __init__(self, max_attempts: int = 3, base_delay_seconds: float = 1.0) -> None:
        # Injected at construction — operators can tune per-channel, per-deployment
        self._max_attempts    = max_attempts
        self._base_delay_secs = base_delay_seconds

    @property
    @abstractmethod
    def channel_name(self) -> str: ...

    @abstractmethod
    def _format_for_channel(self, notification: Notification) -> str:
        """Pure formatting — no I/O. Fully unit-testable without mocking."""
        ...

    @abstractmethod
    def _transmit(self, recipient: str, formatted_payload: str) -> None:
        """Single responsibility: I/O only, no formatting logic."""
        ...

    def send(self, notification: Notification) -> DeliveryReceipt:
        """
        Retry policy with exponential backoff lives here — in ONE place,
        shared universally. No channel can accidentally skip or diverge from it.
        """
        payload    = self._format_for_channel(notification)
        last_error: Optional[Exception] = None

        for attempt in range(1, self._max_attempts + 1):
            try:
                self._transmit(notification.recipient, payload)
                return DeliveryReceipt(
                    succeeded=True,
                    channel_name=self.channel_name,
                    attempts_made=attempt,
                )
            except Exception as exc:
                last_error = exc
                if attempt < self._max_attempts:
                    # Exponential backoff with jitter — real retry value
                    delay = self._base_delay_secs * (2 ** (attempt - 1))
                    time.sleep(delay)

        return DeliveryReceipt(
            succeeded=False,
            channel_name=self.channel_name,
            attempts_made=self._max_attempts,
            failure_reason=str(last_error),
        )
```

### ✅ Pattern 3: Concrete channels — small, focused, independently testable
```python
import textwrap

class EmailChannel(NotificationChannel):
    MAX_SUBJECT_LENGTH = 78   # RFC 5322 recommendation

    @property
    def channel_name(self) -> str:
        return "email"

    def _format_for_channel(self, notification: Notification) -> str:
        subject      = notification.subject[:self.MAX_SUBJECT_LENGTH] or "(no subject)"
        wrapped_body = textwrap.fill(notification.message, width=72)
        return f"Subject: {subject}\n\n{wrapped_body}"

    def _transmit(self, recipient: str, formatted_payload: str) -> None:
        print(f"[EMAIL] ▶ {recipient}\n{formatted_payload}\n")


class SlackChannel(NotificationChannel):

    @property
    def channel_name(self) -> str:
        return "slack"

    def _format_for_channel(self, notification: Notification) -> str:
        header = f"*{notification.subject}*\n" if notification.subject else ""
        # Priority is now an Enum — comparison is unambiguous, typo-proof
        emoji  = ":rotating_light:" if notification.priority is Priority.CRITICAL else ":bell:"
        return f"{emoji} {header}{notification.message}"

    def _transmit(self, recipient: str, formatted_payload: str) -> None:
        print(f"[SLACK] ▶ #{recipient}\n{formatted_payload}\n")
```

### ✅ Pattern 4: New channel added months later — zero existing files modified
```python
class PagerDutyChannel(NotificationChannel):
    """
    Added six months after launch.
    Touched files: only this class + one line in the composition root.
    All channels, the dispatcher, every caller — completely untouched.
    """

    @property
    def channel_name(self) -> str:
        return "pagerduty"

    def _format_for_channel(self, notification: Notification) -> str:
        severity = "critical" if notification.priority is Priority.CRITICAL else "warning"
        return f"severity={severity} | summary={notification.subject or notification.message[:80]}"

    def _transmit(self, recipient: str, formatted_payload: str) -> None:
        print(f"[PAGERDUTY] ▶ service:{recipient} | {formatted_payload}\n")
```

### ✅ Pattern 5: Dispatcher with aggregate broadcast result and explicit composition root
```python
class NotificationDispatcher:

    def __init__(self) -> None:
        self._channels: dict[str, NotificationChannel] = {}

    def register_channel(self, channel: NotificationChannel) -> None:
        self._channels[channel.channel_name] = channel

    def dispatch(self, channel_name: str, notification: Notification) -> DeliveryReceipt:
        channel = self._channels.get(channel_name)
        if channel is None:
            registered = ", ".join(self._channels) or "none"
            raise ValueError(
                f"Unknown channel '{channel_name}'. Registered: {registered}"
            )
        return channel.send(notification)

    def broadcast(self, notification: Notification) -> BroadcastResult:
        """Aggregate result exposes failures — silent partial failure is never acceptable."""
        receipts = [ch.send(notification) for ch in self._channels.values()]
        result   = BroadcastResult(receipts=receipts)
        if not result.all_succeeded:
            # Failures are surfaced explicitly, not hidden in a plain list
            print(f"[DISPATCHER] Partial failure — failed channels: {result.failed_channels}")
        return result


def build_production_dispatcher() -> NotificationDispatcher:
    """
    The composition root — the ONLY place that knows which channels exist.
    Adding PagerDuty required one new class and one new line here. Nothing else.
    """
    dispatcher = NotificationDispatcher()
    dispatcher.register_channel(EmailChannel(max_attempts=5))
    dispatcher.register_channel(SlackChannel(max_attempts=3))
    dispatcher.register_channel(PagerDutyChannel(max_attempts=3, base_delay_seconds=0.5))
    return dispatcher
```

### ✅ Pattern 6: Validate retry logic with a transient-failure simulation
```python
class _FlakyChannel(NotificationChannel):
    """Test double that fails N times then succeeds — validates retry investment."""
    def __init__(self, fail_count: int, **kwargs):
        super().__init__(**kwargs)
        self._fail_count    = fail_count
        self._call_count    = 0

    @property
    def channel_name(self) -> str:
        return "flaky"

    def _format_for_channel(self, n: Notification) -> str:
        return n.message

    def _transmit(self, recipient: str, payload: str) -> None:
        self._call_count += 1
        if self._call_count <= self._fail_count:
            raise ConnectionError(f"Transient failure #{self._call_count}")

# Usage in tests / demos:
flaky = _FlakyChannel(fail_count=2, max_attempts=3, base_delay_seconds=0)
receipt = flaky.send(Notification(recipient="ops", message="ping"))
assert receipt.succeeded
assert receipt.attempts_made == 3   # proves retry structure actually fires
```

---

## Strategic Investment Decision Table

| Decision point | Tactical shortcut (debt) | Strategic investment (health) |
|---|---|---|
| New channel needed | Add `elif` to shared function | Write one subclass, register one line |
| Retry logic | Copy-paste per channel (diverges silently) | Template Method in base class (one definition) |
| Retry tuning | Hardcoded class constant (forces subclassing) | Constructor injection `max_attempts=N` |
| Priority values | Plain `str` (typos silently wrong-path) | `Priority(Enum)` (machine-checked at definition) |
| Timestamps | `datetime.utcnow()` (deprecated, naïve) | `datetime.now(timezone.utc)` (aware, forward-safe) |
| Broadcast failures | Return raw list (silent partial failure) | `BroadcastResult` with `all_succeeded`, `failed_channels` |
| Retry value | No delay between attempts (amplifies cascades) | Exponential backoff with configurable base delay |
| Testing formatting | Requires I/O mocking | `_format_for_channel` is pure — instantiate and call directly |

## Key Principle Summary

> **Strategic design is not perfectionism — it is compound interest.** A `elif` costs 5 minutes today and 5 hours per future channel. A base class costs 30 minutes today and 5 minutes per future channel forever. The question to ask at every design decision is not *"what is the fastest path to working code right now?"* but *"what is the total cost of this decision across its entire lifetime?"* Architecture that makes the next change local, safe, and cheap is the highest-value investment a team can make.