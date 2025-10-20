"""Outbox dispatcher with monotonic-aware scheduling."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from sqlalchemy.orm import Session

from .backoff import BackoffPolicy
from .clock import Clock
from .models import OutboxMessage
from .repository import OutboxRepository


logger = logging.getLogger(__name__)


class Publisher(Protocol):
    """Transport-agnostic publisher contract."""

    def publish(self, *, event_type: str, payload: dict, headers: dict[str, str]) -> None:
        """Publish the serialized payload downstream."""


@dataclass(slots=True)
class OutboxDispatcher:
    """Dispatcher that publishes pending outbox events in order."""

    session: Session
    publisher: Publisher
    clock: Clock
    backoff: BackoffPolicy = field(default_factory=BackoffPolicy)
    batch_size: int = 50
    status_hook: Callable[[str, str, dict[str, Any]], None] | None = None

    def dispatch_once(self) -> int:
        repo = OutboxRepository(self.session)
        messages = repo.list_due_for_update(clock=self.clock, limit=self.batch_size)
        dispatched = 0
        for message in messages:
            model = message.model
            current_wall = self.clock.now()
            headers = {
                "x-event-id": model.event_id,
                "x-aggregate-id": model.aggregate_id,
                "x-idempotency-key": self._extract_idempotency_key(model.payload_json),
            }
            try:
                payload = json.loads(model.payload_json)
                self.publisher.publish(
                    event_type=model.event_type,
                    payload=payload,
                    headers=headers,
                )
            except Exception as exc:  # pylint: disable=broad-except
                self.schedule_next(message=message, exc=exc)
                continue

            message.status = "SENT"
            model.published_at = current_wall
            model.last_error = None
            logger.info(
                "رویداد با موفقیت ارسال شد",
                extra={
                    "event_id": model.event_id,
                    "aggregate_id": model.aggregate_id,
                    "کد": "SENT",
                },
            )
            self._notify(event_id=model.event_id, status="SENT", extra={"aggregate_id": model.aggregate_id})
            dispatched += 1

        self.session.commit()
        return dispatched

    def schedule_next(self, *, message: OutboxMessage, exc: Exception) -> None:
        """Update the message for a retry using monotonic timing."""

        model = message.model
        model.retry_count += 1
        if model.retry_count > self.backoff.max_retries:
            message.status = "FAILED"
            model.last_error = f"MAX_RETRIES_REACHED:{exc}"[:256]
            logger.error(
                "MAX_RETRIES_REACHED: انتشار رویداد پس از حداکثر تلاش متوقف شد",
                extra={
                    "event_id": model.event_id,
                    "retry_count": model.retry_count,
                    "کد": "MAX_RETRIES_REACHED",
                },
            )
            self._notify(
                event_id=model.event_id,
                status="FAILED",
                extra={"retry_count": model.retry_count},
            )
            return

        next_available_at, delay, skew_seconds, remaining = message.compute_next_available_at(
            clock=self.clock,
            backoff=self.backoff,
        )

        model.available_at = next_available_at
        model.last_error = f"RETRYING:{exc}"[:256]
        if delay >= self.backoff.cap_seconds:
            backoff_code = "BACKOFF_CAPPED"
        else:
            backoff_code = "RETRYING"
        logger.warning(
            "ارسال رویداد ناموفق بود؛ تلاش مجدد برنامه‌ریزی شد",
            extra={
                "event_id": model.event_id,
                "retry_count": model.retry_count,
                "تاخیر": delay,
                "کد": backoff_code,
                "انحراف": skew_seconds,
                "تاخیر_مؤثر": remaining,
            },
        )
        if abs(skew_seconds) >= 1e-3:
            logger.info(
                "اختلاف ساعت با مرجع مونو تونیک جبران شد",
                extra={
                    "event_id": model.event_id,
                    "retry_count": model.retry_count,
                    "انحراف": skew_seconds,
                    "کد": "MONO_SKEW_HANDLED",
                },
            )
        self._notify(
            event_id=model.event_id,
            status="PENDING",
            extra={
                "retry_count": model.retry_count,
                "delay": remaining,
                "code": backoff_code,
            },
        )

    def run_loop(self, *, once: bool = False, sleep: float = 1.0) -> None:
        import time

        while True:
            sent = self.dispatch_once()
            if once:
                return
            if sent == 0:
                time.sleep(sleep)

    @staticmethod
    def _extract_idempotency_key(payload_json: str) -> str:
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError:  # pragma: no cover - defensive guard
            return ""
        return str(payload.get("idempotency_key", ""))

    def _notify(self, *, event_id: str, status: str, extra: dict[str, Any]) -> None:
        if self.status_hook is None:
            return
        try:
            self.status_hook(event_id, status, extra)
        except Exception:  # pragma: no cover - defensive log guard
            logger.debug("وضعیت اوتباکس به شنونده GUI ارسال نشد", extra={"event_id": event_id})
