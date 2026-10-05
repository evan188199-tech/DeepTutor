"""Shared retrieval-mode resolution for mode-aware pipelines (LightRAG, GraphRAG).

Resolution order, first valid wins:

1. an explicit ``mode`` kwarg (a one-off override on the search call),
2. the KB's own ``search_mode`` (``kb_config.json`` → ``knowledge_bases[kb]``),
3. the engine's global default mode set from the engine card
   (``kb_config.json`` → ``defaults.provider_modes[provider]``),
4. the engine's built-in default.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional, Sequence

logger = logging.getLogger(__name__)


def resolve_kb_mode(
    kb_base_dir: str | Path,
    kb_name: Optional[str],
    provider: str,
    *,
    explicit: Any = None,
    supported: Sequence[str],
    default: str,
) -> str:
    candidates: list[Any] = [explicit]
    cfg_path = Path(kb_base_dir) / "kb_config.json"
    try:
        if cfg_path.exists():
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            if kb_name:
                entry = data.get("knowledge_bases", {}).get(kb_name, {})
                candidates.append(entry.get("search_mode"))
            candidates.append(data.get("defaults", {}).get("provider_modes", {}).get(provider))
    except Exception as exc:
        # A missing config file is a legal default state (handled by the
        # ``exists()`` check above); an existing but unreadable/unusable one
        # must be visible instead of silently degrading retrieval mode.
        logger.warning(
            "Failed to read %s; falling back to default retrieval mode %r for provider %r: %s",
            cfg_path,
            default,
            provider,
            exc,
        )

    supported_set = {m.lower() for m in supported}
    for candidate in candidates:
        norm = (str(candidate) if candidate else "").strip().lower()
        if norm in supported_set:
            return norm
    return default


__all__ = ["resolve_kb_mode"]
