"""Focused tests for the visual-review frame service (visual_review.py).

Covers the artifact-to-attachment envelope and the frame-sampling helpers
with a faked subprocess layer, so no ffmpeg/ffprobe is ever launched.
"""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from types import SimpleNamespace

import pytest

from deeptutor.agents.math_animator.models import RenderedArtifact, RenderResult
from deeptutor.agents.math_animator.renderer import ManimRenderError
import deeptutor.agents.math_animator.visual_review as visual_review_module
from deeptutor.agents.math_animator.visual_review import VisualReviewService


class FakeProcess:
    def __init__(
        self,
        command: list[str],
        *,
        returncode: int = 0,
        stdout: bytes = b"",
        stderr: bytes = b"",
        create: Path | None = None,
    ) -> None:
        self.command = command
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self._create = create

    async def communicate(self) -> tuple[bytes, bytes]:
        if self.returncode == 0 and self._create is not None:
            self._create.parent.mkdir(parents=True, exist_ok=True)
            self._create.write_bytes(b"png-stub")
        return self._stdout, self._stderr


def _install_subprocess_factory(monkeypatch: pytest.MonkeyPatch, factory) -> None:
    fake_asyncio = SimpleNamespace(subprocess=asyncio.subprocess, create_subprocess_exec=factory)
    monkeypatch.setattr(visual_review_module, "asyncio", fake_asyncio)


def _recording_factory(
    commands: list[list[str]],
    *,
    ffprobe_stdout: bytes = b"10\n",
    ffprobe_returncode: int = 0,
    ffmpeg_returncode: int = 0,
    create_frames: bool = True,
):
    async def factory(*command: str, **_kwargs):
        commands.append(list(command))
        if command[0] == "ffprobe":
            return FakeProcess(
                list(command),
                returncode=ffprobe_returncode,
                stdout=ffprobe_stdout,
                stderr=b"probe exploded" if ffprobe_returncode else b"",
            )
        frame_path = Path(command[-1])
        return FakeProcess(
            list(command),
            returncode=ffmpeg_returncode,
            stderr=b"Invalid data" if ffmpeg_returncode else b"",
            create=frame_path if create_frames else None,
        )

    return factory


def _video_render_result(filename: str = "out.mp4") -> RenderResult:
    return RenderResult(
        output_mode="video",
        artifacts=[RenderedArtifact(type="video", url="", filename=filename)],
    )


