#!/usr/bin/env python3
"""Collect retry / backoff / timeout parameter evidence for AGEN-896.

Scans a fixed list of (file, regex, label) probes against the DeepTutor
source tree and emits one JSON record per hit:

    {"id", "group", "file", "line", "label", "value", "text"}

The probe list is intentionally explicit: every row cited in
``report.md`` must be reproducible from this script alone.  Usage:

    python3 collect_retry_params.py <repo-root> > ../data/retry-params.json

Exit code 0 when every probe matched at least once, 1 otherwise, so the
run fails loudly if the source layout drifted.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# (probe id, group, repo-relative file, regex, capture group name or None)
PROBES: list[tuple[str, str, str, str, str | None]] = [
    # ---- LLM provider core: outer retry policy -------------------------
    ("llm-settings-retries", "llm", "deeptutor/config/settings.py",
     r"max_retries: int = Field\(default=(\d+)", "max_retries"),
    ("llm-settings-delay", "llm", "deeptutor/config/settings.py",
     r"base_delay: float = Field\(default=([\d.]+)", "base_delay"),
    ("llm-settings-doc-retries", "llm", "deeptutor/config/settings.py",
     r"LLM_RETRY__MAX_RETRIES: Maximum retry attempts .*\(default: (\d+)\)", "doc_default"),
    ("llm-factory-defaults", "llm", "deeptutor/services/llm/factory.py",
     r"DEFAULT_MAX_RETRIES = settings\.retry\.max_retries", None),
    ("llm-factory-retry-delays", "llm", "deeptutor/services/llm/factory.py",
     r"delay = base \* \(2\*\*attempt\) if exponential_backoff else base", None),
    ("llm-factory-cap", "llm", "deeptutor/services/llm/factory.py",
     r"delays\.append\(min\(delay, ([\d.]+)\)\)", "cap_s"),
    ("llm-base-fallback-delays", "llm", "deeptutor/services/llm/provider_core/base.py",
     r"_CHAT_RETRY_DELAYS = \((.+)\)", "delays"),
    ("llm-base-retryable-status", "llm", "deeptutor/services/llm/provider_core/base.py",
     r"_RETRYABLE_HTTP_STATUS_CODES = frozenset\(\{(.+)\}\)", "codes"),
    ("llm-base-sleep", "llm", "deeptutor/services/llm/provider_core/base.py",
     r"await asyncio\.sleep\(delay\)", None),
    # ---- SDK-level retry budgets ---------------------------------------
    ("llm-sdk-openai-compat", "llm", "deeptutor/services/llm/provider_core/openai_compat_provider.py",
     r"sdk_max_retries=(\d+)", "sdk_max_retries"),
    ("llm-sdk-azure", "llm", "deeptutor/services/llm/provider_core/azure_openai_provider.py",
     r"max_retries=(\d+),", "max_retries"),
    ("llm-sdk-anthropic", "llm", "deeptutor/services/llm/provider_core/anthropic_provider.py",
     r'client_kw: dict\[str, Any\] = \{"max_retries": (\d+)\}', "max_retries"),
    ("llm-sdk-agentic-default", "llm", "deeptutor/runtime/agentic/client.py",
     r"sdk_max_retries: int \| None = None", None),
    ("llm-sdk-agentic-keypool", "llm", "deeptutor/runtime/agentic/client.py",
     r"sdk_max_retries=0,", None),
    # ---- stream stall guards -------------------------------------------
    ("stall-openai-compat", "llm", "deeptutor/services/llm/provider_core/openai_compat_provider.py",
     r"idle_timeout_s = (\d+)", "idle_s"),
    ("stall-azure", "llm", "deeptutor/services/llm/provider_core/azure_openai_provider.py",
     r"idle_timeout_s = (\d+)", "idle_s"),
    ("stall-anthropic", "llm", "deeptutor/services/llm/provider_core/anthropic_provider.py",
     r"idle_timeout_s = (\d+)", "idle_s"),
    # ---- key rotation ----------------------------------------------------
    ("keyrot-openai-compat", "llm", "deeptutor/services/llm/provider_core/openai_compat_provider.py",
     r"attempts = max\(2, len\(self\._key_pool\)\)", None),
    # ---- structured retry seam ------------------------------------------
    ("structured-single-retry", "llm", "deeptutor/services/llm/structured_retry.py",
     r"retrying once at low reasoning effort", None),
    # ---- agents that add their own outer retry ---------------------------
    ("agent-base-default", "llm", "deeptutor/agents/base_agent.py",
     r'agent_config\.get\("max_retries", settings\.retry\.max_retries\)', None),
    ("agent-mathanim-render-retries", "llm", "deeptutor/agents/math_animator/pipeline.py",
     r"max_retries=(\d+),", "max_retries"),
    ("agent-mathanim-structured", "llm", "deeptutor/agents/math_animator/agents/code_generator_agent.py",
     r"attempts = max_retries \+ 1", None),
    ("agent-research-step-attempts", "llm", "deeptutor/agents/research/pipeline.py",
     r"DEFAULT_REPORT_STEP_MAX_ATTEMPTS = (\d+)", "attempts"),
    ("agent-question-repair-attempts", "llm", "deeptutor/agents/question/pipeline.py",
     r"FINALIZATION_REPAIR_ATTEMPTS = (\d+)", "attempts"),
    ("book-block-retry-attempts", "llm", "deeptutor/book/compiler.py",
     r"block_retry_attempts: int = (\d+)", "attempts"),
    ("book-block-retry-backoff", "llm", "deeptutor/book/compiler.py",
     r"block_retry_backoff_seconds: float = ([\d.]+)", "backoff_s"),
    # ---- traffic control / hints explicitly disabled ---------------------
    ("traffic-token-wait", "llm", "deeptutor/services/llm/traffic_control.py",
     r"await asyncio\.sleep\(wait_time\)", None),
    ("hints-mastery-zero", "llm", "deeptutor/services/mastery_hints.py",
     r"max_retries=(\d+),", "max_retries"),
    ("hints-chat-zero", "llm", "deeptutor/services/chat_hints.py",
     r"max_retries=(\d+),", "max_retries"),
    ("hints-reading-zero", "llm", "deeptutor/services/reading_hints.py",
     r"max_retries=(\d+),", "max_retries"),
    ("doctor-zero", "llm", "deeptutor/services/doctor.py",
     r"max_retries=(\d+),", "max_retries"),
    # ---- embedding adapters ----------------------------------------------
    ("embed-compat-max-retries", "embedding", "deeptutor/services/embedding/adapters/openai_compatible.py",
     r"_MAX_RETRIES = (\d+)", "max_retries"),
    ("embed-compat-backoff", "embedding", "deeptutor/services/embedding/adapters/openai_compatible.py",
     r"_RETRY_BACKOFF = ([\d.]+)", "backoff_s"),
    ("embed-compat-loop", "embedding", "deeptutor/services/embedding/adapters/openai_compatible.py",
     r"for attempt in range\(1 \+ max\(self\._MAX_RETRIES, (\d+)\)\)\:", "min_attempts_m1"),
    ("embed-compat-429-wait", "embedding", "deeptutor/services/embedding/adapters/openai_compatible.py",
     r"await asyncio\.sleep\(max\(retry_after or 0\.0, (\d+)\)\)", "min_wait_s"),
    ("embed-compat-generic-wait", "embedding", "deeptutor/services/embedding/adapters/openai_compatible.py",
     r"wait = self\._RETRY_BACKOFF \* \(2\*\*attempt\)", None),
    ("embed-sdk-budget", "embedding", "deeptutor/services/embedding/adapters/openai_sdk.py",
     r"max_retries=(\d+),", "max_retries"),
    # ---- search providers -------------------------------------------------
    ("search-brave-timeout", "search", "deeptutor/services/search/providers/brave.py",
     r"timeout: int = (\d+)", "timeout_s"),
    ("search-searxng-timeout", "search", "deeptutor/services/search/providers/searxng.py",
     r"timeout: int = (\d+)", "timeout_s"),
    ("search-duckduckgo-timeout", "search", "deeptutor/services/search/providers/duckduckgo.py",
     r"timeout: int = (\d+)", "timeout_s"),
    ("search-bocha-timeout", "search", "deeptutor/services/search/providers/bocha.py",
     r"timeout: int = (\d+)", "timeout_s"),
    ("search-aliyun-timeout", "search", "deeptutor/services/search/providers/aliyun_iqs.py",
     r"timeout: int = (\d+)", "timeout_s"),
    ("search-zhipu-timeout", "search", "deeptutor/services/search/providers/zhipu.py",
     r"timeout: int = (\d+)", "timeout_s"),
    ("search-serper-timeout", "search", "deeptutor/services/search/providers/serper.py",
     r"timeout: int = (\d+)", "timeout_s"),
    ("search-serply-timeout", "search", "deeptutor/services/search/providers/serply.py",
     r"timeout: int = (\d+)", "timeout_s"),
    ("search-qianfan-timeout", "search", "deeptutor/services/search/providers/qianfan.py",
     r"timeout: int = (\d+)", "timeout_s"),
    ("search-tavily-timeout", "search", "deeptutor/services/search/providers/tavily.py",
     r"timeout: int = (\d+)", "timeout_s"),
    ("search-jina-timeout", "search", "deeptutor/services/search/providers/jina.py",
     r"timeout: int = (\d+)", "timeout_s"),
    ("search-firecrawl-timeout", "search", "deeptutor/services/search/providers/firecrawl.py",
     r"timeout: int = (\d+)", "timeout_s"),
    ("search-doubao-timeout", "search", "deeptutor/services/search/providers/doubao.py",
     r"timeout: int = (\d+)", "timeout_s"),
    ("search-perplexity-sdk-call", "search", "deeptutor/services/search/providers/perplexity.py",
     r"completion = self\.client\.chat\.completions\.create\(model=model, messages=messages\)", None),
    ("search-arxiv-timeout", "search", "deeptutor/tools/paper_search_tool.py",
     r"_REQUEST_TIMEOUT_S = (\d+)", "timeout_s"),
    ("search-arxiv-retry-delay", "search", "deeptutor/tools/paper_search_tool.py",
     r"_RETRY_DELAY_S = ([\d.]+)", "delay_s"),
    # ---- channel network layer --------------------------------------------
    ("chan-manager-send-delays", "channel", "deeptutor/partners/channels/manager.py",
     r"_SEND_RETRY_DELAYS = \((.+)\)", "delays"),
    ("chan-manager-max-attempts", "channel", "deeptutor/partners/channels/manager.py",
     r"max_attempts: int = (\d+)", "max_attempts"),
    ("chan-telegram-max-retries", "channel", "deeptutor/partners/channels/telegram.py",
     r"_SEND_MAX_RETRIES = (\d+)", "max_retries"),
    ("chan-telegram-base-delay", "channel", "deeptutor/partners/channels/telegram.py",
     r"_SEND_RETRY_BASE_DELAY = ([\d.]+)", "base_delay_s"),
    ("chan-telegram-timeouts", "channel", "deeptutor/partners/channels/telegram.py",
     r"(connect_timeout|read_timeout|pool_timeout)=[\d.]+", None),
    ("chan-discord-inner-retry", "channel", "deeptutor/partners/channels/discord.py",
     r"for _?attempt in range\((\d+)\)\:", "attempts"),
    ("chan-discord-client-timeout", "channel", "deeptutor/partners/channels/discord.py",
     r"httpx\.AsyncClient\(timeout=([\d.]+)\)", "timeout_s"),
    ("chan-napcat-download-timeout", "channel", "deeptutor/partners/channels/napcat.py",
     r"_DOWNLOAD_TIMEOUT = aiohttp\.ClientTimeout\(total=(\d+)\)", "timeout_s"),
    ("chan-napcat-action-timeout", "channel", "deeptutor/partners/channels/napcat.py",
     r"_ACTION_TIMEOUT = ([\d.]+)", "timeout_s"),
    ("chan-napcat-backoff", "channel", "deeptutor/partners/channels/napcat.py",
     r"backoff = iter\(\((.+)\)\)", "delays"),
    ("chan-mattermost-reconnect", "channel", "deeptutor/partners/channels/mattermost.py",
     r"WS_RECONNECT_DELAY_S = ([\d.]+)", "delay_s"),
    ("chan-qq-reconnect", "channel", "deeptutor/partners/channels/qq.py",
     r"await asyncio\.sleep\((\d+)\)", "delay_s"),
    ("chan-discord-reconnect", "channel", "deeptutor/partners/channels/discord.py",
     r"await asyncio\.sleep\((\d+)\)", "delay_s"),
    ("chan-whatsapp-reconnect", "channel", "deeptutor/partners/channels/whatsapp.py",
     r"await asyncio\.sleep\((\d+)\)", "delay_s"),
    ("chan-wecom-reconnect", "channel", "deeptutor/partners/channels/wecom.py",
     r"max_reconnect_attempts=(-?\d+)", "attempts"),
    ("chan-matrix-sync-reconnect", "channel", "deeptutor/partners/channels/matrix.py",
     r"await asyncio\.sleep\((\d+)\)", "delay_s"),
    ("chan-slack-connect-timeout", "channel", "deeptutor/partners/channels/slack.py",
     r"SLACK_SOCKET_CONNECT_TIMEOUT_S = ([\d.]+)", "timeout_s"),
    ("chan-slack-reconnect", "channel", "deeptutor/partners/channels/slack.py",
     r"await asyncio\.sleep\((\d+)\)", "delay_s"),
    ("chan-msteams-client-timeout", "channel", "deeptutor/partners/channels/msteams.py",
     r"httpx\.AsyncClient\(timeout=([\d.]+)\)", "timeout_s"),
    ("chan-mochat-socket-connect", "channel", "deeptutor/partners/channels/mochat.py",
     r"socket_connect_timeout_ms: int = (\d+)", "timeout_ms"),
    ("chan-mochat-watch", "channel", "deeptutor/partners/channels/mochat.py",
     r"watch_timeout_ms: int = (\d+)", "timeout_ms"),
    ("chan-mochat-retry-delay", "channel", "deeptutor/partners/channels/mochat.py",
     r"retry_delay_ms: int = (\d+)", "delay_ms"),
    ("chan-mochat-max-retry", "channel", "deeptutor/partners/channels/mochat.py",
     r"max_retry_attempts: int = (\d+)", "attempts"),
    ("chan-mochat-client-timeout", "channel", "deeptutor/partners/channels/mochat.py",
     r"httpx\.AsyncClient\(timeout=([\d.]+)\)", "timeout_s"),
    ("chan-zulip-timeout", "channel", "deeptutor/partners/channels/zulip.py",
     r"timeout: float = Field\(default=([\d.]+)\)", "timeout_s"),
    ("chan-email-smtp-timeout", "channel", "deeptutor/partners/channels/email.py",
     r"timeout = (\d+)", "timeout_s"),
    ("chan-feishu-stream-retry", "channel", "deeptutor/partners/channels/feishu.py",
     r"_STREAM_CREATE_RETRY_INTERVAL = ([\d.]+)", "interval_s"),
    ("chan-feishu-reaction-del", "channel", "deeptutor/partners/channels/feishu.py",
     r"_REACTION_DELETE_RETRY_DELAYS = \((.+)\)", "delays"),
    ("chan-feishu-reaction-late", "channel", "deeptutor/partners/channels/feishu.py",
     r"_REACTION_LATE_RETRY_DELAYS = \((.+)\)", "delays"),
    ("chan-feishu-ws-reconnect", "channel", "deeptutor/partners/channels/feishu.py",
     r"time\.sleep\((\d+)\)", "delay_s"),
    # ---- KB retrieval clients (KB 代理轴) ----------------------------------
    ("kb-lightrag-timeout", "kb", "deeptutor/services/rag/pipelines/lightrag_server/client.py",
     r"timeout: float = ([\d.]+),", "timeout_s"),
    ("kb-weknora-timeout", "kb", "deeptutor/services/rag/pipelines/weknora/client.py",
     r"timeout: float = ([\d.]+),", "timeout_s"),
    ("kb-ima-default-timeout", "kb", "deeptutor/services/rag/pipelines/ima/transport.py",
     r"DEFAULT_TIMEOUT = ([\d.]+)", "timeout_s"),
    ("kb-kiwix-timeout", "kb", "deeptutor/services/rag/pipelines/kiwix/client.py",
     r"timeout=httpx\.Timeout\(([\d.]+)\)", "timeout_s"),
    ("kb-web-proxy-pass", "kb", "web/proxy.ts", r"proxy", None),
]

# Probes where multiple hits in one file are all meaningful.
MULTI = {"chan-telegram-timeouts", "chan-discord-inner-retry", "chan-discord-reconnect",
         "chan-qq-reconnect", "chan-whatsapp-reconnect", "chan-matrix-sync-reconnect",
         "chan-slack-reconnect", "chan-telegram-max-retries"}


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    records: list[dict] = []
    missing: list[str] = []
    for pid, group, rel, pattern, cap in PROBES:
        path = root / rel
        if not path.exists():
            missing.append(f"{pid}: file not found: {rel}")
            continue
        rx = re.compile(pattern)
        hits = 0
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        ):
            m = rx.search(line)
            if not m:
                continue
            hits += 1
            value = m.group(1) if m.groups() else ""
            records.append(
                {
                    "id": pid,
                    "group": group,
                    "file": rel,
                    "line": lineno,
                    "value": value,
                    "text": line.strip()[:160],
                }
            )
            if pid not in MULTI:
                break
        if hits == 0:
            missing.append(f"{pid}: no match for {pattern!r} in {rel}")
    json.dump(records, sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write("\n")
    if missing:
        for item in missing:
            print(f"MISSING {item}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
