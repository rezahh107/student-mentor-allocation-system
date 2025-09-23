from __future__ import annotations

"""ماژول امنیتی برای محافظت از داده‌ها و عملیات.

Security module providing hardening helpers for data handling, logging and
rate limiting across bilingual (FA/EN) surfaces.
"""

import functools
import hashlib
import logging
import re
import secrets
import time
from pathlib import Path
from typing import Any, Callable, Deque, Dict, Iterable, List, Optional, Tuple
from collections import deque

__all__ = [
    "SecurityViolationError",
    "RateLimiter",
    "sanitize_input",
    "validate_path",
    "mask_pii",
    "secure_hash",
    "secure_logging",
    "check_persian_injection",
    "SecurityMonitor",
]


class SecurityViolationError(Exception):
    """Raised when a security policy is violated."""


class RateLimiter:
    """Simple in-memory rate limiter to prevent burst attacks."""

    def __init__(self, max_calls: int, time_window: int) -> None:
        self.max_calls = max_calls
        self.time_window = time_window
        self.calls: Dict[str, Deque[float]] = {}

    def check_limit(self, key: str, current_time: float) -> bool:
        """Return True if the invocation is within limits for the key."""

        window: Deque[float] = self.calls.setdefault(key, deque())
        while window and current_time - window[0] > self.time_window:
            window.popleft()
        if len(window) >= self.max_calls:
            return False
        window.append(current_time)
        return True


_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
_RTL_OVERRIDE = re.compile(r"[\u202E\u202D\u202C\u202B\u202A]")
_SCRIPT_TAG = re.compile(r"<script[^>]*?>.*?</script>", flags=re.IGNORECASE | re.DOTALL)
_HTML_TAGS = re.compile(r"<[^>]*>")


def sanitize_input(text: str) -> str:
    """Strip control characters, RTL overrides, and HTML/script tags."""

    if text is None:
        return ""
    cleaned = _CONTROL_CHARS.sub("", str(text))
    cleaned = _RTL_OVERRIDE.sub("", cleaned)
    cleaned = _SCRIPT_TAG.sub("", cleaned)
    cleaned = _HTML_TAGS.sub("", cleaned)
    return cleaned


_WINDOWS_DRIVE = re.compile(r"^[a-zA-Z]:\\")


def validate_path(path: str) -> bool:
    """Return True when the provided path is safe for relative usage."""

    if not path:
        return False
    if ".." in path or "~" in path:
        return False
    if path.startswith("/"):
        return False
    if _WINDOWS_DRIVE.match(path):
        return False
    return True


_NATIONAL_ID_PATTERN = re.compile(r"(?<!\d)(\d{3})(\d{6})(\d)(?!\d)")
_PHONE_PATTERN = re.compile(r"(?<!\d)(09\d{2})(\d{5})(\d{2})(?!\d)")
_EMAIL_PATTERN = re.compile(
    r"(?i)(?<![\w._%+-])([a-z0-9])[a-z0-9._%+-]*@([a-z0-9.-]+\.[a-z]{2,})(?![a-z0-9._%+-])"
)



def _mask_national(match: re.Match[str]) -> str:
    return f"{match.group(1)}*******{match.group(3)}"


def _mask_phone(match: re.Match[str]) -> str:
    return f"{match.group(1)}*****{match.group(3)}"


def _mask_email(match: re.Match[str]) -> str:
    return f"{match.group(1)}***@{match.group(2)}"


def mask_pii(text: str) -> str:
    """Mask common PII tokens (national code, phone numbers, email)."""

    if text is None:
        return ""
    masked = _NATIONAL_ID_PATTERN.sub(_mask_national, str(text))
    masked = _PHONE_PATTERN.sub(_mask_phone, masked)
    masked = _EMAIL_PATTERN.sub(_mask_email, masked)
    return masked


def secure_hash(data: str) -> str:
    """Return a salted BLAKE2b hash of the provided data."""

    salt = secrets.token_hex(16)
    digest = hashlib.blake2b((data + salt).encode("utf-8"), digest_size=32)
    return digest.hexdigest()


