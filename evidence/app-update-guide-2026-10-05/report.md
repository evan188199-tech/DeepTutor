# 自更新链路导读（检查 → 下载 → 交接 → 重启 → 版本展示）

- 基线：origin/main `f07029cfc`（v1.6.13），2026-10-05 读取（worktree `dt-agen676-wt`，分支 `guide/app-update-20261005`）。
- 本文为只读导读，不改任何代码。所有结论附 `path:line`（基于上述基线）。
- 目的：为评估上游 issue [#725](https://github.com/HKUDS/DeepTutor/issues/725)（"Auto-update button" feature request）提供现状地图。#725 及其关联 PR 只读参考，不在本文实现或评审其改动。

## 0. 去重与相关产出（先读）

| 产出 | 位置/分支 | 关系 | 处理 |
| --- | --- | --- | --- |
| runtime 更新链路导读（2026-10-04） | 分支 `docs/guides/runtime-update-chain`，`evidence/guide-runtime-2026-10-04/guide.md`（基线 v1.6.12 `ef2d9e5c3`） | 已深读 launcher handoff / update_worker / job store 与失败模式表（其 F1–F8） | 本文不重复其 job store 细节，只在 §7 用 v1.6.13 行号刷新断点表；补齐它未覆盖的「检查 / 下载」环节与 web 设置页版本展示 |
| fix-update-worker（吞错修复，另一视角） | AGEN-138/139 → 分支 `myfork/fix/update-worker-state-load-fail(-pr)`，已并入上游 PR [#1704](https://github.com/HKUDS/DeepTutor/pull/1704)（OPEN，head `pr/runtime-log-swallowed-failures`） | 修复视角；本文只标注断点归属，不重复给修法 | §7 中 F1、F2 标注"已认领（PR #1704）" |
| test-app-update-version（行为基线） | AGEN-669（in_review），分支 `test/app-update-version-parsing-20261005`，新增 `tests/services/test_app_update_version_parsing.py`（357 行） | 钉住 `VersionCheckService` 版本比较与发布响应解析行为 | 本文 §3 引用其覆盖面，不再展开解析规则逐条 |
| 上游 PR #1186（MERGED，`fix/source-install-update-detection`） | 已进入本基线 | source checkout 误判 pypi 的修复 | 现状即其成果：`deeptutor/services/app_update.py:174-180`（检测）+ `:231-238`（分类为 source） |

上游开工前检查：#725 为 OPEN，评论区引用 PR #1186（已 MERGED）；未发现针对「检查→下载→交接→重启」主链的其它开放实现 PR（PR #1704 只覆盖吞错修复）。本卡不实现、不动其关联 PR，符合卡面要求。

## 1. 参与者与调用图

| 角色 | 文件 | 关键符号 |
| --- | --- | --- |
| 安装形态识别 | `deeptutor/services/app_update.py:219-285` | `detect_installation` |
| 版本检查服务 | `deeptutor/services/app_update.py:288-379` | `VersionCheckService.check/_fetch/_fetch_latest_redirect` |
| 发布响应解析 | `deeptutor/services/app_update.py:382-468` | `_release_from_payload` / `_release_from_latest_url` / `_plain_release_excerpt` |
| 任务持久层（job store） | `deeptutor/services/app_update.py:475-597` | `UpdateJobStore`（详见 2026-10-04 导读） |
| 后端 API | `deeptutor/api/routers/system.py:236-317` | `get_update_status` / `check_for_update` / `update_check_settings` / `get_update_job` / `request_managed_update` |
| 空闲门控 | `deeptutor/services/session/turns/lifecycle.py:130-149` | `reserve_managed_update` |
| 交接方（launcher） | `deeptutor/runtime/launcher.py:1211-1259` | `_handoff_pending_update` |
| 闭环方（launcher） | `deeptutor/runtime/launcher.py:1262-1276` | `_complete_restarted_update` |
| 独立执行器（worker） | `deeptutor/runtime/update_worker.py:103-146` | `run_update_worker` |
| 前端 API 客户端 | `web/lib/app-update.ts:103-157` | `fetchAppUpdateStatus` / `checkAppUpdate` / `requestAppUpdate` / `fetchAppUpdateJob` |
| 设置页版本展示 | `web/features/settings/sections/AboutSettingsSection.tsx` | About 页整页 |
| 侧边栏版本徽标 | `web/components/sidebar/VersionBadge.tsx:23-63` | `VersionBadge` |

数据文件：`<home>/data/user/update/` 下 `state.json`（`app_update.py:480`）、`active`（单飞槽位，`app_update.py:481,498`）、`worker.log`（`app_update.py:482`；写入点 `app_update.py:650-651`、`update_worker.py:67,97`）。目录根：`update_store_root`（`app_update.py:471-472`）。

```mermaid
flowchart TD
    subgraph 检查
        A1["About 页加载<br/>AboutSettingsSection.tsx:68-84"] -->|GET /api/system/update| A2["get_update_status<br/>system.py:236-240"]
        A3["Check now 按钮<br/>AboutSettingsSection.tsx:228-240"] -->|POST /api/system/update/check<br/>admin| A4["check_for_update force=True<br/>system.py:243-246"]
        A2 --> A5["_checked_update_payload<br/>system.py:204-234"]
        A4 --> A5
        A5 --> A6["VersionCheckService.check<br/>app_update.py:318-331（24h 进程内缓存 :311-316）"]
        A6 --> A7["_fetch → GitHub Releases API<br/>app_update.py:333-354"]
        A7 -->|失败| A8["_fetch_latest_redirect<br/>app_update.py:356-379"]
        A7 --> A9["_release_from_payload<br/>app_update.py:382-408"]
        A8 --> A10["_release_from_latest_url<br/>app_update.py:411-443"]
        A9 --> A11["VersionBadge 订阅广播<br/>app-update.ts:66-71 → VersionBadge.tsx:23-44"]
    end
    subgraph 下载（预约）
        B1["Update to vX 按钮<br/>AboutSettingsSection.tsx:241-250,409-422"] -->|POST /api/system/update<br/>admin| B2["request_managed_update 守卫链<br/>system.py:269-297"]
        B2 --> B3["reserve_managed_update 空闲门控<br/>lifecycle.py:130-149"]
        B3 --> B4["UpdateJobStore.create<br/>app_update.py:484-510（active 槽位 O_EXCL :498）"]
    end
    subgraph 交接
        B4 -->|state.json=pending| C1["launcher 主循环每 ~1s<br/>launcher.py:1571-1573"]
        C1 --> C2["_handoff_pending_update<br/>launcher.py:1211-1259"]
        C2 --> C3["prepare_handoff pending→handoff<br/>app_update.py:518-536"]
        C3 --> C4["launch_update_worker（detached）<br/>app_update.py:623-651"]
        C4 --> C5["launcher 置 shutdown 并退出<br/>launcher.py:1572-1573"]
    end
    subgraph 重启
        C5 --> D1["run_update_worker<br/>update_worker.py:103-146"]
        D1 --> D2["wait_for_parent 60s<br/>update_worker.py:56-63,118"]
        D2 --> D3["mark_running → pip install --upgrade deeptutor==target<br/>update_worker.py:119,123-127（命令构造 :17-40）"]
        D3 --> D4["mark_restarting<br/>update_worker.py:128"]
        D4 --> D5["_launch_restart 受信 argv<br/>update_worker.py:43-49,81-100"]
        D5 --> D6["新 launcher start()<br/>launcher.py:1278"]
        D6 --> D7["_complete_restarted_update → mark_succeeded<br/>launcher.py:1558,1262-1276"]
        D1 -.失败.-> D8["恢复段 mark_failed + 尽力拉起<br/>update_worker.py:134-146（:144-145 吞错，见 §7 F2）"]
    end
    D6 -.轮询.-> E1["前端 job 轮询 800ms/120s<br/>AboutSettingsSection.tsx:90-125<br/>← GET /api/system/update/job system.py:258-260"]
    E1 -.succeeded.-> A1
```

鉴权基线：全部 `/api/system` 路由挂登录依赖（`deeptutor/api/main.py:732`），其中 `POST /update/check`、`PUT /update/settings`、`POST /update` 额外 `require_admin`（`system.py:243,250,263-267`）；`GET /update`、`GET /update/job` 登录即可（产品取舍：徽标对所有登录用户可用）。

## 2. 环节 A：检查（现状：已实现，GitHub 单源）

1. **入口**：About 页加载即 `GET /api/system/update`（`AboutSettingsSection.tsx:68-84` → `system.py:236-240`）；管理员可 `Check now` 强制刷新（`AboutSettingsSection.tsx:228-240` → `system.py:243-246`，`force=True`）。
2. **开关与缓存**：`version_check_enabled` 存于 runtime settings（`system.py:204-208,250-254`）；`VersionCheckService` 进程内 24h 缓存（`app_update.py:29,311-316`），单例（`app_update.py:654-658`）。
3. **取数**：GitHub Releases API（`app_update.py:27,333-354`）；API 失败（含限流）回退 `HEAD /releases/latest` 重定向解析（`app_update.py:356-379`），传输错误转 `VersionCheckError` 且原因可安全展示（`app_update.py:373-378`）。
4. **解析与校验**：拒绝 draft/prerelease（`app_update.py:383-384`）、tag 必须稳定三段版本（`app_update.py:386-388,143-147`）、URL 白名单 `https://github.com/HKUDS/DeepTutor/releases/`（`app_update.py:390-391`；重定向分支更严：`app_update.py:419-428`）。changelog 摘要压成 ≤640 字符纯文本（`app_update.py:446-468`）；migration 提示用英文关键词正则（`app_update.py:395-400`）。
5. **比较**：`update_available` = 目标 > 当前（`app_update.py:82-84,136-140`；当前版本来自 `deeptutor/__version__.py`，`app_update.py:22,324`）。
6. **展示**：About 页 running version 大字（`AboutSettingsSection.tsx:206-215`）、latest 行 + 上次检查时间（`:316-331`）、excerpt（`:342-351`）、migration 警示（`:333-340`）；侧边栏 `VersionBadge` 圆点状态并订阅 About 页的检查结果广播（`VersionBadge.tsx:23-63`，广播机制 `app-update.ts:59-71,83-101`）。
7. **错误面**：非强制检查失败 → `_update_payload` 携带 `check_error` 字符串，前端红字展示（`system.py:217-228`；`AboutSettingsSection.tsx:255-260`）；强制检查失败 → HTTP 503（`system.py:218-222`）。

行为基线测试：`tests/services/test_app_update.py`（本基线 13 项，含缓存 TTL、限流回退、重定向校验、source/docker 识别、systemd cgroup、job store 生命周期；运行记录见 §9）+ AGEN-669 的 `tests/services/test_app_update_version_parsing.py`。

## 3. 环节 B：下载（现状：无独立下载步；"预约 + worker 内 pip 安装"）

"下载"在本链路中不是一个独立阶段——安装包的下载与安装合并为 worker 里的一条 pip 命令，发生在 launcher 退出之后：

1. **前端确认**：`Update to {{version}}` 按钮仅在 `is_admin ∧ check_enabled ∧ update_available ∧ installation.automatic_update ∧ launcher_managed ∧ 无活跃 job` 时出现（`AboutSettingsSection.tsx:182-189,241-250`），点击后经 `ConfirmDialog` 显式确认（`:409-422`）→ `requestAppUpdate`（`app-update.ts:134-142`）。
2. **API 守卫链**（`system.py:263-317`，任一不过即 409/503）：开关关闭 `:269-270` → systemd 环境 `:271-272`（原因文案 `app_update.py:31-35`）→ launcher 不存活 `:273-277`（探活 `app_update.py:614-620`，PID 由 launcher 注入子进程环境 `launcher.py:1419`，env 名 `app_update.py:30`）→ 安装形态非"可自动更新的 pypi" `:278-283` → 重新检查无新版 `:285-290` → 复核安装形态未变 `:292-297`。
3. **空闲门控**：`reserve_managed_update` 在与 turn 调度同一把锁内确认无存活对话才创建 job，并冻结后续 turn（`lifecycle.py:130-149`）；有活跃对话返回 None → 409 "Finish the active conversation"（`system.py:313-317`）。
4. **落盘**：`UpdateJobStore.create` 要求目标版本严格更新（`app_update.py:487-488`），`active` 槽位 `O_CREAT|O_EXCL` 单飞（`:498-500`），写 `state.json` 失败回滚释放槽位（`:505-509`）。
5. **实际安装命令**：worker 唯一允许的变更是 `python -m pip install --no-input --disable-pip-version-check --upgrade deeptutor==<target>`（`update_worker.py:17-40`，目标版本先经 `UpdateJob.from_dict` 严格校验 `:21-30`）。无断点续传/预下载；pip 失败以非零码抛 `RuntimeError`（`:126-127`）。

## 4. 环节 C：交接（现状：已实现；断点见 §7）

1. launcher 主循环每 ~1s 调 `_handoff_pending_update`（`launcher.py:1571-1573`），命中即置 `shutdown_requested` 退出，交出整个进程组。
2. `_handoff_pending_update`（`launcher.py:1211-1259`）：读 `state.json`（类型化异常静默 `return False`，`:1229-1232`）→ 仅认 `pending`（`:1233-1234`）→ systemd 环境拒绝并 `mark_failed` 保活（`:1236-1243`）→ `prepare_handoff` 写入 `restart_home`/`restart_argv`（`app_update.py:518-536`；argv 白名单 `app_update.py:600-611`，由 `launcher.py:1303-1305` 构造）→ `launch_update_worker` 以 `start_new_session` 拉起 detached worker（`app_update.py:623-651`）。
3. 交接路径任何异常 → `mark_failed`，其自身再失败被 bare `except Exception: pass` 吞掉（`launcher.py:1253-1257`，§7 F1，已认领 PR #1704）。

## 5. 环节 D：重启与闭环（现状：已实现）

1. `run_update_worker`（`update_worker.py:103-146`）：`load()` 要求 `handoff`（`:115-117`）→ 等旧 launcher 退出（60s 超时，`:56-63,118`）→ `mark_running`（`:119`）→ 执行 pip（`:123-125`）→ `mark_restarting`（`:128`）→ `_launch_restart` 以受信向量 `[python, -m deeptutor_cli.main, start --home <home> [--dev]]` 拉起新 launcher（`:43-49,81-100`）→ 返回 0。
2. 失败兜底（`:134-146`）：重新 `load()`，状态未终态则 `mark_failed`，再尽力用已记录向量拉起应用；兜底自身再抛异常被 bare pass 吞掉（`:144-145`，§7 F2，已认领 PR #1704）。
3. 新 launcher 就绪前后端后调 `_complete_restarted_update`（`launcher.py:1558` → `:1262-1276`）：要求 `restarting` 且 `restart_home` 与当前 home 一致，然后 `mark_succeeded`（`app_update.py:553-554`；终态释放槽位 `:584-585`）。
4. 前端全程轮询 `GET /api/system/update/job`（800ms 间隔、120s 上限，容忍后端短暂消失；`AboutSettingsSection.tsx:90-125` → `app-update.ts:144-153` → `system.py:258-260`），终态后 `succeeded` 触发重新加载版本状态（`:104`）。

## 6. 环节间的交接点（跨进程契约一览）

| 交接点 | 写方 → 读方 | 载体 | 校验 |
| --- | --- | --- | --- |
| API → launcher | `system.py:299-311` → `launcher.py:1571-1573` | `state.json`（pending）+ `active` 槽位 | `from_dict` 严格校验（`app_update.py:106-126`） |
| launcher → worker | `launcher.py:1243-1252` → `update_worker.py:113-117` | `state.json`（handoff）+ 命令行 `--store-root/--parent-pid`（`update_worker.py:150-153`） | argv 白名单（`app_update.py:600-611`） |
| worker → 新 launcher | `update_worker.py:129-132` → `launcher.py:1558` | detached Popen（`start_new_session`）+ `state.json`（restarting） | `restart_home` 一致性（`launcher.py:1273`） |
| 后端 → 前端 | `system.py:168-198` → `app-update.ts:33-50` | JSON payload（类型契约 `web/lib/app-update.ts:12-50`） | 前端仅做类型断言，展示层容错 |

## 7. 现状断点表（v1.6.13 行号刷新）

| # | 位置 | 行为 | 后果 | 状态（v1.6.13） |
| --- | --- | --- | --- | --- |
| F1 | `deeptutor/runtime/launcher.py:1256-1257`（触发 `:1253-1255`） | handoff 异常后 `mark_failed` 再抛 → bare pass | 双重失败零痕迹；job 停 `pending`，主循环每 ~1s 重试 | **已认领**：上游 PR #1704（OPEN）；fix-update-worker 卡群另一视角 |
| F2 | `deeptutor/runtime/update_worker.py:144-145`（触发 `:134-143`） | 恢复段自身抛异常（如 `state.json` 损坏）→ bare pass | job 卡死、无日志、应用不被拉起 | **已认领**：上游 PR #1704（OPEN） |
| F3 | `deeptutor/runtime/launcher.py:1229-1232` | 读态失败（类型化捕获）→ `return False` | 损坏的 `state.json` 被当作"无待更新"；`active` 残留时新请求 409 卡死（`app_update.py:498-500`），无提示 | 未认领（类型化静默属设计取舍，409 卡死无观测） |
| F4 | `deeptutor/runtime/launcher.py:1270-1272` | `_complete_restarted_update` 读态失败 → `return False` | 更新实际成功但 job 停 `restarting`、槽位不释放 → 后续 409；无日志 | 未认领 |
| F5 | `deeptutor/runtime/launcher.py:1274` | `mark_succeeded` 内部校验抛 `RuntimeError`（`app_update.py:573-574`）未捕获 | 穿透 `start()`（该层只捕 `KeyboardInterrupt`，`launcher.py:1582,1584`）→ 成功更新场景下 launcher 带异常退出 | 未认领（边缘） |
| F6 | `deeptutor/runtime/launcher.py:1273` | `restart_home` 与重启后 home 不一致 → 不标记 | job 永久停 `restarting`；仅人工迁移 home 触发 | 未认领（防御性检查，无观测） |
| N1 | `deeptutor/services/app_update.py:307-308` | 版本检查缓存仅进程内 | 后端重启后"上次检查"丢失，About 页回到 Not checked yet | 评估项（#725 建议的 24h 缓存已满足字面要求，持久化是增强） |
| N2 | `deeptutor/services/app_update.py:395-400` | migration 警示为英文关键词正则 | 中文/非模板化 release notes 可能漏报 | 评估项（与 #725 "Flag migration-bearing releases" 相关） |
| N3 | `deeptutor/services/app_update.py:27,333-354` | 发布源仅 GitHub Releases（+重定向兜底），未接 PyPI JSON API | GitHub 不可达区域（无兜底成功时）无法检查 | 与 #725 建议直接相关，上游方向 |

不属于断点：`file_io.py` 原子写与 fsync 取舍（`deeptutor/services/file_io.py:54,79`，详见 2026-10-04 导读 §3）；`systemd` 拒绝路径有日志（`launcher.py:1240-1241`）；API 读态失败返回 `job: null`（`system.py:157-162`）。

## 8. 上游 #725 对照（评估地图）

#725 请求 Settings "Version & updates" 区块。逐条对照现状：

| #725 诉求 | 现状 | 证据 |
| --- | --- | --- |
| 1. 显示当前版本 + 最新 release | ✅ 已实现 | `AboutSettingsSection.tsx:206-215,316-331`；侧边栏徽标 `VersionBadge.tsx:46-63` |
| 2. Check for updates（GitHub Releases 或 PyPI JSON） | ✅ 已实现（仅 GitHub 源） | `system.py:243-246`；`app_update.py:333-379`；PyPI 备源未接（N3） |
| 3. changelog 摘要 + release 链接 | ✅ 已实现 | 摘要 `app_update.py:446-468`；URL 校验 `:390-391`；展示 `AboutSettingsSection.tsx:217-227,342-351` |
| 4. Update now（可行处） | ✅ 已实现（pypi+venv+非 systemd+launcher 托管） | `system.py:263-317`；确认框 `AboutSettingsSection.tsx:409-422` |
| Additional: 显式更新、绝不静默 | ✅ | admin 确认框 + job 状态展示（`AboutSettingsSection.tsx:409-422,368-391`） |
| Additional: 缓存检查（~24h） | ✅ | `app_update.py:29,311-316`（进程内，见 N1） |
| Additional: 允许完全关闭 | ✅ | `system.py:250-254`；开关 `AboutSettingsSection.tsx:297-315` |
| Additional: 标记含迁移的 release | ✅（关键词正则） | `app_update.py:395-400`；展示 `AboutSettingsSection.tsx:333-340`（见 N2） |
| Additional: pip 失败优雅处理并暴露真实错误 | ◐ 主路径已实现；恢复段吞错 F2 在 PR #1704 处理 | `job.error` 展示 `AboutSettingsSection.tsx:385-389`；`update_worker.py:126-127,138` |
| Additional: 记录上一版本以便回滚 | ◐ 仅记录，无回滚操作 | `UpdateJob.current_version`（`app_update.py:91,117`）；无回滚入口 |
| Use case: 各安装方式给出正确升级命令 | ✅ | `detect_installation` 各分支 `command` 字段（`app_update.py:222-285`）；展示 `AboutSettingsSection.tsx:353-366` |

**评估结论（供人工参考，非实现建议）**：#725 的功能面在 v1.6.13 基本全部落地；评估上游后续动作时，重点应放在 §7 的 F3/F4（未认领静默路径 → 409 卡死）与 N1–N3（缓存持久化、迁移提示健壮性、PyPI 备源），而非重复实现主链。

## 9. 复核命令与测试数字

```bash
cd /Users/Shared/DeepTutor && git fetch --multiple origin myfork
git show f07029cfc:deeptutor/services/app_update.py   | sed -n '219,285p;288,379p;475,597p'
git show f07029cfc:deeptutor/api/routers/system.py    | sed -n '141,317p'
git show f07029cfc:deeptutor/runtime/launcher.py      | sed -n '1211,1276p;1558,1581p'
git show f07029cfc:deeptutor/runtime/update_worker.py | sed -n '17,49p;103,146p'
```

本基线验证（只读运行，未改任何代码）：

- `gtimeout 900 … pytest -q -p no:cacheprovider tests/services/test_app_update.py` → **13 passed in 0.34s**（离线，无出网）。
- 前端测试 `web/tests/app-update.test.ts` 存在（未运行，避免在本 worktree 安装 node_modules）。

## 10. 可拆卡条目（现状缺口 → 候选卡）

| 候选 | 内容 | 建议规模 |
| --- | --- | --- |
| C1 | F3/F4 观测补齐：`_handoff_pending_update`/`_complete_restarted_update` 读态失败路径加一行 `_log`（控制流不变），并提供 `active` 槽位残留的清理/提示 | 小（同 PR #1704 风格） |
| C2 | N1：版本检查结果持久化（`data/user/update/` 下缓存文件），重启后保留"上次检查" | 小 |
| C3 | N3：发布源增加 PyPI JSON 备源（#725 原文建议），复用 `VersionCheckService` 缓存 | 中 |
| C4 | N2：migration 警示扩展（i18n 关键词或上游 release 元数据字段） | 小 |
| C5 | 回滚提示：更新成功后展示"从 X 升级"并给出手动回滚命令（`current_version` 已有） | 小 |

（以上均为候选，未开工、未建卡。）
