# CLI Copilot 设备登录流导读（运维者视角）

> 范围：`deeptutor` CLI 的 GitHub Copilot 登录链路——`init` 交互流、`provider login` 命令、token 存储位置与安全属性、过期与重登路径、无头环境的可行与不可行。Copilot 推理请求的协议细节（endpoints 协商、responses 归一化）不在本文展开。
> 基线：`origin/main` @ 6cf793bd8（v1.6.14；设备登录流由 #1277 `feat(cli): add GitHub Copilot device login to init` 引入，提交 b19a83745）。所有 `path:line` 以该提交为准。
> 本文不改任何代码与文档源文件；证据目录只新增本文件与 SHA256SUMS。撰写过程只做静态阅读与离线测试，未实际发起登录、未写入任何 token。

## 0. 去重说明

- `guide-cli`（CLI 总览）讲 deeptutor 命令族全貌；本文只讲其中 `init` 与 `provider login` 里 github-copilot 这一条轴。
- `guide-codex-auth`（codex 轴）讲 openai-copilot 之外的 OpenAI Codex OAuth 回调登录；本文不覆盖。两者共用 codex_auth 的存储原语（`deeptutor/services/codex_auth/storage.py`），但凭据目录、登录协议、过期模型完全独立。
- `test-copilot-provider` 卡验证 provider 运行时行为；本文只在故障定位处引用对应测试名，不重复其覆盖矩阵。

## 1. 总览：一次登录到底发生了什么

GitHub Copilot 在 DeepTutor 里有**两种 token**，生命周期不同，运维必须分开理解：

| token | 获得方式 | 寿命 | 存储位置 |
| --- | --- | --- | --- |
| GitHub OAuth token（设备流产物） | `github.com/login/device/code` 设备授权（`deeptutor/services/github_copilot_auth.py:78-84`） | 默认 10 年（`expires_in` 兜底 31536000 秒，`github_copilot_auth.py:27,104,120`） | 落盘：`<home>/data/system/user-secrets/<owner>/private/github-copilot/credentials.v1.json`（见 §3） |
| Copilot API token（短期票） | 用上面的 OAuth token 向 `api.github.com/copilot_internal/v2/token` 换取（`github_copilot_auth.py:174-178`） | 服务端给 `expires_at`，缺省按 `refresh_in`（1500 秒）计（`github_copilot_auth.py:184-186`） | **只在进程内存**（`deeptutor/services/llm/provider_core/github_copilot_provider.py:36-37`），从不落盘 |

```
deeptutor init（LLM 步选 GitHub Copilot）          deeptutor provider login github-copilot
  init_cmd.py:98-105 → _github_copilot_step          provider_cmd.py:32-33 → _login_github_copilot
  init_cmd.py:152-221                                provider_cmd.py:86-116
        └──────────────┬────────────────────────────────────┘
                       ▼
        login_github_copilot（github_copilot_auth.py:59-156）
          1. POST device/code → device_code + user_code（78-93）
          2. 打印 Open/Code，尽力开浏览器（95-99）
          3. 轮询 access_token 直到授权/过期/超时（101-136）
          4. GET /user 取账号名（138-148）
          5. storage.save 落盘 GitHubToken（150-156）
                       ▼
        运行时每次推理前（GitHubCopilotProvider._chat_impl → _ensure_api_key，
        github_copilot_provider.py:150-164,75-88）
          OAuth token → 短期 Copilot token（内存，60 秒过期余量，24,79-88）
```

provider 注册面：`ProviderSpec(name="github_copilot", backend="github_copilot", is_oauth=True, default_api_base="https://api.githubcopilot.com", strip_model_prefix=True)`（`deeptutor/services/provider_registry.py:432-442`），别名 `github-copilot`（`provider_registry.py:145`）。`env_key` 为空（`provider_registry.py:435`）：**Copilot 不消费任何 API key 环境变量**，profile 里 `api_key` 恒为空串（`deeptutor_cli/init_cmd.py:200-206`），鉴权完全来自落盘的 OAuth token。

