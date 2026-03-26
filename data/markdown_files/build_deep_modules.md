---
rule_id: build-deep-modules
principle: Build Deep Modules
category: architecture, encapsulation, information-hiding
tags: [deep-modules, encapsulation, information-hiding, narrow-interface, complexity-absorption, private-methods, coupling, cohesion]
severity: high
language: python
---

# Rule: Build Deep Modules — Narrow Interface, Hidden Complexity

## Core Constraint

A well-designed module exposes the **smallest possible public interface** while absorbing the **maximum possible internal complexity**. Callers should never need to understand, orchestrate, or replicate internal pipeline steps. Every implementation detail — sorting, batching, formatting, validation, statistics — belongs behind the encapsulation boundary, invisible to the outside world.

> **Depth ratio**: measure a module's quality by `complexity absorbed ÷ interface surface exposed`. A three-method class that hides sorting, pagination, column alignment, statistics, and report assembly is deep. A class where callers must call `sort()` → `batch()` → `compute_widths()` → `render()` → `assemble()` in sequence is shallow.

---

## Negative Patterns — What to Avoid

### ❌ Anti-Pattern 1: Leaking internal pipeline steps to the caller
```python
# VIOLATION: caller must understand and manually orchestrate the entire pipeline
class LeakyReportBuilder:
    def __init__(self):
        self.raw_records      = []   # caller populates directly
        self.sorted_records   = []   # caller must call sort_records() first
        self.batches          = []   # caller must call batch_records() after
        self.column_widths    = {}   # caller must compute and pass widths
        self.rendered_batches = []   # caller must call render() per batch

    def sort_records(self): ...
    def batch_records(self, batch_size): ...
    def compute_column_widths(self): ...
    def render_batch(self, batch): ...
    def assemble_report(self): ...

# Caller is forced to know the correct sequence:
builder.raw_records = records
builder.sort_records()
builder.batch_records(batch_size=5)
builder.compute_column_widths()
builder.rendered_batches = [builder.render_batch(b) for b in builder.batches]
report = builder.assemble_report()
# Change any internal step → every caller breaks.
```
**Why it fails:** The interface surface equals the implementation surface. Callers are tightly coupled to every internal detail. This is a *shallow* module masquerading as a class.

### ❌ Anti-Pattern 2: Untyped shared dictionaries keyed by magic strings
```python
# VIOLATION: column widths passed as raw dict across four private methods
def _compute_column_widths(self, records) -> dict[str, int]:
    return {"region": ..., "salesperson": ..., "revenue": ..., "units": ...}

def _render_column_headers(self, column_widths: dict[str, int]) -> str:
    return f"{'Region'.ljust(column_widths['region'])}"   # KeyError on typo
                                                          # silently wrong key
```
**Why it fails:** A typo in any string key (`"revnue"`, `"unit"`) produces a silent `KeyError` at render time. The coupling between producer and all consumers is invisible to the type checker.

### ❌ Anti-Pattern 3: Column order duplicated across sibling methods
```python
# VIOLATION: both methods independently hard-code the same four-column sequence
def _render_column_headers(self, column_widths):
    return f"Region ... Salesperson ... Revenue ... Units"   # ← copy 1

def _render_data_row(self, record, column_widths):
    return f"{record.region} ... {record.salesperson} ... {record.revenue} ... {record.units_sold}"  # ← copy 2

# Adding or reordering a column requires synchronised edits in two places.
```

### ❌ Anti-Pattern 4: Non-idempotent `render()` due to embedded `datetime.now()`
```python
# VIOLATION: two calls on the same unchanged object produce different strings
def render(self) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")   # changes every call
    ...
```
**Why it fails:** Callers expecting a stable report string (caching, comparison, testing) get unpredictable results. A deep module should behave predictably.

### ❌ Anti-Pattern 5: Private methods with invisible preconditions
```python
# VIOLATION: assumes non-empty list but documents nothing
def _build_summary_section(self, sorted_records: list[SalesRecord]) -> str:
    top_performer = sorted_records[0]   # IndexError if called on empty list
    # Only safe because render() guards upstream — but that's invisible here.
```

---

## Positive Patterns — The Fix

### ✅ Pattern 1: Three-method public interface absorbs the full pipeline
```python
class SalesReport:
    """
    Public interface (3 methods only):
        add_record(record)  — feed data in
        set_title(title)    — optional configuration
        render()            — get the finished report

    Sorting, batching, column alignment, statistics, and assembly are
    completely hidden. Callers never touch any of it.
    """

    _DEFAULT_TITLE    = "Sales Performance Report"
    _COLUMN_SEPARATOR = "  │  "

    def __init__(self, page_size: int = 5) -> None:
        self._records:   list[SalesRecord] = []
        self._title:     str               = self._DEFAULT_TITLE
        self._page_size: int               = page_size
        # Capture generation timestamp once — render() is idempotent
        self._generated_at: str            = datetime.now().strftime("%Y-%m-%d %H:%M")

    def add_record(self, record: SalesRecord) -> None:
        """Accept a single sales record; validate and defensively copy it."""
        self._validate_record(record)
        import dataclasses
        self._records.append(dataclasses.replace(record))   # close mutation boundary

    def set_title(self, title: str) -> None:
        if not title.strip():
            raise ValueError("Report title must not be blank.")
        self._title = title.strip()

    def render(self) -> str:
        """
        Return the complete formatted report. All steps — sort, batch,
        align, summarise, assemble — are automatic and invisible.
        """
        if not self._records:
            return f"{self._title}\n{'═' * 60}\n(no records)\n"

        sorted_records = self._sort_by_revenue_descending()
        batches        = self._split_into_batches(sorted_records)
        column_widths  = self._compute_column_widths(sorted_records)
        rendered_pages = [
            self._render_page(batch, page_number, column_widths)
            for page_number, batch in enumerate(batches, start=1)
        ]
        summary = self._build_summary_section(sorted_records)
        header  = self._build_header()
        return self._assemble_full_report(header, rendered_pages, summary)
```

