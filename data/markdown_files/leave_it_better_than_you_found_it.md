---
rule_id: boy-scout-rule-leave-it-better
principle: Leave It Better Than You Found It
alias: Boy Scout Rule, Continuous Refactoring
category: architecture, maintainability, code-quality
tags: [boy-scout-rule, refactoring, dead-code, incremental-cleanup, technical-debt, imports, enums, mutation, api-design]
severity: high
language: python
---

# Rule: Leave It Better Than You Found It (Boy Scout Rule)

## Core Constraint

Every time you touch a file, **remove at least one small mess** — a magic number, a dead function, a forgotten debug print, a missing type hint, a mid-module import. Cleanup is not a dedicated sprint; it is a continuous byproduct of normal work. Critically, "leaving it better" means **replacing and deleting** old code, not appending improved versions alongside the originals. Accumulating versioned copies is the opposite of the rule.

---

## Negative Patterns — What to Avoid

### ❌ Anti-Pattern 1: Appending new versions instead of replacing old ones
```python
# VIOLATION: all six versions coexist — the module is dirtier after each "cleanup"
def process_order_v1(order): ...   # dead
def process_order_v2(order): ...   # dead
def process_order_v3(order): ...   # dead
def process_order_v4(order): ...   # dead
def process_order_v5(order: Order) -> Optional[Order]: ...  # dead
def process_order(order: Order) -> Optional[Order]: ...     # ← only this should exist

# The Boy Scout Rule means DELETE each predecessor.
# Version history belongs in git, not in the source file.
```

### ❌ Anti-Pattern 2: Duplicate helpers from successive refactors left unrectired
```python
# VIOLATION: dict-based helpers from commit 03 were never removed after commit 05
# introduced typed equivalents — both sets live in the module simultaneously

def is_pending(order: dict) -> bool:          # ← stale, dict-based, unused
    return order['status'] == STATUS_PENDING

def is_cancelled(order: dict) -> bool:        # ← stale, dict-based, unused
    return order['status'] == STATUS_CANCELLED

def is_pending_order(order: Order) -> bool:   # ← current
    return order.status == STATUS_PENDING

def is_cancelled_order(order: Order) -> bool: # ← current
    return order.status == STATUS_CANCELLED
```

### ❌ Anti-Pattern 3: Mid-module imports left uncorrected by cleanup passes
```python
def process_order_v4(order): ...
def calculate_final_total(order_total: float) -> float: ...

# VIOLATION: imports buried after function definitions — PEP 8 requires all
# imports at the top of the module. Each cleanup pass should have corrected this.
from dataclasses import dataclass, field
from typing import Optional
```

### ❌ Anti-Pattern 4: Broken smoke test with an undefined name, guarded by `if False`
```python
# VIOLATION: pytest_approx is never imported; `if False` silently swallows the
# NameError at runtime — a reader must mentally evaluate the ternary to confirm safety
assert processed.final_amount_due == pytest_approx \
    if False else abs(processed.final_amount_due - 583.20) < 0.01

# The "clean" version of the file should have replaced this with:
assert abs(processed.final_amount_due - 583.20) < 0.01
```

### ❌ Anti-Pattern 5: Mutate-and-return API ambiguity
```python
# VIOLATION: the function mutates `order` in place AND returns it, creating
# ambiguous ownership — callers cannot tell whether to use the original
# reference or the return value; the docstring cannot fully resolve this.
def process_order(order: Order) -> Optional[Order]:
    order.discount_applied = calculate_discount(order.order_total)
    order.final_amount_due = calculate_final_total(order.order_total)
    order.status           = STATUS_PROCESSED
    return order   # ← same object; caller already has it; return is misleading
```

### ❌ Anti-Pattern 6: Integer status codes instead of an Enum
```python
# VIOLATION: bare integers cannot be validated by the type system;
# any int is a valid status, making invalid-state bugs invisible
STATUS_PENDING   = 1
STATUS_PROCESSED = 2
STATUS_CANCELLED = 3

order.status = 99   # silently accepted; no error until logic fails downstream
```

---

## Positive Patterns — The Fix

### ✅ Pattern 1: All imports at the top; one canonical function replaces all predecessors
```python
# CORRECT module structure after all cleanup passes
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Optional


# ── Constants ─────────────────────────────────────────────────────────────────

BULK_ORDER_THRESHOLD = 500.00   # dollars — orders above this qualify for bulk discount
BULK_DISCOUNT_RATE   = 0.10     # 10%
SALES_TAX_RATE       = 0.08     # 8% — US state default; override per region
```

### ✅ Pattern 2: Enum eliminates invalid-state bugs entirely
```python
class OrderStatus(enum.IntEnum):
    PENDING    = 1
    PROCESSED  = 2
    CANCELLED  = 3

# Now invalid assignments are caught by linters and type checkers:
# order.status = 99   ← TypeError / type-checker error
```

