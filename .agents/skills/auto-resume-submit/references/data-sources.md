# 秋招看板数据与 API 操作

看板地址与凭据由 `QIUZHAO_API_URL` 或 `work/user_config.json` 的 `dashboard_url` 决定，缺省是本机看板 `http://127.0.0.1:8898`（`work/board/`）。完整端点定义见 [`看板API手册.md`](看板API手册.md)。

## 1. 直写与查询机制

自 2026-10-28 起，外部 Agent 与脚本**直接通过 REST API 读写看板，无需经过看板助手（对话接口）**。
- 写操作（`POST /api/agent/applications`、`PATCH /api/agent/applications`、`POST /api/agent/jobs`、`POST /api/agent/exams`）直接原子加锁落盘 Excel、自动轮转备份，并重生成看板 HTML，耗时约 0.3s。
- 优先使用本技能 `scripts/qiuzhao_api.py` 的 CLI 命令或 `QiuzhaoAgentClient`。

## 2. 核心操作规范

- **查重先行**：投前同时核查本地断点、看板（`qiuzhao_api.py apps` / `company`）及官网记录；公司简称、职位标识和已确认的多岗位政策均须考虑。同一岗位不重复申请。`unapplied` 和公司汇总方向不保证岗位未投或当前开放。
- **投递登记（直写）**：
  - 仅对官网已验证成功的申请调用 `qiuzhao_api.record_application(company, position, status="已投递", date=...)` 或 CLI `python scripts/qiuzhao_api.py record <公司> <岗位>`。
  - 同公司再投新岗位时，默认 `mode="auto"`，会自动合并为 `岗位A + 岗位B` 并递增岗位数，不会覆盖已有状态。
- **状态流转（直写）**：
  - 收到笔面通知、约面、挂或 offer 时，调用 `qiuzhao_api.update_application(company, position=..., status=...)` 或 CLI `update`，修改状态会自动将「阶段更新」日期盖为今天。
  - 标准状态词表：
    - 在流程：`已投递` `测评通知` `测评完成` `笔试通知` `笔试完成` `AI面完成` `面试通知` `约一面` `面试中` `offer`
    - 已淘汰：`简历挂` `笔试挂` `测评挂` `一面挂` `二面挂` `面试挂` `已淘汰` `不合适` `终止` `挂`
- **日程登记（直写）**：
  - 收到考试/面试通知时，调用 `qiuzhao_api.add_exam(company, kind="面试", when="2026-11-02 15:00", place="线上", status="面试通知")`，将同时登记考场日程并将投递状态变更为对应状态。
- **撤销误录（直写）**：
  - 若录错条目需删除，调用 `qiuzhao_api.remove_application(company, confirm=True)`；淘汰/流程结束请使用更新状态，切勿删除。
- **看板凭据与安全**：不得在命令输出或日志中打印 Token 或敏感个人资料。写入操作应核对响应中的 `changes` 字段，确认变更符合预期。