### ✅ Pattern 2: Private `ColumnWidths` dataclass eliminates magic-string coupling
```python
from dataclasses import dataclass as _dataclass

@_dataclass
class _ColumnWidths:
    """Type-safe column width bundle — never exposed to callers."""
    region:      int
    salesperson: int
    revenue:     int
    units:       int

def _compute_column_widths(self, records: list[SalesRecord]) -> _ColumnWidths:
    return _ColumnWidths(
        region      = max(len(r.region)                            for r in records),
        salesperson = max(len(r.salesperson)                       for r in records),
        revenue     = max(len(self._format_currency(r.revenue))    for r in records),
        units       = max(len(str(r.units_sold))                   for r in records),
    )

def _render_column_headers(self, cw: _ColumnWidths) -> str:
    sep = self._COLUMN_SEPARATOR
    return (
        f"{'Region'.ljust(cw.region)}{sep}"
        f"{'Salesperson'.ljust(cw.salesperson)}{sep}"
        f"{'Revenue'.rjust(cw.revenue)}{sep}"
        f"{'Units'.rjust(cw.units)}"
    )
# Typo on `cw.revnue` → AttributeError caught immediately by type checker.
```

### ✅ Pattern 3: Single column-specification eliminates render duplication
```python
from typing import Callable

@_dataclass
class _ColumnSpec:
    """Declares one column: header label, alignment, and value accessor."""
    header:    str
    align:     Literal["left", "right"]
    accessor:  Callable[[SalesRecord], str]

def _get_column_specs(self) -> list[_ColumnSpec]:
    """Single declaration drives both headers and data rows."""
    return [
        _ColumnSpec("Region",      "left",  lambda r: r.region),
        _ColumnSpec("Salesperson", "left",  lambda r: r.salesperson),
        _ColumnSpec("Revenue",     "right", lambda r: self._format_currency(r.revenue)),
        _ColumnSpec("Units",       "right", lambda r: str(r.units_sold)),
    ]

def _render_row(self, cells: list[str], widths: list[int], specs: list[_ColumnSpec]) -> str:
    sep = self._COLUMN_SEPARATOR
    parts = [
        cell.ljust(w) if spec.align == "left" else cell.rjust(w)
        for cell, w, spec in zip(cells, widths, specs)
    ]
    return sep.join(parts)
# Adding a column: one entry in _get_column_specs() propagates everywhere.
```

### ✅ Pattern 4: `page_size` configurable via `__init__`; timestamp captured once
```python
# page_size exposed through the constructor — one parameter, all logic still hidden
report = SalesReport(page_size=10)
report.set_title("Q2 Regional Sales Report")

# render() is now idempotent: same object always produces the same string
assert report.render() == report.render()
```

### ✅ Pattern 5: Explicit precondition guard inside private method
```python
def _build_summary_section(self, sorted_records: list[SalesRecord]) -> str:
    assert sorted_records, "_build_summary_section requires at least one record"
    total_revenue   = sum(r.revenue    for r in sorted_records)
    total_units     = sum(r.units_sold for r in sorted_records)
    average_revenue = total_revenue / len(sorted_records)
    top_performer   = sorted_records[0]
    return (
        f"  Total Revenue:    {self._format_currency(total_revenue)}\n"
        f"  Average Revenue:  {self._format_currency(average_revenue)}\n"
        f"  Total Units Sold: {total_units}\n"
        f"  Top Performer:    {top_performer.salesperson}"
        f" ({top_performer.region})"
        f" — {self._format_currency(top_performer.revenue)}\n"
    )
```

### ✅ Pattern 6: Caller remains blissfully unaware of all internals
```python
if __name__ == "__main__":
    report = SalesReport(page_size=5)
    report.set_title("Q2 Regional Sales Report")

    for record in sales_data:
        report.add_record(record)

    # The entire pipeline — validate, copy, sort, batch, align,
    # summarise, assemble — is triggered by this single call.
    print(report.render())

    # Proof of encapsulation: replacing internal sort or batch strategy
    # requires zero changes at this call site.
```

---

## Decision Checklist

| Question | Required Answer |
|---|---|
| Can the caller accomplish its goal with ≤ 5 public methods? | ✅ Yes |
| Are all pipeline steps (`sort`, `batch`, `format`, `assemble`) private? | ✅ Yes |
| Are inter-method data bundles typed (dataclass) rather than raw `dict[str, X]`? | ✅ Yes |
| Is column/field order declared once and derived everywhere? | ✅ Yes |
| Is `render()` or equivalent idempotent on unchanged state? | ✅ Yes |
| Is configurable behaviour exposed via `__init__` rather than requiring subclassing or source edits? | ✅ Yes |
| Are private method preconditions made explicit via assertions or guards? | ✅ Yes |
| Are caller-supplied objects defensively copied before storage? | ✅ Yes |

---

## Key Principle Summary

> **Interface width and implementation depth are inversely proportional in well-designed modules.** Every step a caller is forced to perform manually is a step the module failed to absorb. The ideal caller interaction is: *configure once, trigger once, receive result*. Everything between configuration and result — validation, transformation, formatting, assembly — belongs inside the module, invisible and unchangeable from the outside.