# Windows 兼容风险静态扫描报告（AGEN-547）

- 日期：2026-10-04
- 基线：`origin/dev` = `origin/main` = `f07029cfc`（release: v1.6.13），新 worktree + 新分支 `scan/win-compat-20261004`，未改动任何业务代码
- 范围：`deeptutor/`、`deeptutor_cli/`、`scripts/`、`tests/`、`web/tests/`（Python 1066 个文件 + TS 契约测试）
- 方法：静态扫描（ripgrep 模式匹配 + AST 精确解析），未在 Windows 上运行（按验收标准 1）
- 分类：A 路径拼接/分隔符、B 编码未显式声明、C Unix-only API、D 进程启动参数差异

## 计数汇总

| 等级 | 数量 |
|---|---|
| HIGH | 1 |
| MEDIUM | 6 |
| LOW | 8 |
| 合计 | 15 |

原始命中（未去重的扫描行）：A 类 93+58 行、B 类 AST 精确 32（非测试代码）+106（tests）、C 类 175 行、D 类 34 行，全部经人工分型去伪（URL 拼接、二进制模式 open、POSIX-only 分支等不计入）。

## Top 10（按风险排序）

### 1. [HIGH] workspace/catalog.py:402 — 未加防护的 `os.kill(pid, 0)` 存活探测

- 类别：C（Unix-only API 语义差异）
- 依据：`assert_available()` 中 `os.kill(int(migration["pid"]), 0)` 仅捕获 `ProcessLookupError`。CPython 在 Windows 上把常规 `os.kill` 实现为 `TerminateProcess`（仓库自己在 `deeptutor/runtime/process.py:39-41` 注释了这一点）：探测会直接**终止**本机同 host 的迁移进程；且 pid 不存在时抛出的是 `OSError`/`PermissionError`，不被 `except ProcessLookupError` 捕获，`assert_available` 崩溃。该文件无任何 `os.name`/`sys.platform` 分支。
- 建议：改用已存在的 `deeptutor.runtime.process.is_process_alive(pid)`（Windows 走 ctypes `OpenProcess` 探测）。

### 2. [MEDIUM] reading/ingestion.py:1015、1067 — ffmpeg/ffprobe 输出按本地代码页解码

- 类别：B（编码未显式声明）
- 依据：`subprocess.run(command, capture_output=True, text=True, timeout=…)` 未传 `encoding`/`errors`。Windows 上 text 模式按 locale（cp936/cp1252）解码，ffmpeg 输出含 UTF-8 字符时抛 `UnicodeDecodeError`，阅读材料音视频分段/时长探测在中文 Windows 直接失败。ffmpeg 本身可经 `shutil.which("ffmpeg")` 找到（979 行有判空），依赖未文档化是另一已登记问题（上游 #1554）。
- 建议：加 `encoding="utf-8", errors="replace"`。

### 3. [MEDIUM] parsing/engines/mineru/local.py:85、99 — MinerU 版本探测解码崩溃

- 类别：B
- 依据：`subprocess.run(["mineru", "--version"], …, text=True)` 只捕获 `FileNotFoundError`；中文 Windows 上 mineru/magic-pdf 输出 UTF-8 横幅时 `UnicodeDecodeError` 直接传播，"未安装" 误判为崩溃。上游 #844 修过 MinerU 转换管线的解码，但版本探测点漏掉。
- 建议：补 `encoding="utf-8", errors="replace"`，并将探测包进 `except (OSError, UnicodeDecodeError)`。

### 4. [MEDIUM] workspace 迁移/恢复链路 8 处 `json.loads(path.read_text())` 无 encoding

- 类别：B
- 依据：`deeptutor/services/workspace/data_migration.py:489、755、900、931、944`、`dependencies.py:104、213`、`session_move.py:80`、`deeptutor/services/session/usage_recovery.py:68`。写入侧 `atomic_write_text`（file_io.py:63）固定 UTF-8，读取侧裸 `read_text()` 用 locale —— 编码不对称。Windows 非 UTF-8 locale 下，含中文文件名/标题的快照、manifest、usage 报表在迁移与恢复时抛 `UnicodeDecodeError`。
- 建议：统一 `read_text(encoding="utf-8")`（可加 `errors="strict"` 保持失败可见）。

### 5. [MEDIUM] cli_apps/installer.py:243-245 — 安装环境 allow-list 是 POSIX 形状

