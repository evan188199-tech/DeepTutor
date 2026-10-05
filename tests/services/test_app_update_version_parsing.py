from __future__ import annotations

import httpx
import pytest

from deeptutor.__version__ import __version__
from deeptutor.services.app_update import (
    ReleaseInfo,
    VersionCheckError,
    VersionCheckResult,
    VersionCheckService,
    _normalise_stable_version,
    _release_from_latest_url,
    _release_from_payload,
    _version_tuple,
)

GITHUB_RELEASE_URL = "https://github.com/HKUDS/DeepTutor/releases/tag/v1.7.0"


def _github_release(**overrides: object) -> dict:
    payload = {
        "tag_name": "v1.7.0",
        "name": "DeepTutor 1.7",
        "published_at": "2026-08-30T00:00:00Z",
        "html_url": GITHUB_RELEASE_URL,
        "body": "A stable release.",
        "draft": False,
        "prerelease": False,
    }
    payload.update(overrides)
    return payload


def _pypi_json(version: str = "1.7.0") -> dict:
    return {
        "info": {"name": "deeptutor", "version": version, "summary": "PyPI JSON payload"},
        "urls": [],
    }


def _canned_transport(payload: object, *, status_code: int = 200):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=payload)

    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _release_info(version: str) -> ReleaseInfo:
    return ReleaseInfo(
        version=version,
        name=f"DeepTutor {version}",
        published_at="",
        url=f"https://github.com/HKUDS/DeepTutor/releases/tag/v{version}",
        excerpt="",
        migration_warning=False,
    )


def _check_result(current: str, release: str) -> VersionCheckResult:
    return VersionCheckResult(
        current_version=current,
        release=_release_info(release),
        checked_at="",
        cached=False,
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param("1.6.1", (1, 6, 1), id="plain-patch"),
        pytest.param("v1.6.1", (1, 6, 1), id="v-prefix"),
        pytest.param("  v2.0.0  ", (2, 0, 0), id="surrounding-whitespace"),
        pytest.param("v01.02.03", (1, 2, 3), id="zero-padding"),
        pytest.param("1.6.1rc1", (1, 6, 1), id="pre-release-suffix-truncated"),
        pytest.param("1.6.1.5", (1, 6, 1), id="extra-components-truncated"),
        pytest.param("10.20.30", (10, 20, 30), id="multi-digit"),
    ],
)
def test_version_tuple_parses_boundaries(raw: str, expected: tuple[int, int, int]) -> None:
    assert _version_tuple(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param("1.6", id="two-components"),
        pytest.param("", id="empty"),
        pytest.param("latest", id="non-numeric"),
        pytest.param("v", id="prefix-only"),
    ],
)
def test_version_tuple_rejects_malformed_versions(raw: str) -> None:
    with pytest.raises(ValueError, match="Invalid DeepTutor version"):
        _version_tuple(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param("1.7.0", "1.7.0", id="plain"),
        pytest.param("v1.7.0", "1.7.0", id="v-prefix-stripped"),
        pytest.param(" 1.7.0 ", "1.7.0", id="whitespace-stripped"),
        pytest.param("v01.02.03", "01.02.03", id="zero-padding-preserved-in-tag"),
    ],
)
def test_normalise_stable_version_accepts_stable_tags(raw: str, expected: str) -> None:
    assert _normalise_stable_version(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param("1.7.0rc1", id="pre-release"),
        pytest.param("1.7.0-beta", id="hyphen-suffix"),
        pytest.param("1.7", id="two-components"),
        pytest.param("1.7.0.1", id="four-components"),
        pytest.param("nightly", id="moving-tag"),
    ],
)
def test_normalise_stable_version_rejects_unstable_tags(raw: str) -> None:
    with pytest.raises(ValueError, match="stable semantic version"):
        _normalise_stable_version(raw)


