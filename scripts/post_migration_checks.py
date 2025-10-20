from __future__ import annotations

import sys
from pathlib import Path
from typing import List

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sma.core.logging_config import setup_logging

setup_logging()

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from sma.infrastructure.persistence.models import Base, CounterSequenceModel, StudentModel
from sma.phase2_counter_service.validation import COUNTER_PATTERN, COUNTER_PREFIX, COUNTER_MAX_SEQ


EXPECTED_PATTERN = r"^\d{2}(357|373)\d{4}$"


def _build_engine() -> Engine:
    return create_engine("sqlite+pysqlite:///:memory:", future=True)


def run_checks() -> List[str]:
    issues: List[str] = []
    engine = _build_engine()
    Base.metadata.create_all(engine)

    counter_col = StudentModel.__table__.c["شمارنده"]
    if not getattr(counter_col, "unique", False):
        issues.append("Student counter column must be UNIQUE")
    if getattr(counter_col.type, "length", None) != 9:
        issues.append("Student counter column must be length 9")

    if COUNTER_PATTERN.pattern != EXPECTED_PATTERN:
        issues.append("Counter regex drifted from specification")
    if COUNTER_PREFIX != {0: "373", 1: "357"}:
        issues.append("Gender prefix mapping drifted from SSOT")
    if COUNTER_MAX_SEQ != 9999:
        issues.append("Sequence upper bound must remain 9999")

    seq_col = CounterSequenceModel.__table__.c["آخرین_عدد"]
    python_type = getattr(seq_col.type, "python_type", int)
    if python_type is not int:
        issues.append("Sequence column must be integer")

    return issues


def main() -> int:
    issues = run_checks()
    if issues:
        for issue in issues:
            print(f"❌ {issue}")
        return 1
    print("✅ post_migration_checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
