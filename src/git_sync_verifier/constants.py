"""Constants for git sync verifier."""

from __future__ import annotations

import re


REMOTE_REGEX = re.compile(
    r"^https://github\.com/rezahh107/student-mentor-allocation-system(\.git)?$"
)

BRANCH_REGEX = re.compile(r"^[A-Za-z0-9._/\-]+$")