@pytest.mark.parametrize(
    ("current", "release", "expected"),
    [
        pytest.param("1.6.1", "1.7.0", True, id="newer-minor"),
        pytest.param("1.6.1", "1.6.2", True, id="newer-patch"),
        pytest.param("1.6.1", "2.0.0", True, id="newer-major"),
        pytest.param("1.6.1", "1.6.1", False, id="same-version"),
        pytest.param("1.6.1", "1.6.0", False, id="older-release"),
        pytest.param("v1.6.1", "1.7.0", True, id="v-prefixed-current"),
        pytest.param("1.10.0", "1.9.0", False, id="numeric-not-lexical"),
        pytest.param("1.6.1rc1", "1.6.1", False, id="pre-release-current-truncated"),
    ],
)
def test_update_available_compares_semantically(current: str, release: str, expected: bool) -> None:
    assert _check_result(current, release).update_available is expected


def test_github_release_payload_parses_all_fields() -> None:
    release = _release_from_payload(_github_release(tag_name="1.7.0"))

    assert release.version == "1.7.0"
    assert release.name == "DeepTutor 1.7"
    assert release.published_at == "2026-08-30T00:00:00Z"
    assert release.url == GITHUB_RELEASE_URL
    assert release.excerpt == "A stable release."
    assert release.migration_warning is False


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        pytest.param({"draft": True}, "latest stable release is unavailable", id="draft-release"),
        pytest.param(
            {"prerelease": True},
            "latest stable release is unavailable",
            id="prerelease-flag",
        ),
        pytest.param({"tag_name": ""}, "invalid version", id="missing-tag"),
        pytest.param({"tag_name": "v1.7"}, "invalid version", id="unstable-tag"),
        pytest.param({"html_url": ""}, "invalid URL", id="missing-url"),
        pytest.param(
            {"html_url": "https://example.com/releases/tag/v1.7.0"},
            "invalid URL",
            id="foreign-url",
        ),
    ],
)
def test_github_release_payload_rejects_malformed_entries(overrides: dict, match: str) -> None:
    with pytest.raises(VersionCheckError, match=match):
        _release_from_payload(_github_release(**overrides))


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(None, id="null-body"),
        pytest.param([], id="array-body"),
        pytest.param("release", id="string-body"),
        pytest.param({}, id="empty-object"),
    ],
)
def test_release_payload_rejects_non_release_shapes(payload: object) -> None:
    with pytest.raises(VersionCheckError):
        _release_from_payload(payload)


def test_github_release_payload_defaults_optional_fields() -> None:
    release = _release_from_payload({"tag_name": "v1.7.0", "html_url": GITHUB_RELEASE_URL})

    assert release.version == "1.7.0"
    assert release.name == ""
    assert release.published_at == ""
    assert release.excerpt == ""
    assert release.migration_warning is False


def test_release_body_normalises_windows_line_endings() -> None:
    release = _release_from_payload(
        _github_release(body="Line one.\r\n\r\nBreaking changes ahead.\r\n")
    )

    assert release.migration_warning is True
    assert "Line one." in release.excerpt


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param("Breaking changes in this release.", True, id="breaking-changes"),
        pytest.param("Migration needed: back up first.", True, id="migration-needed"),
        pytest.param("A database migration ships with this release.", True, id="db-migration"),
        pytest.param("Run migration scripts before starting.", True, id="run-migration"),
        pytest.param("Please migrate your data first.", True, id="migrate-your"),
        pytest.param("Minor fixes only.", False, id="no-migration"),
    ],
)
def test_migration_warning_detection(body: str, expected: bool) -> None:
    release = _release_from_payload(_github_release(body=body))

    assert release.migration_warning is expected


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(_pypi_json(), id="pypi-json"),
        pytest.param({"info": {"version": "1.7.0"}}, id="pypi-info-only"),
        pytest.param({"releases": {"1.7.0": []}}, id="pypi-releases-only"),
    ],
)
def test_pypi_json_payload_is_not_a_github_release(payload: object) -> None:
    with pytest.raises(VersionCheckError):
        _release_from_payload(payload)


