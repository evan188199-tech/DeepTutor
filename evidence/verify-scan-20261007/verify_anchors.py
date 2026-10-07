#!/usr/bin/env python3
"""AGEN-1091 verify-scan-20261007 anchor re-check (read-only).

Re-reads the 55+ path:line anchors tabulated in verify-memo.md against the
current worktree and prints one line per anchor: OK when the line exists and
contains the expected token, MISS otherwise. Exit 0 iff no MISS.

Usage: python3 verify_anchors.py <repo-root>
"""
import sys
from pathlib import Path

A = [  # (path, line, expected-token)
    ("deeptutor/agents/research/utils/json_utils.py", 25, "```(?:json)?"),
    ("deeptutor/agents/question/pipeline.py", 1390, "```(?:json)?"),
    ("deeptutor/agents/vision_solver/vision_solver_agent.py", 157, "```(?:json)?"),
    ("deeptutor/agents/_shared/json_output.py", 18, "<think\\b"),
    ("deeptutor/agents/_shared/json_output.py", 30, "```(?:json)?"),
    ("deeptutor/agents/loop/dsml_tool_calls.py", 39, "_INVOKE_RE"),
    ("deeptutor/agents/loop/dsml_tool_calls.py", 34, "DSML_SIGNAL_RE"),
    ("deeptutor/agents/loop/dsml_tool_calls.py", 43, "_PARAM_RE"),
    ("deeptutor/agents/loop/dsml_tool_calls.py", 83, "_INVOKE_RE.finditer"),
    ("deeptutor/agents/loop/dsml_tool_calls.py", 211, "DSML_SIGNAL_RE.search"),
    ("deeptutor/agents/loop/dsml_tool_calls.py", 255, "_INVOKE_RE.finditer"),
    ("deeptutor/agents/loop/dsml_tool_calls.py", 261, "_PARAM_RE.finditer"),
    ("deeptutor/services/skill/service.py", 63, "^---\\s*\\n(.*?)\\n---"),
    ("deeptutor/services/skill/service.py", 352, "_FRONTMATTER_RE"),
    ("deeptutor/services/skill/service.py", 951, "_FRONTMATTER_RE"),
    ("deeptutor/services/skill/hub.py", 891, "^---\\s*\\n(.*?)\\n---"),
    ("deeptutor/services/skill/hub.py", 917, "_FRONTMATTER_RE"),
    ("deeptutor/services/web_source/html_extractor.py", 333, "<title[^>]*>"),
    ("deeptutor/services/web_source/html_extractor.py", 347, "[^|]+$"),
    ("deeptutor/services/web_source/markdown.py", 8, "source:"),
    ("deeptutor/services/web_source/markdown.py", 22, "fullmatch"),
    ("web/components/space/SkillsSection.tsx", 73, "^---"),
    ("web/components/space/PersonasSection.tsx", 58, "^---"),
    ("web/lib/deep-research-report.ts", 53, "(# [^\\r\\n]*?)"),
    ("deeptutor/api/routers/knowledge.py", 379, "_sanitize_path_segment"),
    ("deeptutor/api/routers/knowledge.py", 381, "_BAD_PATH_CHARS"),
    ("deeptutor/api/routers/knowledge.py", 3038, "_resolve_kb_raw_file_or_404"),
    ("deeptutor/api/routers/knowledge.py", 3075, "str(p).lower()"),
    ("deeptutor/api/routers/knowledge.py", 893, "_resolve_registered_kb_name"),
    ("deeptutor/api/routers/knowledge.py", 3316, "Form(None)"),
    ("deeptutor/api/routers/knowledge.py", 3122, "files/move"),
    ("deeptutor/api/routers/knowledge.py", 3311, "upload"),
    ("deeptutor/utils/document_validator.py", 97, 'normalize("NFC"'),
    ("deeptutor/services/rag/pipelines/pageindex/pipeline.py", 202, "upsert_doc"),
    ("deeptutor/services/rag/pipelines/pageindex/pipeline.py", 273, "Path(file_name).name"),
    ("deeptutor/services/rag/pipelines/pageindex/storage.py", 103, "docs[file_name]"),
    ("deeptutor/services/courses.py", 324, "casefold()"),
    ("deeptutor/services/courses.py", 331, "casefold()"),
    ("deeptutor/services/mcp/catalog/loader.py", 114, "casefold()"),
    ("deeptutor/services/mcp/catalog/loader.py", 141, "casefold()"),
    ("deeptutor/services/mcp/catalog/loader.py", 168, "casefold()"),
    ("deeptutor/services/session/pocketbase_store.py", 679, "casefold()"),
    ("deeptutor/services/reading_hints.py", 335, "casefold()"),
    ("deeptutor/services/chat_hints.py", 184, "casefold()"),
    ("deeptutor/services/partners/commands.py", 293, "casefold()"),
    ("deeptutor/services/partners/commands.py", 362, "casefold()"),
    ("deeptutor/services/partner_groups/manager.py", 1538, "casefold()"),
    ("deeptutor/services/partner_groups/manager.py", 1630, "casefold()"),
    ("web/components/knowledge/KbDocumentList.tsx", 99, "localeCompare"),
    ("web/components/knowledge/KbDocumentList.tsx", 104, "localeCompare"),
    ("deeptutor/api/routers/co_writer.py", 736, "_docx_download_filename"),
    ("deeptutor/runtime/launcher.py", 1036, "def _handler"),
    ("deeptutor/runtime/launcher.py", 1064, "signal.signal(sig, _handler)"),
    ("deeptutor/runtime/launcher.py", 1491, "_log("),
    ("deeptutor/runtime/launcher.py", 263, "wait(timeout=8)"),
    ("deeptutor/runtime/launcher.py", 266, "KILL_SIGNAL"),
    ("deeptutor/runtime/launcher.py", 240, "subprocess.run("),
    ("deeptutor/runtime/launcher.py", 251, "os.kill(pid, sig)"),
    ("deeptutor/runtime/launcher.py", 504, "_send_tree_signal(pid, None"),
    ("deeptutor/runtime/launcher.py", 1022, "time.sleep(0.5)"),
    ("deeptutor/runtime/launcher.py", 1233, '!= "pending"'),
    ("deeptutor/runtime/launcher.py", 1272, '!= "restarting"'),
    ("deeptutor/services/subagent/opencode_server.py", 171, "def _terminate_sync"),
    ("deeptutor/services/subagent/opencode_server.py", 175, "terminate()"),
    ("deeptutor/services/subagent/opencode_server.py", 197, "atexit.register"),
    ("deeptutor/services/subagent/claude_models.py", 222, "SIGTERM"),
    ("deeptutor/services/subagent/claude_models.py", 226, "os.waitpid(pid, 0)"),
    ("deeptutor/runtime/update_worker.py", 96, "start_new_session"),
    ("deeptutor/runtime/update_worker.py", 134, "except Exception"),
    ("web/scripts/dev.mjs", 64, "child.kill(signal)"),
    ("web/scripts/dev.mjs", 67, "process.kill(process.pid, signal)"),
    ("deeptutor/services/sandbox/runner/server.py", 367, "KeyboardInterrupt"),
    ("deeptutor/services/sandbox/backends.py", 453, "killpg"),
    ("deeptutor/services/parsing/engines/mineru/models.py", 166, "terminate()"),
    ("deeptutor/services/setup/data_volume.py", 195, "waitpid(pid, 0)"),
    ("deeptutor/api/routers/auth.py", 818, '{"ok": True'),
    ("deeptutor/api/routers/auth.py", 838, "username"),
    ("deeptutor/api/routers/settings.py", 898, '{"ui"'),
    ("deeptutor/api/routers/system.py", 418, '{"available": False}'),
    ("deeptutor/api/routers/memory.py", 681, "limit: int = 200"),
    ("deeptutor/api/routers/dashboard.py", 21, "limit: int = 50"),
    ("deeptutor/api/routers/sessions.py", 135, '{"sessions": sessions}'),
    ("deeptutor/api/routers/skills.py", 280, '@router.put("/{name}")'),
    ("deeptutor/api/routers/skills.py", 293, "404"),
    ("deeptutor/api/routers/skills.py", 295, "403"),
    ("deeptutor/api/routers/skills.py", 297, "409"),
    ("deeptutor/api/routers/courses.py", 96, "@router.patch"),
    ("deeptutor/api/routers/reading_extensions.py", 195, "actions/{action}"),
    ("deeptutor/api/routers/reading_extensions.py", 363, "quiz/answers"),
    ("web/components/partners/PartnerChat.tsx", 734, "setTimeout"),
    ("web/components/partners/PartnerChat.tsx", 767, "setTimeout"),
    ("web/components/reading/ReaderPane.tsx", 696, "setTimeout"),
    ("web/components/reading/workspace/MediaReadingStage.tsx", 433, "setTimeout"),
    ("web/components/reading/EpubDocumentView.tsx", 623, "setTimeout"),
    ("web/components/chat/preview/FilePreviewDrawer.tsx", 156, "setTimeout"),
    ("web/components/courses/CourseConventions.tsx", 49, "setTimeout"),
    ("web/components/knowledge/KbFilePreview.tsx", 201, "setTimeout"),
    ("web/components/partners/PartnerLinkModal.tsx", 75, "setTimeout"),
    ("web/components/partners/group/PartnerSeat.tsx", 74, "setTimeout"),
    ("web/components/whisper/WhisperRoomChip.tsx", 19, "setTimeout"),
    ("web/components/reading/workspace/ReadingComposer.tsx", 113, "setTimeout"),
    ("web/components/reading/workspace/ReadingWorkspace.tsx", 327, "setTimeout"),
    ("web/components/common/ToastViewport.tsx", 25, "setTimeout"),
]

def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    cache: dict[str, list[str]] = {}
    miss = 0
    for path, line, token in A:
        if path not in cache:
            fp = root / path
            cache[path] = fp.read_text(encoding="utf-8", errors="replace").splitlines() if fp.exists() else []
        lines = cache[path]
        text = lines[line - 1] if 0 < line <= len(lines) else ""
        ok = token in text
        miss += 0 if ok else 1
        print(f"{'OK ' if ok else 'MISS'} {path}:{line} :: {text.strip()[:100]}")
    print(f"\nanchors: {len(A)}  ok: {len(A) - miss}  miss: {miss}")
    return 1 if miss else 0

if __name__ == "__main__":
    raise SystemExit(main())