- 类别：D（进程启动参数差异）
- 依据：`keep = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", …)` 保留 POSIX 变量，不含 `USERPROFILE`/`TEMP`/`TMP`/`APPDATA`；兜底 `env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")` 用 `:` 分隔且指向 Unix 路径。Windows 上第三方 CLI 的 pip 安装拿不到临时目录与用户目录，兜底 PATH 无效。
- 建议：按 `os.name == "nt"` 扩展 keep 集合（TEMP/TMP/USERPROFILE/APPDATA/SystemRoot），兜底 PATH 用 `os.pathsep` 并给出 Windows 合法默认。

### 6. [MEDIUM] skill/hub.py:629 — skill fetch 子进程解码

- 类别：B
- 依据：hub fetch 命令（git/curl 类）`subprocess.run(…, text=True)` 无 encoding，非 UTF-8 代码页下输出解码抛错，skill 安装失败且报错被截断混入解码异常。
- 建议：同上，显式 UTF-8 + replace。

### 7. [MEDIUM] 长流式安装/下载 Popen 无 encoding（3 处）

- 类别：B
- 依据：`deeptutor/services/parsing/engines/_install.py:197`、`parsing/engines/mineru/models.py:123`、`cli_apps/installer.py:259`。`Popen(…, text=True)` 流式读取 pip/模型下载输出，Windows locale 解码在安装中途抛 `UnicodeDecodeError`，安装流程中断。
- 建议：显式 `encoding="utf-8", errors="replace"`。

### 8. [LOW] office_preview.py:74 — `shutil.which("soffice")` 找不到默认安装

