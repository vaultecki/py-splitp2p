from pathlib import Path

from config_manager import ConfigManager


def test_config_manager_creates_directory_and_starts_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cfg = ConfigManager("TestApp", "config.json")
    assert cfg.config_path.exists()
    assert cfg.data == {}


def test_config_manager_set_save_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cfg = ConfigManager("TestApp", "config.json")
    cfg.set("key", "value")
    cfg.save()

    reloaded = ConfigManager("TestApp", "config.json")
    assert reloaded.get("key") == "value"


def test_config_manager_get_default_and_has_key(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cfg = ConfigManager("TestApp", "config.json")
    assert cfg.get("missing", "fallback") == "fallback"
    assert cfg.has_key("missing") is False
    cfg.set("present", 1)
    assert cfg.has_key("present") is True


def test_config_manager_delete():
    from config_manager import ConfigManager as CM

    cfg = CM.__new__(CM)
    cfg.data = {"a": 1}
    assert cfg.delete("a") is True
    assert cfg.delete("a") is False


def test_config_manager_invalid_json_starts_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    config_dir = tmp_path / ".config" / "TestApp"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text("{not valid json")

    cfg = ConfigManager("TestApp", "config.json")
    assert cfg.data == {}
