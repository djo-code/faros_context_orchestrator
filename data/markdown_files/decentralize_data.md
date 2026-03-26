---
rule_id: decentralize-data-database-per-service
principle: Decentralize Data
category: architecture, microservices, data-ownership
tags: [decentralization, database-per-service, SSOT, microservices, event-driven, data-ownership, autonomous-services, bounded-context, saga, outbox]
severity: high
language: python
pattern_context: microservice architecture, distributed systems, service-oriented design
---

# Rule: Decentralize Data — Database-per-Service Pattern

## Core Constraint

Every autonomous service must **own its data exclusively**. No service may read from, write to, or mutate another service's data store directly. Cross-service communication happens **only** through typed public APIs, published domain events, or asynchronous messaging — never through shared table access or shared in-process object references. A single shared database is a single point of failure, a schema-coupling trap, and a deployment bottleneck.

---

## Negative Patterns — What to Avoid

### ❌ Anti-Pattern 1: Shared database with direct cross-service table access
```python
# VIOLATION: one database namespace shared by all services
class SharedDatabase:
    def __init__(self) -> None:
        self.customers: dict = {}   # owned by... everyone?
        self.inventory: dict = {}
        self.orders:    dict = {}

_shared_db = SharedDatabase()

class BadOrderService:
    def place_order(self, customer_id: str, product_id: str, quantity: int) -> str:
        # ❌ Reads another service's table directly — hard schema coupling
        customer = _shared_db.execute_raw_query("customers", customer_id)

        # ❌ Mutates another service's data from inside OrderService
        inventory = _shared_db.execute_raw_query("inventory", product_id)
        inventory["stock"] -= quantity
        _shared_db.inventory[product_id] = inventory   # ← OrderService writing inventory!

        order_id = str(uuid.uuid4())
        _shared_db.orders[order_id] = { ... }
        return order_id

# Consequences:
#   • Schema change in "inventory" silently breaks OrderService.
#   • Services cannot be deployed, scaled, or replaced independently.
#   • The shared DB is a single point of failure for all services.
#   • Stock mutation logic is now duplicated across any service that needs it.
```

### ❌ Anti-Pattern 2: Implicit dependency on a module-level shared singleton
```python
# VIOLATION: EventBus created at module scope and consumed via implicit global
event_bus = EventBus()   # ← centralized shared state

class CustomerService:
    def __init__(self) -> None:
        self._customer_store: dict = {}
        event_bus.subscribe(...)   # ← silently depends on a global — not injected
```
**Why it fails:** Services should receive all collaborators through constructor injection. An implicit module-level singleton is a hidden coupling that contradicts the decentralization principle and makes the service untestable in isolation.

### ❌ Anti-Pattern 3: Leaking unnecessary data across service boundaries
```python
# VIOLATION: CustomerLookupResult exposes fields the consumer never uses
@dataclass
class CustomerLookupResult:
    found:         bool
    customer_name: str   = ""
    credit_limit:  float = 0.0   # ← OrderService never reads this; widens coupling surface
```
**Why it fails:** Every field in a cross-service DTO is a coupling point. Unused fields widen the contract unnecessarily and make future changes more expensive.

### ❌ Anti-Pattern 4: No compensation strategy for partial cross-service failures
```python
# VIOLATION: stock reserved but order write or event publish may fail —
# no saga, outbox, or idempotency key protects consistency
reservation = inventory_service.attempt_stock_reservation(request)  # succeeds
# → crash here leaves stock decremented but no order record
self._order_store[order_id] = OrderRecord(...)   # may never execute
event_bus.publish(Event(...))                    # may never execute
```
**Why it fails:** Decentralized data ownership requires an explicit cross-service consistency strategy. Without a Saga, outbox pattern, or at-least-once delivery guarantee, partial failures produce permanently inconsistent state.

---

## Positive Patterns — The Fix

### ✅ Pattern 1: Each service holds a strictly private data store
```python
class CustomerService:
    """Sole owner of customer data. No other service may access _customer_store."""

    def __init__(self, event_bus: EventBus) -> None:       # ← injected, not global
        self._customer_store: dict[str, CustomerRecord] = {}
        self._event_bus = event_bus
        self._event_bus.subscribe(EventType.ORDER_PLACED, self._on_order_placed)

    def look_up_customer(self, customer_id: str) -> CustomerLookupResult:
        """Public API — the ONLY way other services read customer data."""
        record = self._customer_store.get(customer_id)
        if not record:
            return CustomerLookupResult(found=False)
        return CustomerLookupResult(
            found=True,
            customer_name=record.customer_name,
            # credit_limit intentionally omitted — OrderService does not need it
        )

    def _on_order_placed(self, event: Event) -> None:
        """React to domain events without being called directly by OrderService."""
        customer_id = event.payload.get("customer_id")
        record = self._customer_store.get(customer_id)
        if record:
            record.loyalty_points += 10


class InventoryService:
    """Sole owner of product and stock data."""

    def __init__(self) -> None:
        self._inventory_store: dict[str, ProductRecord] = {}

    def attempt_stock_reservation(
        self, request: StockReservationRequest
    ) -> StockReservationResult:
        """Only InventoryService ever mutates stock_count."""
        record = self._inventory_store.get(request.product_id)
        if not record:
            return StockReservationResult(success=False, order_id=request.order_id,
                                          reason="Product not found")
        if record.stock_count < request.quantity:
            return StockReservationResult(success=False, order_id=request.order_id,
                                          reason=f"Only {record.stock_count} units in stock")
        record.stock_count -= request.quantity   # ← mutation stays inside the owner
        return StockReservationResult(success=True, order_id=request.order_id)
```

