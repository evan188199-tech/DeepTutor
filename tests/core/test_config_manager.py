import os
from pathlib import Path

import pytest
import yaml

from deeptutor.utils.config_manager import ConfigManager


def write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


@pytest.fixture(autouse=True)
def reset_config_manager_singleton():
    ConfigManager.reset_for_tests()
    yield
    ConfigManager.reset_for_tests()


def test_atomic_save_and_deep_merge(tmp_path: Path):
    project = tmp_path
    cfg_path = project / "data" / "user" / "settings" / "main.yaml"
    base_cfg = {
        "llm": {"model": "Pro/Flash", "provider": "openai"},
        "paths": {
            "user_data_dir": "./data/user",
            "knowledge_bases_dir": "./data/knowledge_bases",
            "user_log_dir": "./data/user/logs",
        },
    }
    write_yaml(cfg_path, base_cfg)

    cm = ConfigManager(project_root=project)

    loaded = cm.load_config(force_reload=True)
    assert loaded["llm"]["model"] == "Pro/Flash"

    # Deep merge update
    assert cm.save_config({"llm": {"model": "Other"}, "features": {"enable_solve": True}})

    updated = cm.load_config(force_reload=True)
    assert updated["llm"]["model"] == "Other"
    assert updated["llm"]["provider"] == "openai"
    assert updated["features"]["enable_solve"] is True


def test_env_info_reads_project_model_catalog(tmp_path: Path):
    project = tmp_path

    # Minimal valid config for schema
    settings_dir = project / "data" / "user" / "settings"
    cfg_path = settings_dir / "main.yaml"
    base_cfg = {
        "llm": {"model": "Pro/Flash", "provider": "openai"},
        "paths": {
            "user_data_dir": "./data/user",
            "knowledge_bases_dir": "./data/knowledge_bases",
            "user_log_dir": "./data/user/logs",
        },
    }
    write_yaml(cfg_path, base_cfg)
    (settings_dir / "model_catalog.json").write_text(
        """
{
  "version": 1,
  "services": {
    "llm": {
      "active_profile_id": "llm-p",
      "active_model_id": "llm-m",
      "profiles": [
        {
          "id": "llm-p",
          "name": "LLM",
          "binding": "openai",
          "base_url": "https://example.test/v1",
          "api_key": "sk-test",
          "api_version": "",
          "extra_headers": {},
          "models": [{"id": "llm-m", "name": "Base", "model": "Base"}]
        }
      ]
    },
    "embedding": {"active_profile_id": null, "active_model_id": null, "profiles": []},
    "search": {"active_profile_id": null, "profiles": []}
  }
}
""",
        encoding="utf-8",
    )

    cm = ConfigManager(project_root=project)
    env = cm.get_env_info()
    assert env["model"] == "Base"


def test_missing_config_file_loads_empty(tmp_path: Path):
    cm = ConfigManager(project_root=tmp_path)
    assert cm.load_config() == {}
    assert cm._read_yaml() == {}


def test_singleton_reuses_instance_until_reset(tmp_path: Path):
    first = ConfigManager(project_root=tmp_path)
    second = ConfigManager(project_root=tmp_path / "elsewhere")
    assert second is first
    ConfigManager.reset_for_tests()
    assert ConfigManager(project_root=tmp_path) is not first


def test_save_config_creates_missing_settings_dir(tmp_path: Path):
    cm = ConfigManager(project_root=tmp_path)
    assert cm.save_config({"nested": {"key": "value"}})
    config_path = tmp_path / "data" / "user" / "settings" / "main.yaml"
    assert yaml.safe_load(config_path.read_text(encoding="utf-8")) == {"nested": {"key": "value"}}


def test_validate_required_env_reports_missing_llm_keys(tmp_path: Path):
    """Without an active LLM profile the LLM_* keys are empty; ports have defaults."""
    cm = ConfigManager(project_root=tmp_path)
    result = cm.validate_required_env(["LLM_MODEL", "LLM_API_KEY", "BACKEND_PORT"])
    assert result["missing"] == ["LLM_MODEL", "LLM_API_KEY"]


def test_save_failure_leaves_no_partial_file(tmp_path: Path, monkeypatch):
    cfg_path = tmp_path / "data" / "user" / "settings" / "main.yaml"
    write_yaml(cfg_path, {"original": True})
    cm = ConfigManager(project_root=tmp_path)
    cm.load_config(force_reload=True)

    def failing_replace(src, dst, **kwargs):
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", failing_replace)

    with pytest.raises(OSError):
        cm.save_config({"new": True})

    assert yaml.safe_load(cfg_path.read_text(encoding="utf-8")) == {"original": True}
    assert not list((tmp_path / "data" / "user" / "settings").glob("main.yaml.*"))
