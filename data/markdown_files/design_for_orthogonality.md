---
rule_id: design-for-orthogonality
principle: Design for Orthogonality
category: architecture, coupling, separation-of-concerns
tags: [orthogonality, low-coupling, event-bus, pub-sub, composition-root, side-effects, isolation, subscribers]
severity: high
language: python
---

# Rule: Design for Orthogonality — Changing One Component Must Not Break Unrelated Areas

## Core Constraint

Structure systems so that **each component has exactly one reason to change, and changes to one component produce zero side effects in unrelated components**. Components must communicate through **shared contracts** (pure-data events, interfaces), never by calling each other directly. The composition root is the only location permitted to hold wiring knowledge.

---

## Negative Patterns — What to Avoid

### ❌ Anti-Pattern 1: Orchestrator that hard-wires all downstream collaborators
```python
# VIOLATION: OrderProcessor directly owns and calls every subsystem.
# Any change to BillingService, InventoryService, or EmailService
# creates pressure to modify this class — adding audit logging requires
# editing order-processing logic even though the two are unrelated.
class BadOrderProcessor:
    def __init__(self) -> None:
        self.email_service     = BadEmailService()      # hard-wired
        self.inventory_service = BadInventoryService()  # hard-wired
        self.billing_service   = BadBillingService()    # hard-wired

    def place_order(self, order_id, customer_id, customer_email,
                    product_id, quantity, total_amount):
        self.billing_service.charge_customer(customer_id, total_amount)
        self.inventory_service.deduct_stock(product_id, quantity)
        self.email_service.send_confirmation(customer_email, order_id)
        # Adding audit logging forces a change here — a violation of orthogonality
```

### ❌ Anti-Pattern 2: Bare exception propagation couples handlers at runtime
```python
# VIOLATION: if BillingSubscriber raises, InventorySubscriber and
# NotificationSubscriber never execute. One handler's failure becomes
# a hidden coupling that violates the orthogonality promise at runtime.
class EventBus:
    def publish(self, event: object) -> None:
        for handler in self._handlers.get(type(event), []):
            handler(event)   # ← unguarded: a single failure silences all subsequent handlers
```

### ❌ Anti-Pattern 3: Fat event payload couples all subscribers to a shared schema
```python
# VIOLATION: every field for every subscriber lives in one frozen dataclass.
# Adding a field for a new subscriber forces recompilation against the new
# schema for all existing subscribers — even those that ignore the field.
@dataclass(frozen=True)
class OrderPlacedEvent:
    event_id:          str
    order_id:          str
    customer_id:       str
    customer_email:    str     # only NotificationSubscriber cares
    product_id:        str     # only InventorySubscriber cares
    quantity:          int     # only InventorySubscriber cares
    total_amount:      float   # only BillingSubscriber cares
    new_field_for_sms: str     # adding this touches every subscriber's import
```

### ❌ Anti-Pattern 4: Unreachable state from composition root
```python
# VIOLATION: AuditLogSubscriber is constructed inside the function and
# permanently unreachable by the caller. The subscriber's only meaningful
# output — all_entries — can never be observed.
def build_order_system() -> OrderProcessor:
    audit_log = AuditLogSubscriber()                         # created here
    event_bus.subscribe(OrderPlacedEvent, audit_log.handle_order_placed)
    return OrderProcessor(event_bus)                         # audit_log is lost
```

### ❌ Anti-Pattern 5: Deprecated datetime API
```python
# VIOLATION: datetime.utcnow() is deprecated since Python 3.12.
occurred_at: datetime = field(default_factory=datetime.utcnow)
```

---

## Positive Patterns — The Fix

### ✅ Pattern 1: Event bus as the decoupling axis — publishers and subscribers are mutually invisible
```python
from __future__ import annotations
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

logger = logging.getLogger(__name__)

EventHandler = Callable[[object], None]


class EventBus:
    """
    Publishers emit into a void; subscribers react without knowing who published
    or what else reacted. Neither party holds a reference to the other.
    """
    def __init__(self) -> None:
        self._handlers: dict[type, list[EventHandler]] = {}

    def subscribe(self, event_type: type, handler: EventHandler) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    def publish(self, event: object) -> None:
        # ✅ Each handler is isolated: one failure cannot silence subsequent handlers.
        for handler in self._handlers.get(type(event), []):
            try:
                handler(event)
            except Exception:
                logger.exception(
                    "Handler %s failed for event %s — continuing dispatch.",
                    handler, type(event).__name__
                )
```

### ✅ Pattern 2: Pure-data event as the minimal shared contract
```python
@dataclass(frozen=True)
class OrderPlacedEvent:
    """
    The ONE thing all parties may legitimately know about.
    No behaviour — pure data only.
    Use timezone-aware datetime to avoid deprecated utcnow().
    """
    event_id:       str
    order_id:       str
    customer_id:    str
    customer_email: str
    product_id:     str
    quantity:       int
    total_amount:   float
    occurred_at:    datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)  # ✅ not utcnow()
    )
```

