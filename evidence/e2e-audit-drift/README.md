# evidence: web e2e audit 清单与界面漂移复核

卡片：verify: web e2e audit 清单与界面漂移复核（AGEN-1796）
基线：origin/main `6cf793bd8`（release: v1.6.14），分支 `review/e2e-audit-drift`
方式：纯静态复核（源码 / locale / 契约 / 依赖安装产物对照），未启动浏览器与服务。

## 交付

- `drift-matrix.md` — 11 个 `web/tests/e2e/*.audit.ts` 逐文件核对记录（文件 / 引用目标 / 现状 / 建议）+ 汇总表。

## 一句话结论

9/11 一致；过期项 2 处（turn-lifecycle 的 "drop connection" 按钮无 UI 对应；release-ui-matrix 默认端口 3300 已漂移）；健壮性建议 1 处（ask-user 自由文本 textarea 建议补 aria-label）；相邻发现 1 条（e2e 目录外的 epub-reader.audit.ts "Source layout" 失效，建议另开卡）。

## 复核命令参考（未在运行中执行浏览器侧）

- 文件清单：`ls web/tests/e2e/*.audit.ts`（11 个，共 2307 行）
- 选择器核对：`grep -rn "chapter-scroll-container|chapter-progress|Collapse chapters|dt-reader-scroll|data-reader-unit|data-reader-heading-id|dt.reader.history|Settings sections|data-settings-page" web/app web/components web/lib`
- 依赖核对：`grep -n "jspdf|pdfjs-dist|@recogito/text-annotator" web/package.json`
- 漂移核对：`grep -rn "drop connection|3300" web/ --include='*.ts*'`（均仅命中 audit 文件自身）
