---
rule_id: independent-deployability
principle: Ensure Independent Deployability
category: architecture, distributed-systems
tags: [microservices, decoupling, event-driven, async-messaging, tolerant-reader, schema-versioning, idempotency, independent-deployment, service-isolation]
severity: high
language: python
---

# Rule: Design Services for Independent Deployability

## Core Constraint

Every service must be **modifiable, testable, and deployable without coordinating with any other service**. If deploying Service A requires simultaneously deploying Service B, they are too tightly coupled. Enforce this via: async event-driven communication, private data stores, versioned backward-compatible event contracts, tolerant reader pattern in consumers, and fully isolated test suites.

---

## Negative Patterns — What to Avoid

### ❌ Anti-Pattern 1: Synchronous inter-service calls create hard deployment dependencies
```python
# VIOLATION: OrderService directly instantiates and calls InventoryService.
# Rename any InventoryService method → OrderService breaks at runtime.
# Deploy InventoryService with a schema change → OrderService must redeploy simultaneously.
class BadOrderService:
    def place_order(self, product_id: str, quantity: int) -> dict:
        inventory_service = BadInventoryService()                  # ← hard coupling
        available = inventory_service.get_stock(product_id)       # ← sync call
        if available < quantity:
            raise ValueError("Insufficient stock")
        inventory_service.decrement_stock(product_id, quantity)   # ← sync call
```
**Why it fails:** Any change to `BadInventoryService`'s API or deployment state is a breaking change for `BadOrderService`. Both must deploy together — zero independent deployability.

### ❌ Anti-Pattern 2: Shared database schema owned by no one
```python
# VIOLATION: both services read and write the same tables.
# Adding a column to `inventory` forces both services to migrate simultaneously.
class BadSharedDatabase:
    orders: dict[str, dict] = {}       # ← shared by multiple services
    inventory: dict[str, dict] = {}    # ← shared by multiple services

class BadOrderService:
    def place_order(self, product_id, quantity):
        BadSharedDatabase.orders[...] = {...}           # ← writes shared schema

class BadInventoryService:
    def decrement_stock(self, product_id, quantity):
        BadSharedDatabase.inventory[product_id]["stock"] -= quantity  # ← shared schema
```
**Why it fails:** A schema migration in either service requires coordinated deployment of all services that touch those tables.

### ❌ Anti-Pattern 3: Synchronous in-process event delivery defeats async guarantees
```python
# VIOLATION: the bus calls handlers inline before publish() returns.
# An exception in InventoryService._on_order_placed propagates back to OrderService.place_order.
# OrderService is now blocked on InventoryService — temporal coupling survives.
class MessageBus:
    def publish(self, event: dict) -> None:
        self.published_events.append(event)
        for handler in self._subscribers.get(event.get("event_type", ""), []):
            handler(event)   # ← inline: OrderService blocks until handler completes
```
**Why it fails (production context):** Production buses (Kafka, SQS) deliver asynchronously with retry and dead-letter semantics. The in-process synchronous pattern is acceptable only as a demo simplification — **never ship this model**.

### ❌ Anti-Pattern 4: Brittle event consumers that crash on missing or renamed fields
```python
# VIOLATION: KeyError if any required field is absent or renamed by the producer.
# A single missing key crashes the handler with no dead-letter path.
def _on_order_placed(self, event: dict) -> None:
    order_id   = event["order_id"]    # ← KeyError if field removed or renamed
    product_id = event["product_id"]  # ← KeyError on schema mismatch
    quantity   = event["quantity"]    # ← KeyError if producer renames to "qty"
```

### ❌ Anti-Pattern 5: No idempotency guard on event handlers
```python
# VIOLATION: at-least-once delivery (Kafka, SQS standard) may deliver the same
# event twice. Without an idempotency check, stock is decremented twice.
def _on_order_placed(self, event: dict) -> None:
    # event["event_id"] is present but never checked
    stock.units_available -= quantity   # ← double-decrement on redelivery
    self._bus.publish(build_stock_reserved_event(...))  # ← duplicate event emitted
```

### ❌ Anti-Pattern 6: Shared event-contract module reintroduces a coordination point
```python
# VIOLATION: both services import from a shared module.
# Any change to shared_contracts.py forces both services to redeploy.
from shared_contracts import build_order_placed_event    # ← shared coordination point
from shared_contracts import build_stock_reserved_event  # ← InventoryService now coupled
                                                         #   to OrderService's release cycle
```

