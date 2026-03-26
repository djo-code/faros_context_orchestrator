---
rule_id: decoupled-ingestion-kafka
principle: Decoupled Ingestion
category: architecture, reliability, scalability
tags: [kafka, webhooks, message-broker, producer, consumer, at-least-once, CICD, telemetry, decoupling, backpressure, dead-letter-queue, offset-commit]
severity: critical
language: python
domain: distributed-systems, event-streaming
---

# Rule: Decouple High-Volume Telemetry via a Message Broker (Kafka)

## Core Constraint

HTTP webhook ingestion and event processing **must be separated by a durable message broker**. The HTTP handler's only job is to enqueue the event and return `202 Accepted` immediately. Processing happens independently, at the consumer's own pace. This boundary guarantees:

- **Zero data loss** during traffic spikes — the broker absorbs bursts the processor cannot handle in real time
- **At-least-once delivery** — offsets commit only after successful processing; crashes trigger redelivery
- **Independent scaling** — producers and consumers scale on separate axes
- **Non-blocking ingestion** — senders never wait for processing to complete

---

## Negative Patterns — What to Avoid

### ❌ Anti-Pattern 1: Synchronous processing inside the HTTP handler
```python
# VIOLATION: processing blocks the HTTP thread — slow consumers = dropped webhooks
class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        event = WebhookEvent.from_raw_payload("github", payload)
        result = processor.process(event)   # ← blocks until done
        store_result(result)                # ← blocks further
        self.send_response(200)
        self.end_headers()
# Problem: if `process()` is slow or the DB is lagging, incoming webhooks
# queue up inside the OS TCP buffer and are eventually dropped.
```

### ❌ Anti-Pattern 2: Unnecessary lock around a thread-safe producer call
```python
# VIOLATION: confluent-kafka Producer.produce() is already thread-safe.
# Adding a Lock serializes all concurrent HTTP handler threads through a
# single chokepoint — re-coupling ingestion latency to producer throughput.
class KafkaWebhookProducer:
    def __init__(self):
        self._producer = Producer(config)
        self._publish_lock = threading.Lock()   # ← unnecessary

    def publish(self, topic, event):
        with self._publish_lock:                # ← all threads block here
            self._producer.produce(...)
            self._producer.poll(0)
```

### ❌ Anti-Pattern 3: `put_nowait` silently drops events when queue is full
```python
# VIOLATION: raises queue.Full when at capacity — caller gets an unhandled
# exception and the event is lost. This breaks the zero-data-loss guarantee
# the in-memory simulation is supposed to mirror.
class InMemoryWebhookProducer:
    def publish(self, topic, event):
        message = {"topic": topic, "event_bytes": event.to_kafka_message_bytes()}
        self._queue.put_nowait(message)   # ← silent data loss under load
```

### ❌ Anti-Pattern 4: Auto-committing offsets before processing completes
```python
# VIOLATION: if the worker crashes after commit but before processing,
# the message is permanently lost — no redelivery.
CONSUMER_CONFIG = {
    "enable.auto.commit": True,    # ← commits on poll, not after process
    "auto.commit.interval.ms": 5000,
}
```

### ❌ Anti-Pattern 5: Unbounded in-memory result accumulation
```python
# VIOLATION: appending every ProcessingResult forever exhausts heap
# in a long-running consumer. Mixes processing with state management.
class KafkaWebhookConsumer:
    def __init__(self):
        self._results: list[ProcessingResult] = []   # grows without bound

    def start_consuming(self, backend):
        while self._is_running:
            ...
            result = self._processor.process(event)
            self._results.append(result)             # ← unbounded growth
```

### ❌ Anti-Pattern 6: No HTTP boundary — ingest handler never implemented
```python
# VIOLATION: claiming "fast 202 Accepted" without implementing the handler
# leaves the most critical decoupling boundary — where HTTP ends and the
# queue begins — undemonstrated and unenforced.
from http.server import BaseHTTPRequestHandler  # imported but never subclassed
```

---

## Positive Patterns — The Fix

