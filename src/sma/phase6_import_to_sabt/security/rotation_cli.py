from __future__ import annotations

import argparse
import hashlib
import json
import secrets
from dataclasses import asdict
from typing import Iterable, Sequence, TYPE_CHECKING

from sma.phase6_import_to_sabt.security.config import AccessConfigGuard, AccessSettings, SigningKeyDefinition

if TYPE_CHECKING:  # pragma: no cover - typing helper
    from sma.phase6_import_to_sabt.obs.metrics import ServiceMetrics


def _load_settings(args: argparse.Namespace) -> AccessSettings:
    guard = AccessConfigGuard()
    return guard.load(
        tokens_env=args.tokens_env,
        signing_keys_env=args.signing_keys_env,
        download_ttl_seconds=args.ttl,
    )


def _serialize_keys(keys: Iterable[SigningKeyDefinition]) -> list[dict[str, str]]:
    return [asdict(key) for key in keys]


def _derive_secret(seed: str | None, *, length: int = 48) -> str:
    if seed:
        digest = hashlib.blake2b(seed.encode("utf-8"), digest_size=32).hexdigest()
        return digest[:length]
    token = secrets.token_urlsafe(length)
    return token[:length]


def _record_event(args: argparse.Namespace, event: str) -> None:
    metrics: "ServiceMetrics | None" = getattr(args, "metrics", None)
    if metrics is not None:
        metrics.token_rotation_total.labels(event=event).inc()


def _cmd_list(args: argparse.Namespace) -> None:
    settings = _load_settings(args)
    payload = {
        "active_kid": settings.active_kid,
        "next_kid": settings.next_kid,
        "keys": _serialize_keys(settings.signing_keys),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _cmd_promote(args: argparse.Namespace) -> None:
    settings = _load_settings(args)
    updated: list[SigningKeyDefinition] = []
    promoted = False
    for key in settings.signing_keys:
        if key.kid == args.kid:
            updated.append(SigningKeyDefinition(key.kid, key.secret, "active"))
            promoted = True
        elif key.state == "active":
            updated.append(SigningKeyDefinition(key.kid, key.secret, "retired"))
        else:
            updated.append(SigningKeyDefinition(key.kid, key.secret, key.state))
    if not promoted:
        raise SystemExit("kid not found")
    payload = {
        "active_kid": args.kid,
        "next_kid": None,
        "keys": _serialize_keys(updated),
        "event": "promote",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    _record_event(args, "promote")


def _cmd_generate(args: argparse.Namespace) -> None:
    settings = _load_settings(args)
    existing = {key.kid for key in settings.signing_keys}
    if args.kid in existing:
        raise SystemExit("kid already exists")
    generated = SigningKeyDefinition(args.kid, _derive_secret(args.seed), "next")
    rotated: list[SigningKeyDefinition] = []
    for key in settings.signing_keys:
        state = "retired" if key.state == "next" else key.state
        rotated.append(SigningKeyDefinition(key.kid, key.secret, state))
    rotated.append(generated)
    payload = {
        "active_kid": settings.active_kid,
        "next_kid": args.kid,
        "keys": _serialize_keys(rotated),
        "event": "generate",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    _record_event(args, "generate")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dual-key rotation helper")
    parser.add_argument("--tokens-env", default="TOKENS")
    parser.add_argument("--signing-keys-env", default="DOWNLOAD_SIGNING_KEYS")
    parser.add_argument("--ttl", type=int, default=900)
    sub = parser.add_subparsers(dest="command", required=True)

    list_parser = sub.add_parser("list", help="List current key metadata")
    list_parser.set_defaults(func=_cmd_list)

    promote_parser = sub.add_parser("promote", help="Promote a key to active")
    promote_parser.add_argument("--kid", required=True)
    promote_parser.set_defaults(func=_cmd_promote)

    generate_parser = sub.add_parser("generate-next", help="Generate the next rotation key")
    generate_parser.add_argument("--kid", required=True)
    generate_parser.add_argument("--seed")
    generate_parser.set_defaults(func=_cmd_generate)

    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


__all__ = ["build_parser", "main"]

