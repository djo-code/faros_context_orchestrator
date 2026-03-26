---
rule_id: dry-single-source-of-truth-pricing
principle: Don't Repeat Yourself (DRY)
alias: Single Source of Truth (SSOT)
category: architecture, maintainability, code-quality
severity: high
tags: [DRY, SSOT, duplication, synchronization-bugs, delegation, policy-object, pricing, derived-artifacts]
language: python
---

# Rule: Don't Repeat Yourself (DRY) — Single Source of Truth for Business Rules

## Core Constraint

Every business rule, threshold, rate, formula, and predicate **must be declared exactly once** in a single authoritative location. All collaborating classes must **read from or delegate to** that authority — they must never re-declare, re-implement, or re-derive the same logic independently. This applies at two scales: (1) **macro** — the same rule written across multiple classes; (2) **micro** — the same formula or expression duplicated within a single class or function.

---

## Negative Patterns — What to Avoid

### ❌ Anti-Pattern 1: Business rule constants scattered across multiple classes
```python
# VIOLATION: tax rate 0.08, bulk threshold 10, loyalty rate 0.05, and
# currency symbol are each written in multiple independent locations.
class BadPriceCalculator:
    def calculate_total(self, subtotal: float, quantity: int) -> float:
        tax = subtotal * 0.08          # ← rule copy #1
        if quantity >= 10:             # ← rule copy #1
            subtotal *= 0.90
        return round(subtotal + tax, 2)

class BadInvoiceFormatter:
    def format_tax_note(self, subtotal: float) -> str:
        tax = subtotal * 0.08          # ← rule copy #2 — already drifting
        return f"Tax (8%): USD {tax:.2f}"

class BadOrderValidator:
    def is_bulk_order(self, quantity: int) -> bool:
        return quantity >= 10          # ← rule copy #2

class BadReportGenerator:
    def summarise(self, subtotal, quantity, is_member):
        tax = subtotal * 0.08          # ← rule copy #3
        if quantity >= 10:             # ← rule copy #3
            ...

# Changing the tax rate from 8% to 10% requires edits in at least four
# separate places. Miss one → silent synchronization bug.
```

### ❌ Anti-Pattern 2: Formula duplicated across two collaborating classes
```python
# VIOLATION: the tax formula is defined in PriceCalculator AND re-implemented
# independently in InvoiceFormatter. If tax becomes tiered or gains exemptions,
# both sites must be updated — and the formatter will silently diverge.
class PriceCalculator:
    def calculate_tax(self, subtotal: float) -> float:
        return subtotal * self._policy.tax_rate          # formula lives here

class InvoiceFormatter:
    def format_tax_note(self, subtotal: float) -> str:
        tax = subtotal * self._policy.tax_rate           # formula duplicated here
        return f"Tax ({self._policy.tax_rate_as_percentage}): ..."
```

### ❌ Anti-Pattern 3: Eligibility predicate duplicated across two classes
```python
# VIOLATION: the bulk-discount eligibility condition exists independently in
# both PriceCalculator and OrderValidator. A rule change (e.g., must also have
# unit_price > 50) requires updating both sites.
class PriceCalculator:
    def apply_bulk_discount_if_eligible(self, subtotal, quantity):
        if quantity >= self._policy.bulk_order_minimum_quantity:   # predicate #1
            return subtotal * (1 - self._policy.bulk_discount_rate)
        return subtotal

class OrderValidator:
    def qualifies_for_bulk_discount(self, quantity: int) -> bool:
        return quantity >= self._policy.bulk_order_minimum_quantity  # predicate #2
```

### ❌ Anti-Pattern 4: Repeated literal expressions within a single function
```python
# VIOLATION: the separator string is reconstructed three times.
# A width change requires three edits.
def generate_order_report(self, ...) -> str:
    return (
        f"{'─' * 50}\n"    # ← copy #1
        f"  Product : {product_name}\n"
        f"{'─' * 50}\n"    # ← copy #2
        f"  ORDER TOTAL: ...\n"
        f"{'─' * 50}"      # ← copy #3
    )
```

### ❌ Anti-Pattern 5: Tax note computed on the wrong base (correctness consequence of DRY violation)
```python
# VIOLATION: subtotal (pre-discount) is passed to format_tax_note, but
# calculate_order_total applies tax to after_loyalty (post-discount total).
# The invoice therefore displays a tax figure that does not match the actual
# tax collected — a correctness bug caused by the formula duplication above.
tax_note = self._formatter.format_tax_note(subtotal)    # wrong base!
order_total = self._calculator.calculate_order_total(
    subtotal, quantity, customer_is_loyalty_member       # tax applied to after_loyalty internally
)
```

---

## Positive Patterns — The Fix

### ✅ Pattern 1: Single authoritative policy object owns all business rules
```python
@dataclass(frozen=True)
class PricingPolicy:
    """
    THE single source of truth for every pricing rule in the system.
    To change a rule, edit exactly this dataclass — and only this dataclass.
    """
    tax_rate:                     float = 0.08   # 8%
    bulk_discount_rate:           float = 0.10   # 10% off
    bulk_order_minimum_quantity:  int   = 10     # units
    loyalty_member_discount_rate: float = 0.05   # 5% off
    currency_symbol:              str   = "USD"
    decimal_places:               int   = 2

    @property
    def tax_rate_as_percentage(self) -> str:
        return f"{self.tax_rate * 100:.0f}%"

    def format_amount(self, amount: float) -> str:
        """Canonical money formatting — declared once, used everywhere."""
        return f"{self.currency_symbol} {amount:.{self.decimal_places}f}"
```

