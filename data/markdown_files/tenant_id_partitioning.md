---
rule_id: kafka-tenant-id-partitioning
principle: Tenant-ID Partitioning
category: kafka, multi-tenancy, data-isolation, architecture
tags: [kafka, tenant-id, partition-key, noisy-neighbor, SSOT, producer, consumer, topic-policy, data-isolation, multi-tenant]
severity: critical
language: python
---

# Rule: Kafka Topic Partitioning by Tenant-ID (Strict Isolation)

## Core Constraint

Every Kafka producer **must** set `key=tenant_id.encode("utf-8")` on every `produce()` call. It must be **structurally impossible** — not merely conventional — to publish a message without a tenant partition key. Topic partition counts must be validated against the active tenant population at startup. Consumers must enforce tenant identity as a second line of defence by rejecting any envelope whose `tenant_id` does not match the authorised tenant.

---

## Negative Patterns — What to Avoid

### ❌ Anti-Pattern 1: Producing without a partition key
```python
# VIOLATION: no key → Kafka round-robins across all partitions
# All tenants share partitions randomly; one high-throughput tenant
# can saturate shared partition bandwidth and starve all others.
class BadKafkaProducer:
    def send(self, topic: str, payload: dict) -> None:
        self._producer.produce(topic, value=json.dumps(payload))
        # ✗ tenant_id is absent — data isolation is NOT guaranteed
        # ✗ noisy-neighbor contention is guaranteed under high load
```

### ❌ Anti-Pattern 2: Constructing messages without enforced tenant identity
```python
# VIOLATION: nothing prevents tenant_id from being empty or omitted
@dataclass
class Message:
    topic:   str
    payload: dict
    tenant_id: str = ""   # ← optional by default; silent omission is possible
```

### ❌ Anti-Pattern 3: Topic partition count not validated against tenant population
```python
# VIOLATION: topic created with a fixed low partition count that is never
# checked against the number of active tenants at startup.
# Two or more tenants will consistently collide onto the same partition,
# defeating isolation and re-introducing noisy-neighbor risk.
producer = KafkaProducer(bootstrap_servers="...")
# No policy check — num_partitions=1 for a 50-tenant deployment
```

### ❌ Anti-Pattern 4: Consumer using subscribe() with no envelope verification
```python
# VIOLATION: subscribe() with a consumer group means the rebalancer may
# assign this consumer partitions carrying other tenants' messages.
# Without envelope-level tenant_id verification, cross-tenant data leaks.
consumer.subscribe(["payments.processed"])
for msg in consumer:
    process(json.loads(msg.value))   # ← no tenant_id check; leaks tenant B data to tenant A consumer
```

### ❌ Anti-Pattern 5: Dead `hashlib` import signals unimplemented custom partitioner
```python
import hashlib   # VIOLATION: imported but never used

@property
def partition_key(self) -> bytes:
    return self.tenant_id.encode("utf-8")  # hashing delegated to Kafka murmur2
# ✗ Implies a deterministic tenant→partition mapping that does not exist.
# ✗ min_partitions >= num_tenants check is necessary but NOT sufficient
#   under the default Kafka partitioner — hash collisions mean two tenants
#   can still share a partition regardless of the count check.
```

### ❌ Anti-Pattern 6: Tenant-ID not normalised before use as a partition key
```python
# VIOLATION: "ACME" and "acme" hash to different partitions under murmur2,
# silently splitting one tenant's message stream across multiple partitions.
TenantMessage(tenant_id="ACME", ...)   # routes to partition X
TenantMessage(tenant_id="acme", ...)   # routes to partition Y — divergence!
```

---

## Positive Patterns — The Fix

### ✅ Pattern 1: Structural impossibility of key omission via validated dataclass
```python
@dataclass(frozen=True)
class TenantMessage:
    """
    Canonical Kafka envelope. Cannot be constructed without a valid tenant_id.
    The partition key is derived deterministically from the normalised tenant_id.
    """
    tenant_id:   str
    topic:       str
    payload:     dict
    event_type:  str
    produced_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def __post_init__(self) -> None:
        # Normalise before validation to prevent casing-based routing divergence
        object.__setattr__(self, "tenant_id", self.tenant_id.strip().lower())
        if not self.tenant_id:
            raise ValueError(
                "TenantMessage requires a non-empty tenant_id. "
                "All Kafka messages must be partitioned by tenant_id "
                "to enforce data isolation."
            )
        if not self.topic or not self.topic.strip():
            raise ValueError("TenantMessage requires a non-empty topic.")

    @property
    def partition_key(self) -> bytes:
        """Bytes Kafka uses to assign this message to a partition."""
        return self.tenant_id.encode("utf-8")

    def to_wire_format(self) -> bytes:
        """tenant_id is embedded in the envelope for consumer-side verification."""
        return json.dumps({
            "tenant_id":   self.tenant_id,
            "event_type":  self.event_type,
            "produced_at": self.produced_at,
            "payload":     self.payload,
        }).encode("utf-8")
```

