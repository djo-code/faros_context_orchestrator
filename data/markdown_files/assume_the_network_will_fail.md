---
rule_id: resilience-network-will-fail
principle: Assume the Network Will Fail
category: resilience, distributed-systems, networking
tags: [timeout, retry, exponential-backoff, jitter, circuit-breaker, fallback, cache, idempotency, thread-safety, network-resilience]
severity: critical
language: python
---

# Rule: Assume the Network Will Fail — Build Resilience In

## Core Constraint

**Never assume zero latency, infinite bandwidth, or perfect reliability.** Every network call must be wrapped with: (1) an enforced wall-clock timeout, (2) retries with exponential backoff and full jitter, (3) a circuit breaker that distinguishes transient from permanent failures, and (4) a stale-cache fallback. Omitting any pillar leaves a real system exposed to hangs, thundering herds, cascading failures, or silent data loss.

---

## Negative Patterns — What to Avoid

### ❌ Anti-Pattern 1: No timeout — hangs forever on a slow or unresponsive host
```python
# VIOLATION: urlopen blocks indefinitely; one slow server stalls the entire thread
def naive_fetch_user_profile(user_id: int) -> dict:
    import urllib.request
    url = f"https://api.example.com/users/{user_id}"
    with urllib.request.urlopen(url) as response:  # no timeout argument
        return response.read()                      # crashes on any failure
```

### ❌ Anti-Pattern 2: Timeout parameter accepted but never enforced
```python
# VIOLATION: timeout_sec is ignored — the call still blocks indefinitely
def _call_with_timeout(self, call: Callable[[], Any], timeout_sec: float) -> Any:
    try:
        return call()          # timeout_sec is never passed to anything
    except TimeoutError as timeout:
        raise RetriableError(...) from timeout
# A real urllib / requests call placed here hangs forever —
# identical behaviour to the naive_fetch bad example.
```
**Why it fails:** Accepting a timeout parameter without enforcing it is a silent contract violation. It provides false confidence to callers and reviewers while offering zero protection.

### ❌ Anti-Pattern 3: Circuit breaker opens on permanent (4xx) errors
```python
# VIOLATION: a 404 or 401 is a healthy response from a working service —
# recording it as a circuit-breaker failure will trip the breaker on valid
# requests and block ALL traffic during the cooldown period.
except PermanentError as permanent_failure:
    self._circuit_breaker.record_failure()   # ← wrong: 4xx ≠ service down
    return Result(error=f"Permanent failure: {permanent_failure}")
```
**Why it fails:** Circuit breakers should only register failures that indicate service *unavailability* (5xx, timeouts, connection refused). Tripping on 404/401 causes self-inflicted cascading outages.

### ❌ Anti-Pattern 4: State mutation inside a property getter
```python
# VIOLATION: property getters must be idempotent — mutation on read is
# a violation of least surprise and a race condition under concurrency.
@property
def state(self) -> CircuitState:
    if self._state is CircuitState.OPEN:
        if time_since_opened >= self.recovery_timeout_sec:
            self._state = CircuitState.HALF_OPEN   # mutates on read
    return self._state
```

### ❌ Anti-Pattern 5: Shared mutable state without thread-safety
```python
# VIOLATION: _failure_count, _state, and _response_cache mutated without locks.
# Concurrent retry storms — the normal failure mode — will produce race conditions
# on exactly these fields.
self._failure_count += 1        # non-atomic read-modify-write
self._state = CircuitState.OPEN # non-atomic state transition
self._response_cache[key] = v   # concurrent dict mutation
```

### ❌ Anti-Pattern 6: Unconditional retry of non-idempotent operations
```python
# VIOLATION: retrying a payment POST after receiving a 503 that arrived
# *after* the server processed the request causes duplicate charges.
for attempt in range(max_attempts):
    try:
        return call()   # no check whether this operation is safe to retry
    except RetriableError:
        continue        # blindly retries — dangerous for POST/PUT/PATCH
```