### ✅ Pattern 2: Formatter delegates formula to calculator — no re-implementation
```python
class PriceCalculator:
    def __init__(self, policy: PricingPolicy) -> None:
        self._policy = policy

    def calculate_tax(self, subtotal: float) -> float:
        """Single definition of the tax formula."""
        return subtotal * self._policy.tax_rate

    def calculate_order_total(
        self, subtotal: float, quantity: int, customer_is_loyalty_member: bool
    ) -> float:
        after_bulk    = self.apply_bulk_discount_if_eligible(subtotal, quantity)
        after_loyalty = self.apply_loyalty_discount_if_eligible(
            after_bulk, customer_is_loyalty_member
        )
        after_tax = after_loyalty + self.calculate_tax(after_loyalty)
        return round(after_tax, self._policy.decimal_places)


class InvoiceFormatter:
    def __init__(self, policy: PricingPolicy) -> None:
        self._policy = policy

    def format_tax_note(self, taxable_base: float, calculator: PriceCalculator) -> str:
        """Delegates to calculator — formula defined in exactly one place."""
        tax = calculator.calculate_tax(taxable_base)         # ← delegation, not duplication
        return (
            f"Tax ({self._policy.tax_rate_as_percentage}): "
            f"{self._policy.format_amount(tax)}"
        )
```

### ✅ Pattern 3: Calculator delegates eligibility predicate to validator
```python
class OrderValidator:
    def __init__(self, policy: PricingPolicy) -> None:
        self._policy = policy

    def qualifies_for_bulk_discount(self, quantity: int) -> bool:
        """Single authority for bulk-discount eligibility."""
        return quantity >= self._policy.bulk_order_minimum_quantity


class PriceCalculator:
    def __init__(self, policy: PricingPolicy, validator: OrderValidator) -> None:
        self._policy    = policy
        self._validator = validator

    def apply_bulk_discount_if_eligible(self, subtotal: float, quantity: int) -> float:
        """Delegates eligibility check — predicate defined in exactly one place."""
        if self._validator.qualifies_for_bulk_discount(quantity):   # ← delegation
            return subtotal * (1 - self._policy.bulk_discount_rate)
        return subtotal
```

### ✅ Pattern 4: Hoisted constant eliminates repeated literal expressions
```python
REPORT_SEPARATOR = "─" * 50   # width defined once; change here propagates everywhere

def generate_order_report(self, ...) -> str:
    # Correct taxable base: pass after_loyalty (what was actually taxed)
    after_bulk    = self._calculator.apply_bulk_discount_if_eligible(subtotal, quantity)
    after_loyalty = self._calculator.apply_loyalty_discount_if_eligible(
        after_bulk, customer_is_loyalty_member
    )
    tax_note = self._formatter.format_tax_note(after_loyalty, self._calculator)

    return (
        f"{REPORT_SEPARATOR}\n"              # ← single reference
        f"  Product : {product_name}\n"
        f"  Subtotal: {self._policy.format_amount(subtotal)}\n"
        f"  {tax_note}\n"
        f"{REPORT_SEPARATOR}\n"              # ← single reference
        f"  ORDER TOTAL: {self._policy.format_amount(order_total)}\n"
        f"{REPORT_SEPARATOR}"               # ← single reference
    )
```

### ✅ Pattern 5: Factory wires the entire pipeline from a single policy object
```python
def build_pricing_system(policy: PricingPolicy) -> ReportGenerator:
    """Compose the entire pricing pipeline from one policy outward."""
    validator  = OrderValidator(policy)
    calculator = PriceCalculator(policy, validator)   # validator injected → no predicate duplication
    formatter  = InvoiceFormatter(policy)
    return ReportGenerator(policy, calculator, formatter, validator)

# Changing tax rate to 10%, raising bulk threshold to 20, switching to EUR:
updated_policy = PricingPolicy(
    tax_rate=0.10,
    bulk_order_minimum_quantity=20,
    currency_symbol="EUR",
)
updated_system = build_pricing_system(updated_policy)
# Every calculator, formatter, validator, and report reflects the new rules
# automatically — zero risk of synchronization bugs.
```

---

## Decision Rules

| Situation | Required Action |
|---|---|
| Same constant (rate, threshold, symbol) referenced in 2+ classes | Move to a single policy/config object; all consumers read from it |
| Same formula implemented in 2+ classes | Designate one class as the authority; all others **delegate** to it |
| Same eligibility predicate in 2+ classes | Extract to a validator class; all callers invoke that single method |
| Same literal expression (e.g., separator string) repeated 2+ times | Hoist to a named constant before first use |
| Output/invoice figure does not match the internally computed value | Trace the data flow — a formula duplication is causing the mismatch |
| A new consumer needs an existing rule | It must **read from** the authority, never re-declare the rule |

---

## Key Insight

> DRY violations occur at two scales. **Macro**: the same *rule* (a rate, a threshold, a formula) declared independently across multiple classes — changing one copy silently leaves others stale. **Micro**: the same *expression* written twice within a single function or class. The fix is identical at both scales: **identify the single authoritative location, implement once, and have all other sites delegate or reference**. The policy-object + factory pattern enforces this structurally: no collaborator can even express a rule without going through the shared authority.