class TestConstructorLayout:
    def test_explicit_output_dir_creates_artifacts_and_review_dirs(self, tmp_path: Path) -> None:
        service = VisualReviewService("turn-1", output_dir=tmp_path)

        assert service.base_dir == tmp_path.resolve()
        assert service.artifacts_dir == tmp_path.resolve() / "artifacts"
        assert service.review_dir == tmp_path.resolve() / "review"
        # Only the review dir is materialised up front; artifacts arrive later.
        assert not service.artifacts_dir.exists()
        assert service.review_dir.is_dir()

    def test_default_dir_comes_from_path_service(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent_root = tmp_path / "agent" / "math_animator"
        fake_path_service = SimpleNamespace(get_agent_dir=lambda module: agent_root)
        monkeypatch.setattr(visual_review_module, "get_path_service", lambda: fake_path_service)

        service = VisualReviewService("turn-42")

        assert service.base_dir == agent_root / "turn-42"
        assert service.review_dir.is_dir()


class TestChooseTimestamps:
    @pytest.mark.parametrize(
        ("duration", "expected"),
        [
            (0.0, [0.0]),
            (-3.5, [0.0]),
            (0.5, [0.0, 0.25, 0.45]),
            (0.04, [0.0, 0.02, 0.0]),
            (1.99, [0.0, 0.995, 1.94]),
            (2.0, [0.3, 1.0, 1.7]),
            (10.0, [1.5, 5.0, 8.5]),
            (100.0, [15.0, 50.0, 85.0]),
        ],
    )
    def test_samples_three_frames_per_duration_band(
        self, duration: float, expected: list[float]
    ) -> None:
        assert VisualReviewService._choose_timestamps(duration) == pytest.approx(expected)


class TestPathToAttachment:
    @pytest.mark.parametrize(
        ("filename", "mime_type"),
        [
            ("frame.png", "image/png"),
            ("frame.PNG", "image/png"),
            ("frame.jpg", "image/jpeg"),
            ("frame.jpeg", "image/jpeg"),
            ("frame.JPEG", "image/jpeg"),
            ("frame.webp", "image/png"),
        ],
    )
    def test_maps_suffix_to_mime_and_encodes_bytes(
        self, tmp_path: Path, filename: str, mime_type: str
    ) -> None:
        path = tmp_path / filename
        payload = b"\x89PNG-image-bytes"
        path.write_bytes(payload)

        attachment = VisualReviewService._path_to_attachment(path)

        assert attachment.type == "image"
        assert attachment.filename == filename
        assert attachment.mime_type == mime_type
        assert base64.b64decode(attachment.base64) == payload


class TestBuildAttachments:
    @pytest.mark.asyncio
    async def test_image_mode_returns_one_attachment_per_artifact(self, tmp_path: Path) -> None:
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir(parents=True)
        (artifacts_dir / "a.png").write_bytes(b"AAA")
        (artifacts_dir / "b.png").write_bytes(b"BBB")
        render_result = RenderResult(
            output_mode="image",
            artifacts=[
                RenderedArtifact(type="image", url="", filename="a.png"),
                RenderedArtifact(type="image", url="", filename="b.png"),
            ],
        )
        messages: list[tuple[str, bool]] = []

        async def progress(message: str, raw: bool = False) -> None:
            messages.append((message, raw))

        service = VisualReviewService("turn", progress_callback=progress, output_dir=tmp_path)

        attachments = await service.build_attachments(render_result)

        assert [a.filename for a in attachments] == ["a.png", "b.png"]
        assert [a.mime_type for a in attachments] == ["image/png", "image/png"]
        assert messages == [("Preparing 2 rendered image(s) for visual review.", False)]

    @pytest.mark.asyncio
    async def test_video_mode_without_video_artifact_returns_empty(self, tmp_path: Path) -> None:
        render_result = RenderResult(
            output_mode="video",
            artifacts=[RenderedArtifact(type="image", url="", filename="still.png")],
        )
        messages: list[str] = []

        async def progress(message: str, raw: bool = False) -> None:
            messages.append(message)

        service = VisualReviewService("turn", progress_callback=progress, output_dir=tmp_path)

        assert await service.build_attachments(render_result) == []
        assert messages == []

    @pytest.mark.asyncio
    async def test_video_mode_extracts_frames_and_reports_progress(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir(parents=True)
        (artifacts_dir / "out.mp4").write_bytes(b"fake video")
        commands: list[list[str]] = []
        _install_subprocess_factory(monkeypatch, _recording_factory(commands))
        messages: list[tuple[str, bool]] = []

        async def progress(message: str, raw: bool = False) -> None:
            messages.append((message, raw))

        service = VisualReviewService("turn", progress_callback=progress, output_dir=tmp_path)

        attachments = await service.build_attachments(_video_render_result())

        assert [a.filename for a in attachments] == [
            "review_frame_01.png",
            "review_frame_02.png",
            "review_frame_03.png",
        ]
        assert commands[0][0] == "ffprobe"
        assert [command[0] for command in commands[1:]] == ["ffmpeg"] * 3
        assert messages[-1] == ("Prepared 3 review frame(s) from rendered video.", False)
        raw_messages = [entry for entry in messages if entry[1]]
        assert len(raw_messages) == 3
        assert raw_messages[0][0].startswith("Extracting review frame 1/3")


class TestProbeDuration:
    @pytest.mark.asyncio
    async def test_parses_ffprobe_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        commands: list[list[str]] = []
        _install_subprocess_factory(
            monkeypatch, _recording_factory(commands, ffprobe_stdout=b"12.5\n")
        )
        service = VisualReviewService("turn", output_dir=tmp_path)

        duration = await service._probe_duration(tmp_path / "video.mp4")

        assert duration == 12.5
        assert commands[0][0] == "ffprobe"
        assert "format=duration" in commands[0]

    @pytest.mark.asyncio
    async def test_empty_ffprobe_output_counts_as_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        commands: list[list[str]] = []
        _install_subprocess_factory(monkeypatch, _recording_factory(commands, ffprobe_stdout=b"\n"))
        service = VisualReviewService("turn", output_dir=tmp_path)

        assert await service._probe_duration(tmp_path / "video.mp4") == 0.0

    @pytest.mark.asyncio
    async def test_unparsable_duration_raises_render_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        commands: list[list[str]] = []
        _install_subprocess_factory(
            monkeypatch, _recording_factory(commands, ffprobe_stdout=b"not-a-number")
        )
        service = VisualReviewService("turn", output_dir=tmp_path)

        with pytest.raises(ManimRenderError, match="duration could not be parsed"):
            await service._probe_duration(tmp_path / "video.mp4")

    @pytest.mark.asyncio
    async def test_ffprobe_failure_raises_render_error_with_stderr(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        commands: list[list[str]] = []
        _install_subprocess_factory(monkeypatch, _recording_factory(commands, ffprobe_returncode=1))
        service = VisualReviewService("turn", output_dir=tmp_path)

        with pytest.raises(
            ManimRenderError, match="Failed to inspect rendered video duration"
        ) as raised:
            await service._probe_duration(tmp_path / "video.mp4")

        assert "probe exploded" in str(raised.value)


class TestExtractVideoFrames:
    @pytest.mark.asyncio
    async def test_missing_video_raises_render_error(self, tmp_path: Path) -> None:
        service = VisualReviewService("turn", output_dir=tmp_path)

        with pytest.raises(ManimRenderError, match="video artifact missing"):
            await service._extract_video_frames(tmp_path / "missing.mp4")

    @pytest.mark.asyncio
    async def test_success_writes_numbered_review_frames(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir(parents=True)
        video = artifacts_dir / "out.mp4"
        video.write_bytes(b"fake video")
        commands: list[list[str]] = []
        _install_subprocess_factory(monkeypatch, _recording_factory(commands))
        service = VisualReviewService("turn", output_dir=tmp_path)

        frames = await service._extract_video_frames(video)

        assert [frame.name for frame in frames] == [
            "review_frame_01.png",
            "review_frame_02.png",
            "review_frame_03.png",
        ]
        assert all(frame.parent == service.review_dir for frame in frames)
        ffmpeg_commands = [command for command in commands if command[0] == "ffmpeg"]
        assert len(ffmpeg_commands) == 3
        for command, frame in zip(ffmpeg_commands, frames, strict=True):
            assert command[0] == "ffmpeg"
            assert command[command.index("-frames:v") + 1] == "1"
            assert Path(command[-1]) == frame

    @pytest.mark.asyncio
    async def test_ffmpeg_failure_raises_render_error_with_stderr(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir(parents=True)
        video = artifacts_dir / "out.mp4"
        video.write_bytes(b"fake video")
        commands: list[list[str]] = []
        _install_subprocess_factory(monkeypatch, _recording_factory(commands, ffmpeg_returncode=1))
        service = VisualReviewService("turn", output_dir=tmp_path)

        with pytest.raises(ManimRenderError, match="Failed to extract review frames") as raised:
            await service._extract_video_frames(video)

        assert "Invalid data" in str(raised.value)

    @pytest.mark.asyncio
    async def test_ffmpeg_success_without_frame_file_raises_render_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir(parents=True)
        video = artifacts_dir / "out.mp4"
        video.write_bytes(b"fake video")
        commands: list[list[str]] = []
        _install_subprocess_factory(monkeypatch, _recording_factory(commands, create_frames=False))
        service = VisualReviewService("turn", output_dir=tmp_path)

        with pytest.raises(ManimRenderError, match="Failed to extract review frames"):
            await service._extract_video_frames(video)


class TestEmitProgress:
    @pytest.mark.asyncio
    async def test_without_callback_is_a_no_op(self, tmp_path: Path) -> None:
        service = VisualReviewService("turn", output_dir=tmp_path)

        await service._emit_progress("ignored", raw=True)

        assert service.review_dir.is_dir()