### ✅ Pattern 2: OrderService communicates only through typed APIs and events
```python
class OrderService:
    """Sole owner of order data. Communicates through public APIs and events only."""

    def __init__(
        self,
        customer_service:  CustomerService,
        inventory_service: InventoryService,
        event_bus:         EventBus,           # ← all collaborators injected
    ) -> None:
        self._order_store:        dict[str, OrderRecord] = {}
        self._customer_service  = customer_service
        self._inventory_service = inventory_service
        self._event_bus         = event_bus

    def place_order(self, customer_id: str, product_id: str, quantity: int) -> str:
        # ✅ Read customer existence via public API — no DB access
        customer = self._customer_service.look_up_customer(customer_id)
        if not customer.found:
            raise ValueError(f"Customer '{customer_id}' does not exist")

        order_id    = str(uuid.uuid4())
        reservation = self._inventory_service.attempt_stock_reservation(
            StockReservationRequest(product_id=product_id,
                                    quantity=quantity,
                                    order_id=order_id)
        )
        order_status = "CONFIRMED" if reservation.success else "FAILED"

        # ✅ Write only to OrderService's own store
        self._order_store[order_id] = OrderRecord(
            order_id=order_id, customer_id=customer_id,
            product_id=product_id, quantity=quantity, status=order_status,
        )

        if reservation.success:
            # ✅ Publish event so subscribers react without direct coupling
            # NOTE: in production, use the Outbox Pattern to guarantee atomicity
            # between the _order_store write and event publication.
            self._event_bus.publish(Event(
                event_type=EventType.ORDER_PLACED,
                payload={"order_id": order_id, "customer_id": customer_id,
                         "product_id": product_id, "quantity": quantity},
            ))
        return order_id
```

### ✅ Pattern 3: Explicit EventBus injection + narrow DTOs
```python
# EventBus passed as a constructor argument — no hidden global dependency
event_bus         = EventBus()
customer_service  = CustomerService(event_bus=event_bus)
inventory_service = InventoryService()
order_service     = OrderService(customer_service, inventory_service, event_bus)

# Narrow DTO — expose only what the consumer needs
@dataclass
class CustomerLookupResult:
    found:         bool
    customer_name: str = ""
    # credit_limit removed — not consumed by any current subscriber

# Isolation verified programmatically
assert not hasattr(order_service, "_customer_store"),  "OrderService must not own customer data"
assert not hasattr(order_service, "_inventory_store"), "OrderService must not own inventory data"
assert not hasattr(customer_service, "_order_store"),  "CustomerService must not own order data"
```

### ✅ Pattern 4: Cross-service consistency annotation (Saga / Outbox)
```python
def place_order(self, customer_id: str, product_id: str, quantity: int) -> str:
    """
    Cross-service consistency note:
    The sequence — reserve stock → write order → publish event — is NOT atomic.
    In production, use one of:
      • Outbox Pattern: write order record + outbox event in one local transaction;
        a relay process publishes reliably.
      • Saga (choreography): each step publishes compensating events on failure
        (e.g., STOCK_RELEASE_REQUESTED if order write fails).
      • Idempotency keys: allow safe retry of the full sequence.
    This demo omits these mechanisms for brevity; do not omit them in production.
    """
    ...
    # Guard against negative totals or over-deduction at each boundary
    actual_deduction = max(0, min(reservation.quantity, record.stock_count))
```

---

## Decision Rules

| Situation | Required Action |
|---|---|
| Service A needs data owned by Service B | Call Service B's typed public API; never access its store |
| Service A must react to Service B's actions | Subscribe to a domain event; never have B call A directly |
| Adding a new service that needs customer/inventory data | Inject the owning service as a constructor dependency; publish/subscribe to events |
| Shared infrastructure (event bus, message broker) | Inject as a constructor argument — never consume as a module-level global |
| Cross-service write sequence (reserve → order → notify) | Document and implement Outbox or Saga pattern; never leave partial failure unaddressed |
| DTO fields exposed across a service boundary | Include only fields the consumer demonstrably uses; remove all others |
| Python `_private` convention for data store enforcement | Acknowledge the limitation; note that real enforcement comes from network boundaries in production |

---

## Key Principle Summary

> **A service that can reach into another service's database is not autonomous — it is a module with a misleading name.** True decentralization means each service's data store is invisible to all other services. The only permitted channels are typed API calls, domain events, and asynchronous messages. When a shared database disappears, services survive independently; when a shared database fails, every service that touches it fails with it.