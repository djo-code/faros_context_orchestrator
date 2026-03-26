---
rule_id: align-with-business-boundaries
principle: Align with Business Boundaries
alias: Bounded Contexts / Domain-Driven Design (DDD)
category: architecture, microservices, system-design
tags: [bounded-context, DDD, microservices, domain-events, SSOT, event-driven, decoupling, ubiquitous-language, anti-corruption-layer]
severity: high
language: python
scope: system-architecture
---

# Rule: Structure Components Around Business Domains, Not Technical Layers

## Core Constraint

Microservices and system components **must be organized around distinct business domains (Bounded Contexts)**, each owning its own models, language, data, and logic. Cross-context communication must happen exclusively through **published domain events** — never through direct service instantiation, shared tables, or internal cross-domain imports. Each context must be independently deployable and testable without spinning up neighboring contexts.

---

## Negative Patterns — What to Avoid

### ❌ Anti-Pattern 1: Technical layer organization with direct cross-domain calls
```
# BAD — directory structure organized by technical layer
bad_layered_app/
├── models/
│   ├── order_model.py       ← Order, InventoryItem, Invoice all share one layer
│   ├── inventory_model.py
│   └── billing_model.py
├── services/
│   ├── order_service.py     ← directly imports and calls inventory + billing
│   ├── inventory_service.py
│   └── billing_service.py
└── repositories/
    ├── order_repo.py        ← all contexts share one persistence layer;
    ├── inventory_repo.py      a schema change anywhere breaks everything
    └── billing_repo.py
```
```python
# BAD — OrderService reaches directly into other bounded contexts
class BadOrderService:
    def place_order(self, product_id: str, quantity: int, customer_id: str):
        # Hard dependency: Orders is now coupled to Inventory at instantiation time
        inventory_service = BadInventoryService()
        if not inventory_service.has_stock(product_id, quantity):
            raise RuntimeError("Out of stock")
        inventory_service.deduct_stock(product_id, quantity)   # ← direct mutation

        # Hard dependency: Orders is now coupled to Billing
        billing_service = BadBillingService()
        unit_price = inventory_service.get_price(product_id)   # ← pricing leaked into Inventory
        billing_service.charge_customer(customer_id, unit_price * quantity)
```
**Why it fails:**
- Adding a new payment method requires modifying `OrderService`.
- Splitting into separate deployable services requires cutting across every layer.
- Integration tests must spin up all three services for any single scenario.
- "Price" lives in Inventory but semantically belongs in a Pricing/Billing context.
- Any schema change in one domain can silently break all dependents.

### ❌ Anti-Pattern 2: Shared concrete event types creating compile-time coupling
```python
# BAD — consuming contexts import Orders' concrete Python types directly
# This means Inventory and Billing have a compile-time dependency on the
# Orders module. Splitting into separate deployable services would require
# a shared Python package, reintroducing the coupling being avoided.
from orders.events import OrderPlaced, OrderFulfilled, OrderCancelled  # ← hard import

class InventoryService:
    def __init__(self, bus: EventBus) -> None:
        bus.subscribe(OrderPlaced, self._on_order_placed)   # ← coupled to Orders type
```
**Why it fails:** In a true bounded context architecture, events are serialized contracts (JSON schema, Protobuf, Avro). Each consuming context deserializes into its own internal representation via an anti-corruption layer. Sharing Python types re-couples deployment units.

### ❌ Anti-Pattern 3: Pricing responsibility with no owning context
```python
# BAD — unit_price is caller-supplied with no validation or authoritative source
def place_order(self, customer_id: str, sku: str, quantity: int, unit_price: float):
    # Who owns price determination? It is undefined territory between contexts.
    # Any caller can pass any price with no enforcement.
    ...
```
**Why it fails:** Pricing authority is ambiguous. A dedicated Pricing context (or Catalog context) should own price determination. Orders should receive a `PriceQuoteProvided` event or query a Pricing service before capturing the immutable price at order time.

