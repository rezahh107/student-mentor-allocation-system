"""Domain enumerations and normalization maps for student data."""
from __future__ import annotations

from typing import Dict

from sma.shared.counter_rules import COUNTER_PREFIX_MAP

COUNTER_PREFIX: Dict[int, str] = dict(COUNTER_PREFIX_MAP)
"""Mapping gender counters to their associated prefixes.

The mapping is exposed for downstream systems that derive counters based on
normalized gender identifiers. Keys are normalized gender values where ``1``
represents مرد (male) and ``0`` represents زن (female).
"""

GENDER_NORMALIZATION_MAP: Dict[str, int] = {
    "0": 0,
    "1": 1,
    "female": 0,
    "f": 0,
    "girl": 0,
    "زن": 0,
    "خانم": 0,
    "دختر": 0,
    "خانوم": 0,
    "male": 1,
    "m": 1,
    "boy": 1,
    "مرد": 1,
    "آقا": 1,
    "پسر": 1,
    "اناث": 0,
    "ذكور": 1,
}
"""Normalized mappings for gender values.

Values are keyed by normalized (NFKC + lowercase + stripped) representations of
possible raw inputs.
"""

REG_STATUS_NORMALIZATION_MAP: Dict[str, int] = {
    "0": 0,
    "1": 1,
    "3": 3,
    "pending": 0,
    "ثبت نام ناقص": 0,
    "incomplete": 0,
    "در انتظار": 0,
    "منتظر": 0,
    "active": 1,
    "فعال": 1,
    "confirmed": 1,
    "تایید شده": 1,
    "approved": 1,
    "hakmat": 3,
    "حکمت": 3,
}
"""Mappings for registration status normalization to ``{0, 1, 3}``.

The free-form value "Hakmat" is explicitly mapped to ``3`` as required.
"""

REG_CENTER_NORMALIZATION_MAP: Dict[str, int] = {
    "0": 0,
    "1": 1,
    "2": 2,
}
"""Mappings for registration center identifiers constrained to ``{0, 1, 2}``."""
