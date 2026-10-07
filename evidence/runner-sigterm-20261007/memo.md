# sandbox runner SIGTERM 收尾路径行为备忘（signal 审计 #15 补测）

日期：2026-10-07　分支：`test/runner-sigterm-20261007`（基线 origin/main @ f07029cfc, v1.6.13）
性质：只加测试与备忘，不改产品代码。

## 背景（#15 原文要点）

`deeptutor/services/sandbox/runner/server.py:356-370` 的 `main()` 只捕获
`KeyboardInterrupt`；SIGTERM 走默认处置直接终止进程，`finally: server.server_close()`
被跳过。审计判断：`ThreadingHTTPServer` 线程为 daemon，无挂起风险；runner 本就由
父方 SIGKILL 回收（`backends.py:453`），实际影响仅为端口/临时文件即刻释放路径不一致。

## 现状代码结构（origin/main 实读）

```python
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    server.server_close()
```

无 `signal` 模块引用，未注册任何 SIGTERM handler，也无 atexit 兜底。

## 实测方法（tests/services/sandbox/test_runner_sigterm.py）

- 子进程运行真实 `main()`（信号处置是进程级的，进程内无法安全模拟）；
- 测试侧给 `ThreadingHTTPServer` 打补丁：绑定地址改写为 `127.0.0.1` 临时端口
  （测试不开对外端口），`server_close` 外包一层标记写入器，执行与否落盘可查；
- 就绪判定：读子进程实际绑定端口 + `GET /health` 200 后才发信号；
- 对照组 SIGINT（KeyboardInterrupt 路径）与实验组 SIGTERM（默认处置路径）各跑一次。

## 实测结果（本机 macOS，Python 3.13.13 / pytest 9.1.1）

| 信号 | 进程退出 | server_close 标记 |
| --- | --- | --- |
| SIGTERM | 被信号杀死，`returncode == -15` | 无标记文件（未执行） |
| SIGINT | 正常退出，`returncode == 0` | 恰好一次 `server_close` |

命令：`timeout 900 python -m pytest -q -p no:cacheprovider tests/services/sandbox/test_runner_sigterm.py`
结果：`2 passed`；连同既有 sandbox 套件 `tests/services/sandbox/` 共 `67 passed`。

## 结论

1. **SIGTERM 下 `server_close()` 不执行**——实测子进程被 SIGTERM 默认处置直接杀死
   （returncode -15），清理标记未写入；`finally` 分支确实被跳过。
2. SIGINT 对照路径行为正常：KeyboardInterrupt 被捕获，`server_close()` 恰好执行一次，
   进程干净退出（0）。两条路径的不对称与 #15 描述完全一致。
3. 影响面与审计一致：无线程挂起风险（daemon 线程），父方 `backends.py:453` 以 SIGKILL
   回收 runner；差异仅在退出路径上端口/临时文件的即刻释放不一致，属低危一致性问题。

## 供后续修复决策参考（本卡未改代码）

- 方向 A：注册 `signal.signal(SIGTERM, handler)`，handler 内 `raise SystemExit`/复用
  KeyboardInterrupt 路径，让现有 `finally` 生效；
- 方向 B：`atexit.register(server.server_close)` 兜底；
- 任一方向落地时，本测试的 SIGTERM 断言（期望 `returncode == 0` 且标记存在）即为
  需要翻转的红灯。