### ✅ Pattern 1: HTTP handler enqueues and immediately acknowledges
```python
class WebhookIngestHandler(BaseHTTPRequestHandler):
    """
    The ONLY job of this handler: validate, enqueue, return 202.
    Processing is decoupled entirely — this thread never waits for it.
    """
    publisher: WebhookEventPublisher   # injected at server construction
    topic: str

    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length)
            payload  = json.loads(raw_body)

            source = self.headers.get("X-Webhook-Source", "unknown")
            event  = WebhookEvent.from_raw_payload(source, payload)

            # Enqueue — returns in microseconds regardless of consumer load
            self.publisher.publish(self.topic, event)

            self.send_response(202)     # Accepted — not yet processed
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"event_id": event.event_id}).encode())
        except Exception as exc:
            log.error("Ingest handler error: %s", exc)
            self.send_response(500)
            self.end_headers()

    def log_message(self, *args):
        pass   # suppress default stderr noise; structured logging handles this
```

### ✅ Pattern 2: Thread-safe producer — no lock needed
```python
class KafkaWebhookProducer(WebhookEventPublisher):
    """
    acks=all + idempotent producer = zero data loss on broker failover.
    confluent-kafka Producer is thread-safe; no external Lock required.
    """
    PRODUCER_CONFIG = {
        "bootstrap.servers":     "kafka-broker-1:9092,kafka-broker-2:9092",
        "acks":                  "all",
        "retries":               2_147_483_647,
        "max.in.flight.requests.per.connection": 1,
        "enable.idempotence":    True,
        "compression.type":      "lz4",
        "linger.ms":             5,
        "batch.size":            65_536,
        "delivery.timeout.ms":   120_000,
    }

    def publish(self, topic: str, event: WebhookEvent) -> None:
        # No Lock — Producer.produce() is thread-safe by design
        self._producer.produce(
            topic       = topic,
            key         = event.kafka_partition_key,
            value       = event.to_kafka_message_bytes(),
            on_delivery = self._make_delivery_callback(event),
        )
        self._producer.poll(0)   # trigger callbacks without blocking

    def _make_delivery_callback(self, event: WebhookEvent):
        def on_delivery(error, message):
            if error:
                log.error("Delivery FAILED — event_id=%s  error=%s", event.event_id, error)
                self._dead_letter_publisher.publish(event, reason=str(error))
            else:
                log.debug(
                    "Delivered — event_id=%s  partition=%d  offset=%d",
                    event.event_id, message.partition(), message.offset(),
                )
        return on_delivery
```

### ✅ Pattern 3: In-memory producer with blocking put + backpressure
```python
class InMemoryWebhookProducer(WebhookEventPublisher):
    """
    Preserves the zero-data-loss contract: block the caller rather than
    silently dropping events when the queue is full.
    """
    def publish(self, topic: str, event: WebhookEvent) -> None:
        message = {"topic": topic, "event_bytes": event.to_kafka_message_bytes()}
        try:
            # block=True + timeout applies backpressure instead of data loss
            self._queue.put(message, block=True, timeout=5.0)
        except queue.Full:
            log.error(
                "Ingest queue full — event_id=%s will be sent to DLQ", event.event_id
            )
            self._dead_letter_publisher.publish(event, reason="queue_full")
```

### ✅ Pattern 4: Commit offsets only after successful processing
```python
CONSUMER_CONFIG = {
    "enable.auto.commit":    False,      # ← we control offset advancement
    "auto.offset.reset":     "earliest", # never skip messages on new group
    "isolation.level":       "read_committed",
    "max.poll.interval.ms":  300_000,
}

class KafkaWebhookConsumer:
    def start_consuming(self, consumer_backend, result_sink: ResultSink) -> None:
        consumer_backend.subscribe([self._topic])
        try:
            while self._is_running:
                raw_message = consumer_backend.poll(timeout=1.0)
                if raw_message is None:
                    continue
                if raw_message.error():
                    log.error("Consumer error: %s", raw_message.error())
                    continue

                event  = WebhookEvent.from_kafka_message_bytes(raw_message.value())
                result = self._processor.process(event)

                # Persist result BEFORE committing offset — crash safety
                result_sink.store(result)

                # Commit AFTER processing — guarantees at-least-once delivery
                consumer_backend.commit(message=raw_message, asynchronous=False)

                log.info(
                    "PROCESSED ← event_id=%.8s  pipeline=%-20s  status=%-10s  took=%.2fms",
                    result.event_id, result.pipeline_name,
                    result.status, result.processing_ms,
                )
        finally:
            consumer_backend.close()
```