---

## Positive Patterns — The Fix

### ✅ Pattern 1: Async event-driven communication — no inter-service imports
```python
# Each service imports ONLY the message bus abstraction.
# Neither service references the other by name, class, or module.

class OrderService:
    """No import of, or reference to, InventoryService anywhere in this file."""

    def __init__(self, bus: MessageBus) -> None:
        self._bus = bus
        self._orders: dict[str, Order] = {}   # private data store — not shared
        bus.subscribe("StockReserved",          self._on_stock_reserved)
        bus.subscribe("StockReservationFailed", self._on_stock_reservation_failed)

    def place_order(self, product_id: str, quantity: int,
                    customer_tier: Optional[str] = None) -> Order:
        order = Order(order_id=str(uuid.uuid4()), product_id=product_id,
                      quantity=quantity, status="awaiting_stock_reservation")
        self._orders[order.order_id] = order
        # Fire-and-forget: no synchronous dependency on any other service
        self._bus.publish(build_order_placed_event(
            order.order_id, product_id, quantity, customer_tier=customer_tier
        ))
        return order


class InventoryService:
    """No import of, or reference to, OrderService anywhere in this file."""

    def __init__(self, bus: MessageBus) -> None:
        self._bus = bus
        self._stock: dict[str, StockRecord] = {}   # private data store
        bus.subscribe("OrderPlaced", self._on_order_placed)
```

### ✅ Pattern 2: Define a bus Protocol so services never depend on a concrete implementation
```python
from typing import Protocol

class BusProtocol(Protocol):
    """The only seam each service depends on. Swap Kafka, SQS, or a test double freely."""
    def subscribe(self, event_type: str, handler: Callable[[dict], None]) -> None: ...
    def publish(self, event: dict) -> None: ...

# Both services accept BusProtocol, not the concrete MessageBus class.
class OrderService:
    def __init__(self, bus: BusProtocol) -> None: ...

class InventoryService:
    def __init__(self, bus: BusProtocol) -> None: ...
```

### ✅ Pattern 3: Additive schema versioning preserves backward compatibility
```python
# Producer-owned contract: new optional fields never break existing consumers.
def build_order_placed_event(
    order_id: str,
    product_id: str,
    quantity: int,
    *,
    customer_tier: Optional[str] = None,   # v2 addition — optional, never required
) -> dict:
    event: dict[str, Any] = {
        "event_type":     "OrderPlaced",
        "schema_version": 2,
        "event_id":       str(uuid.uuid4()),
        "occurred_at":    datetime.now(timezone.utc).isoformat(),
        "order_id":       order_id,
        "product_id":     product_id,
        "quantity":       quantity,
    }
    if customer_tier is not None:    # purely additive — v1 consumers ignore it
        event["customer_tier"] = customer_tier
    return event
```

### ✅ Pattern 4: Tolerant reader + defensive field extraction + dead-letter path
```python
def _on_order_placed(self, event: dict) -> None:
    """
    Tolerant reader: extract only the fields this service needs.
    Unknown fields (e.g. customer_tier) are silently ignored.
    Missing required fields route to a dead-letter path — never crash the handler.
    """
    order_id   = event.get("order_id")
    product_id = event.get("product_id")
    quantity   = event.get("quantity")

    if not all([order_id, product_id, quantity is not None]):
        # Dead-letter: log and discard malformed event — do not crash
        self._bus.publish({"event_type": "MalformedEvent", "raw": event})
        return

    # 'customer_tier' present in schema v2 — deliberately ignored here;
    # InventoryService deploys independently and is unaffected by that addition.
    stock = self._stock.get(product_id)
    if stock is None or stock.units_available < quantity:
        self._bus.publish(build_stock_reservation_failed_event(
            order_id, product_id, reason="insufficient_stock"
        ))
        return

    stock.units_available -= quantity
    stock.units_reserved  += quantity
    self._bus.publish(build_stock_reserved_event(order_id, product_id, quantity))
```