## 2. `init` 交互流逐步分解

入口：`deeptutor init`（`deeptutor_cli/main.py:79` 注册，命令定义 `deeptutor_cli/init_cmd.py:620-633`，选项 `--cli` / `--home` / `--non-interactive`）。交互向导按 端口(全模式)→LLM→Embedding→Search→Review 走（`init_cmd.py:508-510` 的步骤计数）。

1. **LLM 步进入**：`run_init` 在 `init_cmd.py:541-549` 调 `_llm_step`；provider 菜单里 GitHub Copilot 在精选列表（`deeptutor_cli/init_wizard.py:40-52`，第 50 行）。选中后走专属分支 `init_cmd.py:98-105`，**跳过** base_url 编辑、API key 输入与通用 `/models` 拉取。
2. **复用判定**：`_github_copilot_step`（`init_cmd.py:152-221`）先 `load_github_token()`（`github_copilot_auth.py:42-46`）读存量凭据；已有则问 "Reuse the GitHub Copilot login for {account}?"（默认 yes，`init_cmd.py:170-176`；文案 `deeptutor/runtime/banner.py:81`）。选 yes 不再发起设备流，直接进模型拉取。
3. **设备流登录**：答 no（或本无凭据）时 `asyncio.run(login_github_copilot(print_fn=console.print))`（`init_cmd.py:177-179`）。终端打印 `Open: https://github.com/login/device` 与 `Code: XXXX-XXXX`（`github_copilot_auth.py:95-96`），随后尽力打开 `verification_uri_complete`，失败（无浏览器/无 DISPLAY）被 `suppress` 吞掉不报错（`github_copilot_auth.py:97-99`）。
4. **轮询与完成**：按服务端 `interval`（兜底 5 秒）轮询，`slow_down` 时轮询间隔 +5（`github_copilot_auth.py:126-128`）；拿到 access_token 后取 `GET /user` 的 `login` 作为 account_id（`github_copilot_auth.py:138-148`），构造 `GitHubToken(access, expires=now+expires_in 毫秒, account_id)` 并原子落盘（`github_copilot_auth.py:150-156`）。
5. **模型发现**：`list_github_copilot_models()`（`init_cmd.py:186` → `github_copilot_auth.py:254-256`）内部先换短期 token 再 `GET {api_base}/models`，过滤 `model_picker_enabled=false`、`policy.state=disabled`、endpoints 不含 `/responses` 或 `/chat/completions` 的行（`github_copilot_auth.py:226-249`）。结果为空即报 "No usable GitHub Copilot models are available for this account."（`init_cmd.py:187-188`）。
6. **选模型与探活**：`select_model`（`init_cmd.py:194-199`）后强制探活 `validate_github_copilot_model(model)`——真实发一条 "Reply with OK." 推理（`deeptutor/services/llm/provider_core/github_copilot_provider.py:246-260`）；失败即退出码 1（`init_cmd.py:211-216`）。探活失败**不会**回滚已落盘的 OAuth token：登录成果保留，下次重跑 init 可直接复用。
7. **落 catalog**：确认保存后 `catalog_service.save(catalog)`（`init_cmd.py:609`）；LLM profile 写 `binding="github_copilot"`、`api_key=""`（`init_cmd.py:200-206,552-556`）。

`--non-interactive`（`init_cmd.py:625-629`）走 `run_init` 的早退分支（`init_cmd.py:488-503`）：只建默认目录与默认设置，**完全不触发设备登录**，提示 `next_step: deeptutor config apply setup.json`。

## 3. token 存储位置与安全属性

存储类 `GitHubCopilotStorage`（`deeptutor/services/github_copilot_storage.py:30-34`）：

