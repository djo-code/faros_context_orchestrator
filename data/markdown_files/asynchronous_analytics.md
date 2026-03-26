---
rule_id: async-analytics-snowflake-offload
principle: Asynchronous Analytics
category: architecture, performance, reliability
tags: [async, snowflake, analytics, offload, postgres, job-queue, polling, caching, dashboard, OLTP, OLAP]
severity: critical
language: python
---

# Rule: Offload Heavy Analytical Joins to an Async Snowflake Connector

## Core Constraint

Heavy analytical joins (e.g., Cloud Billing ⨝ Jira) **must never execute synchronously against Postgres**. Postgres is an OLTP database — it will timeout, hold connection-pool slots, and block the request thread for minutes. All such queries must be **enqueued immediately, executed asynchronously against Snowflake (columnar MPP), and polled by the caller**. Completed results must be cached to prevent redundant re-execution.

The four required steps are:
1. **Enqueue** — return a `job_id` instantly; never block the request thread.
2. **Execute** — a background worker dispatches the job to Snowflake concurrently.
3. **Poll** — the dashboard polls a status endpoint until the result is ready.
4. **Cache** — completed results are stored so identical queries never re-run.

---

## Negative Patterns — What to Avoid

### ❌ Anti-Pattern 1: Synchronous analytical join executed directly in Postgres
```python
# VIOLATION: blocks the HTTP request thread; Postgres kills it with statement_timeout
class BadDashboardService:
    def get_billing_to_jira_report(self, start_date: str, end_date: str) -> list[dict]:
        query = """
            SELECT cb.project_id, SUM(cb.cost_usd), COUNT(DISTINCT j.issue_key)
            FROM   cloud_billing cb
            JOIN   jira_issues   j ON cb.project_id = j.project_id
            WHERE  cb.billing_date BETWEEN :start_date AND :end_date
            GROUP BY cb.project_id
        """
        # Blocks for 30-120 s, exhausts connection pool, then:
        # ERROR: canceling statement due to statement timeout
        return self._pg.execute(query, start_date=start_date, end_date=end_date)
```
**Why it fails:** Postgres holds a connection-pool slot for the full query duration, starves other traffic, and terminates with a `statement_timeout` error. The user sees a 500. Every refresh re-executes the full join.

### ❌ Anti-Pattern 2: `completed_at` never set on cache-hit jobs — silent negative elapsed time
```python
# VIOLATION: job.completed_at is None; elapsed becomes a large negative number
if cached_result is not None:
    job.status = JobStatus.COMPLETE
    job.result = cached_result
    # BUG: job.completed_at is never set
    self._job_store.save(job)
    return job.job_id

# Later in get_job_status():
elapsed = (job.completed_at or 0) - job.submitted_at  # → large negative value
response["elapsed_seconds"] = round(elapsed, 3)        # silent data corruption
```

### ❌ Anti-Pattern 3: Unbounded `asyncio.create_task` — no concurrency cap on Snowflake
```python
# VIOLATION: every dequeued job spawns an unconstrained task; burst load
# saturates Snowflake's concurrency limits or exhausts memory
async def run_worker(self) -> None:
    while True:
        job = await self._queue.get()
        asyncio.create_task(self._execute_job(job))   # ← no semaphore
        self._queue.task_done()
```

### ❌ Anti-Pattern 4: No in-flight deduplication — redundant concurrent Snowflake queries
```python
# VIOLATION: cache only prevents re-runs AFTER a result is stored.
# Two rapid identical requests each get a distinct job_id and both hit Snowflake.
def enqueue_billing_to_jira_report(self, start_date: str, end_date: str) -> str:
    job = AnalyticsJob(...)
    cached_result = self._result_cache.get(job.cache_key)
    if cached_result:
        ...
        return job.job_id
    # No check for an already-running job with the same cache_key
    self._queue.put_nowait(job)
    return job.job_id
```

### ❌ Anti-Pattern 5: Incomplete polling loop with `NameError`
```python
# VIOLATION: parameter is named `timeout_seconds` but referenced as `timeout_`
async def poll_until_complete(
    queue, job_id, poll_interval_seconds=0.05, timeout_seconds=30.0
) -> dict:
    deadline = time.monotonic() + timeout_   # NameError: timeout_ is not defined
    # polling loop never implemented — the third pillar of the pattern is missing
```