@pytest.mark.parametrize(
    ("url", "expected_version"),
    [
        pytest.param(
            "https://github.com/HKUDS/DeepTutor/releases/tag/v1.6.1",
            "1.6.1",
            id="https-default-port",
        ),
        pytest.param(
            "https://github.com:443/HKUDS/DeepTutor/releases/tag/v1.6.1",
            "1.6.1",
            id="explicit-443-port",
        ),
        pytest.param(
            "https://github.com/HKUDS/DeepTutor/releases/tag/1.6.1",
            "1.6.1",
            id="unprefixed-tag",
        ),
    ],
)
def test_latest_redirect_url_resolves_stable_release(url: str, expected_version: str) -> None:
    release = _release_from_latest_url(url)

    assert release.version == expected_version
    assert release.name == f"DeepTutor {expected_version}"
    assert release.published_at == ""
    assert release.excerpt == ""
    assert release.migration_warning is False


@pytest.mark.parametrize(
    "url",
    [
        pytest.param(
            "http://github.com/HKUDS/DeepTutor/releases/tag/v1.6.1",
            id="plain-http-scheme",
        ),
        pytest.param(
            "https://example.com/HKUDS/DeepTutor/releases/tag/v1.6.1",
            id="foreign-host",
        ),
        pytest.param(
            "https://user:pass@github.com/HKUDS/DeepTutor/releases/tag/v1.6.1",
            id="embedded-userinfo",
        ),
        pytest.param(
            "https://github.com:8080/HKUDS/DeepTutor/releases/tag/v1.6.1",
            id="non-standard-port",
        ),
        pytest.param(
            "https://github.com:evil.com/HKUDS/DeepTutor/releases/tag/v1.6.1",
            id="non-numeric-port",
        ),
        pytest.param(
            "https://github.com/HKUDS/DeepTutor/releases/latest",
            id="untagged-latest-path",
        ),
        pytest.param(
            "https://github.com/HKUDS/DeepTutor/releases/tag/v1.6.1-beta",
            id="pre-release-tag",
        ),
        pytest.param(
            "https://github.com/HKUDS/DeepTutor/releases/tag/dir/v1.6.1",
            id="nested-tag-path",
        ),
    ],
)
def test_latest_redirect_url_rejects_untrusted_or_unstable_urls(url: str) -> None:
    with pytest.raises(VersionCheckError):
        _release_from_latest_url(url)


@pytest.mark.asyncio
async def test_github_canned_response_resolves_latest_release() -> None:
    service = VersionCheckService(client_factory=_canned_transport(_github_release()))

    result = await service.check(force=True)

    assert result.current_version == __version__
    assert result.cached is False
    assert result.release.version == "1.7.0"
    assert result.release.url == GITHUB_RELEASE_URL


@pytest.mark.asyncio
async def test_pypi_json_canned_response_raises_check_error() -> None:
    service = VersionCheckService(client_factory=_canned_transport(_pypi_json()))

    with pytest.raises(VersionCheckError):
        await service.check(force=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("elapsed", "expected_cached"),
    [
        pytest.param(0.0, True, id="just-checked"),
        pytest.param(86_399.0, True, id="within-ttl"),
        pytest.param(86_400.0, False, id="ttl-expired"),
    ],
)
async def test_cached_release_respects_ttl_boundary(elapsed: float, expected_cached: bool) -> None:
    now = {"t": 100.0}
    service = VersionCheckService(
        client_factory=_canned_transport(_github_release()),
        clock=lambda: now["t"],
    )
    await service.check(force=True)
    now["t"] = 100.0 + elapsed

    cached = service.cached()

    assert (cached is not None) is expected_cached
    if cached is not None:
        assert cached.cached is True
        assert cached.release.version == "1.7.0"
