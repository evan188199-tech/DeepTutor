"""Small runtime i18n helper for backend-facing user messages."""

from __future__ import annotations

from typing import Any


def _parse_language(language: str | None) -> str:
    raw = (language or "en").strip().lower()
    if raw.startswith("zh") or raw in {"cn", "chinese"}:
        return "zh"
    return "en"


_MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "api.access_denied": "Access denied",
        "api.content_required": "content is required",
        "api.file_not_found": "File not found",
        "api.invalid_channels_config": "Invalid channels config",
        "api.not_authenticated": "Not authenticated",
        "api.partner_already_exists": "Partner '{name}' already exists",
        "api.partner_not_found": "Partner not found",
        "api.partner_not_found_or_not_running": "Partner not found or not running",
        "api.partner_not_running": "Partner not running",
        "api.partner_stopped_start_required": "Partner is stopped. Start it before chatting.",
        "api.persona_already_exists": "Persona already exists: {name}",
        "api.persona_name_required": "Persona name is required",
        "api.persona_not_found": "Persona not found: {name}",
        "api.soul_already_exists": "Soul '{name}' already exists",
        "api.soul_content_empty": "Custom soul content is empty",
        "api.soul_library_not_found": "Soul '{name}' not found in library",
        "api.soul_not_found": "Soul not found",
        "api.tool_not_found": "Tool '{name}' not found",
        "auth.admin_required": "Admin access required",
        "auth.avatar_invalid_type": "Avatar must be a PNG, JPEG or WebP image.",
        "auth.avatar_not_found": "Avatar not found",
        "auth.avatar_pb_unsupported": "Avatar upload is not available in PocketBase mode.",
        "auth.avatar_store_failed": "Cannot store an avatar for this account.",
        "auth.avatar_too_large": "Avatar image is too large (max 1 MB).",
        "auth.cannot_change_own_role": "You cannot change your own role",
        "auth.cannot_delete_self": "You cannot delete your own account",
        "auth.conflicting_workspace_scopes": "Conflicting workspace scopes.",
        "auth.create_user_failed": "Failed to create user — username may already be taken.",
        "auth.device_credential_not_found": "Device credential not found",
        "auth.device_pb_unsupported": "Device credentials are not supported in PocketBase mode.",
        "auth.device_requires_builtin": "Device credentials require built-in authentication.",
        "auth.device_session_inactive": "Device session is no longer active",
        "auth.handoff_no_frontend_host": "Handoff request has no valid frontend host",
        "auth.handoff_requires_private": (
            "Session handoff requires authentication and configured private login hosts."
        ),
        "auth.handoff_ticket_invalid": "Handoff ticket is invalid, expired, or already used",
        "auth.import_header": "CSV header must be exactly: username,password,preset",
        "auth.import_no_rows": "User import file contains no user rows.",
        "auth.import_too_large": "User import file exceeds 2 MB.",
        "auth.import_too_many_rows": "User import cannot exceed {max_rows} rows.",
        "auth.import_utf8_csv": "User import must be a UTF-8 CSV file.",
        "auth.incorrect_device_credentials": "Incorrect device credentials",
        "auth.incorrect_email_or_password": "Incorrect email or password",
        "auth.incorrect_username_or_password": "Incorrect username or password",
        "auth.invalid_or_expired_token": "Invalid or expired token",
        "auth.learner_profile_required": "Learner profile required",
        "auth.learner_preset_failed": "The learner preset could not be initialized.",
        "auth.login_disabled": "Auth is disabled — no login required.",
        "auth.non_admin_provisioning_only": (
            "Only non-admin users can be provisioned by this endpoint."
        ),
        "auth.pairing_code_invalid": "Pairing code is invalid, expired, or already used",
        "auth.pairing_no_frontend_host": "Pairing request has no valid frontend host",
        "auth.profiles_disabled": "Auth is disabled — profiles are not available.",
        "auth.registration_disabled": "Auth is disabled — registration is not available.",
        "auth.registration_failed": "Registration failed — username or email may already be taken.",
        "auth.self_registration_closed": (
            "Self-registration is closed. Ask an administrator to create your account."
        ),
        "auth.session_not_device": "This session does not use a device credential.",
        "auth.signin_private_origin": "Sign-in is only available from a private DeepTutor origin",
        "auth.standard_preset_only": "Only the standard preset is available in PocketBase mode.",
        "auth.too_many_handoff": "Too many handoff requests. Try again later.",
        "auth.user_creation_disabled": "Auth is disabled — user creation is not available.",
        "auth.user_import_disabled": "Auth is disabled — user import is not available.",
        "auth.user_not_found": "User not found",
        "auth.username_taken": "Username already taken",
        "auth.valid_https_origin_required": "Enter a valid HTTPS public origin",
        "book.action_failed": "Book action failed",
        "book.block_not_editable": "Block not found or not editable",
        "book.block_not_found": "Block not found",
        "book.book_or_page_not_found": "Book or page not found",
        "book.capture_not_found": "Learning capture not found",
        "book.creation_not_allowed": "Book creation is not allowed",
        "book.focus_check_save_failed": "Failed to save Focus-Check evidence",
        "book.invalid_capture_status": "Invalid capture status: {status}",
        "book.invalid_proposal": "Invalid proposal: {error}",
        "book.invalid_spine": "Invalid spine: {error}",
        "book.invalid_transition": "Invalid state transition: {current} -> {next}",
        "book.not_found": "Book not found",
        "book.page_not_found": "Page not found",
        "book.page_or_chapter_not_found": "Page or chapter not found",
        "book.parent_page_not_found": "Parent page not found",
        "book.revision_conflict_own": (
            "This book changed since your last action — reloading the latest version."
        ),
        "book.revision_conflict_shared": "The book was updated by another collaborator.",
        "book.revision_required": "Refresh the shared book before editing.",
        "book.source_text_required": "source_text is required",
        "book.spine_not_found": "Spine not found",
        "book.unknown_block_type": "Unknown block type: {name}",
        "book.unknown_content_type": "Unknown content type: {name}",
        "book.user_intent_required": "user_intent is required",
        "cli_apps.abi_mismatch": (
            "The CLI app {app!r} was installed for {installed} but this runtime is "
            "{current}. An administrator needs to reinstall it."
        ),
        "cli_apps.args_required": (
            "{tool} needs an 'args' array — one command-line argument per element."
        ),
        "cli_apps.entry_admin_only": (
            "CLI apps are installed by an administrator; ask yours to add this one."
        ),
        "cli_apps.install_in_progress": "That app is already being installed.",
        "cli_apps.not_in_catalog": "No CLI app named {id!r} in the catalog.",
        "cli_apps.not_installed": (
            "The CLI app {app!r} is not installed on this deployment any more."
        ),
        "cli_apps.still_running": "{app} is still running ({seconds}s)",
        "knowledge.archive_empty": "Archive '{name}' contained no supported files.",
        "knowledge.archive_rejected": "Rejected archive '{name}': {reason}",
        "knowledge.archive_too_large": "Archive '{name}' exceeds maximum size limit of {limit}",
        "knowledge.bound_embedding_unavailable": (
            "The bound embedding model is unavailable or changed. Check the model "
            "settings or select a model to re-index this knowledge base."
        ),
        "knowledge.cancel_boundary": (
            "Cancellation takes effect at the next safe boundary; "
            "completed parser outputs remain reusable."
        ),
        "knowledge.cancel_requested": "Cancellation requested",
        "knowledge.change_embedding_via_reindex": (
            "Change a knowledge base's embedding model through re-indexing."
        ),
        "knowledge.configs_synced": "Configurations synced from metadata files",
        "knowledge.delete_failed": "Failed to delete knowledge base",
        "knowledge.duplicate_filename": (
            "Duplicate filename after sanitization: '{name}'. "
            "Rename one of the files and try again."
        ),
        "knowledge.embedding_updated_empty": (
            "Embedding model updated for the empty knowledge base."
        ),
        "knowledge.empty_kb_defaults": (
            "Empty LightRAG knowledge bases follow defaults. Configure models in Settings."
        ),
        "knowledge.file_too_large": "File '{name}' exceeds maximum size limit of {limit}",
        "knowledge.folder_fields_required": "Both name and folder_path are required.",
        "knowledge.folder_into_itself": "Cannot move a folder into itself",
        "knowledge.folder_name_required": "Folder name is required",
        "knowledge.folder_not_linkable": "Folder is not linkable.",
        "knowledge.folder_not_found": "Folder '{id}' not found",
        "knowledge.folder_path_required": "folder_path is required.",
        "knowledge.folder_unlinked": "Folder unlinked successfully",
        "knowledge.graphrag_compat_failed": (
            "GraphRAG compatibility could not be tested because of an internal error."
        ),
        "knowledge.graphrag_not_installed": (
            "GraphRAG is not installed. Run `pip install 'deeptutor[graphrag]'` on the "
            "server before creating a GraphRAG knowledge base."
        ),
        "knowledge.graphrag_preflight_failed": "GraphRAG preflight failed: {details}",
        "knowledge.ima_connect_failed": "Could not connect the IMA knowledge base.",
        "knowledge.ima_connect_probe_failed": "Could not connect to the IMA knowledge base.",
        "knowledge.ima_credentials_required": "Client ID and API key are required.",
        "knowledge.ima_invalid_response": "IMA returned an invalid response.",
        "knowledge.ima_rate_limited": "IMA rate limit reached. Try again shortly.",
        "knowledge.ima_rejected": "IMA rejected the supplied credentials.",
        "knowledge.ima_unreachable": "Could not reach Tencent IMA.",
        "knowledge.index_already_ready": (
            "Knowledge base '{name}' already has an index for the active embedding "
            "configuration; no reindex needed."
        ),
        "knowledge.index_run_inactive": "This indexing run is no longer active.",
        "knowledge.index_worker_owns": "An indexing worker still owns this knowledge base.",
        "knowledge.initializing": "Initializing knowledge base...",
        "knowledge.init_complete": "Knowledge base initialization complete!",
        "knowledge.init_failed": "Initialization failed: {error}",
        "knowledge.invalid_folder_path": "Invalid folder path",
        "knowledge.invalid_mode": "Invalid mode '{mode}' for {engine}. Choose one of: {modes}.",
        "knowledge.invalid_search_mode": (
            "Invalid search mode '{mode}' for {engine}. Choose one of: {modes}."
        ),
        "knowledge.kb_already_exists": "Knowledge base '{name}' already exists",
        "knowledge.kb_alias_not_found": "KB '{name}' not found",
        "knowledge.kb_created_empty": "Knowledge base created (no documents yet).",
        "knowledge.kb_created_named": "Knowledge base '{name}' created (no documents yet).",
        "knowledge.kb_created_processing": (
            "Knowledge base '{name}' created. Processing {count} files in background."
        ),
        "knowledge.kb_deleted": "Knowledge base '{name}' deleted successfully",
        "knowledge.kb_legacy_reindex": (
            "Knowledge base '{name}' uses legacy index format and needs reindex before "
            "accepting incremental uploads."
        ),
        "knowledge.kb_name_required": "Knowledge base name is required.",
        "knowledge.kb_needs_reindex": "Knowledge base needs reindex or initialization.",
        "knowledge.kb_no_local_files": (
            "Knowledge base '{name}' is connected to an external resource and has no "
            "local files."
        ),
        "knowledge.kb_not_error_state": (
            "Knowledge base '{name}' is not in an error state. Use re-index when you "
            "want to rebuild a healthy knowledge base."
        ),
        "knowledge.kb_not_found": "Knowledge base '{name}' not found",
        "knowledge.kb_ready": "Knowledge base is ready.",
        "knowledge.kb_read_only": (
            "Knowledge base '{name}' is connected to an external resource and is "
            "read-only. Local file operations and re-indexing are not available for it."
        ),
        "knowledge.kiwix_kb_not_found": "Kiwix knowledge base not found.",
        "knowledge.kiwix_search_failed": "Kiwix search failed.",
        "knowledge.list_failed": "Failed to list knowledge bases: {error}",
        "knowledge.lightrag_model_pair_required": (
            "LightRAG model selection requires both profile_id and model_id."
        ),
        "knowledge.lightrag_not_installed": (
            "LightRAG is not installed. Run `pip install 'deeptutor[rag-lightrag]'` on "
            "the server before creating a LightRAG knowledge base."
        ),
        "knowledge.lightrag_overrides_removed": (
            "Configure LightRAG models in Settings; per-knowledge-base overrides are "
            "no longer supported."
        ),
        "knowledge.lightrag_server_fields_required": "Both name and server_url are required.",
        "knowledge.lightrag_server_unreachable": "Could not connect to the LightRAG server.",
        "knowledge.linked_folder_not_found": "Linked folder '{id}' not found",
        "knowledge.load_all_failed": "Failed to load knowledge bases. Errors: {errors}",
        "knowledge.load_assigned_failed": "Failed to load assigned knowledge base info.",
        "knowledge.load_kb_info_failed": "Failed to load knowledge base info.",
        "knowledge.name_exists_in_folder": "'{name}' already exists in the target folder",
        "knowledge.name_required": "name is required.",
        "knowledge.no_default_kb": "No default knowledge base is configured",
        "knowledge.no_embedding_configured": (
            "No embedding model is configured. Set up the embedding profile in Settings "
            "before re-indexing."
        ),
        "knowledge.no_files_to_sync": "No new or modified files to sync",
        "knowledge.no_github_sources": "No GitHub sources",
        "knowledge.no_enabled_web_sources": "No enabled web sources",
        "knowledge.no_local_embedding": "This knowledge engine does not use a local embedding model.",
        "knowledge.no_models_configured": "No '{kind}' models configured.",
        "knowledge.no_retrieval_modes": "No retrieval modes for engine '{engine}'.",
        "knowledge.no_web_sources": "No web sources",
        "knowledge.not_a_zip": "'{name}' is not a valid zip archive.",
        "knowledge.obsidian_fields_required": "Both name and vault_path are required.",
        "knowledge.pageindex_key_missing": (
            "PageIndex API key is not configured. Add it under Knowledge → RAG pipeline "
            "settings before creating a PageIndex knowledge base."
        ),
        "knowledge.pageindex_oss_mode": "PageIndex OSS mode must be 'flash', 'standard', or omitted.",
        "knowledge.pageindex_preflight_failed": "PageIndex OSS preflight failed: {details}",
        "knowledge.pageindex_unsupported_formats": (
            "PageIndex knowledge bases accept: {supported}. Unsupported: {unsupported}."
        ),
        "knowledge.processing_uploaded": "Processing {count} uploaded file(s)...",
        "knowledge.progress_cleared": "Progress cleared for {name}",
        "knowledge.progress_not_started": "Initialization not started",
        "knowledge.provider_changed_message": (
            "Provider changed from {old} to {new}; re-index this knowledge base before use."
        ),
        "knowledge.provider_index_locked": (
            "Knowledge base '{name}' already has a ready {provider} index. Provider "
            "changes require an explicit re-index/migration instead of a silent config edit."
        ),
        "knowledge.provider_mismatch": (
            "Requested provider '{requested}' does not match KB provider '{current}'. "
            "A knowledge base is locked to the engine it was created with."
        ),
        "knowledge.queueing_reindex": "Queueing re-index...",
        "knowledge.readiness_note": (
            "Readiness checks configuration and local prerequisites; runtime downloads, "
            "resource limits and provider responses can still fail."
        ),
        "knowledge.rebuild_config_changed": (
            "Rebuild configuration changed. Review the updated configuration and confirm again."
        ),
        "knowledge.rebuild_confirm_defaults": (
            "Review current defaults in Index versions and confirm the LightRAG rebuild."
        ),
        "knowledge.rebuild_confirm_review": (
            "Review the current rebuild configuration and confirm before rebuilding."
        ),
        "knowledge.rebuild_lightrag_only": "Rebuild configuration is only for LightRAG.",
        "knowledge.reindexing": "Re-indexing '{name}' in the background.",
        "knowledge.retry_scheduled": "Retry scheduled",
        "knowledge.role_models_cannot_clear": "Role models cannot be cleared.",
        "knowledge.saved_files_preparing": "Saved {count} files, preparing to process...",
        "knowledge.server_url_required": "server_url is required.",
        "knowledge.source_not_found": "Source not found",
        "knowledge.source_not_found_by_id": "Source '{id}' not found",
        "knowledge.source_operation_failed": "Knowledge source operation failed",
        "knowledge.source_path_required": "Source path is required",
        "knowledge.source_removed": "Removed",
        "knowledge.sync_enable_before_retry": (
            "Enable the source and automatic synchronization before retrying"
        ),
        "knowledge.sync_job_not_found": "Synchronization job not found",
        "knowledge.sync_not_cancellable": "Synchronization job cannot be cancelled",
        "knowledge.synced_sources": "Synced {count} source(s)",
        "knowledge.syncing_folder": "Syncing {count} file(s) from linked folder...",
        "knowledge.syncing_folder_message": "Syncing {count} files from linked folder",
        "knowledge.task_completed": "Knowledge-base processing completed.",
        "knowledge.task_failed": "Knowledge-base processing failed.",
        "knowledge.task_interrupted": (
            "Knowledge-base processing was interrupted by a server restart. "
            "Retry the operation to continue."
        ),
        "knowledge.unknown_model": "Unknown model for this profile.",
        "knowledge.unknown_profile": "Unknown profile for this kind.",
        "knowledge.unsupported_model_kind": (
            "Unsupported model kind '{kind}'. Choose one of: {kinds}."
        ),
        "knowledge.uploaded_processing": "Uploaded {count} files. Processing in background.",
        "knowledge.use_role_models": "Use role_models for this configuration.",
        "knowledge.validation_failed": "Validation failed for file '{name}': {error}",
        "knowledge.visual_asset_not_found": "Visual asset not found",
        "knowledge.visual_coverage_unreadable": (
            "Visual coverage is unreadable; original evidence files have been preserved."
        ),
        "knowledge.visual_source_changed": (
            "The referenced source changed or is missing. Select its current version explicitly."
        ),
        "knowledge.weknora_all_fields_required": (
            "name, server_url, and knowledge_base_id are required."
        ),
        "knowledge.weknora_fields_required": "Both server_url and knowledge_base_id are required.",
        "knowledge.weknora_unreachable": "Could not connect to the WeKnora knowledge base.",
        "mastery.active_turn_not_stopped": (
            "Active learning turn could not be stopped before changing this path"
        ),
        "mastery.invalid_book_id": "Invalid book_id",
        "mastery.invalid_kp_data": "Invalid knowledge_point data in modules[{index}]: {errors}",
        "mastery.invalid_mode": "mode must be one of: {modes}",
        "mastery.invalid_module_data": "Invalid module data in modules[{index}]: {errors}",
        "mastery.llm_invalid_json": "LLM returned invalid JSON",
        "mastery.llm_invalid_structure": "LLM returned invalid structure: modules is not a list",
        "mastery.module_needs_kp": "Module '{id}' must contain at least one knowledge point",
        "mastery.module_required": "At least one learning module is required",
        "mastery.no_records": "No records provided",
        "mastery.objective_not_found": "Objective not found",
        "mastery.path_activity_changed": (
            "Mastery path changed activity while the operation was starting; "
            "active session: {session}"
        ),
        "mastery.progress_generic_not_found": "Progress not found",
        "mastery.progress_not_found": "Mastery progress not found",
        "mastery.session_not_found": "Session not found",
        "mastery.topic_not_found": "Mastery topic not found",
        "mcp.configure_command_or_url": "Server {name!r}: configure either a command (stdio) or a url.",
        "mcp.configure_before_testing": "Configure either a command (stdio) or a url before testing.",
        "mcp.server_error": "Server {name!r}: {error}",
        "mcp.server_missing": "No server named {name!r} in your list.",
        "mcp.not_oauth": "This server does not use OAuth; give it a credential instead.",
        "mcp.oauth_callback_incomplete": "The authorization response was incomplete.",
        "mcp.oauth_callback_unknown": "That authorization has expired or already completed. Start it again.",
        "mcp.oauth_done": "Authorized. You can close this tab.",
        "mcp.oauth_failed": "Authorization failed.",
        "mcp.catalog_entry_missing": "No MCP service named {id!r} in the catalog.",
        "mcp.entry_admin_only": (
            "This service runs as a local command and can only be added by an administrator."
        ),
        "mcp.tool_not_available": (
            "This tool is not available in this conversation. "
            "Only the tools listed in the prompt can be called."
        ),
        "sandbox.command_blocked": "Error: command blocked by safety guard (dangerous pattern).",
        "sandbox.disabled_for_account": "Code execution is disabled for your account.",
        "sandbox.no_backend": "no sandbox backend available",
    },
    "zh": {
        "api.access_denied": "无权访问",
        "api.content_required": "content 不能为空",
        "api.file_not_found": "未找到文件",
        "api.invalid_channels_config": "渠道配置无效",
        "api.not_authenticated": "未认证",
        "api.partner_already_exists": "伙伴 '{name}' 已存在",
        "api.partner_not_found": "未找到伙伴",
        "api.partner_not_found_or_not_running": "未找到伙伴或伙伴未运行",
        "api.partner_not_running": "伙伴未运行",
        "api.partner_stopped_start_required": "伙伴已停止。请先启动后再聊天。",
        "api.persona_already_exists": "Persona 已存在：{name}",
        "api.persona_name_required": "Persona 名称不能为空",
        "api.persona_not_found": "未找到 Persona：{name}",
        "api.soul_already_exists": "Soul '{name}' 已存在",
        "api.soul_content_empty": "自定义 soul 内容为空",
        "api.soul_library_not_found": "素材库中未找到 soul '{name}'",
        "api.soul_not_found": "未找到 soul",
        "api.tool_not_found": "未找到工具 '{name}'",
        "auth.admin_required": "需要管理员权限",
        "auth.avatar_invalid_type": "头像必须是 PNG、JPEG 或 WebP 图片。",
        "auth.avatar_not_found": "未找到头像",
        "auth.avatar_pb_unsupported": "PocketBase 模式不支持上传头像。",
        "auth.avatar_store_failed": "无法为此账号存储头像。",
        "auth.avatar_too_large": "头像图片过大（最大 1 MB）。",
        "auth.cannot_change_own_role": "不能更改自己的角色",
        "auth.cannot_delete_self": "不能删除自己的账号",
        "auth.conflicting_workspace_scopes": "工作区范围冲突。",
        "auth.create_user_failed": "创建用户失败——用户名可能已被占用。",
        "auth.device_credential_not_found": "未找到设备凭据",
        "auth.device_pb_unsupported": "PocketBase 模式不支持设备凭据。",
        "auth.device_requires_builtin": "设备凭据需要内置认证。",
        "auth.device_session_inactive": "设备会话已失效",
        "auth.handoff_no_frontend_host": "交接请求缺少有效的前端主机",
        "auth.handoff_requires_private": "会话交接需要认证并配置私有登录主机。",
        "auth.handoff_ticket_invalid": "交接票据无效、已过期或已被使用",
        "auth.import_header": "CSV 表头必须恰好是：username,password,preset",
        "auth.import_no_rows": "用户导入文件中没有用户数据行。",
        "auth.import_too_large": "用户导入文件超过 2 MB。",
        "auth.import_too_many_rows": "用户导入不能超过 {max_rows} 行。",
        "auth.import_utf8_csv": "用户导入文件必须是 UTF-8 编码的 CSV。",
        "auth.incorrect_device_credentials": "设备凭据错误",
        "auth.incorrect_email_or_password": "邮箱或密码错误",
        "auth.incorrect_username_or_password": "用户名或密码错误",
        "auth.invalid_or_expired_token": "令牌无效或已过期",
        "auth.learner_profile_required": "需要学习者身份",
        "auth.learner_preset_failed": "学习者预设初始化失败。",
        "auth.login_disabled": "认证已禁用——无需登录。",
        "auth.non_admin_provisioning_only": "此端点只能创建非管理员用户。",
        "auth.pairing_code_invalid": "配对码无效、已过期或已被使用",
        "auth.pairing_no_frontend_host": "配对请求缺少有效的前端主机",
        "auth.profiles_disabled": "认证已禁用——无法使用个人资料。",
        "auth.registration_disabled": "认证已禁用——无法注册。",
        "auth.registration_failed": "注册失败——用户名或邮箱可能已被占用。",
        "auth.self_registration_closed": "自助注册已关闭。请联系管理员创建账号。",
        "auth.session_not_device": "此会话未使用设备凭据。",
        "auth.signin_private_origin": "仅可从私有的 DeepTutor 源登录",
        "auth.standard_preset_only": "PocketBase 模式仅支持 standard 预设。",
        "auth.too_many_handoff": "交接请求过于频繁，请稍后再试。",
        "auth.user_creation_disabled": "认证已禁用——无法创建用户。",
        "auth.user_import_disabled": "认证已禁用——无法导入用户。",
        "auth.user_not_found": "未找到用户",
        "auth.username_taken": "用户名已被占用",
        "auth.valid_https_origin_required": "请输入有效的 HTTPS 公开源",
        "book.action_failed": "书籍操作失败",
        "book.block_not_editable": "内容块不存在或不可编辑",
        "book.block_not_found": "未找到内容块",
        "book.book_or_page_not_found": "未找到书籍或页面",
        "book.capture_not_found": "未找到学习记录",
        "book.creation_not_allowed": "不允许创建书籍",
        "book.focus_check_save_failed": "保存专注检测证据失败",
        "book.invalid_capture_status": "无效的记录状态：{status}",
        "book.invalid_proposal": "无效的书籍方案：{error}",
        "book.invalid_spine": "无效的大纲：{error}",
        "book.invalid_transition": "无效的状态转换：{current} -> {next}",
        "book.not_found": "未找到书籍",
        "book.page_not_found": "未找到页面",
        "book.page_or_chapter_not_found": "未找到页面或章节",
        "book.parent_page_not_found": "未找到父页面",
        "book.revision_conflict_own": "自你上次操作后书籍已变化——正在重新加载最新版本。",
        "book.revision_conflict_shared": "该书籍已被其他协作者更新。",
        "book.revision_required": "编辑前请刷新共享书籍。",
        "book.source_text_required": "source_text 不能为空",
        "book.spine_not_found": "未找到大纲",
        "book.unknown_block_type": "未知的内容块类型：{name}",
        "book.unknown_content_type": "未知的内容类型：{name}",
        "book.user_intent_required": "user_intent 不能为空",
        "cli_apps.abi_mismatch": (
            "CLI 应用 {app!r} 是为 {installed} 安装的，当前运行环境是 {current}，需要管理员重新安装。"
        ),
        "cli_apps.args_required": "{tool} 需要 args 数组：每个命令行参数占一个元素。",
        "cli_apps.entry_admin_only": "CLI 应用由管理员安装，请联系管理员添加。",
        "cli_apps.install_in_progress": "该应用正在安装中。",
        "cli_apps.not_in_catalog": "目录中没有名为 {id!r} 的 CLI 应用。",
        "cli_apps.not_installed": "CLI 应用 {app!r} 已不在本部署中。",
        "cli_apps.still_running": "{app} 仍在运行（已 {seconds} 秒）",
        "knowledge.archive_empty": "归档 '{name}' 中没有受支持的文件。",
        "knowledge.archive_rejected": "已拒绝归档 '{name}'：{reason}",
        "knowledge.archive_too_large": "归档 '{name}' 超过最大大小限制 {limit}",
        "knowledge.bound_embedding_unavailable": (
            "绑定的嵌入模型不可用或已更改。请检查模型设置，或选择模型重建此知识库的索引。"
        ),
        "knowledge.cancel_boundary": "取消将在下一个安全边界生效；已完成解析的产物仍可复用。",
        "knowledge.cancel_requested": "已请求取消",
        "knowledge.change_embedding_via_reindex": "请通过重建索引更改知识库的嵌入模型。",
        "knowledge.configs_synced": "已从元数据文件同步配置",
        "knowledge.delete_failed": "删除知识库失败",
        "knowledge.duplicate_filename": (
            "清理文件名后出现重复：'{name}'。请重命名其中一个文件后重试。"
        ),
        "knowledge.embedding_updated_empty": "已更新空知识库的嵌入模型。",
        "knowledge.empty_kb_defaults": "空的 LightRAG 知识库使用默认配置。请在设置中配置模型。",
        "knowledge.file_too_large": "文件 '{name}' 超过最大大小限制 {limit}",
        "knowledge.folder_fields_required": "name 和 folder_path 均为必填项。",
        "knowledge.folder_into_itself": "不能把文件夹移动到自身内部",
        "knowledge.folder_name_required": "文件夹名称为必填项",
        "knowledge.folder_not_linkable": "该文件夹无法关联。",
        "knowledge.folder_not_found": "未找到文件夹 '{id}'",
        "knowledge.folder_path_required": "folder_path 为必填项。",
        "knowledge.folder_unlinked": "文件夹已成功取消关联",
        "knowledge.graphrag_compat_failed": "因内部错误无法测试 GraphRAG 兼容性。",
        "knowledge.graphrag_not_installed": (
            "未安装 GraphRAG。请先在服务器上运行 `pip install 'deeptutor[graphrag]'` "
            "再创建 GraphRAG 知识库。"
        ),
        "knowledge.graphrag_preflight_failed": "GraphRAG 预检失败：{details}",
        "knowledge.ima_connect_failed": "连接 IMA 知识库失败。",
        "knowledge.ima_connect_probe_failed": "无法连接到 IMA 知识库。",
        "knowledge.ima_credentials_required": "Client ID 和 API key 为必填项。",
        "knowledge.ima_invalid_response": "IMA 返回了无效响应。",
        "knowledge.ima_rate_limited": "已达到 IMA 速率限制，请稍后重试。",
        "knowledge.ima_rejected": "IMA 拒绝了提供的凭据。",
        "knowledge.ima_unreachable": "无法连接腾讯 IMA。",
        "knowledge.index_already_ready": (
            "知识库 '{name}' 已有适用于当前嵌入配置的索引，无需重建。"
        ),
        "knowledge.index_run_inactive": "该索引任务已不再运行。",
        "knowledge.index_worker_owns": "仍有索引任务占用此知识库。",
        "knowledge.initializing": "正在初始化知识库……",
        "knowledge.init_complete": "知识库初始化完成！",
        "knowledge.init_failed": "初始化失败：{error}",
        "knowledge.invalid_folder_path": "无效的文件夹路径",
        "knowledge.invalid_mode": "模式 '{mode}' 对 {engine} 无效。请从以下选择：{modes}。",
        "knowledge.invalid_search_mode": "检索模式 '{mode}' 对 {engine} 无效。请从以下选择：{modes}。",
        "knowledge.kb_already_exists": "知识库 '{name}' 已存在",
        "knowledge.kb_alias_not_found": "未找到知识库 '{name}'",
        "knowledge.kb_created_empty": "知识库已创建（暂无文档）。",
        "knowledge.kb_created_named": "知识库 '{name}' 已创建（暂无文档）。",
        "knowledge.kb_created_processing": "知识库 '{name}' 已创建。正在后台处理 {count} 个文件。",
        "knowledge.kb_deleted": "知识库 '{name}' 删除成功",
        "knowledge.kb_legacy_reindex": (
            "知识库 '{name}' 使用旧版索引格式，需先重建索引才能接受增量上传。"
        ),
        "knowledge.kb_name_required": "知识库名称为必填项。",
        "knowledge.kb_needs_reindex": "知识库需要重建索引或初始化。",
        "knowledge.kb_no_local_files": "知识库 '{name}' 连接到外部资源，没有本地文件。",
        "knowledge.kb_not_error_state": (
            "知识库 '{name}' 不处于错误状态。如需重建正常的知识库，请使用重建索引。"
        ),
        "knowledge.kb_not_found": "未找到知识库 '{name}'",
        "knowledge.kb_ready": "知识库已就绪。",
        "knowledge.kb_read_only": (
            "知识库 '{name}' 连接到外部资源，为只读状态。无法对其进行本地文件操作和重建索引。"
        ),
        "knowledge.kiwix_kb_not_found": "未找到 Kiwix 知识库。",
        "knowledge.kiwix_search_failed": "Kiwix 搜索失败。",
        "knowledge.list_failed": "列出知识库失败：{error}",
        "knowledge.lightrag_model_pair_required": "LightRAG 模型选择需要同时提供 profile_id 和 model_id。",
        "knowledge.lightrag_not_installed": (
            "未安装 LightRAG。请先在服务器上运行 `pip install 'deeptutor[rag-lightrag]'` "
            "再创建 LightRAG 知识库。"
        ),
        "knowledge.lightrag_overrides_removed": (
            "请在设置中配置 LightRAG 模型；不再支持按知识库单独覆盖。"
        ),
        "knowledge.lightrag_server_fields_required": "name 和 server_url 均为必填项。",
        "knowledge.lightrag_server_unreachable": "无法连接到 LightRAG 服务器。",
        "knowledge.linked_folder_not_found": "未找到关联文件夹 '{id}'",
        "knowledge.load_all_failed": "加载知识库失败。错误：{errors}",
        "knowledge.load_assigned_failed": "加载分配的知识库信息失败。",
        "knowledge.load_kb_info_failed": "加载知识库信息失败。",
        "knowledge.name_exists_in_folder": "'{name}' 已存在于目标文件夹",
        "knowledge.name_required": "name 为必填项。",
        "knowledge.no_default_kb": "未配置默认知识库",
        "knowledge.no_embedding_configured": (
            "尚未配置嵌入模型。重建索引前请先在设置中配置嵌入档案。"
        ),
        "knowledge.no_files_to_sync": "没有新文件或已修改的文件需要同步",
        "knowledge.no_github_sources": "没有 GitHub 来源",
        "knowledge.no_enabled_web_sources": "没有已启用的网页来源",
        "knowledge.no_local_embedding": "该知识引擎不使用本地嵌入模型。",
        "knowledge.no_models_configured": "尚未配置 '{kind}' 模型。",
        "knowledge.no_retrieval_modes": "引擎 '{engine}' 没有可用的检索模式。",
        "knowledge.no_web_sources": "没有网页来源",
        "knowledge.not_a_zip": "'{name}' 不是有效的 zip 归档。",
        "knowledge.obsidian_fields_required": "name 和 vault_path 均为必填项。",
        "knowledge.pageindex_key_missing": (
            "尚未配置 PageIndex API key。请在创建 PageIndex 知识库前，"
            "在「知识库 → RAG 管道设置」中添加。"
        ),
        "knowledge.pageindex_oss_mode": "PageIndex OSS 模式必须是 'flash'、'standard' 或省略。",
        "knowledge.pageindex_preflight_failed": "PageIndex OSS 预检失败：{details}",
        "knowledge.pageindex_unsupported_formats": (
            "PageIndex 知识库接受：{supported}。不支持的格式：{unsupported}。"
        ),
        "knowledge.processing_uploaded": "正在处理 {count} 个上传的文件……",
        "knowledge.progress_cleared": "已清除 {name} 的进度",
        "knowledge.progress_not_started": "初始化尚未开始",
        "knowledge.provider_changed_message": (
            "引擎已从 {old} 切换为 {new}；使用前请先重建此知识库的索引。"
        ),
        "knowledge.provider_index_locked": (
            "知识库 '{name}' 已有可用的 {provider} 索引。更改引擎需要显式重建索引或迁移，"
            "而不是静默修改配置。"
        ),
        "knowledge.provider_mismatch": (
            "请求的引擎 '{requested}' 与知识库引擎 '{current}' 不一致。"
            "知识库锁定在创建时使用的引擎上。"
        ),
        "knowledge.queueing_reindex": "正在排队重建索引……",
        "knowledge.readiness_note": (
            "就绪检查只覆盖配置与本地依赖；运行时下载、资源限制和服务方响应仍可能失败。"
        ),
        "knowledge.rebuild_config_changed": "重建配置已变化。请查看更新后的配置并再次确认。",
        "knowledge.rebuild_confirm_defaults": "请在「索引版本」中查看当前默认配置并确认 LightRAG 重建。",
        "knowledge.rebuild_confirm_review": "重建前请查看当前重建配置并确认。",
        "knowledge.rebuild_lightrag_only": "重建配置仅适用于 LightRAG。",
        "knowledge.reindexing": "正在后台重建 '{name}' 的索引。",
        "knowledge.retry_scheduled": "已安排重试",
        "knowledge.role_models_cannot_clear": "不能清空角色模型。",
        "knowledge.saved_files_preparing": "已保存 {count} 个文件，准备处理……",
        "knowledge.server_url_required": "server_url 为必填项。",
        "knowledge.source_not_found": "未找到源对象",
        "knowledge.source_not_found_by_id": "未找到来源 '{id}'",
        "knowledge.source_operation_failed": "知识库来源操作失败",
        "knowledge.source_path_required": "源路径为必填项",
        "knowledge.source_removed": "已移除",
        "knowledge.sync_enable_before_retry": "重试前请先启用该来源和自动同步",
        "knowledge.sync_job_not_found": "未找到同步任务",
        "knowledge.sync_not_cancellable": "同步任务无法取消",
        "knowledge.synced_sources": "已同步 {count} 个来源",
        "knowledge.syncing_folder": "正在从关联文件夹同步 {count} 个文件……",
        "knowledge.syncing_folder_message": "正在从关联文件夹同步 {count} 个文件",
        "knowledge.task_completed": "知识库处理已完成。",
        "knowledge.task_failed": "知识库处理失败。",
        "knowledge.task_interrupted": "知识库处理因服务器重启而中断。请重试以继续。",
        "knowledge.unknown_model": "该配置档案下没有此模型。",
        "knowledge.unknown_profile": "该类别下没有此配置档案。",
        "knowledge.unsupported_model_kind": "不支持的模型类别 '{kind}'。请从以下选择：{kinds}。",
        "knowledge.uploaded_processing": "已上传 {count} 个文件，正在后台处理。",
        "knowledge.use_role_models": "此配置请使用 role_models。",
        "knowledge.validation_failed": "文件 '{name}' 校验失败：{error}",
        "knowledge.visual_asset_not_found": "未找到可视化素材",
        "knowledge.visual_coverage_unreadable": "可视化覆盖信息不可读；原始证据文件已保留。",
        "knowledge.visual_source_changed": "引用的来源已更改或缺失。请明确选择其当前版本。",
        "knowledge.weknora_all_fields_required": "name、server_url 和 knowledge_base_id 均为必填项。",
        "knowledge.weknora_fields_required": "server_url 和 knowledge_base_id 均为必填项。",
        "knowledge.weknora_unreachable": "无法连接到 WeKnora 知识库。",
        "mastery.active_turn_not_stopped": "更改此路径前无法停止进行中的学习回合",
        "mastery.invalid_book_id": "无效的 book_id",
        "mastery.invalid_kp_data": "modules[{index}] 中的 knowledge_point 数据无效：{errors}",
        "mastery.invalid_mode": "mode 必须是以下之一：{modes}",
        "mastery.invalid_module_data": "modules[{index}] 中的 module 数据无效：{errors}",
        "mastery.llm_invalid_json": "LLM 返回了无效的 JSON",
        "mastery.llm_invalid_structure": "LLM 返回了无效结构：modules 不是列表",
        "mastery.module_needs_kp": "模块 '{id}' 必须包含至少一个知识点",
        "mastery.module_required": "至少需要一个学习模块",
        "mastery.no_records": "未提供记录",
        "mastery.objective_not_found": "未找到目标",
        "mastery.path_activity_changed": "操作启动时掌握路径的活动状态发生变化；活跃会话：{session}",
        "mastery.progress_generic_not_found": "未找到进度",
        "mastery.progress_not_found": "未找到掌握进度",
        "mastery.session_not_found": "未找到会话",
        "mastery.topic_not_found": "未找到掌握主题",
        "mcp.configure_command_or_url": "服务器 {name!r}：请配置 command（stdio）或 url。",
        "mcp.configure_before_testing": "测试前请先配置 command（stdio）或 url。",
        "mcp.server_error": "服务器 {name!r}：{error}",
        "mcp.server_missing": "你的列表中没有名为 {name!r} 的服务器。",
        "mcp.not_oauth": "该服务器不使用 OAuth，请改为填写凭据。",
        "mcp.oauth_callback_incomplete": "授权回调信息不完整。",
        "mcp.oauth_callback_unknown": "该授权已过期或已完成，请重新发起。",
        "mcp.oauth_done": "已授权，可以关闭此页。",
        "mcp.oauth_failed": "授权失败。",
        "mcp.catalog_entry_missing": "目录中没有名为 {id!r} 的 MCP 服务。",
        "mcp.entry_admin_only": "该服务以本地命令方式运行，只能由管理员添加。",
        "mcp.tool_not_available": "该工具在本次对话中不可用，只能调用提示中列出的工具。",
        "sandbox.command_blocked": "错误：命令被安全防护拦截（匹配危险模式）。",
        "sandbox.disabled_for_account": "你的账号已禁用代码执行。",
        "sandbox.no_backend": "没有可用的沙箱后端",
    },
}


def current_language(default: str = "en") -> str:
    try:
        from deeptutor.services.settings.interface_settings import get_ui_language

        return _parse_language(get_ui_language(default=default))
    except Exception:
        return _parse_language(default)


def t(key: str, default: str = "", *, language: str | None = None, **kwargs: Any) -> str:
    lang = _parse_language(language) if language else current_language()
    text = _MESSAGES.get(lang, {}).get(key) or _MESSAGES["en"].get(key) or default
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text


__all__ = ["current_language", "t"]