### ✅ Pattern 3: Typed dataclass with unambiguous fields
```python
@dataclass
class Order:
    order_id:         str
    customer_name:    str
    order_total:      float
    status:           OrderStatus = OrderStatus.PENDING
    discount_applied: float       = field(default=0.0, init=False)
    final_amount_due: float       = field(default=0.0, init=False)
```

### ✅ Pattern 4: Small, focused helpers — no duplicates, typed throughout
```python
def is_eligible_for_bulk_discount(order_total: float) -> bool:
    return order_total > BULK_ORDER_THRESHOLD

def calculate_discount(order_total: float) -> float:
    if is_eligible_for_bulk_discount(order_total):
        return order_total * BULK_DISCOUNT_RATE
    return 0.0

def apply_sales_tax(pre_tax_amount: float) -> float:
    return pre_tax_amount * (1 + SALES_TAX_RATE)

def calculate_final_total(order_total: float) -> float:
    discount      = calculate_discount(order_total)
    pre_tax_total = order_total - discount
    return apply_sales_tax(pre_tax_total)
```

### ✅ Pattern 5: Clean API — mutate without returning, or return new instance; never both
```python
def process_order(order: Order) -> None:
    """
    Transition a pending order to processed, applying bulk discount and
    sales tax in place. Raises ValueError for non-pending orders.

    Mutates `order` directly; no return value avoids ownership ambiguity.
    """
    if order.status == OrderStatus.CANCELLED:
        raise ValueError(f"Order {order.order_id!r} is cancelled and cannot be processed.")
    if order.status != OrderStatus.PENDING:
        raise ValueError(
            f"Order {order.order_id!r} has status {order.status!r}; expected PENDING."
        )
    order.discount_applied = calculate_discount(order.order_total)
    order.final_amount_due = calculate_final_total(order.order_total)
    order.status           = OrderStatus.PROCESSED
```

### ✅ Pattern 6: Honest, self-contained smoke test with no undefined names
```python
if __name__ == "__main__":
    bulk_order = Order(order_id="ORD-001", customer_name="Bob Marley", order_total=600.00)
    process_order(bulk_order)

    assert bulk_order.status           == OrderStatus.PROCESSED
    assert bulk_order.discount_applied == 60.00                          # 10% of 600
    assert abs(bulk_order.final_amount_due - 583.20) < 0.01              # (600-60)*1.08

    small_order = Order(order_id="ORD-002", customer_name="Sam Smith", order_total=100.00)
    process_order(small_order)
    assert small_order.discount_applied == 0.0
    assert abs(small_order.final_amount_due - 108.00) < 0.01

    import pytest
    with pytest.raises(ValueError):
        cancelled = Order("ORD-003", "Jane Doe", 200.00, status=OrderStatus.CANCELLED)
        process_order(cancelled)

    print("All assertions passed — left it cleaner than we found it. ✓")
```

---

## Incremental Cleanup Commit Model

Each pass fixes **one class of mess**, triggered by normal work — not a cleanup sprint:

| Commit | Trigger | What was cleaned |
|---|---|---|
| `01` | Deadline delivery | Initial working implementation (baseline) |
| `02` | Adding payment method | Magic numbers → named constants |
| `03` | Writing cancellation unit test | Debug print removed; status helpers extracted |
| `04` | Testing discount logic in isolation | God-function decomposed into focused helpers |
| `05` | Adding to public API | Raw dict → typed `dataclass`; type hints added |
| `06` | Code review | Imports hoisted; predecessors **deleted**; Enum introduced; API ambiguity resolved |

---

## Decision Checklist

| Question | Required Answer |
|---|---|
| Are all previous versions of refactored functions deleted (not commented out)? | ✅ Yes — use git for history |
| Are all imports at the top of the module, even after incremental additions? | ✅ Yes |
| Are status/state codes represented as `enum.Enum` rather than bare integers? | ✅ Yes |
| Are duplicate helpers from successive refactors retired when superseded? | ✅ Yes |
| Does the API either mutate without returning, or return a new instance — not both? | ✅ Yes |
| Are all test assertions free of undefined names and hidden control flow? | ✅ Yes |
| Is every small mess encountered during feature work cleaned up before the PR? | ✅ Yes |

---

## Key Principle Summary

> **The Boy Scout Rule is a deletion discipline as much as an addition discipline.** Appending `_v2`, `_v3`, `_v4` functions alongside their predecessors is the most common way teams *believe* they are applying the rule while actually doing the opposite. Leave the file with fewer lines of code, fewer concepts, and fewer surprises than it had when you opened it. Version history belongs in git; the source file should only contain the current best understanding.