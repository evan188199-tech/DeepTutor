# scan: conftest/fixture 重复与作用域清点（AGEN-895）

- 扫描基线：`origin/main` @ `f07029cfcf2c8dfccdb671cdfc343db8334f5741`（release v1.6.13）
- 范围：仅 fixture/conftest 层。覆盖面缺口归 scan-coverage-gaps，隔离行为归 scan-test-isolation，本卡不重复。
- 方法：AST 解析（脚本见 `scripts/scan_conftest.py`），机器可读数据见 `data/conftest_inventory.json`；成本基准见 `scripts/bench_guard.py` 与 `data/bench_guard_output.txt`。
- 只读扫描：未改动任何产品代码与测试文件。

## 1. conftest 层级图

```
repo root  (pyproject.toml:477  testpaths = ["tests", "deeptutor/learning/tests"])
├── tests/conftest.py                      311 行  14 fixtures（7 autouse + 7 命名）
│     autouse: _guard_real_owner_secrets:48  _guard_legacy_multi_user_migration:74
│              _isolate_codebuddy_login:93  _isolate_llm_config:224
│              _isolate_application_container:269  _restore_process_env:286
│              _isolate_usage_ledger:306
│     命名:   stream_bus:124  minimal_context:135  rich_context:145
│              tmp_db_path:170  sqlite_store:176  stub_capability:202  fake_llm_config:212
├── deeptutor/learning/tests/              ★ 无 conftest、在 tests/ 树之外 → 7 个 autouse 守卫均不生效
└── tests/
    ├── multi_user/conftest.py             141 行  mu_isolated_root:20  make_user:86  as_user:111  seed_user:131
    ├── services/cli_apps/conftest.py       28 行  cli_app_roots:17 (autouse)
    ├── services/partners/conftest.py      106 行  partners_root:18  fake_orchestrator:86
    ├── services/rag/conftest.py            18 行  （仅 pytest_addoption 注册 --pipeline，无 fixture）
    └── services/{partner_groups,storage,session,mcp,codex_auth}、api/、runtime/providers/、video_learning/、utils/、capabilities/ …
                                            ★ 无 conftest → 仅继承根 conftest；路径隔离靠各模块内联手写
```

子 conftest 的隐式依赖：`cli_apps/conftest.py` 的 docstring 明言依赖根 conftest 的
`_guard_real_owner_secrets` 作为最后防线（写漏一个 root 时由守卫兜底 fail）——这是
"子树隔离 + 根树守卫" 的设计耦合，属有意为之，但意味着 **任何不在 tests/ 树下的测试都失去这层兜底**（见 §4-D1）。

## 2. 重复定义清单（同/近同体多份）

| # | 模式 | 定义点 | 差异/漂移 |
|---|------|--------|-----------|
| A1 | "multi_user 根重定向" patch 块（PROJECT_ROOT / ADMIN_WORKSPACE_ROOT / USERS_ROOT / SYSTEM_ROOT / _path_services 五连 patch）三份 conftest 副本 | `tests/multi_user/conftest.py:21`（mu_isolated_root）、`tests/services/cli_apps/conftest.py:18`（cli_app_roots）、`tests/services/partners/conftest.py:19`（partners_root） | multi_user 与 partners 版额外 patch `identity.*`（AUTH_DIR/USERS_FILE/SECRET_FILE/LEGACY_*）；cli_apps 版 **不 patch identity**——同一缺陷面三种覆盖口径 |
| A2 | 同一 patch 块在无 conftest 目录里内联手写，共 16 个测试模块 | `tests/api/test_book_permission_api.py`、`tests/api/test_book_shared_access.py`、`tests/api/test_partner_groups_router.py`、`tests/api/test_partners_router.py`、`tests/api/test_space_cli_apps.py`、`tests/api/test_space_mcp.py`、`tests/runtime/providers/test_cli_app_view.py`、`tests/services/codex_auth/test_credential_location.py`、`tests/services/mcp/test_call_failures.py`、`tests/services/mcp/test_catalog.py`、`tests/services/mcp/test_manager_scopes.py`、`tests/services/mcp/test_oauth.py`、`tests/services/mcp/test_secrets.py`、`tests/services/mcp/test_user_config.py`、`tests/services/partner_groups/test_manager.py:33`、`tests/video_learning/test_invidious_account.py` | 各自独立漂移（是否 patch identity、是否设 user context 不一致），隔离质量取决于"抄的是哪一版" |
| A3 | `tmp_db_path` 两份 | 根 `tests/conftest.py:171`（返回 `test_chat.db`）vs `tests/services/storage/test_file_library.py:24`（返回 `file_library.db`） | 同形不同名文件；模块级定义遮蔽根 conftest 的同名 fixture |
| A4 | `partners_root` 第三份（conftest 体的复制+漂移） | `tests/services/partner_groups/test_manager.py:33` | 手动 `set_current_user` + token（等价于 conftest 的 `paths.user_context`），但不 patch `identity.*`——是 A1 漂移的实例 |

## 3. 同名遮蔽清单