### ✅ Pattern 2: Producer with no bypass path to `produce()` without tenant key
```python
class TenantAwareKafkaProducer:
    """
    The ONLY sanctioned way to publish to Kafka.
    Every call to produce() passes key=message.partition_key — enforced
    in one private method that all public paths funnel through.
    """
    def __init__(
        self,
        raw_producer: Any,
        topic_policies: dict[str, TopicPartitionPolicy],
        on_delivery_error: Optional[Callable[[Exception, TenantMessage], None]] = None,
    ) -> None:
        self._producer          = raw_producer
        self._topic_policies    = topic_policies
        self._on_delivery_error = on_delivery_error or self._default_delivery_error

    def publish(self, message: TenantMessage, flush: bool = False) -> None:
        """Publish one message. Pass flush=True to guarantee durability immediately."""
        self._assert_topic_is_registered(message.topic)
        self._produce_with_tenant_key(message)
        if flush:
            self._producer.flush()

    def publish_batch(self, messages: list[TenantMessage]) -> None:
        """Publish a batch; flush once after all messages are enqueued."""
        for message in messages:
            self._assert_topic_is_registered(message.topic)
            self._produce_with_tenant_key(message)
        self._producer.flush()

    def _assert_topic_is_registered(self, topic: str) -> None:
        if topic not in self._topic_policies:
            raise KeyError(
                f"Topic '{topic}' has no registered TopicPartitionPolicy. "
                "Register every topic before producing to enforce partition "
                "count validation for your tenant population."
            )

    def _produce_with_tenant_key(self, message: TenantMessage) -> None:
        """Single chokepoint — key=message.partition_key is always set."""
        try:
            self._producer.produce(
                topic=message.topic,
                key=message.partition_key,          # ← tenant_id; never absent
                value=message.to_wire_format(),
                on_delivery=self._build_delivery_callback(message),
            )
        except Exception as exc:
            self._on_delivery_error(exc, message)
            raise
```

### ✅ Pattern 3: Topic policy validates partition count at startup, not runtime
```python
@dataclass(frozen=True)
class TopicPartitionPolicy:
    topic:              str
    min_partitions:     int
    replication_factor: int = 3

    def __post_init__(self) -> None:
        if self.min_partitions < 1:
            raise ValueError(f"Topic '{self.topic}' must have at least 1 partition.")

    def assert_sufficient_for_tenant_count(self, active_tenant_count: int) -> None:
        """
        min_partitions >= active_tenant_count is a NECESSARY condition to
        reduce collision probability. For guaranteed per-tenant dedicated
        partitions, pair this check with a custom partitioner that maps
        tenant_id → partition_id deterministically (see Pattern 4).
        """
        if self.min_partitions < active_tenant_count:
            raise RuntimeError(
                f"Topic '{self.topic}' has only {self.min_partitions} partition(s) "
                f"but {active_tenant_count} active tenant(s) require at least "
                f"{active_tenant_count} partition(s) to reduce noisy-neighbor risk. "
                "Increase the partition count before deploying."
            )


class TenantTopicRegistry:
    """Central registry; call validate_capacity_for_tenant_population() at startup."""
    def __init__(self) -> None:
        self._policies: dict[str, TopicPartitionPolicy] = {}

    def register(self, policy: TopicPartitionPolicy) -> None:
        self._policies[policy.topic] = policy

    def validate_capacity_for_tenant_population(self, active_tenant_count: int) -> None:
        for policy in self._policies.values():
            policy.assert_sufficient_for_tenant_count(active_tenant_count)
```

### ✅ Pattern 4: Custom partitioner for deterministic tenant→partition mapping
```python
# Use this instead of relying on Kafka's default murmur2 hash when strict
# per-tenant partition ownership is required. Eliminates hash collisions.
def deterministic_tenant_partitioner(
    tenant_id: str,
    num_partitions: int,
) -> int:
    """
    Maps tenant_id to a partition index deterministically.
    Consistent across all producers and consumers in the fleet.
    """
    tenant_hash = int(hashlib.sha256(tenant_id.encode("utf-8")).hexdigest(), 16)
    return tenant_hash % num_partitions

# Wire up at producer creation:
#   partition = deterministic_tenant_partitioner(message.tenant_id, num_partitions)
#   self._producer.produce(topic=..., key=..., value=..., partition=partition)
```