- **定位链**：`get_github_copilot_storage()` 每次调用现算（`github_copilot_storage.py:80-85`，注释明确为支持 `init --home` 运行中改家目录）→ `get_owner_secrets_dir(runtime_home=get_runtime_home())`（`deeptutor/multi_user/paths.py:238-256`）→ `<runtime_home>/data/system/user-secrets/<owner_id>/`（`owner_secrets_dir`，`paths.py:217-235`）。runtime home 优先级：`--home` 参数 > `DEEPTUTOR_HOME` 环境变量 > 当前工作目录（`deeptutor/runtime/home.py:28-43`，常量在 `home.py:8`）；`init` 用 `select_runtime_home` 校验并钉住 env（`deeptutor_cli/setup_config.py:65-73`）。**cwd 起服务时家目录跟着 cwd 走**——在错误目录里登录，凭据会写到那个目录的 `data/system/...` 下，这是最常见的"登录了却不生效"原因。
- **文件布局**：`credentials.v1.json`（`{"schema_version":1,"access":...,"expires":<ms epoch>,"account_id":...}`，写入 `github_copilot_storage.py:75-77`，校验 `50-68`）与 `auth.lock`（flock 互斥文件，`github_copilot_storage.py:44`，实现 `deeptutor/services/codex_auth/storage.py:55-82`）。
- **权限**：目录链逐层 `chmod 0700` 并拒绝符号链接/reparse point（`github_copilot_storage.py:40-43`，路径断言 `codex_auth/storage.py:39-51`）；凭据文件写入 `mkstemp` → `fsync` → `chmod 0600` → `os.replace` 原子替换（`codex_auth/storage.py:85-103`），lock 文件同样 0600（`codex_auth/storage.py:59`）。
- **归属隔离**：`data/system` 不挂进沙箱 runner（`paths.py:9-11` 模块注释），Partner 会话解析到其 owner（人类）的 secrets 目录（`paths.py:238-249`）；owner 缺省回退 `local-admin`（`paths.py:227`，常量 `deeptutor/multi_user/models.py:103`）。存取行为有测试锁定：owner/home 双维隔离 `tests/services/test_github_copilot_auth.py:87`，不读外部应用凭据、不写环境变量 `:120`，坏数据与不安全路径拒载 `:138`。
- **不落盘的东西**：短期 Copilot token 与其 `expires_at` 只活在 `GitHubCopilotProvider` 实例内存（`github_copilot_provider.py:36-37,71-72`）；模型 catalog 里也只有一个空 `api_key`（§1）。

运维速查：凭据实际路径 = `<启动家目录>/data/system/user-secrets/<owner>/private/github-copilot/credentials.v1.json`。手工重置 = 删掉该 `credentials.v1.json`（没有 logout 子命令，`deeptutor_cli/provider_cmd.py:16-40` 只有 login）；删除后下一次运行时调用会报"未登录"（§4 场景 4）。

## 4. 过期与重登路径

- **短期 token（分钟级）自动续**：每次推理前 `_ensure_api_key` 检查内存票，距过期不足 60 秒（`_EXPIRY_SKEW_SECONDS`，`github_copilot_provider.py:24`）即重新换取（`github_copilot_provider.py:79-88`）。换票失败只影响当次请求，不动落盘凭据。
- **落盘 OAuth token（十年级）不主动校验**：`load_github_token` 只验证结构与类型，不看 `expires` 字段（`github_copilot_storage.py:50-68`）。因此真正的失效信号是**换票接口返回 HTTP 错误**（典型：你在 GitHub 侧撤销了授权，Settings → Applications → DeepTutor），表现为推理报 `GitHub Copilot login failed: ...`（CLI 场景，`deeptutor_cli/provider_cmd.py:111-113`）或 provider 抛 "GitHub Copilot is not logged in for this owner..." 之前的 4xx（`github_copilot_provider.py:58-73`）。
- **重登只有两条路**，都执行完整设备流并覆盖写凭据（`github_copilot_auth.py:155`）：
  1. `deeptutor provider login github-copilot`（`deeptutor_cli/README.md:249,255`；实现 `provider_cmd.py:86-116`）。成功即验证模型并打印 `GitHub Copilot login succeeded for <account>`（`provider_cmd.py:114-116`）。依赖缺失时给出安装提示并退出 1（`provider_cmd.py:96-101`）。
  2. `deeptutor init` 的 LLM 步复用问句答 no（`init_cmd.py:171-179`）。
  升级后官方口径也是重跑登录（`deeptutor_cli/README.md:257`）。
