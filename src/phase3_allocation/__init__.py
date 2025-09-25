"""Phase 3 allocation public API."""

from .allocation_tx import (
    AllocationIdentifiers,
    AllocationRequest,
    AllocationResult,
    AllocationSequenceProvider,
    AtomicAllocator,
    PolicyEngine,
    PolicyVerdict,
    SimpleAllocationSequenceProvider,
)
from .idempotency import (
    IdempotentResult,
    derive_event_id,
    derive_idempotency_key,
    normalize_identifier,
    normalize_payload,
)
from .outbox import (
    BackoffPolicy,
    OutboxDispatcher,
    OutboxEvent,
    OutboxMessage,
    OutboxRepository,
    SystemClock,
)
from .uow import SQLAlchemyUnitOfWork, UnitOfWorkFactory

__all__ = [
    "AllocationIdentifiers",
    "AllocationRequest",
    "AllocationResult",
    "AllocationSequenceProvider",
    "AtomicAllocator",
    "PolicyEngine",
    "PolicyVerdict",
    "SimpleAllocationSequenceProvider",
    "IdempotentResult",
    "derive_event_id",
    "derive_idempotency_key",
    "normalize_identifier",
    "normalize_payload",
    "BackoffPolicy",
    "OutboxDispatcher",
    "OutboxEvent",
    "OutboxMessage",
    "OutboxRepository",
    "SystemClock",
    "SQLAlchemyUnitOfWork",
    "UnitOfWorkFactory",
]
