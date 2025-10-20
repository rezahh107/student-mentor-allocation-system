from __future__ import annotations

import pytest

from sma.phase7_release.versioning import resolve_build_version


@pytest.fixture
def clean_state():
    yield


def test_semver_from_tag_or_sha(clean_state):
    sha = "ABCDEF1234567890"
    version = resolve_build_version("v1.2.3", sha)
    assert version.startswith("1.2.3")
    assert version.split("+")[1].endswith(sha.lower()[:12])

    fallback_sha = "deadbeefdeadbeef"
    fallback = resolve_build_version(None, fallback_sha)
    assert fallback == f"0.0.0+{fallback_sha[:12]}"

    with pytest.raises(ValueError):
        resolve_build_version("not-a-tag", "deadbeef")