- **测试佐证**：设备流落盘 `tests/services/test_github_copilot_auth.py:60`；CLI 全链路（登录→模型→探活→成功/失败输出）`tests/cli/test_provider_cli.py:132-179`。本卡基线实测：`pytest tests/services/test_github_copilot_auth.py tests/cli/test_provider_cli.py` → **14 passed in 1.10s**。

## 5. 无头环境限制

- **设备流本身是"无浏览器友好"的**：`Open:` 与 `Code:` 两行总是先打印（`github_copilot_auth.py:95-96`），浏览器打开失败被静默抑制（`github_copilot_auth.py:97-99`）。在无头服务器上从另一台机器访问 `https://github.com/login/device` 输入验证码即可完成授权，轮询侧无感知差异。
- **代理友好**：所有 HTTP 客户端 `trust_env=True`（`github_copilot_auth.py:73-77,169-173`），`HTTP(S)_PROXY` 等环境变量生效；GitHub/Copilot 端点还可用环境变量整体替换（`DEEPTUTOR_GITHUB_COPILOT_CLIENT_ID`、`DEEPTUTOR_GITHUB_DEVICE_CODE_URL`、`DEEPTUTOR_GITHUB_ACCESS_TOKEN_URL`、`DEEPTUTOR_GITHUB_USER_URL`，`github_copilot_auth.py:66-71`；`DEEPTUTOR_COPILOT_TOKEN_URL`、`DEEPTUTOR_COPILOT_BASE_URL`，`github_copilot_auth.py:175,191`；换票响应里的 `endpoints.api` 优先于环境变量，`github_copilot_auth.py:187-192`）。
- **交互式步骤不可无头**：`init` 向导的 provider 菜单、复用问句、模型选择全是 `typer.prompt/confirm`（`deeptutor_cli/init_wizard.py:385`；`init_cmd.py:171,194`），需要 TTY。无头机的正确姿势：交互终端里跑 `deeptutor provider login github-copilot` 一次性落盘凭据 → 服务进程（同一家目录、同 owner）直接读凭据运行，无需再交互。
- **`--non-interactive` 不是登录通道**：见 §2 末尾，它早退且从不触发设备流（`init_cmd.py:488-503`）。
- **家目录漂移**：无头部署常用 systemd/cron 起服务，工作目录与登录时不一致就会读不到凭据（§3 定位链）。用 `DEEPTUTOR_HOME` 或 `--home` 钉死同一路径。

## 6. 故障场景速查（症状 → 定位）

1. **`GitHub device code expired. Please run login again.`**
   症状：登录命令在数分钟到 15 分钟后失败退出 1。原因：验证码有效期（服务端 `expires_in`，兜底 900 秒，`github_copilot_auth.py:93`）内未完成浏览器授权，轮询收到 `expired_token`（`github_copilot_auth.py:129-130`）。定位：`login_github_copilot` 轮询循环。
2. **`GitHub device login timed out.`**
   症状：命令恰好跑满 `expires_in` 后失败，期间无报错。原因：轮询 while 循环的 deadline 走完（`github_copilot_auth.py:101,135-136`）。与场景 1 的区别是 GitHub 未回 `expired_token`（如网络半通、轮询请求被代理吞掉）。
