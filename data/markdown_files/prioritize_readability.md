---
rule_id: readability-humans-first-library
principle: Prioritize Readability
category: code-quality
tags: [naming, self-documenting, intention-revealing, constants, boolean-predicates, guard-clauses, properties, readability, maintainability]
severity: high
language: python
---

# Rule: Write Code for Humans First — Intention-Revealing Names (Library Domain)

## Core Constraint

Every identifier — variable, function, parameter, field, property — **must reveal its intent and its domain meaning without requiring a comment to decode it**. Names are the primary API of your code. When a name requires mental translation (e.g., `b`, `p`, `chk`, `od`, `f`), the name has failed. Optimize relentlessly for the human reader: name things for what they *are* and what they *mean* in the business domain, not for what they *do* mechanically.

---

## Negative Patterns — What to Avoid

### ❌ Abbreviated identifiers that require constant mental translation
```python
# VIOLATION: no identifier carries any domain meaning
def chk(b, p, d):
    od = d + timedelta(14)                     # is 14 days? hours? weeks?
    if date.today() > od:
        f = (date.today() - od).days * 0.25    # 0.25 what? per what?
        p["f"] = p.get("f", 0) + f             # "f" key = fine? flag? factor?
        b["a"] = True                           # "a" = available? approved? active?
        return True
    return False
```
**Why it fails:** `b`, `p`, `d`, `od`, `f` carry zero semantic content. `14` and `0.25` are unexplained magic numbers. A reader cannot determine business intent — is `d` a checkout date, a due date, or a duration? — without external documentation or debugging.

### ❌ Field name implies wrong type or domain concept
```python
# VIOLATION: name says "books" but the list holds ISBN strings, not Book objects
books_currently_borrowed: list[str] = field(default_factory=list)

# VIOLATION: "borrower_id" in LoanRecord is actually a library card number —
# a reader cannot tell if this is a database surrogate key, a UUID, or a card number
borrower_id: str   # populated from borrower.library_card_number
```
**Why it fails:** `books_currently_borrowed` implies the contents are `Book` objects or titles. A reader writing `borrower.books_currently_borrowed[0].title` will hit an `AttributeError`. The mismatch between the name's implication and the actual type is a silent trap.

### ❌ Business logic functions with embedded I/O side-effects
```python
# VIOLATION: print statements mixed into domain logic
def check_out_book(book, borrower, loan_records):
    if not book.is_available:
        print(f"Cannot check out '{book.title}': it is already on loan.")  # ← I/O
        return None
    # ... domain logic ...
    print(f"'{book.title}' checked out to {borrower.full_name}.")           # ← I/O
    return new_loan_record
```
**Why it fails:** A reader unit-testing `check_out_book` must mentally filter stdout from behaviour. The function now has two responsibilities — computing a result *and* presenting it — which makes each responsibility less readable on its own terms.

### ❌ Publicly mutable field that is semantically derived (implicit contract violation)
```python
# VIOLATION: due_date is derived in __post_init__, establishing it as computed,
# but the demo then mutates it directly — breaking the contract a reader infers
@dataclass
class LoanRecord:
    due_date: date = field(init=False)   # ← appears derived and stable

    def __post_init__(self):
        self.due_date = self.checkout_date + timedelta(days=LENDING_PERIOD_DAYS)

# Later:
first_loan.due_date = date.today() - timedelta(days=3)   # ← silent contract breach
```

### ❌ Missing validation guard that readable, defensive code would surface
```python
# VIOLATION: return_book accepts any loan_record without verifying it matches
# the book and borrower — silent failure risk invisible to a reader
def return_book(book: Book, borrower: Borrower, loan_record: LoanRecord) -> float:
    book.is_available = True                             # proceeds unconditionally
    borrower.books_currently_borrowed.remove(book.isbn)
```

---

## Positive Patterns — The Fix

### ✅ Named constants with unit annotations eliminate all magic numbers
```python
LENDING_PERIOD_DAYS         = 14
OVERDUE_FINE_PER_DAY        = 0.25   # dollars
MAXIMUM_BOOKS_PER_BORROWER  = 5
```
**Why it works:** Every literal that encodes a business rule is named and annotated. The name answers *what*, the unit comment answers *in what terms*.

### ✅ Field names match their actual contents and domain source
```python
@dataclass
class Borrower:
    full_name:             str
    library_card_number:   str
    outstanding_fine:      float = 0.00
    checked_out_isbns:     list[str] = field(default_factory=list)   # ← ISBNs, not Books

@dataclass
class LoanRecord:
    book_isbn:                  str
    borrower_library_card_number: str    # ← mirrors Borrower.library_card_number exactly
    checkout_date:              date
```
**Why it works:** `checked_out_isbns` tells a reader exactly what the list contains — strings that are ISBNs — before they inspect a single value. `borrower_library_card_number` in `LoanRecord` matches the source field name in `Borrower`, making the relationship self-evident.

### ✅ Boolean properties as English predicates enable guard clauses that read as sentences
```python
@dataclass
class Borrower:
    @property
    def has_reached_borrowing_limit(self) -> bool:
        return len(self.checked_out_isbns) >= MAXIMUM_BOOKS_PER_BORROWER

    @property
    def has_outstanding_fine(self) -> bool:
        return self.outstanding_fine > 0

# Guard clauses now read as plain business rules:
if borrower.has_outstanding_fine:
    return CheckoutResult(permitted=False, reason="outstanding fine must be paid first")
if borrower.has_reached_borrowing_limit:
    return CheckoutResult(permitted=False, reason=f"limit of {MAXIMUM_BOOKS_PER_BORROWER} books reached")
```
**Why it works:** `if borrower.has_outstanding_fine` is a complete English sentence. No mental translation is required.

