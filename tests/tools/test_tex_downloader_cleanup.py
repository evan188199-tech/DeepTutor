"""Regression tests: TexDownloader must clean up its temp working directory on failure paths.

Every failed download_arxiv_source call should leave the workspace as it was,
without leftover ``tmp*`` directories or partial extraction files.
"""

from __future__ import annotations

import io
from pathlib import Path
import tarfile
from unittest.mock import MagicMock

import pytest

import deeptutor.tools.tex_downloader as tex_downloader_module
from deeptutor.tools.tex_downloader import TexDownloader

MIN_TEX = "\\documentclass{article}\n\\begin{document}\nHello arxiv.\n\\end{document}\n"


def _make_tar_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _mock_response(content: bytes) -> MagicMock:
    response = MagicMock()
    response.content = content
    response.raise_for_status.return_value = None
    return response


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


def test_processing_failure_leaves_no_temp_dir(workspace: Path) -> None:
    downloader = TexDownloader(workspace_dir=str(workspace))
    # paper_<id> collides with an existing regular file, so the final
    # permanent-copy step fails after the temp dir has been created.
    (workspace / "paper_1706.03762").write_text("collision", encoding="utf-8")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            tex_downloader_module.requests,
            "get",
            lambda *a, **k: _mock_response(_make_tar_bytes({"main.tex": MIN_TEX.encode("utf-8")})),
        )
        result = downloader.download_arxiv_source(
            "https://arxiv.org/abs/1706.03762", arxiv_id="1706.03762"
        )

    assert result.success is False
    assert result.error is not None
    assert [p.name for p in workspace.iterdir()] == ["paper_1706.03762"]


def test_main_tex_not_found_failure_leaves_no_temp_dir(workspace: Path) -> None:
    downloader = TexDownloader(workspace_dir=str(workspace))
    # Archive without any .tex file -> "Main tex file not found" early return.
    payload = _make_tar_bytes({"figure.dat": b"not a tex file"})

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(tex_downloader_module.requests, "get", lambda *a, **k: _mock_response(payload))
        result = downloader.download_arxiv_source(
            "https://arxiv.org/abs/1706.03762", arxiv_id="1706.03762"
        )

    assert result.success is False
    assert result.error == "Main tex file not found"
    assert list(workspace.iterdir()) == []


def test_network_failure_leaves_no_temp_dir(workspace: Path) -> None:
    downloader = TexDownloader(workspace_dir=str(workspace))

    def _raise(*args: object, **kwargs: object) -> None:
        raise tex_downloader_module.requests.exceptions.ConnectionError("network down")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(tex_downloader_module.requests, "get", _raise)
        result = downloader.download_arxiv_source(
            "https://arxiv.org/abs/1706.03762", arxiv_id="1706.03762"
        )

    assert result.success is False
    assert result.error is not None
    assert result.error.startswith("Download failed")
    assert list(workspace.iterdir()) == []


def test_success_path_still_cleans_temp_dir(workspace: Path) -> None:
    downloader = TexDownloader(workspace_dir=str(workspace))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            tex_downloader_module.requests,
            "get",
            lambda *a, **k: _mock_response(_make_tar_bytes({"main.tex": MIN_TEX.encode("utf-8")})),
        )
        result = downloader.download_arxiv_source(
            "https://arxiv.org/abs/1706.03762", arxiv_id="1706.03762"
        )

    assert result.success is True, result.error
    assert [p.name for p in workspace.iterdir()] == ["paper_1706.03762"]
