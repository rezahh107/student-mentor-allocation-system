"""آزمون یکپارچه برای تضمین ترتیب RateLimit → Idempotency → Auth."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from reliability.cleanup import CleanupResult
from reliability.config import (
    CleanupConfig,
    IdempotencyConfig,
    PostgresConfig,
    RateLimitConfigModel,
    RateLimitRuleModel,
    RedisConfig,
    ReliabilitySettings,
    RetentionConfig,
    TokenConfig,
)
from reliability.http_app import (
    AuthMiddleware,
    IdempotencyMiddleware,
    RateLimitMiddleware,
    create_reliability_app,
)
from reliability.logging_utils import JSONLogger
from reliability.metrics import ReliabilityMetrics

from tests.conftest import (
    clean_redis_state as sync_clean_redis_state,
    db_session as transactional_db_session,
    retry,
)


clean_redis_state = sync_clean_redis_state
db_session = transactional_db_session


class پاکسازیجعلی:
    """شبیه‌ساز سبک برای CleanupDaemon که فقط نتیجه‌ای خنثی بازمی‌گرداند."""

    def run(self) -> CleanupResult:
        return CleanupResult(removed_part_files=[], removed_links=[])


class نگهداشتجعلی:
    """جایگزین ساده برای RetentionEnforcer جهت جلوگیری از عملیات فایل واقعی."""

    def run(self, *, enforce: bool = True) -> dict[str, Any]:
        return {"dry_run": [], "enforced": [], "enforce": enforce}


class تمرینجعلی:
    """پیاده‌سازی آزمایشی برای DisasterRecoveryDrill."""

    def run(
        self,
        artifacts_root: Path,
        restore_root: Path,
        *,
        correlation_id: str,
        namespace: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return {
            "artifacts_root": str(artifacts_root),
            "restore_root": str(restore_root),
            "correlation_id": correlation_id,
            "namespace": namespace,
            "idempotency_key": idempotency_key,
        }


@retry(times=3, delay=0.2)
@pytest.mark.usefixtures("timing_control")
def test_middleware_order_contract(
    clean_redis_state,
    db_session,
    tmp_path: Path,
    clock,
) -> None:
    """احراز می‌کند که ترتیب اجرای میان‌افزارها دقیقاً RateLimit→Idempotency→Auth است."""

    db_session.execute(text("SELECT 1"))
    artifacts_root = tmp_path / "artifacts"
    backups_root = tmp_path / "backups"
    artifacts_root.mkdir(parents=True, exist_ok=True)
    backups_root.mkdir(parents=True, exist_ok=True)

    settings = ReliabilitySettings(
        redis=RedisConfig(dsn="redis://127.0.0.1:6379/15", namespace=clean_redis_state.namespace),
        postgres=PostgresConfig(
            read_write_dsn="postgresql://ci:ci@localhost:5432/ci",
            replica_dsn="postgresql://ci:ci@localhost:5432/ci",
        ),
        artifacts_root=artifacts_root,
        backups_root=backups_root,
        retention=RetentionConfig(age_days=0, max_total_bytes=0),
        cleanup=CleanupConfig(part_max_age=0, link_ttl=0),
        tokens=TokenConfig(metrics_read="metrics-ci-token"),
        rate_limit=RateLimitConfigModel(default_rule=RateLimitRuleModel(requests=5, window_seconds=1.0)),
        idempotency=IdempotencyConfig(ttl_seconds=120, storage_prefix=clean_redis_state.namespace),
    )

    metrics = ReliabilityMetrics()
    cleanup = پاکسازیجعلی()
    retention = نگهداشتجعلی()
    drill = تمرینجعلی()
    logger = JSONLogger(name="tests.reliability")
    app_clock = settings.build_clock(clock.now)

    app = create_reliability_app(
        settings=settings,
        metrics=metrics,
        retention=retention,
        cleanup=cleanup,
        drill=drill,
        logger=logger,
        clock=app_clock,
    )

    stack_order = [middleware.cls for middleware in app.user_middleware]
    assert stack_order == [RateLimitMiddleware, IdempotencyMiddleware, AuthMiddleware], (
        "ترکیب میان‌افزار با انتظار تطابق ندارد",
        [cls.__name__ for cls in stack_order],
    )

    suffix = uuid4().hex
    idem_key = clean_redis_state.key(f"idem:{suffix}")
    rate_key = clean_redis_state.key(f"ratelimit:{suffix}")
    request_id = clean_redis_state.key(f"request:{suffix}")
    headers = {
        "Authorization": "Bearer metrics-ci-token",
        "Idempotency-Key": idem_key,
        "X-RateLimit-Key": rate_key,
        "X-Request-ID": request_id,
    }

    client = TestClient(app)
    response = client.post("/cleanup/run", headers=headers)
    context = {
        "وضعیت": response.status_code,
        "بدنه": response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text,
        "سرآیند": dict(response.headers),
        "میان‌افزار": [cls.__name__ for cls in stack_order],
    }

    assert response.status_code == 200, f"پاسخ معتبر نبود: {context}"
    order_header = response.headers.get("X-Middleware-Order")
    assert order_header == "RateLimit,Idempotency,Auth", f"ترتیب ثبت‌شده نادرست است: {context}"
    body = response.json()
    assert body.get("correlation_id"), f"شناسه همبستگی خالی است: {context}"