| # | 名称 | 遮蔽关系 | 性质 |
|---|------|----------|------|
| B1 | `partners_root` | `tests/services/partners/test_channel_state_migration.py:15` 模块级 fixture 遮蔽同目录 `tests/services/partners/conftest.py:19` | **真遮蔽且语义不同**：模块版 patch 的是 `deeptutor.partners.config.paths._base_dir`、返回 `tmp_path/"partners"`；conftest 版 patch multi_user paths、返回 `admin_root/"partners"`。同目录同名不同义，易踩 |
| B2 | `make_user` | `tests/multi_user/test_capability_access.py:13`、`test_grants_and_settings.py:29`、`test_owner_bound_models.py:20` 三个普通 helper 与 `tests/multi_user/conftest.py:87` fixture 同名 | 非 fixture 遮蔽：helper 只被模块内直接调用；但该目录内任何测试若把 `make_user` 写进参数，会静默解析到 conftest fixture（依赖 `mu_isolated_root`），行为完全不同 |
| B3 | `as_user` | `tests/services/session/test_turn_event_flush.py:87`、`test_pocketbase_isolation.py:31` 的 `@contextmanager` helper 与 `tests/multi_user/conftest.py:112` fixture 同名 | 不同目录，无实际遮蔽；纯命名复用，提示 `as_user` 这个名字已被两种语义占用 |
| B4 | `fake_llm_config` 类 | 根 `tests/conftest.py:212` 的 fixture 全库仅 1 处间接使用；各模块自建 `_fake_llm_config` helper ×3（`tests/capabilities/test_rag_consistency.py:39`、`tests/agents/chat/test_agent_loop.py:171`、`tests/agents/chat/test_language_prompts.py:15`） | 根 fixture 近乎死代码；同名 helper 各写各的 |

根 conftest 死 fixture（0 外部使用）：`minimal_context:135`、`rich_context:145`、`stub_capability:202`；`fake_llm_config:212` 近死（1 文件）。

## 4. 作用域错配与跨目录隐式依赖

- C1（function 级扛重活，主要发现）：`_guard_real_owner_secrets`（`tests/conftest.py:48`）autouse + function 作用域，每个测试前后各对 4 棵真实树做一次 `Path.rglob` 全量快照（`tests/conftest.py:25`）。全套件 7266 个测试函数 × 2 次快照。基准（本机，scripts/bench_guard.py）：
  - 5,000 文件树 → 每次 x2 ≈ 39 ms → 全套件 ≈ **9.5 分钟**
  - 20,000 文件树 → 每次 x2 ≈ 157 ms → 全套件 ≈ **38 分钟**
  - 开发机 `data/`（runtime home，含上传/KB/ sqlite）接近后者的量级时，守卫本身就是最大的单点测试税。CI 上树为空所以看不见。
- C2 其余 6 个 autouse 均为轻量 monkeypatch/env 拷贝，量级可忽略。
- C3 正面样板：全树唯一非 function 作用域 fixture 是 `tests/utils/test_document_images.py:42` 的 `scope="module"` `png`（PNG 编码每模块一次）——正确用法，可作为重活下放的范式。
- D1 **tests/ 树外无守卫**：`pyproject.toml:478` 把 `deeptutor/learning/tests` 纳入 testpaths，该目录无 conftest、也不在 `tests/` 的 conftest 链上 → 7 个 autouse（真实账户树守卫、legacy 迁移守卫、codebuddy 登录隔离、LLM 配置隔离、容器重置、env 恢复、usage ledger）全部不生效，靠开发者自觉。
- D2 A2 的 16 个内联模块不依赖任何 conftest，漂移无人发现（cli_apps 不 patch identity 即为此类漂移的 conftest 版）。
- D3 `tests/services/rag/conftest.py` 仅注册 `--pipeline` 选项，无 fixture，无问题。

## 5. Top 合并建议（≤5）

1. **收敛路径重定向为单一根级 fixture**：在 `tests/conftest.py` 增加一个 opt-in 的 `isolate_multi_user_roots(monkeypatch, tmp_path, *, patch_identity: bool)`；`mu_isolated_root`、`cli_app_roots`、`partners_root` 改为薄封装，16 个内联副本逐步替换为直接请求该 fixture（一次参数即可）。预计净删 ~150 行重复、消除 identity 覆盖口径漂移。
2. **消除 B1 真遮蔽**：把 `tests/services/partners/test_channel_state_migration.py:15` 的 fixture 改名（如 `partner_base_dir`），避免与同目录 conftest 的 `partners_root` 同名不同义。
3. **清理根 conftest 死重**：删除或下沉 `minimal_context`、`rich_context`、`stub_capability`、`fake_llm_config`（后者的 3 个模块 helper 可合并进根 fixture 的实现）；`tmp_db_path` 参数化文件名后可删 storage 的本地副本。
4. **给 `_guard_real_owner_secrets` 降本**：快照改为对每棵根目录做 mtime+size 的 stat（O(根数) 而非 O(文件数)），或先 `os.scandir` 浅探、仅根目录 mtime 变化时才全量 rglob。语义不变，最坏情形从 ~38 min/套件降到秒级。
5. **补齐 deeptutor/learning/tests 的 conftest 链**：加一个最小 conftest import 根 conftest 的 autouse（或把该目录迁入 tests/），使 7 个守卫覆盖全部 testpaths；短期至少在 `tests/conftest.py` docstring 标注该例外。

## 6. 复现

```bash
git fetch --multiple origin myfork && git worktree add /tmp/dt-scan-conftest -b <branch> origin/main
cd /tmp/dt-scan-conftest
python3 evidence/scan-conftest-dup-20261006/scripts/scan_conftest.py .   # 产出 inventory JSON
python3 evidence/scan-conftest-dup-20261006/scripts/bench_guard.py       # 守卫成本基准
sha256sum -c evidence/scan-conftest-dup-20261006/SHA256SUMS              # 数据自证
```

完整性：`SHA256SUMS` 覆盖本目录全部文件（report、数据、脚本）。