### ✅ Pattern 5: Consumer enforces tenant identity as a second line of defence
```python
class TenantAwareKafkaConsumer:
    """
    Only yields messages whose envelope tenant_id matches the authorised tenant.
    Cross-tenant messages are rejected and logged as security events — they
    should never arrive due to partition keying, but may in edge cases
    (rebalance, misconfigured producer, manual offset reset).
    """
    def __init__(
        self,
        authorised_tenant_id: str,
        raw_consumer: Any,
        topics: list[str],
    ) -> None:
        if not authorised_tenant_id:
            raise ValueError("Consumer must declare an authorised_tenant_id.")
        self._authorised_tenant_id = authorised_tenant_id.strip().lower()
        self._consumer = raw_consumer
        # Use assign() with pre-computed partitions for strict isolation;
        # subscribe() is acceptable when envelope-level rejection is in place.
        self._consumer.subscribe(topics)

    def consume_messages(self, max_messages: int = 100) -> Iterator[dict]:
        consumed = 0
        while consumed < max_messages:
            raw = self._consumer.poll(timeout_seconds=1.0)
            if raw is None:
                break
            envelope = self._deserialise_envelope(raw)
            if envelope is None:
                continue
            if envelope.get("tenant_id") != self._authorised_tenant_id:
                self._reject_cross_tenant_message(envelope)
                continue
            yield envelope
            consumed += 1

    @staticmethod
    def _deserialise_envelope(raw: Any) -> Optional[dict]:
        try:
            return json.loads(raw.value())
        except (json.JSONDecodeError, AttributeError) as exc:
            logger.error("Failed to deserialise Kafka message: %s", exc)
            return None

    def _reject_cross_tenant_message(self, envelope: dict) -> None:
        logger.error(
            "SECURITY: Consumer for tenant '%s' received message for tenant '%s' "
            "— message discarded. Investigate producer key assignment.",
            self._authorised_tenant_id,
            envelope.get("tenant_id", "<unknown>"),
        )
```

---

## Architecture Layers and Responsibilities

| Layer | Responsibility | Isolation Mechanism |
|---|---|---|
| `TenantMessage.__post_init__` | Reject empty or whitespace `tenant_id`; normalise casing | Type-level structural guarantee |
| `TenantMessage.partition_key` | Expose normalised `tenant_id` as partition bytes | Deterministic key derivation |
| `TenantAwareKafkaProducer._produce_with_tenant_key` | Single chokepoint; `key=` always set | No bypass path to `produce()` |
| `TopicPartitionPolicy.assert_sufficient_for_tenant_count` | Validate partition count ≥ tenant count at startup | Fail-fast before first message |
| Custom partitioner (`deterministic_tenant_partitioner`) | Map `tenant_id → partition_id` without hash collisions | Explicit deterministic routing |
| `TenantAwareKafkaConsumer.consume_messages` | Reject envelopes with wrong `tenant_id` | Second line of defence |

---

## Flush Contract
```python
# Single publish — explicit flush parameter for durability control
producer.publish(message, flush=True)   # guaranteed durable before returning

# Batch publish — always flushes once after the full batch
producer.publish_batch([msg_a, msg_b, msg_c])

# DO NOT mix publish() (flush=False) with publish_batch() and expect ordering
# guarantees — messages from publish() may sit in the internal buffer until
# the next explicit flush() or publish_batch() call.
```

---

## Decision Checklist

| Question | Required Answer |
|---|---|
| Is `tenant_id` validated non-empty and normalised (lowercased/stripped) at construction? | ✅ Yes |
| Is `key=partition_key` set on every `produce()` call through a single chokepoint? | ✅ Yes |
| Is there any code path that reaches `produce()` without a tenant key? | ❌ No |
| Is topic partition count validated against active tenant count at service startup? | ✅ Yes |
| Is a custom partitioner used to eliminate murmur2 hash collision risk? | ✅ Recommended for strict isolation |
| Does the consumer verify `envelope["tenant_id"]` against its authorised tenant? | ✅ Yes |
| Is `hashlib` imported only if a custom partitioner is actually implemented? | ✅ Yes — remove dead imports |
| Is `flush` behaviour explicit and documented for both single and batch publish paths? | ✅ Yes |

---

## Key Principle Summary

> **Tenant-ID partitioning has two distinct requirements that are easy to conflate.** First: the structural guarantee that `key=tenant_id` is always set — enforced via a validated envelope type and a single producer chokepoint with no bypass. Second: the routing guarantee that two tenants never share a partition — which requires a **custom deterministic partitioner**, not merely `num_partitions >= num_tenants`. The count check is necessary but not sufficient. `num_partitions >= num_tenants` reduces collision probability under the default murmur2 hash; it does not eliminate it. For true dedicated-partition isolation, implement `deterministic_tenant_partitioner` and wire it into the producer's `partition=` argument.