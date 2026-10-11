"""Reviewed catalog artifact download and install handoff tests."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import httpx
import pytest

from deeptutor.plugins.distribution import (
    CatalogArtifactDownloader,
    CatalogInstallManager,
    PluginDistributionError,
    _default_client,
)


def _artifact(payload: bytes) -> SimpleNamespace:
    return SimpleNamespace(
        url="https://artifacts.example.com/example-1.0.0-py3-none-any.whl",
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _client(response: httpx.Response) -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(lambda request: response),
        follow_redirects=False,
    )


def test_downloader_verifies_reviewed_size_and_digest(tmp_path: Path) -> None:
    payload = b"valid-wheel-bytes"
    downloader = CatalogArtifactDownloader(
        client_factory=lambda timeout: _client(
            httpx.Response(
                200,
                content=payload,
                headers={"content-length": str(len(payload))},
            )
        )
    )

    result = downloader.download(_artifact(payload), destination_dir=tmp_path)

    assert result.path.read_bytes() == payload
    assert result.path.suffix == ".whl"
    assert result.sha256 == hashlib.sha256(payload).hexdigest()
    assert result.size_bytes == len(payload)


def test_downloader_rejects_redirect_and_declared_size_mismatch(
    tmp_path: Path,
) -> None:
    redirect = CatalogArtifactDownloader(
        client_factory=lambda timeout: _client(
            httpx.Response(302, headers={"location": "https://other.example.com/artifact.whl"})
        )
    )
    size_mismatch = CatalogArtifactDownloader(
        client_factory=lambda timeout: _client(
            httpx.Response(200, content=b"12345", headers={"content-length": "5"})
        )
    )
    artifact = _artifact(b"1234")

    with pytest.raises(PluginDistributionError, match="redirects are not allowed"):
        redirect.download(artifact, destination_dir=tmp_path)
    with pytest.raises(
        PluginDistributionError, match="Content-Length does not match reviewed size"
    ):
        size_mismatch.download(artifact, destination_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_downloader_rejects_body_size_or_digest_mismatch_and_cleans(
    tmp_path: Path,
) -> None:
    artifact = _artifact(b"1234")
    oversized_response = httpx.Response(200, content=b"12345")
    oversized_response.headers["content-length"] = "4"
    oversized = CatalogArtifactDownloader(
        client_factory=lambda timeout: _client(oversized_response)
    )
    corrupt = CatalogArtifactDownloader(
        client_factory=lambda timeout: _client(httpx.Response(200, content=b"5678"))
    )

    with pytest.raises(PluginDistributionError, match="exceeds reviewed size"):
        oversized.download(artifact, destination_dir=tmp_path)
    with pytest.raises(PluginDistributionError, match="SHA-256"):
        corrupt.download(artifact, destination_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_catalog_install_uses_lifecycle_after_verified_download(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.plugins.manifest import parse_manifest
    from tests.plugins.test_lifecycle import _raw_manifest, _wheel

    payload = _wheel(tmp_path, "1.0.0").read_bytes()
    manifest = parse_manifest(_raw_manifest())
    artifact = _artifact(payload)
    calls: list[tuple[Path, str]] = []

    class FakeLifecycle:
        def install(self, path, *, expected_sha256, allow_reinstall=False):
            calls.append((path, expected_sha256))
            assert path.is_file()
            return SimpleNamespace(
                plugin_id="org.author.example",
                version="1.0.0",
                action="installed",
                artifact_sha256=expected_sha256,
                venv_path=tmp_path / "venv",
            )

    def fake_resolve(plugin_id, version, *, allow_deprecated, **kwargs):
        assert (plugin_id, version, allow_deprecated) == (
            "org.author.example",
            "1.0.0",
            True,
        )
        return SimpleNamespace(
            artifact=artifact,
            id=manifest.id,
            version=str(manifest.version),
            permissions=manifest.permissions,
            dependencies=manifest.dependencies,
            compatibility=manifest.compatibility,
        )

    monkeypatch.setattr("deeptutor.plugins.distribution.resolve_catalog_entry", fake_resolve)

    result = CatalogInstallManager(
        downloader_factory=lambda: CatalogArtifactDownloader(
            client_factory=lambda timeout: _client(httpx.Response(200, content=payload))
        ),
        lifecycle_factory=FakeLifecycle,
    ).install(
        "org.author.example",
        version="1.0.0",
        allow_deprecated=True,
    )

    assert result.artifact_url == artifact.url
    assert len(calls) == 1
    assert calls[0][1] == artifact.sha256


def test_failed_catalog_download_never_reaches_lifecycle() -> None:
    class FailedDownloader:
        def download(self, artifact, *, destination_dir, timeout_seconds):
            raise PluginDistributionError("catalog artifact download failed")

    class UnexpectedLifecycle:
        def install(self, *args, **kwargs):
            raise AssertionError("download failure must not reach lifecycle")

    with pytest.raises(PluginDistributionError):
        CatalogInstallManager(
            downloader_factory=FailedDownloader,
            lifecycle_factory=UnexpectedLifecycle,
        ).install("org.author.example")


def test_downloader_rejects_non_positive_timeout_and_blank_url(tmp_path: Path) -> None:
    downloader = CatalogArtifactDownloader(
        client_factory=lambda timeout: _client(httpx.Response(200))
    )

    with pytest.raises(PluginDistributionError, match="timeout must be positive"):
        downloader.download(
            _artifact(b"payload"),
            destination_dir=tmp_path,
            timeout_seconds=0,
        )
    with pytest.raises(PluginDistributionError, match="no download URL"):
        downloader.download(
            SimpleNamespace(url="", size_bytes=1, sha256="0" * 64),
            destination_dir=tmp_path,
        )
    assert list(tmp_path.iterdir()) == []


def test_downloader_rejects_non_wheel_artifact_name(tmp_path: Path) -> None:
    downloader = CatalogArtifactDownloader(
        client_factory=lambda timeout: _client(httpx.Response(200))
    )

    with pytest.raises(PluginDistributionError, match="invalid wheel filename"):
        downloader.download(
            SimpleNamespace(
                url="https://artifacts.example.com/example-1.0.0.txt",
                size_bytes=4,
                sha256=hashlib.sha256(b"1234").hexdigest(),
            ),
            destination_dir=tmp_path,
        )
    assert list(tmp_path.iterdir()) == []


def test_downloader_rejects_http_error_status(tmp_path: Path) -> None:
    downloader = CatalogArtifactDownloader(
        client_factory=lambda timeout: _client(httpx.Response(404))
    )

    with pytest.raises(PluginDistributionError, match="download exited 404"):
        downloader.download(_artifact(b"1234"), destination_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_downloader_rejects_invalid_content_length(tmp_path: Path) -> None:
    downloader = CatalogArtifactDownloader(
        client_factory=lambda timeout: _client(
            httpx.Response(200, content=b"1234", headers={"content-length": "abc"})
        )
    )

    with pytest.raises(PluginDistributionError, match="invalid Content-Length"):
        downloader.download(_artifact(b"1234"), destination_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_downloader_rejects_undersized_body(tmp_path: Path) -> None:
    downloader = CatalogArtifactDownloader(
        client_factory=lambda timeout: _client(
            httpx.Response(200, content=b"12", headers={"content-length": "4"})
        )
    )

    with pytest.raises(PluginDistributionError, match="smaller than reviewed size"):
        downloader.download(_artifact(b"1234"), destination_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_downloader_wraps_transport_failure_and_cleans_up(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    downloader = CatalogArtifactDownloader(
        client_factory=lambda timeout: httpx.Client(
            transport=httpx.MockTransport(handler),
            follow_redirects=False,
        )
    )

    with pytest.raises(PluginDistributionError, match="catalog artifact download failed"):
        downloader.download(_artifact(b"1234"), destination_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


def _wheel_bytes(raw_manifest: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "example_plugin/deeptutor.plugin.json",
            json.dumps(raw_manifest),
        )
        archive.writestr(
            "example_plugin-1.dist-info/METADATA",
            "Name: example-plugin\nVersion: 1.0.0\n",
        )
    return buffer.getvalue()


def _resolved_entry(manifest, artifact: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        artifact=artifact,
        id=manifest.id,
        version=str(manifest.version),
        permissions=manifest.permissions,
        dependencies=manifest.dependencies,
        compatibility=manifest.compatibility,
    )


def test_install_rejects_entry_without_download_url(monkeypatch: pytest.MonkeyPatch) -> None:
    from deeptutor.plugins.manifest import parse_manifest
    from tests.plugins.test_lifecycle import _raw_manifest

    manifest = parse_manifest(_raw_manifest())
    entry = _resolved_entry(manifest, SimpleNamespace(url="", size_bytes=0, sha256=""))
    monkeypatch.setattr(
        "deeptutor.plugins.distribution.resolve_catalog_entry",
        lambda *args, **kwargs: entry,
    )

    def unexpected_downloader_factory():
        raise AssertionError("entry without URL must not reach the downloader")

    with pytest.raises(PluginDistributionError, match="has no download URL"):
        CatalogInstallManager(
            downloader_factory=unexpected_downloader_factory,
        ).install("org.author.example")


def test_install_rejects_wheel_manifest_drift_from_reviewed_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.plugins.manifest import parse_manifest
    from tests.plugins.test_lifecycle import _raw_manifest

    reviewed = parse_manifest(_raw_manifest())
    drifted = dict(_raw_manifest())
    drifted["permissions"] = {"network": ["https://other.example.com"]}
    payload = _wheel_bytes(drifted)
    artifact = _artifact(payload)

    monkeypatch.setattr(
        "deeptutor.plugins.distribution.resolve_catalog_entry",
        lambda *args, **kwargs: _resolved_entry(reviewed, artifact),
    )

    class UnexpectedLifecycle:
        def install(self, *args, **kwargs):
            raise AssertionError("manifest drift must not reach lifecycle")

    with pytest.raises(
        PluginDistributionError, match="does not match the reviewed catalog snapshot"
    ):
        CatalogInstallManager(
            downloader_factory=lambda: CatalogArtifactDownloader(
                client_factory=lambda timeout: _client(httpx.Response(200, content=payload))
            ),
            lifecycle_factory=UnexpectedLifecycle,
        ).install("org.author.example")


def test_install_forwards_reinstall_flag_to_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.plugins.manifest import parse_manifest
    from tests.plugins.test_lifecycle import _raw_manifest, _wheel

    payload = _wheel(tmp_path, "1.0.0").read_bytes()
    manifest = parse_manifest(_raw_manifest())
    artifact = _artifact(payload)
    reinstall_flags: list[bool] = []

    class RecordingLifecycle:
        def install(self, path, *, expected_sha256, allow_reinstall=False):
            reinstall_flags.append(allow_reinstall)
            return SimpleNamespace(action="installed")

    monkeypatch.setattr(
        "deeptutor.plugins.distribution.resolve_catalog_entry",
        lambda *args, **kwargs: _resolved_entry(manifest, artifact),
    )

    CatalogInstallManager(
        downloader_factory=lambda: CatalogArtifactDownloader(
            client_factory=lambda timeout: _client(httpx.Response(200, content=payload))
        ),
        lifecycle_factory=RecordingLifecycle,
    ).install("org.author.example", version="1.0.0", allow_reinstall=True)

    assert reinstall_flags == [True]


def test_default_client_disables_redirects_and_uses_timeout() -> None:
    client = _default_client(2.5)
    try:
        assert client.follow_redirects is False
        assert client.timeout.read == 2.5
        assert client.headers["user-agent"] == "DeepTutor-plugin-catalog/2"
    finally:
        client.close()
