from __future__ import annotations


def test_app_mode_reads_config_path(monkeypatch, tmp_path) -> None:
    from src.agents.answer import settings

    config_path = tmp_path / "config.stack.yaml"
    config_path.write_text("mode: light\n", encoding="utf-8")
    monkeypatch.setattr(settings, "CONFIG_PATH", config_path)
    settings._yaml_config.cache_clear()

    try:
        assert settings.app_mode() == "light"
    finally:
        settings._yaml_config.cache_clear()