### ✅ Stepwise named properties make derivation chains traceable
```python
@dataclass
class LoanRecord:
    book_isbn:                    str
    borrower_library_card_number: str
    checkout_date:                date
    _due_date:                    date = field(init=False, repr=False)  # private; derived

    def __post_init__(self) -> None:
        self._due_date = self.checkout_date + timedelta(days=LENDING_PERIOD_DAYS)

    @property
    def due_date(self) -> date:
        """Computed from checkout_date; not directly mutable."""
        return self._due_date

    @property
    def is_overdue(self) -> bool:
        return date.today() > self.due_date

    @property
    def days_overdue(self) -> int:
        if not self.is_overdue:
            return 0
        return (date.today() - self.due_date).days

    @property
    def calculated_overdue_fine(self) -> float:
        return self.days_overdue * OVERDUE_FINE_PER_DAY
```
**Why it works:** `is_overdue → days_overdue → calculated_overdue_fine` is a readable derivation ladder. Making `_due_date` private signals to readers that it should not be mutated directly, preserving the contract established by `__post_init__`.

### ✅ Domain logic returns structured results; I/O stays at the call site
```python
from dataclasses import dataclass as _dc

@_dc
class CheckoutResult:
    permitted:       bool
    loan_record:     Optional[LoanRecord] = None
    rejection_reason: str = ""

def check_out_book(
    book: Book,
    borrower: Borrower,
    loan_records: list[LoanRecord],
) -> CheckoutResult:
    """Return a CheckoutResult; caller decides how to present it."""
    if not book.is_available:
        return CheckoutResult(permitted=False, rejection_reason=f"'{book.title}' is already on loan")
    if borrower.has_reached_borrowing_limit:
        return CheckoutResult(permitted=False, rejection_reason=f"borrowing limit of {MAXIMUM_BOOKS_PER_BORROWER} reached")
    if borrower.has_outstanding_fine:
        return CheckoutResult(permitted=False, rejection_reason=f"outstanding fine of ${borrower.outstanding_fine:.2f} must be paid")

    book.is_available = False
    borrower.checked_out_isbns.append(book.isbn)
    new_loan = LoanRecord(
        book_isbn=book.isbn,
        borrower_library_card_number=borrower.library_card_number,
        checkout_date=date.today(),
    )
    loan_records.append(new_loan)
    return CheckoutResult(permitted=True, loan_record=new_loan)

# I/O lives only at the call site — domain logic is clean and testable
result = check_out_book(design_patterns_book, alice, loan_records)
if result.permitted:
    print(f"'{design_patterns_book.title}' checked out. Due: {result.loan_record.due_date}")
else:
    print(f"Checkout denied: {result.rejection_reason}")
```

### ✅ Defensive guard in return_book makes implicit contract explicit
```python
def return_book(
    book: Book,
    borrower: Borrower,
    loan_record: LoanRecord,
) -> float:
    """Accept a return. Returns fine charged. Raises ValueError on record mismatch."""
    if loan_record.book_isbn != book.isbn:
        raise ValueError(
            f"Loan record is for ISBN {loan_record.book_isbn!r}, "
            f"not '{book.title}' ({book.isbn!r})"
        )
    if loan_record.borrower_library_card_number != borrower.library_card_number:
        raise ValueError(
            f"Loan record belongs to card {loan_record.borrower_library_card_number!r}, "
            f"not {borrower.full_name!r}"
        )

    book.is_available = True
    borrower.checked_out_isbns.remove(book.isbn)

    fine_charged = loan_record.calculated_overdue_fine
    if fine_charged > 0:
        borrower.outstanding_fine += fine_charged
    return fine_charged
```
**Why it works:** A reader immediately understands that `return_book` validates its preconditions before mutating state. The guard clauses are readable English-language assertions about the domain invariant being enforced.

---

## Decision Checklist

| Question | Required Answer |
|---|---|
| Does every identifier reveal its business domain meaning? | ✅ Yes |
| Do list/collection names describe their *element type*, not a vague concept? | ✅ Yes (`checked_out_isbns`, not `books_currently_borrowed`) |
| Are all magic numbers replaced with named constants (with unit annotations)? | ✅ Yes |
| Do boolean properties read as complete English predicates? | ✅ Yes (`has_outstanding_fine`, `is_overdue`) |
| Are derived fields protected from direct external mutation? | ✅ Yes (private `_due_date` + read-only `property`) |
| Is domain logic free of `print` / I/O side-effects? | ✅ Yes (structured return value; I/O at call site) |
| Do functions validate their preconditions with readable guard clauses? | ✅ Yes |
| Do field names in derived records mirror their source field names? | ✅ Yes (`borrower_library_card_number` mirrors `Borrower.library_card_number`) |

---

## Key Principle Summary

> **A name is a contract.** `books_currently_borrowed: list[str]` breaks its contract the moment a reader writes `.title` on an element. `borrower_id` breaks its contract when a reader cannot tell a surrogate key from a card number. Name fields for what they *contain*, name functions for what they *decide or produce*, name booleans as *English predicates*, and name constants for the *business rule* they encode — then the code tells its own story without commentary.