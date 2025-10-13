from __future__ import annotations

from windows_shared.config import config_dir, config_path, load_launcher_config, persist_launcher_config


def test_appdata_paths_sanitized(tmp_path, monkeypatch):
    dirty = tmp_path / "\u200cمسیر بسیار طولانی" / "پیکربندی"
    monkeypatch.setenv("STUDENT_MENTOR_APP_CONFIG_DIR", str(dirty))

    config = load_launcher_config()
    persist_launcher_config(config)

    directory = config_dir()
    path = config_path()
    assert "\u200c" not in str(directory)
    assert directory.exists()
    assert path.exists()