---

## Positive Patterns — The Fix

### ✅ Pattern 1: Enforce real wall-clock timeouts at the transport layer
```python
import requests
from requests.exceptions import Timeout, ConnectionError

def _call_with_timeout(self, call: Callable[[], Any], timeout_sec: float) -> Any:
    """
    Pass timeout_sec to the underlying transport — not just catch an exception
    that the transport would have to raise on its own.
    """
    try:
        # Option A — requests library (synchronous)
        response = requests.get(url, timeout=timeout_sec)   # enforced by library
        response.raise_for_status()
        return response.json()
    except Timeout as exc:
        raise RetriableError(f"Timed out after {timeout_sec}s") from exc
    except ConnectionError as exc:
        raise RetriableError("Connection refused or DNS failure") from exc

    # Option B — asyncio (async context)
    # async with asyncio.timeout(timeout_sec):
    #     return await some_async_call()
```

### ✅ Pattern 2: Distinguish retriable (5xx/timeout) from permanent (4xx) failures
```python
def _classify_http_error(self, response: requests.Response) -> None:
    """Raise the correct error type so the retry loop and circuit breaker behave correctly."""
    if response.status_code in (429, 500, 502, 503, 504):
        raise RetriableError(f"Transient HTTP {response.status_code}")
    if response.status_code in (400, 401, 403, 404, 422):
        raise PermanentError(f"Permanent HTTP {response.status_code} — retrying will not help")

# In the fetch loop:
except PermanentError as permanent_failure:
    # Do NOT record_failure() — the service is healthy; the request is invalid.
    return Result(error=f"Permanent failure: {permanent_failure}")

except RetriableError as transient_failure:
    self._circuit_breaker.record_failure()   # only transient failures count
    last_error = str(transient_failure)
```

### ✅ Pattern 3: Circuit breaker with thread-safe, idempotent state transitions
```python
import threading
from dataclasses import dataclass, field
from enum import Enum, auto

class CircuitState(Enum):
    CLOSED    = auto()   # normal — requests flow through
    OPEN      = auto()   # failing — requests blocked (fail fast)
    HALF_OPEN = auto()   # recovering — one probe request allowed

@dataclass
class CircuitBreaker:
    failure_threshold:    int   = 3
    recovery_timeout_sec: float = 10.0

    _failure_count: int              = field(default=0,                   init=False, repr=False)
    _state:         CircuitState     = field(default=CircuitState.CLOSED, init=False)
    _opened_at:     Optional[float]  = field(default=None,                init=False, repr=False)
    _lock:          threading.Lock   = field(default_factory=threading.Lock, init=False, repr=False)

    def current_state(self) -> CircuitState:
        """Explicit method — not a property — makes mutation visible at the call site."""
        with self._lock:
            if self._state is CircuitState.OPEN:
                if time.monotonic() - self._opened_at >= self.recovery_timeout_sec:
                    log.info("Circuit HALF-OPEN: probing service…")
                    self._state = CircuitState.HALF_OPEN
            return self._state

    def allow_request(self) -> bool:
        return self.current_state() in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    def record_success(self) -> None:
        with self._lock:
            if self._state is not CircuitState.CLOSED:
                log.info("Circuit CLOSED: service recovered.")
            self._state         = CircuitState.CLOSED
            self._failure_count = 0
            self._opened_at     = None

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            if (self._state is CircuitState.HALF_OPEN or
                    self._failure_count >= self.failure_threshold):
                self._state     = CircuitState.OPEN
                self._opened_at = time.monotonic()
                log.warning(
                    "Circuit OPEN: %d failures. Blocking for %.1fs.",
                    self._failure_count, self.recovery_timeout_sec,
                )
```