### ✅ Pattern 5: Idempotency guard using event_id
```python
class InventoryService:
    def __init__(self, bus: BusProtocol) -> None:
        self._bus = bus
        self._stock: dict[str, StockRecord] = {}
        self._processed_event_ids: set[str] = set()   # idempotency log
        bus.subscribe("OrderPlaced", self._on_order_placed)

    def _on_order_placed(self, event: dict) -> None:
        event_id = event.get("event_id")
        if event_id and event_id in self._processed_event_ids:
            return   # at-least-once redelivery — safe to discard
        if event_id:
            self._processed_event_ids.add(event_id)
        # ... remainder of handler
```

### ✅ Pattern 6: Fully isolated test suites — each service tested with no peer present
```python
class TestOrderServiceInIsolation(unittest.TestCase):
    """OrderService tested with NO InventoryService instantiated anywhere."""

    def setUp(self) -> None:
        self.bus           = MessageBus()
        self.order_service = OrderService(self.bus)   # ← only OrderService

    def test_place_order_publishes_order_placed_event(self) -> None:
        order = self.order_service.place_order("prod-123", quantity=2)
        self.assertEqual(len(self.bus.published_events), 1)
        event = self.bus.published_events[0]
        self.assertEqual(event["event_type"], "OrderPlaced")
        self.assertEqual(event["order_id"],   order.order_id)

    def test_order_confirmed_when_stock_reserved_event_received(self) -> None:
        order = self.order_service.place_order("prod-123", quantity=2)
        # Simulate InventoryService response — no real service needed
        self.bus.publish(build_stock_reserved_event(order.order_id, "prod-123", 2))
        self.assertEqual(self.order_service.get_order(order.order_id).status, "confirmed")


class TestInventoryServiceInIsolation(unittest.TestCase):
    """InventoryService tested with NO OrderService instantiated anywhere."""

    def setUp(self) -> None:
        self.bus               = MessageBus()
        self.inventory_service = InventoryService(self.bus)   # ← only InventoryService
        self.inventory_service.add_stock("prod-123", units=10)

    def test_reservation_succeeds_when_stock_is_available(self) -> None:
        self.bus.publish(build_order_placed_event("order-1", "prod-123", quantity=3))
        reserved = [e for e in self.bus.published_events if e["event_type"] == "StockReserved"]
        self.assertEqual(len(reserved), 1)
        self.assertEqual(reserved[0]["quantity_reserved"], 3)
        stock = self.inventory_service.get_stock_record("prod-123")
        self.assertEqual(stock.units_available, 7)

    def test_reservation_fails_when_stock_is_insufficient(self) -> None:
        self.bus.publish(build_order_placed_event("order-2", "prod-123", quantity=99))
        failed = [e for e in self.bus.published_events if e["event_type"] == "StockReservationFailed"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["reason"], "insufficient_stock")
```

---

## Decision Checklist

| Question | Required Answer |
|---|---|
| Does Service A import or instantiate Service B? | ❌ Never |
| Do services share a database schema or data store? | ❌ Never |
| Does placing an order block on an inventory response? | ❌ Never in production |
| Is the message bus dependency expressed as a Protocol/interface? | ✅ Yes |
| Are event schemas additive-only, with new fields optional? | ✅ Yes |
| Do consumers use `.get()` with validation and a dead-letter path? | ✅ Yes |
| Is each service's test suite free of all peer service instantiations? | ✅ Yes |
| Are event handlers idempotent, checked against a processed-event log? | ✅ Yes |
| Do event contracts live in the producer's own package, not a shared module? | ✅ Yes |

---

## Production Deployment Notes

| In-process demo simplification | Production replacement |
|---|---|
| `MessageBus.publish()` calls handlers synchronously | Kafka / SQS / RabbitMQ: async delivery, retry, dead-letter queue |
| `_processed_event_ids` is an in-memory `set` | Distributed idempotency store: Redis, DynamoDB conditional writes |
| Event contracts in a shared module | Producer-owned versioned package published to an internal registry |
| `MessageBus` concrete class | `BusProtocol` with adapter implementations per broker |

---

## Key Principle Summary

> **Independent deployability is enforced at the boundary, not by convention.** The structural proof is: if you can delete Service B's entire codebase and Service A's tests still pass, the services are correctly decoupled. Achieve this through async events, private data stores, tolerant readers, additive schema versioning, and idempotent handlers — each property independently necessary, collectively sufficient.