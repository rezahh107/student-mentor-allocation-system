"""JSON schema validation helpers for Tailored v2.4 artifacts."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Tuple, Union

from jsonschema import Draft202012Validator, exceptions as jsonschema_exceptions

from .bootstrap import (
    SCHEMA_DIR,
    BootstrapError,
    PERSIAN_SCHEMA_ERROR,
    bilingual_message,
)

Pathish = Union[str, os.PathLike[str]]


@lru_cache(maxsize=None)
def _load_schema(name: str) -> Mapping[str, Any]:
    schema_path = SCHEMA_DIR / name
    if not schema_path.is_file():
        raise BootstrapError(
            bilingual_message(
                PERSIAN_SCHEMA_ERROR,
                f"Schema missing: {schema_path}",
            )
        )
    with schema_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_and_validate(path: Path, schema_name: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:  # pragma: no cover - filesystem errors
        raise BootstrapError(
            bilingual_message(
                PERSIAN_SCHEMA_ERROR,
                f"Unable to read artifact {path}: {exc}",
            )
        ) from exc
    except json.JSONDecodeError as exc:
        raise BootstrapError(
            bilingual_message(
                PERSIAN_SCHEMA_ERROR,
                f"Invalid JSON payload in {path}: {exc}",
            )
        ) from exc

    schema = _load_schema(schema_name)
    try:
        Draft202012Validator(schema).validate(payload)
    except jsonschema_exceptions.ValidationError as exc:
        raise BootstrapError(
            bilingual_message(
                PERSIAN_SCHEMA_ERROR,
                f"Schema validation error for {path}: {exc.message}",
            )
        ) from exc

    return payload


def validate_pytest_json(path: Pathish) -> Mapping[str, Any]:
    """Load and validate a pytest JSON report."""

    return _load_and_validate(Path(path), "pytest.schema.json")


def validate_strict_score(path: Pathish) -> Mapping[str, Any]:
    """Load and validate a strict score JSON artifact."""

    return _load_and_validate(Path(path), "strict_score.schema.json")


__all__: Tuple[str, ...] = ("validate_pytest_json", "validate_strict_score")