### ❌ Anti-Pattern 6: Synchronous `enqueue` method prevents future `await` calls
```python
# VIOLATION: when JobStatusStore / ResultCache become async-backed (Redis, Postgres),
# this method cannot await them without a breaking API change
def enqueue_billing_to_jira_report(self, start_date: str, end_date: str) -> str:
    ...  # cannot await self._result_cache.get() or self._job_store.save()
```

### ❌ Anti-Pattern 7: No retry on transient Snowflake failures
```python
# VIOLATION: a network blip permanently fails a job that should be retried
async def _execute_job(self, job: AnalyticsJob) -> None:
    try:
        result = await self._snowflake.execute_billing_to_jira_join(job.parameters)
        ...
    except Exception as exc:
        self._job_store.mark_failed(job.job_id, str(exc))  # no retry, no backoff
```

---

## Positive Patterns — The Fix

### ✅ Pattern 1: Enqueue returns `job_id` instantly — request thread never blocked
```python
async def enqueue_billing_to_jira_report(
    self, start_date: str, end_date: str
) -> str:
    """
    Register the job and return a job_id immediately (HTTP 202 Accepted).
    Never blocks — all heavy work happens in the background worker.
    """
    job = AnalyticsJob(
        job_id     = str(uuid.uuid4()),
        query_name = "billing_to_jira_report",
        parameters = {"start_date": start_date, "end_date": end_date},
    )

    # Step 4 (cache): short-circuit if an identical query already completed
    cached_result = await self._result_cache.get(job.cache_key)
    if cached_result is not None:
        log.info("CACHE HIT: key=%s", job.cache_key)
        job.status       = JobStatus.COMPLETE
        job.result       = cached_result
        job.completed_at = time.monotonic()    # ← always set completed_at
        await self._job_store.save(job)
        return job.job_id

    # In-flight deduplication: reuse an existing running job for the same params
    existing_job_id = self._in_flight.get(job.cache_key)
    if existing_job_id is not None:
        log.info("DEDUP HIT: reusing in-flight job_id=%s", existing_job_id)
        return existing_job_id

    await self._job_store.save(job)
    self._in_flight[job.cache_key] = job.job_id
    self._queue.put_nowait(job)
    log.info("ENQUEUED: job_id=%s  params=%s", job.job_id, job.parameters)
    return job.job_id
```

### ✅ Pattern 2: Background worker with bounded concurrency via `asyncio.Semaphore`
```python
MAX_CONCURRENT_SNOWFLAKE_QUERIES = 5

class AnalyticsJobQueue:
    def __init__(self, snowflake, job_store, result_cache) -> None:
        self._snowflake      = snowflake
        self._job_store      = job_store
        self._result_cache   = result_cache
        self._queue: asyncio.Queue[AnalyticsJob] = asyncio.Queue()
        self._in_flight: dict[str, str] = {}   # cache_key → job_id
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_SNOWFLAKE_QUERIES)

    async def run_worker(self) -> None:
        """
        Long-running coroutine — start once at application startup.
        Semaphore caps concurrent Snowflake queries to prevent overload.
        """
        log.info("WORKER: Snowflake analytics worker started")
        while True:
            job: AnalyticsJob = await self._queue.get()
            asyncio.create_task(self._execute_job_with_semaphore(job))
            self._queue.task_done()

    async def _execute_job_with_semaphore(self, job: AnalyticsJob) -> None:
        async with self._semaphore:   # ← at most N jobs hit Snowflake concurrently
            await self._execute_job(job)
```

