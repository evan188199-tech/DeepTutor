"""Application service shared by REST, MCP and the local CLI.

External discovery and playback providers deliberately sit behind this layer.
The MVP can be useful with a local library and imports before credentials for
MusicBrainz, ListenBrainz, Podcast Index, Invidious or Yattee are configured;
adding those providers later does not change public contracts or persistence.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Any, Iterable, Sequence
from urllib.parse import parse_qs, urlparse

from defusedxml import ElementTree

from .models import (
    DiscoveryShelf,
    HomeCard,
    HomeSection,
    HomeSectionKind,
    ImportCandidate,
    ImportCandidateStatus,
    ImportJobStatus,
    MediaItem,
    MediaType,
    PlaybackDescriptor,
    PlaylistKind,
    SmartPlaylistRule,
)
from .store import CatalogStore, MediaNotFound, MediaStore, MediaStoreError, PlaylistNotFound, media_id_for


_MBID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_MB_URL_RE = re.compile(
    r"musicbrainz\.org/(?P<kind>recording|release|collection)/(?P<id>[0-9a-f-]{36})", re.I
)
_YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,32}$")


def _digest(value: str, prefix: str) -> str:
    return f"{prefix}:{sha256(value.encode('utf-8')).hexdigest()[:24]}"


def _candidate_id(index: int, raw: str) -> str:
    return f"candidate_{index}_{sha256(raw.encode('utf-8')).hexdigest()[:12]}"


def _title_from_url(value: str) -> str:
    parsed = urlparse(value)
    host = (parsed.hostname or "").removeprefix("www.")
    last = parsed.path.rstrip("/").split("/")[-1]
    return last.replace("-", " ").replace("_", " ").strip() or host or value


def _media_from_candidate(candidate: dict[str, Any]) -> MediaItem:
    canonical_id = str(candidate.get("canonical_id") or "")
    media_type = MediaType(str(candidate.get("media_type") or MediaType.MUSIC.value))
    return MediaItem(
        item_id=media_id_for(canonical_id),
        canonical_id=canonical_id,
        media_type=media_type,
        title=str(candidate.get("title") or canonical_id),
        creator=str(candidate.get("creator") or ""),
        source_url=str(candidate.get("source_url") or candidate.get("source") or ""),
    )


@dataclass(frozen=True)
class ImportResult:
    payload: dict[str, Any]
    is_background: bool = False


class ImportResolver:
    """Parse user-owned import payloads without network access or silent loss."""

    def __init__(self, store: MediaStore) -> None:
        self.store = store

    def preview(self, inputs: Sequence[str]) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for value in inputs:
            candidates.extend(self._preview_input(value))
        if len(candidates) > 500:
            raise MediaStoreError("An import preview may contain at most 500 items. Split the import.")
        return [self._with_duplicate_status(candidate) for candidate in candidates]

    def _preview_input(self, value: str) -> list[dict[str, Any]]:
        raw = value.strip()
        if not raw:
            return []
        if raw.startswith("{") or raw.startswith("["):
            return self._preview_linguawave_json(raw)
        if raw.startswith("<") and "opml" in raw[:500].lower():
            return self._preview_opml(raw)
        if raw.startswith("#EXTM3U"):
            return self._preview_m3u(raw)
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        return [self._preview_scalar(line, index) for index, line in enumerate(lines)]

    def _preview_linguawave_json(self, raw: str) -> list[dict[str, Any]]:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return [self._unrecognized(0, raw, "LinguaWave JSON is invalid.")]
        items = payload.get("items") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            return [self._unrecognized(0, raw, "LinguaWave JSON needs an items array.")]
        results: list[dict[str, Any]] = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                results.append(self._unrecognized(index, str(item), "Item is not an object."))
                continue
            canonical_id = str(item.get("canonical_id") or "").strip()
            media_type = str(item.get("media_type") or "music")
            if not canonical_id or media_type not in {kind.value for kind in MediaType}:
                results.append(self._unrecognized(index, json.dumps(item, ensure_ascii=False), "Missing canonical media identity."))
                continue
            results.append(
                self._candidate(
                    index,
                    source="LinguaWave JSON",
                    status=ImportCandidateStatus.MATCHED,
                    canonical_id=canonical_id,
                    media_type=media_type,
                    title=str(item.get("title") or canonical_id),
                    creator=str(item.get("creator") or ""),
                    source_url=str(item.get("source_url") or ""),
                )
            )
        return results

    def _preview_opml(self, raw: str) -> list[dict[str, Any]]:
        try:
            root = ElementTree.fromstring(raw)
        except Exception:
            return [self._unrecognized(0, "OPML", "OPML is invalid or unsafe.")]
        results: list[dict[str, Any]] = []
        for index, outline in enumerate(root.findall(".//outline")):
            feed = str(outline.attrib.get("xmlUrl") or "").strip()
            title = str(outline.attrib.get("title") or outline.attrib.get("text") or "").strip()
            if not feed.startswith(("http://", "https://")):
                results.append(self._unrecognized(index, feed or title, "OPML outline has no network RSS URL."))
                continue
            results.append(
                self._candidate(
                    index,
                    source=feed,
                    status=ImportCandidateStatus.NEEDS_CONFIRMATION,
                    canonical_id=_digest(feed, "rss"),
                    media_type=MediaType.PODCAST.value,
                    title=title or _title_from_url(feed),
                    detail="Confirm this RSS feed before subscribing.",
                    source_url=feed,
                )
            )
        return results or [self._unrecognized(0, "OPML", "No podcast feeds were found in this OPML document.")]

    def _preview_m3u(self, raw: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        title = ""
        for index, line in enumerate(raw.splitlines()):
            value = line.strip()
            if value.startswith("#EXTINF:"):
                title = value.partition(",")[2].strip()
                continue
            if not value or value.startswith("#"):
                continue
            if not value.startswith(("https://", "http://")):
                results.append(self._unrecognized(index, value, "M3U items must be network URLs."))
                continue
            results.append(
                self._candidate(
                    index,
                    source=value,
                    status=ImportCandidateStatus.NEEDS_CONFIRMATION,
                    canonical_id=_digest(value, "m3u"),
                    media_type=MediaType.MUSIC.value,
                    title=title or _title_from_url(value),
                    detail="Confirm this network media URL before adding it.",
                    source_url=value,
                )
            )
            title = ""
        return results or [self._unrecognized(0, "M3U", "No network media URLs were found in this M3U file.")]

    def _preview_scalar(self, raw: str, index: int) -> dict[str, Any]:
        mbid_match = _MB_URL_RE.search(raw)
        if mbid_match:
            kind = mbid_match.group("kind").lower()
            identifier = mbid_match.group("id").lower()
            if kind == "recording":
                return self._candidate(
                    index, source=raw, status=ImportCandidateStatus.MATCHED,
                    canonical_id=f"mbid:recording:{identifier}", media_type=MediaType.MUSIC.value,
                    title=f"MusicBrainz recording {identifier}", detail="Recording metadata will be refreshed from MusicBrainz.", source_url=raw,
                )
            return self._candidate(
                index, source=raw, status=ImportCandidateStatus.NEEDS_CONFIRMATION,
                canonical_id=f"mbid:{kind}:{identifier}", media_type=MediaType.MUSIC.value,
                title=f"MusicBrainz {kind} {identifier}", detail=f"Expand this MusicBrainz {kind} after confirmation.", source_url=raw,
            )
        if _MBID_RE.fullmatch(raw):
            identifier = raw.lower()
            return self._candidate(
                index, source=raw, status=ImportCandidateStatus.MATCHED,
                canonical_id=f"mbid:recording:{identifier}", media_type=MediaType.MUSIC.value,
                title=f"MusicBrainz recording {identifier}", detail="Recording metadata will be refreshed from MusicBrainz.",
            )
        parsed = urlparse(raw)
        if parsed.scheme in {"http", "https"}:
            host = (parsed.hostname or "").lower()
            query = parse_qs(parsed.query)
            if host.endswith("youtube.com") or host == "youtu.be":
                video_id = (query.get("v") or [parsed.path.strip("/").split("/")[-1]])[0]
                playlist_id = (query.get("list") or [""])[0]
                if playlist_id:
                    return self._candidate(
                        index, source=raw, status=ImportCandidateStatus.NEEDS_CONFIRMATION,
                        canonical_id=f"youtube:playlist:{playlist_id}", media_type=MediaType.MUSIC.value,
                        title="YouTube playlist", detail="Playlist items will be resolved after confirmation.", source_url=raw,
                    )
                if _YOUTUBE_ID_RE.fullmatch(video_id):
                    return self._candidate(
                        index, source=raw, status=ImportCandidateStatus.MATCHED,
                        canonical_id=f"youtube:video:{video_id}", media_type=MediaType.MUSIC.value,
                        title=f"YouTube media {video_id}", detail="Audio playback uses configured Invidious or Yattee sources.", source_url=raw,
                    )
            if host == "podcastindex.org" and parsed.path.rstrip("/").split("/")[-1].isdigit():
                identifier = parsed.path.rstrip("/").split("/")[-1]
                return self._candidate(
                    index, source=raw, status=ImportCandidateStatus.NEEDS_CONFIRMATION,
                    canonical_id=f"podcastindex:{identifier}", media_type=MediaType.PODCAST.value,
                    title=f"Podcast Index {identifier}", detail="Podcast metadata will be resolved after confirmation.", source_url=raw,
                )
            lower_path = parsed.path.lower()
            if lower_path.endswith((".rss", ".xml")) or "feed" in lower_path:
                return self._candidate(
                    index, source=raw, status=ImportCandidateStatus.NEEDS_CONFIRMATION,
                    canonical_id=_digest(raw, "rss"), media_type=MediaType.PODCAST.value,
                    title=_title_from_url(raw), detail="Confirm this RSS feed before subscribing.", source_url=raw,
                )
            return self._candidate(
                index, source=raw, status=ImportCandidateStatus.NEEDS_CONFIRMATION,
                canonical_id=_digest(raw, "url"), media_type=MediaType.MUSIC.value,
                title=_title_from_url(raw), detail="Confirm the media URL before adding it.", source_url=raw,
            )
        if raw.lower().startswith("podcastindex:"):
            identifier = raw.split(":", 1)[1].strip()
            if identifier.isdigit():
                return self._candidate(
                    index, source=raw, status=ImportCandidateStatus.NEEDS_CONFIRMATION,
                    canonical_id=f"podcastindex:{identifier}", media_type=MediaType.PODCAST.value,
                    title=f"Podcast Index {identifier}", detail="Podcast metadata will be resolved after confirmation.",
                )
        if " - " in raw:
            creator, _, title = raw.partition(" - ")
            return self._candidate(
                index, source=raw, status=ImportCandidateStatus.NEEDS_CONFIRMATION,
                canonical_id=_digest(raw, "text"), media_type=MediaType.MUSIC.value,
                title=title.strip(), creator=creator.strip(), detail="Confirm the title and artist match before adding it.",
            )
        return self._unrecognized(index, raw, "Recognized formats include MusicBrainz, YouTube, RSS, OPML, M3U and LinguaWave JSON.")

    def _candidate(
        self,
        index: int,
        *,
        source: str,
        status: ImportCandidateStatus,
        canonical_id: str = "",
        media_type: str | None = None,
        title: str = "",
        creator: str = "",
        detail: str = "",
        source_url: str = "",
    ) -> dict[str, Any]:
        return {
            "candidate_id": _candidate_id(index, source), "status": status.value, "source": source,
            "canonical_id": canonical_id, "media_type": media_type, "title": title,
            "creator": creator, "detail": detail, "source_url": source_url,
        }

    def _unrecognized(self, index: int, source: str, detail: str) -> dict[str, Any]:
        return self._candidate(index, source=source, status=ImportCandidateStatus.UNRECOGNIZED, detail=detail)

    def _with_duplicate_status(self, candidate: dict[str, Any]) -> dict[str, Any]:
        canonical_id = str(candidate.get("canonical_id") or "")
        if canonical_id and self.store.get_media_by_canonical_id(canonical_id) is not None:
            return {**candidate, "status": ImportCandidateStatus.DUPLICATE.value, "detail": "Already in your library."}
        return candidate


class HomeFeedAssembler:
    """Backend-owned composition rules for the client-rendered home feed."""

    def __init__(self, store: MediaStore) -> None:
        self.store = store

    @staticmethod
    def _card_for_media(media: MediaItem, *, reason: str = "") -> HomeCard:
        progress = None
        if media.duration_seconds > 0:
            progress = min(1.0, media.playback_position_seconds / media.duration_seconds)
        return HomeCard(
            card_id=f"media:{media.item_id}", title=media.title,
            subtitle=media.creator or media.collection_title, artwork_url=media.artwork_url,
            action="play", media=media, progress=progress, reason=reason,
        )

    def build(self, *, content_filter: str = "all", offline: bool = False) -> list[HomeSection]:
        all_media = self.store.list_media(limit=300)
        media = self._filter(all_media, content_filter)
        downloaded = [item for item in media if item.is_downloaded]
        in_progress = [item for item in media if item.playback_position_seconds > 0 and item.learning_progress < 1]
        learning = [item for item in media if item.learning_progress < 1 and item.item_id in {row["item_id"] for row in self._with_timed_text(media)}]
        sections: list[HomeSection] = []
        quick_cards = self._quick_start(in_progress, media, downloaded, learning)
        if offline and downloaded:
            sections.append(HomeSection(section_id="offline", kind=HomeSectionKind.OFFLINE, title="离线可听", display="shelf", cards=[self._card_for_media(item, reason="已下载") for item in downloaded[:12]]))
        sections.append(HomeSection(section_id="quick_start", kind=HomeSectionKind.QUICK_START, title="快速开始", display="grid", cards=quick_cards))
        if in_progress:
            sections.append(HomeSection(section_id="continue", kind=HomeSectionKind.CONTINUE_PLAYING, title="继续播放", display="hero", cards=[self._card_for_media(in_progress[0], reason="从上次的位置继续")] + [self._card_for_media(item) for item in in_progress[1:8]]))
        playlists = self.store.list_playlists()
        playlist_cards = [
            HomeCard(card_id=f"playlist:{playlist['playlist_id']}", title=str(playlist["name"]), subtitle=f"{playlist['item_count']} 项", action="open_playlist")
            for playlist in playlists[:12]
        ]
        if playlist_cards:
            sections.append(HomeSection(section_id="playlists", kind=HomeSectionKind.PLAYLISTS, title="你的播放清单", display="shelf", cards=playlist_cards))
        subscription_cards = self._subscription_cards(media)
        if subscription_cards:
            sections.append(HomeSection(section_id="subscriptions", kind=HomeSectionKind.SUBSCRIPTION_UPDATES, title="订阅有更新", display="shelf", cards=subscription_cards))
        recommendation_cards = [self._card_for_media(item, reason="来自你的资料库和学习偏好") for item in media[:12] if item not in in_progress]
        if recommendation_cards:
            sections.append(HomeSection(section_id="recommendations", kind=HomeSectionKind.RECOMMENDATIONS, title="为你推荐", display="shelf", cards=recommendation_cards))
        if learning:
            sections.append(HomeSection(section_id="learning", kind=HomeSectionKind.CONTINUE_LEARNING, title="继续学习", display="shelf", cards=[self._card_for_media(item, reason="还有可学习的文字片段") for item in learning[:12]]))
        if not offline and downloaded:
            sections.append(HomeSection(section_id="offline", kind=HomeSectionKind.OFFLINE, title="离线可听", display="shelf", cards=[self._card_for_media(item, reason="已下载") for item in downloaded[:12]]))
        return sections

    def _with_timed_text(self, media: Sequence[MediaItem]) -> Iterable[dict[str, Any]]:
        for item in media:
            text = self.store.get_timed_text(item.item_id)
            if text["status"] == "ready":
                yield {"item_id": item.item_id}

    def _quick_start(self, in_progress: list[MediaItem], media: list[MediaItem], downloaded: list[MediaItem], learning: list[MediaItem]) -> list[HomeCard]:
        cards: list[HomeCard] = []
        choices: list[tuple[str, str, MediaItem | None]] = [
            ("继续播放", "上次离开的位置", in_progress[0] if in_progress else None),
            ("每日音乐", "为今天准备", next((item for item in media if item.media_type == MediaType.MUSIC), None)),
            ("最新播客", "订阅节目更新", next((item for item in media if item.media_type == MediaType.EPISODE), None)),
            ("最近添加", "刚加入资料库", media[0] if media else None),
            ("已下载", "无需网络", downloaded[0] if downloaded else None),
            ("待学习", "从上次的片段继续", learning[0] if learning else None),
        ]
        for key, subtitle, item in choices:
            cards.append(HomeCard(card_id=f"quick:{key}", title=key, subtitle=subtitle, action="play" if item else "open", media=item))
        return cards

    def _subscription_cards(self, media: Sequence[MediaItem]) -> list[HomeCard]:
        subscriptions = self.store.list_subscriptions()
        source_urls = [str(subscription["source_url"]) for subscription in subscriptions if subscription["source_url"]]
        matches = [
            item for item in media
            if item.media_type == MediaType.EPISODE and any(item.source_url.startswith(source) for source in source_urls)
        ]
        return [self._card_for_media(item, reason="你订阅的节目") for item in matches[:12]]

    @staticmethod
    def _filter(items: list[MediaItem], content_filter: str) -> list[MediaItem]:
        if content_filter == "music":
            return [item for item in items if item.media_type == MediaType.MUSIC]
        if content_filter == "podcast":
            return [item for item in items if item.media_type in {MediaType.PODCAST, MediaType.EPISODE}]
        if content_filter == "learning":
            return [item for item in items if item.learning_progress < 1]
        return items


class MediaService:
    def __init__(self, store: MediaStore | None = None, catalog: CatalogStore | None = None) -> None:
        self.store = store or MediaStore()
        self.catalog = catalog or CatalogStore()

    def bootstrap(self) -> dict[str, Any]:
        self.store.ensure_system_playlists()
        return {
            "schema_version": 1,
            "playlists": self.store.list_playlists(),
            "providers": {
                "musicbrainz": "cache_ready", "listenbrainz": "optional", "podcast_index": "optional",
                "invidious": "optional", "yattee": "optional",
            },
            "features": {"video_switching": True, "smart_playlists": True, "import_preview": True},
        }

    def home(self, *, content_filter: str = "all", offline: bool = False) -> list[HomeSection]:
        if content_filter not in {"all", "music", "podcast", "learning"}:
            raise MediaStoreError("Unsupported home filter.")
        return HomeFeedAssembler(self.store).build(content_filter=content_filter, offline=offline)

    def discover(self, *, category: str = "recommended") -> list[DiscoveryShelf]:
        if category not in {"recommended", "music", "podcast", "topic"}:
            raise MediaStoreError("Unsupported discovery category.")
        media = self.store.list_media(limit=60)
        shelves: list[DiscoveryShelf] = []
        if category in {"recommended", "music"}:
            music = [item for item in media if item.media_type == MediaType.MUSIC]
            shelves.append(DiscoveryShelf(shelf_id="music_mix", title="基于你的种子的 Mix", category="music", cards=[HomeFeedAssembler._card_for_media(item, reason="来自最近播放与收藏") for item in music[:12]]))
            shelves.append(DiscoveryShelf(shelf_id="music_new", title="新发行与热门 Recording", category="music", cards=[HomeFeedAssembler._card_for_media(item, reason="目录缓存") for item in music[12:24]]))
        if category in {"recommended", "podcast"}:
            podcasts = [item for item in media if item.media_type in {MediaType.PODCAST, MediaType.EPISODE}]
            shelves.append(DiscoveryShelf(shelf_id="podcast_trending", title="播客热门与新节目", category="podcast", cards=[HomeFeedAssembler._card_for_media(item, reason="订阅主题") for item in podcasts[:12]]))
        if category in {"recommended", "topic"}:
            shelves.append(DiscoveryShelf(shelf_id="topics", title="类型与学习主题", category="topic", cards=[HomeCard(card_id=f"topic:{name}", title=name, subtitle="浏览并个性化排序", action="open_topic") for name in ("科技", "文化", "语言", "新闻", "流行", "古典")]))
        return [shelf for shelf in shelves if shelf.cards or shelf.category == "topic"]

    def search(self, query: str, *, limit: int = 30) -> list[MediaItem]:
        local = self.store.list_media(limit=limit, query=query)
        catalog = self.catalog.search(query, limit=limit)
        result: list[MediaItem] = []
        seen: set[str] = set()
        for item in [*local, *catalog]:
            if item.canonical_id not in seen:
                seen.add(item.canonical_id)
                result.append(item)
        return result[:limit]

    def library(self) -> dict[str, Any]:
        media = self.store.list_media(limit=500)
        return {
            "items": media,
            "playlists": self.store.list_playlists(),
            "subscriptions": self.store.list_subscriptions(),
            "downloads": [item for item in media if item.is_downloaded],
            "favorites": [item for item in media if item.is_favorite],
        }

    def add_local_item(self, payload: dict[str, Any]) -> MediaItem:
        canonical_id = str(payload.get("canonical_id") or _digest(str(payload.get("source_url") or payload.get("title") or ""), "local"))
        item = MediaItem(
            item_id=media_id_for(canonical_id), canonical_id=canonical_id,
            media_type=MediaType.LOCAL, title=str(payload.get("title") or "本地音频"),
            creator=str(payload.get("creator") or ""), source_url=str(payload.get("source_url") or ""),
            duration_seconds=float(payload.get("duration_seconds") or 0), language=str(payload.get("language") or ""),
        )
        saved = self.store.upsert_media(item)
        self.catalog.upsert(saved)
        return saved

    # -- playlist API ----------------------------------------------------

    def create_playlist(self, payload: dict[str, Any]) -> dict[str, Any]:
        kind = PlaylistKind(str(payload.get("kind") or PlaylistKind.MANUAL.value))
        rule = SmartPlaylistRule.model_validate(payload.get("rule") or {}) if kind == PlaylistKind.SMART else None
        return self.store.create_playlist(name=str(payload["name"]), description=str(payload.get("description") or ""), kind=kind, pinned=bool(payload.get("pinned")), rule=rule)

    def playlist_detail(self, playlist_id: str) -> dict[str, Any]:
        return {**self.store.get_playlist_row(playlist_id), "items": self.store.get_playlist_items(playlist_id)}

    def update_playlist(self, playlist_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        has_rule = "rule" in payload and payload["rule"] is not None
        rule = SmartPlaylistRule.model_validate(payload["rule"]) if has_rule else None
        return self.store.update_playlist(playlist_id, name=payload.get("name"), description=payload.get("description"), pinned=payload.get("pinned"), rule=rule)

    def add_playlist_items(self, playlist_id: str, canonical_ids: Sequence[str], *, added_from: str = "manual", note: str = "") -> list[dict[str, Any]]:
        return self.store.add_playlist_items(playlist_id, canonical_ids, added_from=added_from, note=note)

    # -- imports ---------------------------------------------------------

    def preview_import(self, inputs: Sequence[str], *, target_playlist_id: str | None, playlist_name: str) -> dict[str, Any]:
        if target_playlist_id:
            self.store.get_playlist_row(target_playlist_id)
        candidates = ImportResolver(self.store).preview(inputs)
        return self.store.save_import_preview(candidates=candidates, target_playlist_id=target_playlist_id, suggested_playlist_name=playlist_name or "导入的播放清单")

    def apply_import(
        self,
        *,
        preview_token: str,
        selected_candidate_ids: Sequence[str] | None,
        target_playlist_id: str | None,
        playlist_name: str,
        idempotency_key: str,
        background: bool = False,
    ) -> ImportResult:
        if not idempotency_key.strip():
            raise MediaStoreError("Idempotency-Key is required for imports.")
        replay = self.store.get_idempotent_response(idempotency_key, "apply_import")
        if replay is not None:
            return ImportResult(replay, is_background=replay.get("status") == ImportJobStatus.QUEUED.value)
        preview = self.store.get_import_preview(preview_token)
        candidates = preview["candidates"]
        selected = set(selected_candidate_ids or [str(candidate["candidate_id"]) for candidate in candidates])
        accepted = [
            candidate for candidate in candidates
            if candidate.get("candidate_id") in selected
            and candidate.get("status") in {ImportCandidateStatus.MATCHED.value, ImportCandidateStatus.NEEDS_CONFIRMATION.value}
        ]
        if not accepted:
            raise MediaStoreError("Select at least one matched or confirmed import candidate.")
        if len(accepted) > 500:
            raise MediaStoreError("Imports over 500 items must be split.")
        if len(accepted) > 100 or background:
            job = self.store.create_import_job(preview_token)
            self.store.save_idempotent_response(idempotency_key, "apply_import", job)
            return ImportResult(job, is_background=True)
        payload = self._apply_import_now(preview, accepted, target_playlist_id, playlist_name)
        self.store.consume_import_preview(preview_token)
        self.store.save_idempotent_response(idempotency_key, "apply_import", payload)
        return ImportResult(payload)

    def run_import_job(self, job_id: str, *, target_playlist_id: str | None = None, playlist_name: str = "") -> dict[str, Any]:
        job = self.store.get_import_job(job_id)
        preview = self.store.get_import_preview(str(job["preview_token"]))
        self.store.update_import_job(job_id, status=ImportJobStatus.RUNNING)
        accepted = [
            candidate for candidate in preview["candidates"]
            if candidate.get("status") in {ImportCandidateStatus.MATCHED.value, ImportCandidateStatus.NEEDS_CONFIRMATION.value}
        ]
        try:
            applied = self._apply_import_now(preview, accepted, target_playlist_id, playlist_name)
            self.store.consume_import_preview(str(job["preview_token"]))
            return self.store.update_import_job(job_id, status=ImportJobStatus.COMPLETED, playlist_id=applied.get("playlist_id"), imported=int(applied.get("imported_item_count") or 0), failed=int(applied.get("failed_item_count") or 0))
        except Exception as exc:
            return self.store.update_import_job(job_id, status=ImportJobStatus.FAILED, error=str(exc))

    def _apply_import_now(self, preview: dict[str, Any], accepted: Sequence[dict[str, Any]], target_playlist_id: str | None, playlist_name: str) -> dict[str, Any]:
        playlist_id = target_playlist_id or preview.get("target_playlist_id")
        if playlist_id:
            playlist = self.store.get_playlist_row(str(playlist_id))
            if playlist["kind"] not in {PlaylistKind.MANUAL.value, PlaylistKind.EXTERNAL_IMPORT.value}:
                raise MediaStoreError("Imports require a manual playlist target.")
        else:
            playlist = self.store.create_playlist(
                name=playlist_name or str(preview.get("suggested_playlist_name") or "导入的播放清单"),
                description="通过 LinguaWave 导入", kind=PlaylistKind.EXTERNAL_IMPORT,
            )
            playlist_id = playlist["playlist_id"]
        canonical_ids: list[str] = []
        failures = 0
        for candidate in accepted:
            try:
                item = _media_from_candidate(candidate)
                saved = self.store.upsert_media(item)
                self.catalog.upsert(saved)
                canonical_ids.append(saved.canonical_id)
            except Exception:
                failures += 1
        if canonical_ids:
            self.store.add_playlist_items(str(playlist_id), canonical_ids, added_from="import", note="")
        return {
            "playlist_id": playlist_id, "status": "completed", "imported_item_count": len(canonical_ids),
            "failed_item_count": failures, "playlist": self.playlist_detail(str(playlist_id)),
        }

    # -- media playback, text and sync ---------------------------------

    def resolve_recording(self, mbid: str, *, persist: bool = True) -> dict[str, Any]:
        if not _MBID_RE.fullmatch(mbid):
            raise MediaStoreError("MusicBrainz Recording MBID is invalid.")
        canonical_id = f"mbid:recording:{mbid.lower()}"
        existing = self.store.get_media_by_canonical_id(canonical_id)
        item = existing or MediaItem(
            item_id=media_id_for(canonical_id),
            canonical_id=canonical_id,
            media_type=MediaType.MUSIC,
            title=f"MusicBrainz recording {mbid.lower()}",
        )
        if persist and existing is None:
            item = self.store.upsert_media(item)
            self.catalog.upsert(item)
        return {"item": item, "sources": self.store.list_source_mappings(canonical_id)}

    def playback(self, item_id: str) -> PlaybackDescriptor:
        item = self.store.get_media(item_id)
        if item.media_type in {MediaType.PODCAST, MediaType.EPISODE} and item.source_url:
            return PlaybackDescriptor(kind="audio", provider="rss", stream_url=item.source_url, supports_video=False)
        if item.media_type == MediaType.LOCAL and item.source_url:
            return PlaybackDescriptor(kind="local", provider="local", stream_url=item.source_url)
        mappings = self.store.list_source_mappings(item.canonical_id)
        preferred = next((mapping for mapping in mappings if mapping["preferred"]), None)
        source = preferred or next((mapping for mapping in mappings if mapping["confirmed"]), None)
        if source:
            return PlaybackDescriptor(kind="audio", provider=str(source["provider"]), stream_url=str(source["source_url"]), supports_video=True)
        return PlaybackDescriptor(kind="unavailable", reason="Resolve an Invidious or Yattee source before playback.")

    def resolve_feed(self, source_url: str, *, title: str = "", language: str = "") -> dict[str, Any]:
        if not source_url.startswith(("http://", "https://")):
            raise MediaStoreError("Podcast feed must use HTTP or HTTPS.")
        feed_id = _digest(source_url, "rss")
        return {"feed_id": feed_id, "title": title or _title_from_url(source_url), "source_url": source_url, "language": language}


__all__ = ["HomeFeedAssembler", "ImportResolver", "ImportResult", "MediaService"]