### ✅ Pattern 3: Core domain publishes and stops — knows nothing downstream
```python
class OrderProcessor:
    """
    Responsible for ONE thing: validating an order and announcing it happened.
    It has no knowledge of billing, inventory, notifications, or audit logging.
    Adding or removing any subscriber never touches this class.
    """
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    def place_order(
        self,
        customer_id: str,
        customer_email: str,
        product_id: str,
        quantity: int,
        total_amount: float,
    ) -> str:
        order_id = str(uuid.uuid4())[:8].upper()
        self._event_bus.publish(
            OrderPlacedEvent(
                event_id=str(uuid.uuid4()),
                order_id=order_id,
                customer_id=customer_id,
                customer_email=customer_email,
                product_id=product_id,
                quantity=quantity,
                total_amount=total_amount,
            )
        )
        return order_id
```

### ✅ Pattern 4: Each subscriber is self-contained — unaware of all others
```python
class BillingSubscriber:
    """Charges the customer. Knows nothing about inventory, email, or audit logs."""
    def handle_order_placed(self, event: OrderPlacedEvent) -> None:
        print(f"[Billing] Charged ${event.total_amount:.2f} to {event.customer_id}.")


class InventorySubscriber:
    """Adjusts stock. Knows nothing about billing, email, or audit logs."""
    def handle_order_placed(self, event: OrderPlacedEvent) -> None:
        print(f"[Inventory] Deducted {event.quantity} × {event.product_id}.")


class NotificationSubscriber:
    """Sends confirmation email. Knows nothing about billing, inventory, or audit logs."""
    def handle_order_placed(self, event: OrderPlacedEvent) -> None:
        print(f"[Notifications] Confirmation sent to {event.customer_email}.")


class AuditLogSubscriber:
    """Records every event for compliance. Added after all others — zero changes elsewhere."""
    def __init__(self) -> None:
        self._log: list[str] = []

    def handle_order_placed(self, event: OrderPlacedEvent) -> None:
        entry = (
            f"{event.occurred_at.isoformat()} | "
            f"ORDER {event.order_id} by {event.customer_id} | "
            f"${event.total_amount:.2f}"
        )
        self._log.append(entry)

    @property
    def all_entries(self) -> list[str]:
        return list(self._log)
```

### ✅ Pattern 5: Composition root — all wiring in one place; observable components returned
```python
from dataclasses import dataclass as _dc

@_dc
class OrderSystem:
    """Return type exposes all observable components, not just the entry point."""
    processor: OrderProcessor
    audit_log: AuditLogSubscriber


def build_order_system() -> OrderSystem:
    """
    The ONLY place that knows which components exist and how they connect.
    Adding SMS alerts = create SmsSubscriber + one subscribe() call here.
    Every other component remains completely untouched.
    """
    event_bus = EventBus()

    billing      = BillingSubscriber()
    inventory    = InventorySubscriber()
    notification = NotificationSubscriber()
    audit_log    = AuditLogSubscriber()   # ✅ returned so caller can inspect all_entries

    event_bus.subscribe(OrderPlacedEvent, billing.handle_order_placed)
    event_bus.subscribe(OrderPlacedEvent, inventory.handle_order_placed)
    event_bus.subscribe(OrderPlacedEvent, notification.handle_order_placed)
    event_bus.subscribe(OrderPlacedEvent, audit_log.handle_order_placed)

    return OrderSystem(
        processor=OrderProcessor(event_bus),
        audit_log=audit_log,
    )


# Usage — each component is independently reachable
system = build_order_system()
system.processor.place_order(
    customer_id="CUST-42",
    customer_email="alice@example.com",
    product_id="PROD-7",
    quantity=3,
    total_amount=149.97,
)
print(system.audit_log.all_entries)   # ✅ observable, not lost inside the factory
```

---

## Decision Rules

| Situation | Required Action |
|---|---|
| Component A needs to trigger behaviour in component B | Publish an event; never call B directly from A |
| Adding a new side-effect (e.g. SMS, analytics) | Create a new subscriber class; register it in the composition root only |
| A handler failure must not silence other handlers | Wrap each handler invocation in `try/except` with logging inside `publish()` |
| Subscriber needs observable state after wiring | Return the subscriber instance from the composition root alongside the entry point |
| A new field is needed by exactly one subscriber | Consider a narrower event type or envelope rather than growing the shared schema |
| `datetime.utcnow()` appears in any new code | Replace with `datetime.now(timezone.utc)` (deprecated since Python 3.12) |
| Wiring logic appears outside the composition root | Consolidate it into the single composition root function |

---

## Key Principle Summary

> **Orthogonality means a change in one component produces zero ripple in unrelated components.** The event bus enforces this at design time by eliminating direct references between subsystems. Isolated `try/except` dispatch in `publish()` enforces it at runtime by preventing one handler's failure from coupling to every subsequent handler. The composition root is the only permitted site of coupling knowledge — everything else communicates through pure-data contracts alone.