### ❌ Anti-Pattern 4: Module-level service singletons leaking shared state
```python
# BAD — a module-level singleton means all tests and instantiations share
# subscription state, making isolated unit testing impossible
event_bus = EventBus()   # ← global mutable state at module level

# Any test that imports this module inadvertently inherits all subscriptions
# registered by previous tests.
```

---

## Positive Patterns — The Fix

### ✅ Pattern 1: Directory structure mirrors business domains
```
# GOOD — each bounded context is a self-contained vertical slice
good_domain_app/
├── orders/
│   ├── models.py        ← Order, LineItem, OrderStatus (Orders language only)
│   ├── events.py        ← OrderPlaced, OrderFulfilled, OrderCancelled
│   └── service.py       ← OrderService (publishes events, owns order lifecycle)
├── inventory/
│   ├── models.py        ← StockItem, StockReservation (Inventory language only)
│   └── service.py       ← InventoryService (subscribes to events, owns stock)
├── billing/
│   ├── models.py        ← Invoice, PaymentRecord (Billing language only)
│   └── service.py       ← BillingService (subscribes to events, owns invoices)
└── infrastructure/
    └── event_bus.py     ← EventBus (shared infrastructure, NOT shared domain)
```

### ✅ Pattern 2: Event-driven cross-context communication with no direct coupling
```python
@dataclass
class DomainEvent:
    """Base contract for all cross-context domain events."""
    event_id:    str      = field(default_factory=lambda: str(uuid.uuid4()))
    occurred_at: datetime = field(default_factory=datetime.utcnow)

# Events are the ONLY shared contract between contexts.
# Each consuming context maps the event to its own internal model.
@dataclass
class OrderPlaced(DomainEvent):
    order_id:    str   = ""
    customer_id: str   = ""
    sku:         str   = ""
    quantity:    int   = 0
    unit_price:  float = 0.0   # price captured immutably at order time

class EventBus:
    """
    Decoupled publish/subscribe bus.
    Producers know nothing about consumers.
    The only shared contract is the event schema.
    In production: replace with Kafka, RabbitMQ, or SNS/SQS.
    """
    def __init__(self) -> None:
        self._subscriptions: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: type[DomainEvent], handler: EventHandler) -> None:
        self._subscriptions[event_type.__name__].append(handler)

    def publish(self, event: DomainEvent) -> None:
        for handler in self._subscriptions.get(type(event).__name__, []):
            handler(event)
```