3. **`GitHub device login was denied.`**
   症状：输入验证码点了授权页的拒绝/cancel 后命令立刻失败。定位：轮询收到 `access_denied`（`github_copilot_auth.py:131-132`）。重跑命令拿新验证码即可。
4. **运行时报 `GitHub Copilot is not logged in (for this owner). Run: deeptutor provider login github-copilot`**
   症状：推理/`provider login` 校验阶段失败，登录明明做过。定位：`exchange_copilot_token`（`github_copilot_auth.py:161-167`）或 provider 换票前检查（`github_copilot_provider.py:59-64`）。按 §3 核对家目录与 owner：`ls <home>/data/system/user-secrets/*/private/github-copilot/credentials.v1.json`；最常见是登录与运行用了不同 `DEEPTUTOR_HOME`/cwd。
5. **`Stored GitHub Copilot credentials are invalid. Run: deeptutor provider login github-copilot`**
   症状：任何读凭据的操作立即失败。定位：`GitHubCopilotStorage.load`（`github_copilot_storage.py:69-73`），触发条件是 JSON 损坏、`schema_version != 1` 或字段类型不符（`github_copilot_storage.py:55-67`）。处理：删文件重登（手工改文件绕不过校验）。
6. **`GitHub Copilot credential storage uses an unsafe path.`**
   症状：load/save 均失败。定位：锁内路径断言失败转译（`github_copilot_storage.py:47-48`；断言实现在 `codex_auth/storage.py:39-51`）。原因是 `data/system/user-secrets` 链上出现符号链接或凭据路径被替换成非常规文件——常见于手工搬运/软链"共享"凭据。处理：移除软链，让程序重建真实目录。
7. **`GitHub Copilot login dependencies are not installed. Install CLI deps: python -m pip install -e ./packaging/deeptutor-cli`**
   症状：`provider login github-copilot` 一进就退出 1，没有设备流输出。定位：延迟导入失败（`provider_cmd.py:88-101`），即 CLI 精简安装缺 httpx/typer 等。
8. **`No usable GitHub Copilot models are available for this account.`**
   症状：设备流已成功、但模型列表为空，登录流程退出 1（`provider_cmd.py:107-109`；init 同文案 `init_cmd.py:186-188`）。原因：账号无 Copilot 订阅，或所有模型被 `policy.state=disabled`/`model_picker_enabled=false` 过滤（`github_copilot_auth.py:226-249`）。注意此失败**之前 OAuth token 已落盘**，重跑会命中"复用登录"问句，需答 no 才会重试设备流。
9. **推理报 `GitHub Copilot model is not currently available: <id>`**
   症状：catalog 里选过的模型突然不可用。定位：`_should_use_responses_api` 在本次换票发现的模型表里查不到该 id（`github_copilot_provider.py:99-108`）。Copilot 侧下架/禁用了该模型；`init` 重新选模型即可。
10. **`GitHub Copilot login failed: Client error '401 ...'`（或 403/404）**
    症状：落盘凭据存在但换票 `GET /copilot_internal/v2/token` 返回 4xx（`raise_for_status` 在 `github_copilot_auth.py:178`，CLI 捕获在 `provider_cmd.py:111-113`）。典型原因：GitHub 侧撤销了 OAuth 授权、账号被移出组织、或 `DEEPTUTOR_COPILOT_TOKEN_URL` 指向了错误端点。处理：确认 GitHub 授权后重跑 `provider login github-copilot`。

## 7. 本文证据与边界

- 全部结论来自对基线提交 6cf793bd8 的静态阅读，引用处以 `path:line` 标注；未发起任何真实登录或网络授权，未写入/读取任何真实 token 文件。
- 离线验证：仓库 venv 执行 `python -m pytest -q -p no:cacheprovider tests/services/test_github_copilot_auth.py tests/cli/test_provider_cli.py`，结果 14 passed / 0 failed（1.10s）。
- SHA256 见同目录 `SHA256SUMS`。
