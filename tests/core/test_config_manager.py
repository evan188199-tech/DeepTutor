import os
from pathlib import Path

import pytest
import yaml

from deeptutor.services import file_io
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


@pytest.mark.skipif(not hasattr(os, "O_DIRECTORY"), reason="platform without os.O_DIRECTORY")
def test_save_config_fsyncs_settings_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    project = tmp_path
    settings_dir = project / "data" / "user" / "settings"
    write_yaml(settings_dir / "main.yaml", {"llm": {"model": "A", "provider": "openai"}})

    synced_dirs = []
    real_open = os.open

    def spy_open(path: str | os.PathLike[str], flags: int, *args: int, **kwargs: int) -> int:
        if flags & os.O_DIRECTORY:
            synced_dirs.append(Path(path))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(file_io.os, "open", spy_open)

    cm = ConfigManager(project_root=project)

    assert cm.save_config({"llm": {"model": "B"}})

    assert synced_dirs == [settings_dir]


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
