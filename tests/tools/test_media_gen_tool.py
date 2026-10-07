"""Focused unit tests for ``deeptutor.tools.media_gen_tool``.

Pure-logic coverage of the imagegen/videogen chat tools: parameter
validation, provider dispatch (argument forwarding + progress plumbing),
and failure paths. Providers are mocked and workspace dirs are injected,
so nothing here touches the network or the real workspace service.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from deeptutor.core.tool_protocol import ToolResult
from deeptutor.services.generation_http import GenerationProviderError
from deeptutor.services.sandbox.artifacts import SandboxArtifact
from deeptutor.tools.media_gen_tool import (
    ImagegenTool,
    VideogenTool,
    _artifact_result,
    _ext,
    _run_dir,
    _slug,
    _write_media,
)


def _artifact(name: str = "a.png", mime_type: str = "image/png") -> SandboxArtifact:
    return SandboxArtifact(
        filename=name,
        path=f"outputs/x/{name}",
        relative_path=f"outputs/x/{name}",
        url="",
        size_bytes=3,
        mime_type=mime_type,
    )


def _patch_collect(
    monkeypatch: pytest.MonkeyPatch, artifacts: list[SandboxArtifact] | None = None
) -> dict[str, Any]:
    """Replace the real artifact collection with an honest tmp-dir listing."""
    seen: dict[str, Any] = {}

    def fake_collect(workdir: str, **kwargs: Any) -> list[SandboxArtifact]:
        seen["workdir"] = str(workdir)
        seen.update(kwargs)
        if artifacts is not None:
            return artifacts
        return [
            SandboxArtifact(
                filename=p.name,
                path=p.name,
                relative_path=p.name,
                url="",
                size_bytes=p.stat().st_size,
                mime_type="application/octet-stream",
            )
            for p in sorted(Path(workdir).iterdir())
        ]

    monkeypatch.setattr(
        "deeptutor.services.sandbox.artifacts.collect_public_artifacts", fake_collect
    )
    return seen


def _ws_kwargs(tmp_path: Path) -> dict[str, str]:
    base = tmp_path / "outputs"
    base.mkdir()
    return {"_workspace_dir": str(base), "_workspace_id": "ws-1"}


def _patch_imagegen(monkeypatch: pytest.MonkeyPatch, fake: Any) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    async def recorder(prompt: str, **kwargs: Any) -> list[tuple[bytes, str]]:
        captured["prompt"] = prompt
        captured.update(kwargs)
        return await fake(prompt, **kwargs)

    monkeypatch.setattr("deeptutor.services.imagegen.generate_image", recorder)
    return captured


def _patch_videogen(monkeypatch: pytest.MonkeyPatch, fake: Any) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    async def recorder(prompt: str, **kwargs: Any) -> tuple[bytes, str]:
        captured["prompt"] = prompt
        captured.update(kwargs)
        return await fake(prompt, **kwargs)

    monkeypatch.setattr("deeptutor.services.videogen.generate_video", recorder)
    return captured


def test_tool_definitions_expose_validated_parameters() -> None:
    imagegen = ImagegenTool().get_definition()
    videogen = VideogenTool().get_definition()
    assert (imagegen.name, videogen.name) == ("imagegen", "videogen")
    imagegen_by_name = {p.name: p for p in imagegen.parameters}
    videogen_by_name = {p.name: p for p in videogen.parameters}
    assert imagegen_by_name["prompt"].required is True
    assert imagegen_by_name["prompt"].type == "string"
    assert imagegen_by_name["size"].required is False
    assert imagegen_by_name["n"].required is False
    assert imagegen_by_name["n"].default == 1
    assert videogen_by_name["prompt"].required is True
    assert videogen_by_name["aspect_ratio"].required is False
    assert videogen_by_name["duration"].required is False


def test_slug_normalizes_prompt_and_falls_back() -> None:
    assert _slug("A Bright Red Fox! Runs, fast", "image") == "a_bright_red_fox_runs_fast"
    assert _slug("图像 生成!!", "image") == "image"
    assert _slug("图像 生成!!", "video") == "video"
    long_word = "x" * 80
    assert _slug(long_word, "image") == "x" * 40


def test_ext_maps_content_type_and_defaults() -> None:
    assert _ext("image/png", "png") == "png"
    assert _ext("video/mp4; charset=binary", "mp4") == "mp4"
    assert _ext("application/octet-stream", "bin") == "bin"
    assert _ext("", "png") == "png"


@pytest.mark.parametrize("prompt", ["", "   "])
@pytest.mark.asyncio
async def test_imagegen_rejects_blank_prompt(monkeypatch: pytest.MonkeyPatch, prompt: str) -> None:
    async def fail(*_a: Any, **_k: Any) -> list[tuple[bytes, str]]:
        raise AssertionError("provider must not be called")

    _patch_imagegen(monkeypatch, fail)
    result = await ImagegenTool().execute(prompt=prompt)
    assert result.success is False
    assert "requires a non-empty 'prompt'" in result.content


@pytest.mark.parametrize("prompt", ["", "  \n\t"])
@pytest.mark.asyncio
async def test_videogen_rejects_blank_prompt(monkeypatch: pytest.MonkeyPatch, prompt: str) -> None:
    async def fail(*_a: Any, **_k: Any) -> tuple[bytes, str]:
        raise AssertionError("provider must not be called")

    _patch_videogen(monkeypatch, fail)
    result = await VideogenTool().execute(prompt=prompt)
    assert result.success is False
    assert "requires a non-empty 'prompt'" in result.content


@pytest.mark.parametrize(
    ("raw_n", "expected"),
    [(None, 1), ("abc", 1), (0, 1), (-3, 1), ("2", 2), (3, 3), (99, 4)],
)
@pytest.mark.asyncio
async def test_imagegen_normalizes_count(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, raw_n: Any, expected: int
) -> None:
    async def fake(prompt: str, **_k: Any) -> list[tuple[bytes, str]]:
        return [(b"data", "image/png")]

    captured = _patch_imagegen(monkeypatch, fake)
    _patch_collect(monkeypatch, [_artifact()])
    result = await ImagegenTool().execute(prompt="cat", n=raw_n, **_ws_kwargs(tmp_path))
    assert result.success, result.content
    assert captured["n"] == expected


@pytest.mark.asyncio
async def test_imagegen_dispatch_forwards_prompt_and_normalized_size(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def fake(prompt: str, **_k: Any) -> list[tuple[bytes, str]]:
        return [(b"data", "image/png")]

    captured = _patch_imagegen(monkeypatch, fake)
    seen = _patch_collect(monkeypatch, [_artifact()])
    result = await ImagegenTool().execute(
        prompt="a cat", size=" 1024x1024 ", **_ws_kwargs(tmp_path)
    )
    assert result.success, result.content
    assert captured["prompt"] == "a cat"
    assert captured["size"] == "1024x1024"
    assert captured["n"] == 1
    assert seen["workspace_id"] == "ws-1"
    assert result.metadata["prompt"] == "a cat"
    assert result.metadata["count"] == 1
    assert result.metadata["kind"] == "image"
    assert result.sources == []
    assert "not yet presented" in result.content
    assert "a.png" in result.content


@pytest.mark.asyncio
async def test_videogen_dispatch_forwards_options_and_progress(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def fake(prompt: str, *, progress: Any = None, **_k: Any) -> tuple[bytes, str]:
        if progress is not None:
            await progress("Rendering…")
        return (b"MP4", "video/mp4")

    captured = _patch_videogen(monkeypatch, fake)
    _patch_collect(monkeypatch, [_artifact("v.mp4", "video/mp4")])
    events: list[tuple[str, str]] = []

    async def event_sink(event_type: str, message: str = "", metadata: Any = None) -> None:
        events.append((event_type, message))

    result = await VideogenTool().execute(
        prompt="a wave",
        aspect_ratio=" 16:9 ",
        duration=" 5 ",
        event_sink=event_sink,
        **_ws_kwargs(tmp_path),
    )
    assert result.success, result.content
    assert captured["prompt"] == "a wave"
    assert captured["aspect_ratio"] == "16:9"
    assert captured["duration"] == "5"
    assert callable(captured["progress"])
    assert events == [("tool_log", "Rendering…")]
    assert result.metadata["kind"] == "video"
    assert "v.mp4" in result.content


@pytest.mark.asyncio
async def test_videogen_progress_survives_broken_event_sink(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def fake(prompt: str, *, progress: Any = None, **_k: Any) -> tuple[bytes, str]:
        if progress is not None:
            await progress("tick")
        return (b"MP4", "video/mp4")

    _patch_videogen(monkeypatch, fake)
    _patch_collect(monkeypatch, [_artifact("v.mp4", "video/mp4")])

    async def broken_sink(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("sink is gone")

    result = await VideogenTool().execute(
        prompt="a wave", event_sink=broken_sink, **_ws_kwargs(tmp_path)
    )
    assert result.success, result.content


@pytest.mark.asyncio
async def test_imagegen_unconfigured_value_error_is_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake(*_a: Any, **_k: Any) -> list[tuple[bytes, str]]:
        raise ValueError("No imagegen model is configured")

    _patch_imagegen(monkeypatch, fake)
    result = await ImagegenTool().execute(prompt="cat")
    assert result.success is False
    assert result.content == "No imagegen model is configured"


@pytest.mark.asyncio
async def test_imagegen_provider_error_is_wrapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake(*_a: Any, **_k: Any) -> list[tuple[bytes, str]]:
        raise GenerationProviderError("upstream 500")

    _patch_imagegen(monkeypatch, fake)
    result = await ImagegenTool().execute(prompt="cat")
    assert result.success is False
    assert result.content == "Image generation failed: upstream 500"


@pytest.mark.asyncio
async def test_videogen_unconfigured_value_error_is_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake(*_a: Any, **_k: Any) -> tuple[bytes, str]:
        raise ValueError("No videogen model is configured")

    _patch_videogen(monkeypatch, fake)
    result = await VideogenTool().execute(prompt="a wave")
    assert result.success is False
    assert result.content == "No videogen model is configured"


@pytest.mark.asyncio
async def test_videogen_provider_error_is_wrapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake(*_a: Any, **_k: Any) -> tuple[bytes, str]:
        raise GenerationProviderError("poll timeout")

    _patch_videogen(monkeypatch, fake)
    result = await VideogenTool().execute(prompt="a wave")
    assert result.success is False
    assert result.content == "Video generation failed: poll timeout"


@pytest.mark.asyncio
async def test_imagegen_empty_media_reports_no_saved_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def fake(*_a: Any, **_k: Any) -> list[tuple[bytes, str]]:
        return []

    _patch_imagegen(monkeypatch, fake)
    seen = _patch_collect(monkeypatch, [])
    result = await ImagegenTool().execute(prompt="cat", **_ws_kwargs(tmp_path))
    assert result.success is False
    assert result.content == "Image generation produced no saved files."
    assert seen["workdir"]


@pytest.mark.asyncio
async def test_videogen_empty_bytes_skip_writing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def fake(*_a: Any, **_k: Any) -> tuple[bytes, str]:
        return (b"", "video/mp4")

    _patch_videogen(monkeypatch, fake)
    seen = _patch_collect(monkeypatch, [])
    result = await VideogenTool().execute(prompt="a wave", **_ws_kwargs(tmp_path))
    assert result.success is False
    assert result.content == "Video generation produced no saved file."
    assert Path(seen["workdir"]).is_dir()
    assert list(Path(seen["workdir"]).iterdir()) == []


@pytest.mark.asyncio
async def test_imagegen_multi_media_naming_skips_empty_entries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def fake(*_a: Any, **_k: Any) -> list[tuple[bytes, str]]:
        return [
            (b"one", "image/png"),
            (b"", "image/jpeg"),
            (b"two", "image/jpeg"),
        ]

    _patch_imagegen(monkeypatch, fake)
    seen = _patch_collect(monkeypatch)
    result = await ImagegenTool().execute(prompt="a bright cat", **_ws_kwargs(tmp_path))
    assert result.success, result.content
    names = {row["filename"] for row in result.metadata["artifacts"]}
    assert names == {"a_bright_cat_1.png", "a_bright_cat_3.jpg"}
    assert Path(seen["workdir"]) / "a_bright_cat_1.png" in Path(seen["workdir"]).iterdir()


@pytest.mark.asyncio
async def test_write_media_uses_default_extension_for_unknown_type(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    written = _write_media(
        run_dir,
        [(b"D", "application/octet-stream")],
        stem="x",
        default_ext="png",
    )
    assert written == []
    assert (run_dir / "x.png").read_bytes() == b"D"


def test_run_dir_uses_injected_workspace(tmp_path: Path) -> None:
    run, workspace_id = _run_dir(str(tmp_path), "imagegen", workspace_id="ws-9")
    assert run.parent == tmp_path
    assert run.name.startswith("imagegen_")
    assert len(run.name.split("_", 1)[1]) == 12
    assert run.is_dir()
    assert workspace_id == "ws-9"


def test_run_dir_runtime_fallback_for_direct_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}

    class FakeRuntime:
        output_dir = str(tmp_path / "out")
        workspace_id = "rt-1"

    class FakeService:
        def create_runtime_context(self, **kwargs: Any) -> FakeRuntime:
            seen.update(kwargs)
            return FakeRuntime()

    monkeypatch.setattr(
        "deeptutor.services.workspace.get_content_workspace_service",
        lambda: FakeService(),
    )
    run, workspace_id = _run_dir(None, "videogen")
    assert run.parent == tmp_path / "out" / "media"
    assert run.name.startswith("videogen_")
    assert workspace_id == "rt-1"
    assert seen == {"capability": "chat", "session_id": "direct", "turn_id": "media_gen"}


def test_artifact_result_empty_reports_failure() -> None:
    result = _artifact_result([], empty_message="nothing saved")
    assert isinstance(result, ToolResult)
    assert result.success is False
    assert result.content == "nothing saved"


def test_artifact_result_with_workspace_hides_sources() -> None:
    result = _artifact_result(
        [_artifact()], empty_message="empty", workspace_id="ws-1", kind="image"
    )
    assert result.success is True
    assert "not yet presented" in result.content
    assert "outputs/x/a.png" in result.content
    assert result.sources == []
    assert result.metadata["kind"] == "image"
    assert result.metadata["workspace_items"] == []
    assert result.metadata["artifacts"][0]["filename"] == "a.png"


def test_artifact_result_without_workspace_exposes_sources() -> None:
    result = _artifact_result([_artifact()], empty_message="empty", kind="image")
    assert result.success is True
    assert "already presented" in result.content
    assert result.sources == [
        {
            "type": "artifact",
            "filename": "a.png",
            "url": "",
            "path": "outputs/x/a.png",
            "mime_type": "image/png",
            "size_bytes": 3,
        }
    ]