### ✅ Pattern 4: Exponential backoff with full jitter and a defensive Result container
```python
@dataclass
class RetryPolicy:
    max_attempts:   int   = 4
    base_delay_sec: float = 0.5
    max_delay_sec:  float = 30.0
    backoff_factor: float = 2.0
    jitter:         bool  = True

    def delay_before_attempt(self, attempt_number: int) -> float:
        """Full jitter prevents thundering herd across concurrent clients."""
        if attempt_number <= 1:
            return 0.0
        exponential_delay = self.base_delay_sec * (self.backoff_factor ** (attempt_number - 2))
        capped_delay = min(exponential_delay, self.max_delay_sec)
        return random.uniform(0, capped_delay) if self.jitter else capped_delay


@dataclass
class Result(Generic[T]):
    """
    Explicit success/failure container — callers cannot ignore failures.
    Mutual exclusivity is enforced at construction time.
    """
    value:             Optional[T]   = None
    error:             Optional[str] = None
    served_from_cache: bool          = False

    def __post_init__(self) -> None:
        if self.value is not None and self.error is not None:
            raise ValueError("Result cannot carry both a value and an error.")

    @property
    def succeeded(self) -> bool:
        return self.error is None
```

### ✅ Pattern 5: Idempotency guard on retries
```python
class HttpMethod(Enum):
    GET    = "GET"    # safe + idempotent — always retriable
    HEAD   = "HEAD"
    PUT    = "PUT"    # idempotent — retriable
    DELETE = "DELETE" # idempotent — retriable
    POST   = "POST"   # NOT idempotent — retry only with explicit opt-in
    PATCH  = "PATCH"  # NOT idempotent — retry only with explicit opt-in

RETRIABLE_METHODS = {HttpMethod.GET, HttpMethod.HEAD, HttpMethod.PUT, HttpMethod.DELETE}

def fetch(self, resource_key: str, call: Callable, method: HttpMethod = HttpMethod.GET) -> Result:
    is_retriable = method in RETRIABLE_METHODS
    max_attempts = self._retry_policy.max_attempts if is_retriable else 1

    for attempt_number in range(1, max_attempts + 1):
        ...
```

### ✅ Pattern 6: Stale-cache fallback — stale data beats an error page
```python
def _serve_from_cache_or_error(self, resource_key: str, last_error: Optional[str] = None) -> Result:
    """Stale data is almost always preferable to surfacing a 503 to the user."""
    if resource_key in self._response_cache:
        log.warning("Serving stale cached response for '%s'.", resource_key)
        return Result(value=self._response_cache[resource_key], served_from_cache=True)
    return Result(error=last_error or "Service unavailable and no cached data.")
```

---

## Four Pillars of Network Resilience — Decision Table

| Pillar | Must Cover | Common Omission to Avoid |
|---|---|---|
| **Timeout** | Pass deadline to the transport layer (`requests(timeout=...)`, `asyncio.timeout(...)`) | Accepting a `timeout_sec` param but never using it |
| **Retry + Backoff** | Exponential delay with full jitter; only retry idempotent/safe operations | Retrying non-idempotent POST/PATCH unconditionally |
| **Circuit Breaker** | Open only on 5xx / timeout / connection errors; never on 4xx | Calling `record_failure()` on `PermanentError` (4xx) |
| **Fallback** | Serve stale cache before returning an error; log that data is stale | Returning bare `None` or raising when cache exists |

## Thread-Safety Checklist for Network Clients

| Shared field | Protection required |
|---|---|
| `_failure_count` | `threading.Lock` around read-modify-write |
| `_state` | `threading.Lock`; transition in explicit method, not property getter |
| `_response_cache` | `threading.Lock` or use `dict` only under lock; prefer `threading.local` for per-thread caches |
| State transition on read | Move mutation out of `@property` into an explicitly named method |

## Key Principle Summary

> **Every network call is a bet against entropy.** A missing timeout is a thread leak waiting to happen. A circuit breaker that fires on 404s will self-inflict cascading outages. Retrying a payment POST without an idempotency key causes duplicate charges. None of these failures require a network outage — they require only a single slow response, a missing resource, or two concurrent threads. Build every network boundary as if the service on the other side is already failing.