- 类别：D
- 依据：Windows LibreOffice 默认装在 `C:\Program Files\LibreOffice\program\`（可执行文件 soffice.exe/soffice.com），不在 PATH；`which("soffice")` 返回空 → 抛 `OfficePreviewUnavailable`，功能静默降级（不崩溃，属可用性缺口）。进程组清理（:136）已有 `os.name == "posix"` 防护。
- 建议：探测标准安装目录后再报不可用。

### 9. [LOW] app_update.py:167 — zip 内 `read_text("direct_url.json")` 无 encoding

- 类别：B
- 依据：`zipfile.Path.read_text(name)` 默认 locale 解码。pip 生成的 direct_url.json 实际为 ASCII，风险为理论性，但与 UTF-8 约定不一致。
- 建议：`read_text(name, encoding="utf-8")`。

### 10. [LOW] mineru/backend.py:170 — 版本探测解码错误被吞成"不可用"

- 类别：B
- 依据：探测包在 `except Exception: return ""` 内，解码错误不会崩溃但导致误判"未安装"（本地 CLI 明明可用）。同类问题在 local.py 会崩溃（见 #3），此处是静默误判变体。
- 建议：显式 UTF-8 解码后保留 except 兜底。

## 其余 LOW（11-15）

11. **scripts/check_branch_policy.py:11、21 与 scripts/check_workspace_hygiene.py:11**（B）— 贡献者工具 text=True 无 encoding，Windows 上 git 输出解码可崩；建议同上加 encoding。
12. **sandbox/runner/server.py:233**（D）— `shell=True` 契约执行器：Windows 走 `%COMSPEC%`（cmd.exe）而非 POSIX shell，脚本语法兼容性由调用方自负；rlimit/preexec_fn 已按 POSIX-only 文档化降级（91 行注释）。仅记录行为差异。
13. **tests/ 共 106 处文本模式 open/read_text/write_text 无 encoding**（B，AST 精确计数）— 测试夹具含非 ASCII 时 Windows 上易解码失败；建议批量补 `encoding="utf-8"`（机械改动）。
14. **os.chmod POSIX 位权限族约 15 处**（C，informational）— `mcp/oauth.py:98,127`、`mcp/secrets.py:55,178`、`mcp/user_config.py:75,217`、`multi_user/paths.py:137,234`、`multi_user/session_handoff.py:192,224-225`、`codex_auth/storage.py:59,100,135-136`、`video_learning/invidious_account_storage.py:38,49`、`knowledge/manager.py:1843`、`cli_apps/paths.py:99`。Windows 上 os.chmod 只实现只读位，`S_IRWXU`/`S_IRUSR` 等收权语义静默失效（不抛错）。属加固效果缺口，非崩溃风险；如需 Windows 等效收权需走 ACL API，可另立设计卡。
15. **web/tests/dev-heap-ceiling.test.ts:51**（A，informational）— 用 `line.includes("bin/next dev")` 匹配日志文本，若启动器在 Windows 记录反斜杠形式会漏判；当前启动器日志为 POSIX 风格字符串，暂无实际问题。

## 上游已修复/已覆盖（本扫描排除，仅标注）

- **UID 兼容（#1584/#1591/#1598）**：`services/setup/data_volume.py:32-33` 用 `getattr(os, "geteuid", None)` 防护；dev 上 `knowledge/add_documents.py`、`knowledge/initializer.py` 现无 geteuid/getuid 直接调用（#1598 未合并，其覆盖点在当前 dev 已不存在或不适用）。
- **测试路径分隔符（#1696/#1697，PR 关闭未合并但问题已解）**：dev 的 `web/tests/architecture-contracts.test.ts:8` 已有 `portablePath`（replaceAll 反斜杠）；`internal-route-contract.test.ts:17-19,37-38` 用 `path.basename` + `path.sep` 重写，Windows 安全。
- **fcntl 文件锁（#1140/#1143/#1177/#1183）**：12 个模块（video_learning/service、session/sqlite_store、session/legacy_migration、cron/repository、multi_user/grants、partners/manager、partners/web_continuity、learning/migration、codex_auth/storage、partners/channels/msteams、knowledge/manager、rag/pipelines/lightrag/write_lock）均为 try/except ImportError + msvcrt.locking 双路径。
- **os.kill Windows 语义**：`runtime/process.py` is_process_alive 在 nt 走 ctypes OpenProcess。
- **进程树终止**：`runtime/launcher.py` `_get_pgid`（:162 nt 早退）、`_send_tree_signal`（:237 taskkill /T /F）；`services/sandbox/backends.py:449-460`、`services/office_preview.py:131-141` 平台分支齐全。
- **CREATE_NO_WINDOW（#1501）**：launcher.py:214-230、update_worker.py:91、app_update.py:644、codebuddy_provider.py:806。
- **npm/.cmd shim（#309/#381/#853）**：`services/subagent/process.py:31-39` PATHEXT 解析。
- **信号注册（#1147/#1152）**：launcher.py:1045-1064 SIGINT/SIGBREAK getattr+try/except。
- **子进程输出编码环境（#702）**：launcher.py:1413 `PYTHONIOENCODING=utf-8:replace`；workspace/execution.py:105 `PYTHONUTF8=1`（:100 有 cp936 注释说明）。
- **入站路径反斜杠归一**：api/routers/knowledge.py:394,455,615；visualizers/protocol.py:59、store.py:231；web/tests/native-button-title.test.ts:31。
- **/proc 读取**：runtime/memory_probe.py 全部 OSError 防护，Windows 走 psutil 路径。
- **termios**：deeptutor_cli/common.py:40-45 ImportError 早退。
- **Windows 沙箱执行（#964/#1033）**：backends.py:70,322 Scripts/bin 分支 + PowerShell 5.1 命令构造（:340）；bwrap 后端为 Linux-only 设计（缺失时报 "bwrap not found"）。
- **pty 预览**：subagent/claude_models.py:150-154 import 失败返回 None。
- **umask 测试**：tests/utils/test_secret_files.py:52 @posix_only。
- **Windows 启动脚本**：scripts/start_backend.bat、start_frontend.bat 已在 dev。

## 复现命令（静态）

```
git fetch --multiple origin myfork
git worktree add <wt> -b scan/win-compat-20261004 f07029cfc
rg -n --glob '*.py' -e 'os\.setsid' -e 'preexec_fn' -e '\bfcntl\b' … deeptutor deeptutor_cli scripts tests
rg -nP 'open\((?![^)]*encoding=)' …（初筛）
python3 evidence/scan-win-compat-20261004/raw/scan_encoding.py deeptutor deeptutor_cli scripts   # AST 精确：32
python3 evidence/scan-win-compat-20261004/raw/scan_encoding.py tests                             # AST 精确：106
rg -nP "f\"[^\"]*\}/[^\"]*\"" …（路径拼接初筛，175 行人工分型）
rg -n 'shell=True|executable=|/bin/(bash|sh)|creationflags|npm\.cmd' …（进程启动）
```

原始输出见 `raw/`（A/A2/B/B2/B3/B4/C/D/E + scan_encoding.py），SHA256 见 `SHA256SUMS`。

## 建议后续（不在本卡执行）

1. 一张小修复卡收编 #1（catalog.py 换 is_process_alive，附中性回归测试）。
2. 一张编码统一卡收编 #2/#3/#4/#6/#7/#9/#11（机械加 encoding="utf-8"，tests 106 处可一并批量处理）。
3. #5（installer env allow-list）与 #8（soffice 探测）可合入"Windows 安装体验"卡。
4. #14 chmod 语义差异建议进设计讨论（Windows ACL 方案），不属机械修复。