### ✅ Pattern 5: Result sink abstraction eliminates unbounded accumulation and duplicated logic
```python
class ResultSink(ABC):
    """Single place to handle post-processing: storage, metrics, DLQ routing."""
    @abstractmethod
    def store(self, result: ProcessingResult) -> None: ...

class InMemoryResultSink(ResultSink):
    """Bounded sink for tests — raises once capacity exceeded."""
    def __init__(self, max_results: int = 10_000) -> None:
        self._results: list[ProcessingResult] = []
        self._max = max_results

    def store(self, result: ProcessingResult) -> None:
        if len(self._results) >= self._max:
            raise RuntimeError(f"ResultSink exceeded capacity of {self._max}")
        self._results.append(result)

    @property
    def all_results(self) -> list[ProcessingResult]:
        return list(self._results)

# Both KafkaWebhookConsumer and InMemoryWebhookConsumer inject a ResultSink —
# logging, metrics, and DLQ routing are written once inside the sink, never duplicated.
```

### ✅ Pattern 6: Dead-letter queue interface — failure path is a first-class citizen
```python
class DeadLetterPublisher(ABC):
    """Receives events that could not be delivered or processed successfully."""
    @abstractmethod
    def publish(self, event: WebhookEvent, reason: str) -> None: ...

class LoggingDeadLetterPublisher(DeadLetterPublisher):
    """Minimal DLQ implementation: structured log + persistent storage hook."""
    def publish(self, event: WebhookEvent, reason: str) -> None:
        log.error(
            "DLQ ← event_id=%s  source=%s  pipeline=%s  reason=%s",
            event.event_id, event.source_system, event.pipeline_name, reason,
        )
        # A production implementation would write to a dedicated Kafka topic
        # (e.g., "ci.cd.webhooks.dlq") or an S3 dead-letter bucket.
```

---

## Architecture Invariants

```
  HTTP Webhook Handler          Kafka Topic               Worker Consumer
  ┌──────────────────┐         ┌──────────────────┐      ┌──────────────────┐
  │  do_POST()       │publish()│  ci.cd.webhooks  │poll()│  process()       │
  │  → enqueue       │────────►│  (acks=all,      │─────►│  → result_sink   │
  │  → 202 Accepted  │         │   idempotent,    │      │  → commit offset │
  │  (microseconds)  │         │   replicated)    │      │  (after success) │
  └──────────────────┘         └──────────────────┘      └──────────────────┘
           │                                                       │
           │                   ┌──────────────────┐               │
           └──── on failure ──►│  Dead Letter     │◄──────────────┘
                               │  Publisher       │  (delivery fail / crash)
                               └──────────────────┘
```

---

## Decision Checklist

| Guarantee | Mechanism | Config / Code Signal |
|---|---|---|
| Zero data loss on broker failover | `acks=all` + `enable.idempotence=true` | `PRODUCER_CONFIG` |
| At-least-once delivery after consumer crash | Manual offset commit after processing | `enable.auto.commit=False` + `commit(asynchronous=False)` |
| No silent event drops under backpressure | Blocking `queue.put()` with timeout → DLQ | `InMemoryWebhookProducer.publish()` |
| Non-blocking HTTP ingestion | Handler only enqueues; returns 202 immediately | `WebhookIngestHandler.do_POST()` |
| No unbounded memory growth | Bounded `ResultSink` abstraction | `InMemoryResultSink(max_results=...)` |
| Failure path is first-class | `DeadLetterPublisher` interface + implementation | `LoggingDeadLetterPublisher` |
| Producer thread-safety without chokepoint | No `Lock` around `Producer.produce()` | Lock removed from `KafkaWebhookProducer` |
| Testability without a broker | `InMemoryWebhookProducer` / `InMemoryWebhookConsumer` swap | `WebhookEventPublisher` ABC |

---

## Key Principle Summary

> **The broker is the contract boundary.** Everything upstream of Kafka (the HTTP handler) must be as fast and simple as possible — enqueue and acknowledge. Everything downstream (the consumer) must be as resilient as possible — commit only on success, route failures to a dead-letter queue, and never accumulate state in memory without a bound. The in-memory simulation must faithfully honour the same guarantees as the real broker, or it will mask production failure modes during development.