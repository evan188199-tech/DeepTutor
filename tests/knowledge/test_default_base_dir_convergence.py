"""Regression tests for runtime-home convergence of default KB/research paths.

The default knowledge-base root, the research output fallbacks, and the KB
manager used by book health checks must derive through ``PathService`` so they
follow ``DEEPTUTOR_HOME`` instead of the process CWD, while keeping the
historical default (``<cwd>/data/...``) when no runtime home is set.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

from deeptutor.services.path_service import PathService

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _reset_path_service():
    yield
    PathService.reset_instance()


def _runtime_home(monkeypatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv("DEEPTUTOR_HOME", str(home))
    monkeypatch.chdir(elsewhere)
    PathService.reset_instance()
    return home


def test_manager_default_follows_runtime_home(monkeypatch, tmp_path: Path) -> None:
    from deeptutor.knowledge.manager import KnowledgeBaseManager

    home = _runtime_home(monkeypatch, tmp_path)

    manager = KnowledgeBaseManager()

    assert manager.base_dir == (home / "data" / "knowledge_bases").resolve()
    assert manager.base_dir.is_dir()
    assert not (Path.cwd() / "data").exists()


def test_manager_default_keeps_cwd_semantics(monkeypatch, tmp_path: Path) -> None:
    from deeptutor.knowledge.manager import KnowledgeBaseManager

    monkeypatch.delenv("DEEPTUTOR_HOME", raising=False)
    monkeypatch.chdir(tmp_path)
    PathService.reset_instance()

    manager = KnowledgeBaseManager()

    assert manager.base_dir == (tmp_path / "data" / "knowledge_bases").resolve()


def test_manager_explicit_base_dir_wins(monkeypatch, tmp_path: Path) -> None:
    from deeptutor.knowledge.manager import KnowledgeBaseManager

    _runtime_home(monkeypatch, tmp_path)
    explicit = tmp_path / "explicit-kbs"
    explicit.mkdir()

    for value in (str(explicit), explicit):
        manager = KnowledgeBaseManager(base_dir=value)
        assert manager.base_dir == explicit


def test_initializer_default_follows_runtime_home(monkeypatch, tmp_path: Path) -> None:
    from deeptutor.knowledge.initializer import KnowledgeBaseInitializer

    home = _runtime_home(monkeypatch, tmp_path)

    initializer = KnowledgeBaseInitializer(kb_name="kb")

    assert initializer.base_dir == (home / "data" / "knowledge_bases").resolve()


def test_document_adder_default_follows_runtime_home(monkeypatch, tmp_path: Path) -> None:
    from deeptutor.knowledge.add_documents import DocumentAdder

    home = _runtime_home(monkeypatch, tmp_path)
    kb_dir = (home / "data" / "knowledge_bases" / "kb").resolve()
    kb_dir.mkdir(parents=True)

    adder = DocumentAdder(kb_name="kb")

    assert adder.base_dir == (home / "data" / "knowledge_bases").resolve()
    assert adder.kb_dir == kb_dir


def test_default_base_dir_constant_follows_env(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    code = "from deeptutor.knowledge.add_documents import DEFAULT_BASE_DIR; print(DEFAULT_BASE_DIR)"
    env = {**os.environ, "DEEPTUTOR_HOME": str(home), "PYTHONPATH": str(REPO_ROOT)}

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=elsewhere,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str((home / "data" / "knowledge_bases").resolve())


def test_research_config_fallbacks_follow_runtime_home(monkeypatch, tmp_path: Path) -> None:
    from deeptutor.agents.research.request_config import (
        build_research_runtime_config,
        validate_research_request_config,
    )

    home = _runtime_home(monkeypatch, tmp_path)
    request = validate_research_request_config({"mode": "notes", "depth": "quick"})

    runtime_config = build_research_runtime_config(
        base_config={}, request_config=request, kb_name=None
    )

    system = runtime_config["system"]
    assert system["output_base_dir"] == str(
        (home / "data" / "user" / "workspace" / "chat" / "deep_research").resolve()
    )
    assert system["reports_dir"] == str(
        (home / "data" / "user" / "workspace" / "chat" / "deep_research" / "reports").resolve()
    )


def test_research_config_injected_paths_still_win(monkeypatch, tmp_path: Path) -> None:
    from deeptutor.agents.research.request_config import (
        build_research_runtime_config,
        validate_research_request_config,
    )

    _runtime_home(monkeypatch, tmp_path)
    request = validate_research_request_config({"mode": "notes", "depth": "quick"})

    runtime_config = build_research_runtime_config(
        base_config={
            "paths": {
                "research_output_dir": "/custom/research",
                "research_reports_dir": "/custom/reports",
            }
        },
        request_config=request,
        kb_name=None,
    )

    assert runtime_config["system"]["output_base_dir"] == "/custom/research"
    assert runtime_config["system"]["reports_dir"] == "/custom/reports"


def test_kb_health_bare_manager_follows_runtime_home(monkeypatch, tmp_path: Path) -> None:
    from deeptutor.book.kb_health import _current_manager

    home = _runtime_home(monkeypatch, tmp_path)

    manager = _current_manager()

    assert manager.base_dir == (home / "data" / "knowledge_bases").resolve()


def test_kb_health_multi_user_resolution_surfaces_errors(monkeypatch, tmp_path: Path) -> None:
    from deeptutor.book.kb_health import _current_manager
    from deeptutor.multi_user.context import reset_current_user, set_current_user
    from deeptutor.multi_user.paths import local_admin_user

    _runtime_home(monkeypatch, tmp_path)

    def _explode():
        raise RuntimeError("multi-user resolution failed")

    monkeypatch.setattr("deeptutor.multi_user.knowledge_access.current_kb_manager", _explode)
    token = set_current_user(local_admin_user())
    try:
        with pytest.raises(RuntimeError, match="multi-user resolution failed"):
            _current_manager()
    finally:
        reset_current_user(token)


def test_kb_health_routes_through_current_user_manager(monkeypatch, tmp_path: Path) -> None:
    from deeptutor.book import kb_health
    from deeptutor.knowledge.manager import KnowledgeBaseManager
    from deeptutor.multi_user.context import reset_current_user, set_current_user
    from deeptutor.multi_user.paths import local_admin_user

    _runtime_home(monkeypatch, tmp_path)

    scoped = KnowledgeBaseManager(
        base_dir=tmp_path / "scoped-kbs",
    )
    monkeypatch.setattr("deeptutor.multi_user.knowledge_access.current_kb_manager", lambda: scoped)
    token = set_current_user(local_admin_user())
    try:
        assert kb_health._current_manager() is scoped
    finally:
        reset_current_user(token)