### ✅ Pattern 3: Retry with exponential backoff for transient Snowflake failures
```python
    async def _execute_job(self, job: AnalyticsJob) -> None:
        """Execute one job against Snowflake with retry on transient failures."""
        await self._job_store.mark_running(job.job_id)
        max_attempts    = 3
        backoff_seconds = 1.0

        for attempt in range(1, max_attempts + 1):
            try:
                result = await self._snowflake.execute_billing_to_jira_join(
                    job.parameters
                )
                await self._job_store.mark_complete(job.job_id, result)
                await self._result_cache.set(job.cache_key, result)
                self._in_flight.pop(job.cache_key, None)
                log.info("WORKER: job_id=%s complete  rows=%d", job.job_id, len(result))
                return
            except TransientSnowflakeError as exc:
                if attempt == max_attempts:
                    await self._job_store.mark_failed(job.job_id, str(exc))
                    self._in_flight.pop(job.cache_key, None)
                    log.error("WORKER: job_id=%s FAILED after %d attempts", job.job_id, attempt)
                    return
                wait = backoff_seconds * (2 ** (attempt - 1))
                log.warning("WORKER: job_id=%s attempt %d failed, retrying in %.1fs", job.job_id, attempt, wait)
                await asyncio.sleep(wait)
            except Exception as exc:
                # Non-transient failure — do not retry
                await self._job_store.mark_failed(job.job_id, str(exc))
                self._in_flight.pop(job.cache_key, None)
                log.error("WORKER: job_id=%s non-retryable failure — %s", job.job_id, exc)
                return
```

### ✅ Pattern 4: Complete polling loop — the third required pillar
```python
async def poll_until_complete(
    queue: AnalyticsJobQueue,
    job_id: str,
    poll_interval_seconds: float = 0.05,
    timeout_seconds: float = 30.0,        # ← name matches usage below
) -> dict[str, Any]:
    """
    Simulates a dashboard polling the status endpoint until the job finishes
    or the timeout is exceeded. Returns the final status dict.
    """
    deadline = time.monotonic() + timeout_seconds   # ← correct name used

    while time.monotonic() < deadline:
        status = queue.get_job_status(job_id)
        job_status = status.get("status")

        if job_status == "COMPLETE":
            log.info("POLL: job_id=%s complete  elapsed=%.3fs", job_id, status.get("elapsed_seconds"))
            return status
        if job_status == "FAILED":
            log.error("POLL: job_id=%s failed — %s", job_id, status.get("error"))
            return status
        if job_status == "NOT_FOUND":
            raise ValueError(f"Unknown job_id: {job_id}")

        log.debug("POLL: job_id=%s  status=%s  waiting %.2fs…", job_id, job_status, poll_interval_seconds)
        await asyncio.sleep(poll_interval_seconds)

    raise TimeoutError(
        f"job_id={job_id} did not complete within {timeout_seconds}s"
    )
```

### ✅ Pattern 5: Non-blocking status check with correct elapsed time
```python
def get_job_status(self, job_id: str) -> dict[str, Any]:
    job = self._job_store.get(job_id)
    if job is None:
        return {"status": "NOT_FOUND", "job_id": job_id}

    response: dict[str, Any] = {"job_id": job_id, "status": job.status.name}

    if job.status == JobStatus.COMPLETE:
        response["result"] = job.result
        # completed_at is always set (cache hits included) — no negative elapsed
        elapsed = (job.completed_at or job.submitted_at) - job.submitted_at
        response["elapsed_seconds"] = round(elapsed, 3)
    elif job.status == JobStatus.FAILED:
        response["error"] = job.error

    return response
```

---

## Architecture Decision Summary

| Concern | Wrong Approach | Correct Approach |
|---|---|---|
| Query execution | Synchronous Postgres join | Async Snowflake (columnar MPP) |
| Request thread | Blocked until query finishes | Returns `job_id` immediately (HTTP 202) |
| Result delivery | Synchronous response | Dashboard polls status endpoint |
| Repeated queries | Re-execute every refresh | Cache by `sha256(query + params)` |
| Concurrent Snowflake load | Unbounded `create_task` | `asyncio.Semaphore` caps in-flight queries |
| Duplicate in-flight requests | Each gets a separate job | In-flight dedup map keyed on `cache_key` |
| Transient failures | Permanent `FAILED` status | Exponential backoff, max N retries |
| Process-restart durability | In-memory `asyncio.Queue` | Durable broker (SQS, Redis Streams) |
| Future async I/O in enqueue | `def enqueue(...)` | `async def enqueue(...)` |

## Key Principle Summary

> **Postgres is for OLTP. Snowflake is for OLAP.** Any query that joins across systems, aggregates millions of rows, or runs longer than a few hundred milliseconds must never touch the Postgres connection pool during a live request. Enqueue it, return a handle, execute it in a bounded background worker against Snowflake, cache the result, and let the client poll. Every deviation from this pattern is a timeout waiting to happen.