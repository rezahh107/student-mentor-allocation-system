from __future__ import annotations

import pytest

from windows_launcher.launcher import LauncherError, SingleInstanceLock


def test_single_instance_lock(tmp_path):
    lock_file = tmp_path / "locks" / "launcher.lock"
    primary = SingleInstanceLock(lock_file)
    secondary = SingleInstanceLock(lock_file)

    with primary:
        with pytest.raises(LauncherError) as excinfo:
            with secondary:
                pass
        assert excinfo.value.code == "ALREADY_RUNNING"

    with secondary:  # lock is released after exiting the first context
        pass
