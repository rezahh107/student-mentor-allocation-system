from sma.phase6_import_to_sabt.security.rbac import (
    AuthenticatedActor,
    AuthorizationError,
    enforce_center_scope,
)


def test_manager_scope_denied_outside_center() -> None:
    actor = AuthenticatedActor(
        token_fingerprint="abc123",
        role="MANAGER",
        center_scope=101,
        metrics_only=False,
    )

    try:
        enforce_center_scope(actor, center=202)
    except AuthorizationError as exc:
        assert exc.message_fa == "دسترسی شما برای این مرکز مجاز نیست."
        assert exc.reason == "scope_denied"
    else:  # pragma: no cover - defensive
        raise AssertionError("expected AuthorizationError for out-of-scope center")