### ✅ Pattern 3: Each context owns its own models and ubiquitous language
```python
# ORDERS CONTEXT — owns order lifecycle; knows nothing about stock or money
class OrderService:
    """Publishes domain events. Never calls Inventory or Billing directly."""
    def __init__(self, bus: EventBus) -> None:
        self._bus    = bus
        self._orders: dict[str, Order] = {}

    def place_order(self, customer_id: str, sku: str, quantity: int, unit_price: float) -> Order:
        order = Order(
            order_id    = str(uuid.uuid4()),
            customer_id = customer_id,
            line_item   = LineItem(sku=sku, quantity=quantity, unit_price=unit_price),
        )
        order.confirm()
        self._orders[order.order_id] = order
        # Publish event — zero knowledge of who reacts or how
        self._bus.publish(OrderPlaced(
            order_id=order.order_id, customer_id=customer_id,
            sku=sku, quantity=quantity, unit_price=unit_price,
        ))
        return order


# INVENTORY CONTEXT — owns stock; language is StockItem, not Order or Invoice
class InventoryService:
    """Reacts to OrderPlaced. Knows nothing about money or order lifecycle."""
    def __init__(self, bus: EventBus) -> None:
        self._stock: dict[str, StockItem] = {}
        bus.subscribe(OrderPlaced, self._on_order_placed)   # only coupling point to Orders

    def _on_order_placed(self, event: OrderPlaced) -> None:
        item = self._stock.get(event.sku)
        if item:
            item.reserve(event.quantity)   # maps event fields to own domain model


# BILLING CONTEXT — owns invoices; language is Invoice, not StockItem or Order
class BillingService:
    """Creates and settles invoices. No direct dependency on Orders or Inventory."""
    def __init__(self, bus: EventBus) -> None:
        self._invoices: dict[str, Invoice] = {}
        bus.subscribe(OrderPlaced,    self._on_order_placed)
        bus.subscribe(OrderFulfilled, self._on_order_fulfilled)
        bus.subscribe(OrderCancelled, self._on_order_cancelled)

    def _on_order_placed(self, event: OrderPlaced) -> None:
        amount_due = event.unit_price * event.quantity   # price was captured at order time
        invoice = Invoice(
            invoice_id=str(uuid.uuid4()), order_id=event.order_id,
            customer_id=event.customer_id, amount_due=amount_due,
        )
        self._invoices[event.order_id] = invoice

    def _on_order_fulfilled(self, event: OrderFulfilled) -> None:
        invoice = self._invoices.get(event.order_id)
        if invoice:
            invoice.mark_paid()

    def _on_order_cancelled(self, event: OrderCancelled) -> None:
        invoice = self._invoices.get(event.order_id)
        if invoice and not invoice.paid:
            voided = self._invoices.pop(event.order_id)
            print(f"  [Billing] Invoice voided for cancelled order {event.order_id[:8]}…")
```

### ✅ Pattern 4: Bus injected via constructor — no module-level singletons
```python
# GOOD — each service receives its bus dependency via constructor injection.
# Tests can provide an isolated EventBus() instance with no shared state.
def build_system() -> tuple[OrderService, InventoryService, BillingService]:
    bus = EventBus()   # scoped here, not at module level
    inventory = InventoryService(bus)
    billing   = BillingService(bus)
    orders    = OrderService(bus)
    return orders, inventory, billing

# Each test creates its own bus — subscription state never leaks between tests.
def test_order_placement():
    orders, inventory, billing = build_system()
    ...
```

### ✅ Pattern 5: Anti-corruption layer for serialized cross-service events (production)
```python
# GOOD — in a polyglot or multi-deployment environment, events are serialized
# contracts. Each context maps the wire format to its own internal model,
# eliminating compile-time dependencies on other contexts' Python types.
class InventoryEventConsumer:
    """Deserializes raw event payloads into Inventory's own internal types."""
    def handle_raw_event(self, event_type: str, payload: dict) -> None:
        if event_type == "OrderPlaced":
            sku      = payload["sku"]        # maps wire field to Inventory language
            quantity = payload["quantity"]
            self._inventory_service.reserve_stock(sku, quantity)
            # No import of orders.events.OrderPlaced required
```

---

## Decision Table

| Situation | Required Action |
|---|---|
| Two contexts need the same data | Each owns its own copy; synchronize via domain events |
| Context A needs to trigger logic in Context B | A publishes an event; B subscribes — no direct call |
| Shared infrastructure (bus, DB connection) | Lives in `infrastructure/`; injected, never imported as domain logic |
| Pricing / authoritative data has no clear owner | Define a dedicated context (Pricing, Catalog) as the single authority |
| Splitting a monolith into deployable services | Each bounded context directory becomes a deployable unit with minimal changes |
| Testing a single context in isolation | Inject a fresh `EventBus()`; no neighboring context code required |
| Cross-language or multi-service deployment | Replace Python event types with serialized contracts (JSON schema, Protobuf); use an anti-corruption layer per consumer |

## Key Principle Summary

> **Business domains change together; technical layers change together for the wrong reasons.** Organize by domain so that adding a new payment method touches only Billing, a new warehouse touches only Inventory, and a new order type touches only Orders. The event bus is the seam — each context is a black box that reacts to facts about the world, never to the internal implementation details of its neighbors.