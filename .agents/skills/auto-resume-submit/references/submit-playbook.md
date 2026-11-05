# 投递执行手册（兼容入口）

流程和安全规则以 [`campus-apply-pipeline`](../../campus-apply-pipeline/SKILL.md) 及其 `references/application-playbook.md`、`platform-troubleshooting.md`、`safety-gates.md` 为准。真实浏览器操作使用当前可用的 `dual-track-browser-agent`，先读该技能及现有工具的约束；不同服务/标签可能共享锁，不假定多个控制器可以安全并发操作同一标签。

## 本机操作要点

1. 在本技能 `config.json` 中查找项目根、简历和看板。交互前可用本技能 `scripts/preflight.py` 检查，纯找岗不启动浏览器。健康检查与浏览器实际所用资料目录是不同信息；当前 CDP 端口可能接管已有浏览器，不能只看配置认定已接入固定资料目录。
2. 保留当前窗口和登录态。牛客助手是否存在、启用且适用于当前页要在**当前浏览器/资料目录**验证；装在另一个 Edge 或 Chrome 资料目录不代表此处可用。解析或填充后仍须逐项核对，并区分正式附件是否上传成功。
3. 核实当前公司、岗位 ID、工作地、批次和职类；当前表单匹配目标后才填。经验上北森列表可能需要先展开目标岗位卡片，再点击真实可见的申请按钮，并检查是否新开了标签；具体页面以当前控件为准。旧的空弹层故障不意味着所有租户都无法自动操作。
4. 任何可能导致真实提交的最早动作前保存 `awaiting_verification` 断点（含“预览并提交”、验证码后自动提交；无反馈先只读查官网记录，不重投不换渠道），流程见 [application-playbook.md](../../campus-apply-pipeline/references/application-playbook.md) §5。
5. 官网确认成功后，调用 `scripts/qiuzhao_api.py` 的直写接口（`record_application` 或 CLI `record`）直接将投递落盘到远程看板，无需经过看板助手对话；回写前后查重，未知结果先回查。使用已有私有资料档案保存用户确认的信息及范围，不保存密码、验证码或认证 cookie。

不关闭浏览器进程、强制杀进程、扩展 cookie 期限、搬运会话资料或编造字段。图形验证、频控与失效登录遵照当前工具和网站的正常接管流程；用户尚未授权的邮箱发送不自动进行。

## 脚本索引（`scripts/`）

| 脚本 | 用途 | 入口 |
|---|---|---|
| `pipeline.py` | 投递流水线编排：`status` / `shortlist` / `plan` / `submit` / `notify`，默认 dry-run | `python pipeline.py --help` |
| `browser_task.py` | 向 8792 dual-track 服务提交单目标任务，带 `--expect-url` / `--expect-text` 终态断言（success=true 不够） | `--goal <一句话目标> [--url --timeout]` |
| `boss_scan.py` | BOSS 直聘 DOM 扫描（避开 wapi 风控）；`--list-only` 只读 | `--query --city [--list-only]` |
| `preflight.py` | 交互前只读体检：浏览器项目/Node/简历/DrissionPage；加 `--start` 才启动 8792 | `preflight.py [--start] [--json]` |
| `attach.py` | 接管在线 CDP 浏览器（`/v1/lease` 共享锁）：`tabs` / `new` / `on id:<tab> get\|shot\|text\|js\|inputs` | `python attach.py tabs` |
| `form_assist.py` | 快照绑定盘点+计划填写普通控件；默认 dry-run，`--apply` 才写入（用法见 campus-apply-pipeline `form-assist.md`） | `{inspect\|fill} --tab-id ... [--plan --apply]` |
| `session_status.py` | 登录观察台账 `doctor` / `list` / `mark`（不存凭据；台账首次 mark 时生成） | `python session_status.py doctor` |
| `qiuzhao_api.py` | 看板直写/查询客户端（仅 8898，28898 代码级拦截；`chat` 子命令已废弃报错） | `python qiuzhao_api.py --help` |
| `fetch_shortlist.mjs` / `notify_dashboard.mjs` | `pipeline.py` 内部步骤：取候选 / 回写看板（无对话降级，解析不出公司即失败） | 经 `pipeline.py` 调用 |
