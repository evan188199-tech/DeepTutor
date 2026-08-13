# 网页阅读时长与 Apple Books 同步

**状态:** 否决(若 Apple 开放写入 API 则重新评估)
**日期:** 2026-08-12

## 目标

把 DeepTutor 网页的阅读时长累计 *写入* Apple Books 的"今日阅读时间/阅读
目标",让 Apple 一侧的计数能反映全部阅读。

## 结论

**不可行。Apple 没有任何接口可向 Apple Books 写入阅读时长。**

- Sign in with Apple / Apple ID 登录只给身份(姓名、邮箱、sub),不附带任何
  Apple Books 数据权限。
- Apple Books 阅读时长存在私有沙盒 SQLite,经按 App 隔离的 CloudKit 容器
  同步,第三方无法读写。
- 直接改私有数据库(如 `ZBCASSETREADINGSESSION`)是脆弱 hack:表结构随系统
  更新变动、无完整性保证,且网页沙盒根本碰不到本地文件。
- 只读汇总面板(把 Apple Books 会话单向拉出、展示在 DeepTutor)曾作为折中
  考虑,但已否决:它不满足"同步回 Apple Books"的原始目标。

## 业内成熟做法

没有统一的"阅读时长中心"。各平台各自记账、互为孤岛(Apple Books、
Kindle、微信读书)。通用模式是:

1. **先自记。** 在你能掌控的 App 里计时并存到本地,这是任何导出的前提。
2. **聚合到开放、自有的目标**,实现跨设备查看:日历(Google Calendar /
   iCloud)、Notion / 飞书多维表格、Google Sheets、时间追踪类(Toggl)。
   Readwise 推广了这种聚合模型。
3. **等开放接口再去追封闭目标。** Apple Books 封闭逾十年无开放迹象,不要
   押注其开放。

## 重新评估触发条件

若 Apple 发布公开的阅读时长写入 API(Books、HealthKit,或可设置分钟数的
Shortcuts 动作),则重开此决策。在那之前,保持 DeepTutor 自记数据完整、
可导出至开放平台。