SanitizedArgs = Tuple[Tuple[Any, ...], Dict[str, Any]]


def _mask_args(args: Iterable[Any]) -> List[str]:
    return [mask_pii(str(arg)) for arg in args]


def _mask_kwargs(kwargs: Dict[str, Any]) -> Dict[str, str]:
    return {key: mask_pii(str(value)) for key, value in kwargs.items()}


def secure_logging(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator masking arguments when logging success or errors."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            logging.error("Error in %s: %s", func.__name__, type(exc).__name__)
            raise
        masked_args = _mask_args(args)
        masked_kwargs = _mask_kwargs(kwargs)
        logging.info(
            "Function %s executed successfully with args=%s kwargs=%s",
            func.__name__,
            masked_args,
            masked_kwargs,
        )
        return result

    return wrapper


_SUSPICIOUS_PATTERNS = [
    r"<.*?>",
    r"javascript:",
    r"eval\s*\(",
    r"document\.",
    r"window\.",
    r"alert\s*\(",
    r"\bSELECT\b.*\bFROM\b",
    r"\bINSERT\b.*\bINTO\b",
    r"\bDELETE\b.*\bFROM\b",
    r"\bDROP\b.*\bTABLE\b",
    r"\bUPDATE\b.*\bSET\b",
    r"\bUNION\b.*\bSELECT\b",
    r"[\u202E\u202D\u202C\u202B\u202A]",
]


def check_persian_injection(text: str) -> bool:
    """Detect code injection attempts within Persian text."""

    if not text:
        return True
    for pattern in _SUSPICIOUS_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return False
    return True


class SecurityMonitor:
    """Collects and summarises security related events."""

    def __init__(self, log_file: Optional[str] = None) -> None:
        self.events: List[Dict[str, Any]] = []
        self.log_file = log_file
        self.rate_limiter = RateLimiter(max_calls=100, time_window=60)

    def log_event(
        self,
        event_type: str,
        details: Dict[str, Any],
        severity: str = "info",
        source: str = "unknown",
    ) -> None:
        masked_details = {key: mask_pii(str(value)) for key, value in details.items()}
        timestamp = time.time()
        event = {
            "type": event_type,
            "details": masked_details,
            "severity": severity,
            "source": source,
            "timestamp": timestamp,
        }
        self.events.append(event)
        if self.log_file:
            Path(self.log_file).parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_file, "a", encoding="utf-8") as handle:
                handle.write(f"{event}\n")

    def get_security_metrics(self) -> Dict[str, Any]:
        if not self.events:
            return {
                "total_events": 0,
                "severity_counts": {},
                "top_event_types": [],
                "security_score": 100,
            }

        severity_counts: Dict[str, int] = {
            "info": 0,
            "warning": 0,
            "error": 0,
            "critical": 0,
        }
        event_type_counts: Dict[str, int] = {}

        for event in self.events:
            severity = event.get("severity", "info")
            if severity in severity_counts:
                severity_counts[severity] += 1
            event_type = event.get("type", "unknown")
            event_type_counts[event_type] = event_type_counts.get(event_type, 0) + 1

        top_events = sorted(
            event_type_counts.items(), key=lambda item: item[1], reverse=True
        )[:5]

        security_score = 100
        security_score -= severity_counts["critical"] * 10
        security_score -= severity_counts["error"] * 5
        security_score -= severity_counts["warning"] * 2
        security_score = max(0, security_score)

        return {
            "total_events": len(self.events),
            "severity_counts": severity_counts,
            "top_event_types": top_events,
            "security_score": security_score,
        }


# Optional helper APIs -----------------------------------------------------

def ensure_secure_path(path: str) -> Path:
    """Validate a path and return an absolute safe path or raise error."""

    if not validate_path(path):
        raise SecurityViolationError("Unsafe path provided")
    return Path("uploads").joinpath(path)
