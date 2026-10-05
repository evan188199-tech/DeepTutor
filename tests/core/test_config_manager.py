import os
from pathlib import Path
import threading

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


def settings_dir(project: Path) -> Path:
    return project / "data" / "user" / "settings"


def tmp_residue(project: Path) -> list[Path]:
    return sorted(settings_dir(project).glob("main.yaml.*"))


def read_main_yaml(project: Path) -> dict:
    return yaml.safe_load((settings_dir(project) / "main.yaml").read_text(encoding="utf-8"))


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


def test_save_config_success_leaves_no_tmp_residue(tmp_path: Path):
    project = tmp_path
    cm = ConfigManager(project_root=project)

    assert cm.save_config({"llm": {"model": "Pro/Flash"}}) is True

    assert read_main_yaml(project) == {"llm": {"model": "Pro/Flash"}}
    assert tmp_residue(project) == []


def test_save_config_replace_failure_keeps_previous_file(tmp_path: Path, monkeypatch):
    project = tmp_path
    cm = ConfigManager(project_root=project)
    assert cm.save_config({"llm": {"model": "keep-me"}}) is True

    def fail_replace(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError):
        cm.save_config({"llm": {"model": "never-persisted"}})

    assert read_main_yaml(project) == {"llm": {"model": "keep-me"}}
    assert tmp_residue(project) == []


def test_save_config_tmp_remove_failure_swallowed_leaves_residue(tmp_path: Path, monkeypatch):
    project = tmp_path
    cm = ConfigManager(project_root=project)
    assert cm.save_config({"llm": {"model": "keep-me"}}) is True

    def fail_replace(src, dst):
        raise OSError("replace failed")

    def fail_remove(path):
        raise OSError("remove failed")

    monkeypatch.setattr(os, "replace", fail_replace)
    monkeypatch.setattr(os, "remove", fail_remove)

    with pytest.raises(OSError):
        cm.save_config({"llm": {"model": "never-persisted"}})

    assert read_main_yaml(project) == {"llm": {"model": "keep-me"}}
    residue = tmp_residue(project)
    assert len(residue) == 1
    for path in residue:
        path.unlink()
    assert tmp_residue(project) == []


def test_load_config_corrupted_file_raises_and_recovers(tmp_path: Path):
    project = tmp_path
    cfg_path = settings_dir(project) / "main.yaml"
    write_yaml(cfg_path, {"llm": {"model": "Pro/Flash"}})
    cm = ConfigManager(project_root=project)
    assert cm.load_config(force_reload=True) == {"llm": {"model": "Pro/Flash"}}

    cfg_path.write_text("{ llm: { model: broken", encoding="utf-8")

    with pytest.raises(yaml.YAMLError):
        cm.load_config(force_reload=True)

    write_yaml(cfg_path, {"llm": {"model": "recovered"}})
    assert cm.load_config(force_reload=True) == {"llm": {"model": "recovered"}}


def test_load_config_empty_file_falls_back_to_empty_dict(tmp_path: Path):
    project = tmp_path
    cfg_path = settings_dir(project) / "main.yaml"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text("", encoding="utf-8")

    cm = ConfigManager(project_root=project)

    assert cm.load_config(force_reload=True) == {}


def test_concurrent_saves_merge_without_overwriting_each_other(tmp_path: Path):
    project = tmp_path
    cm = ConfigManager(project_root=project)
    thread_count = 8
    barrier = threading.Barrier(thread_count)
    errors: list[Exception] = []

    def save_own_key(idx: int) -> None:
        try:
            barrier.wait(timeout=30)
            assert cm.save_config({"features": {f"thread_{idx}": idx}}) is True
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=save_own_key, args=(idx,)) for idx in range(thread_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert errors == []
    assert not any(thread.is_alive() for thread in threads)

    final = cm.load_config(force_reload=True)
    assert final["features"] == {f"thread_{i}": i for i in range(thread_count)}
    assert read_main_yaml(project) == final
    assert tmp_residue(project) == []


def test_default_values_merge_across_partial_saves(tmp_path: Path):
    project = tmp_path
    cm = ConfigManager(project_root=project)

    defaults = {
        "llm": {"model": "Pro/Flash", "provider": "openai"},
        "paths": {"user_data_dir": "./data/user", "user_log_dir": "./data/user/logs"},
    }
    assert cm.save_config(defaults) is True

    assert cm.save_config({"llm": {"model": "Other"}}) is True
    assert cm.save_config({"paths": {"knowledge_bases_dir": "./data/knowledge_bases"}}) is True

    final = cm.load_config(force_reload=True)
    assert final == {
        "llm": {"model": "Other", "provider": "openai"},
        "paths": {
            "user_data_dir": "./data/user",
            "user_log_dir": "./data/user/logs",
            "knowledge_bases_dir": "./data/knowledge_bases",
        },
    }
