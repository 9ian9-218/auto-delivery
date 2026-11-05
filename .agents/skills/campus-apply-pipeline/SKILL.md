---
name: campus-apply-pipeline
description: 校园招聘岗位筛选与网申协调：按已有候选资料核实岗位、填写申请、验证提交结果并登记成功记录。用于查找校招机会、准备网申或用户授权的实际投递；只查岗位时不提交申请。
---

# 校招岗位筛选与投递

协调「选岗核实 → 授权 → 填表 → 交付门 → 提交取证 → 登记」；复用当前环境已有的搜索评分工具、浏览器与投递方式。平台配方是定位线索，不能视为所有门户已验证可用。全流程图与阶段-真源映射见 [pipeline.md](references/pipeline.md)。

## 先确定本次范围

| 用户意图 | 执行范围 |
|---|---|
| 筛选、找岗、核实 | 只读搜索、资格核验、评分及推荐 |
| 帮我投、完成申请 | 在明确的公司、岗位及数量范围内填写并投递 |
| 检查、优化这个 skill | 检查文件和离线验证；不执行真实投递或看板写入 |

既有任务的授权跨轮次有效；「已登录」「继续」可以续接已授权任务，不构成新的批量投递授权。用户换岗时更新目标和断点；同一文件、同一已授权目的地且仍在任务范围内，不重复索要相同授权。审批明确拦截的动作，按 [safety-gates.md](references/safety-gates.md) 处理。

## 1. 读取资料与工具

候选人事实、简历附件、配置、断点与日志 100% 局限并解析自工作区根目录 `D:\auto-delivery\`，严禁读写 `C:\Users\...`（完整边界见 [safety-gates.md](references/safety-gates.md)）。

先看用户指定档案、当前项目配置及已有档案，再补缺失信息。已有 `auto-resume-submit/config.json` 与其 `workspace_root/work/application_profile.json` 时直接复用，按 [onboarding.md](references/onboarding.md) 解析来源和适用范围；不重新访谈已确认的事项。简历附件统一引用 `data/resume/` 下的本地文件。

优先复用已登录、可控的浏览器；交互前可用 `auto-resume-submit/scripts/preflight.py` 只读核对服务与资料目录，确认牛客助手等填表插件确实在当前浏览器可用，不根据其他浏览器已安装就假定可用。不复制 profile、不导出认证 cookie、不改 cookie 有效期、不关闭整批标签页；仅确有需要且在授权范围内才启动现有服务。短信同步服务必须已获用户授权使用，不因配置了地址就自动启动或读取收件箱。登录复用见 [session-management.md](references/session-management.md)（其台账 `work/browser_sessions.json` 首次 mark 时生成）。本机脚本入口一览见 [submit-playbook.md](../auto-resume-submit/references/submit-playbook.md)。

## 2. 核实岗位

按 [screening-playbook.md](references/screening-playbook.md) 执行。要点：平台配方只是线索，逐个核对公司、岗位标识、职类、城市、学历、目标届别与开放状态；标题和职类中的红线按用户最新确认执行（如用户排除算法岗时，标题像开发岗但职类为算法也不能投）。校园招聘、实习等关键词只是线索，不单独证明目标届别合格；搜索摘要仅用于发现，不覆盖官网下线提示；无法核实资格时标为待核实，不提交。

默认公司级去重；投前查本地断点、看板及官网应聘记录，查询失败不等于未投。用户明确允许同公司多岗位时才缩小去重范围；同岗位仍不得重复提交。

## 3. 填表与提交（投递序列 · 三道闸门）

总图见 [pipeline.md](references/pipeline.md)。闸门是硬性人工决策点，任何一道未过都不得进入下一阶段：

1. **🔒 闸门1 · 用户授权**：向用户复述候选清单与数量，拿到明确授权才开始填写；不从配置推断批量授权。授权当场留痕 `python work/tools/gate_log.py gate1 --companies "A,B" --count N --quote "<用户原话>"`（无此记录时闸门3 会拒绝）。
2. **进场**：打开投递页（`dual-track-browser-agent` 8792 优先；CDP 9222 兜底并说明原因），核对页面「正在投递职位」与 URL 岗位标识一致后，再上传获授权的附件。
3. **填表（双轨协作闭环）**：扩展作为 L1 辅助加速器（快速初填常规标准字段），遇 4 大硬墙组件（`isTrusted` 原生事件、附件路径上传、React/Vue 虚拟 DOM 脱节、Portal 浮层/虚拟滚动）时，由 Agent 按 [cdp-form-remediation.md](references/cdp-form-remediation.md) 使用 CDP 执行物理级注入与状态穿透修障。机械辅助执行 `D:\auto-delivery\resume-autofill\tools\loop.py`，台账在 `D:\auto-delivery\resume-autofill\ledger\`。只补已知且语义明确的内容，核对所有结果，缺失必填集中询问用户。
4. **🔒 闸门2 · 交付门（物理终态硬门）**：废除的是“必须由扩展从头到尾填完”，不是冷启动复验——`loop.py gate` 要求 `state.coldStart.pageWasEmpty/ok` 为真且哈希与 `finalShot` 一致（`NO_COLD_START` 即拒收）。以页面真实 DOM 终态及视觉复核为准。逐项核对四项硬指标（必填全覆盖 / 站点红字为 0 / 单选复选真实选中 / 经历区块行数严格等于简历条数 / 必需附件已挂载）。抓取最终整页截图复核通过 = 「可提交状态 + 差异报告」，此时仍未投递。三态：`delivered`(0) / `rejected`(2) / `overridden`(3，用户签字推进，不算过门)。
5. **🔒 闸门3 · 提交同意**：按根 AGENTS.md 铁律，投递前向用户复述当前状态并拿到明确同意并留痕 `gate_log.py gate3 --ckpt work/ckpt_<公司>.json --quote "<用户原话>"`；签名须用户本人，验证码按 [safety-gates.md](references/safety-gates.md)「验证码边界」判定归属。在任何可能触发提交的最早动作前（含「预览并提交」、验证码后自动提交）保存 `awaiting_verification` 断点，完整流程与证据强度见 [application-playbook.md](references/application-playbook.md) §5。
6. **登记与飞轮**：官网核验成功才写看板（直写 API，仅 8898）；中间状态只留本地断点。落层学习成果回写档案与站点规则，下一站复用。

## 4. 汇报与记录

只有核实成功的申请才能写成已投递；中间状态、阻塞和未知结果留在对话或本地断点（`work/ckpt_<公司>.json`，schema 见 [application-playbook.md](references/application-playbook.md) §1），不写入看板成功记录。回写用直写客户端 `auto-resume-submit/scripts/qiuzhao_api.py`（规范见 [看板API手册.md](../auto-resume-submit/references/看板API手册.md)，**仅 8898 端口**）；回写与查重规则（超时先查询、绝不为补看板重新投递）以 [application-playbook.md](references/application-playbook.md) §6 为准。按实际情况报告岗位、渠道、结果与证据链接；有阻塞时说明需要用户补什么或哪一步接管。截止时间未公开就写未公开，不编造。

## 按需参考

- [pipeline.md](references/pipeline.md)：总流程图、阶段-真源映射、人工接管点清单、新站点首跑分支。
- [cdp-form-remediation.md](references/cdp-form-remediation.md)：CDP 疑难表单修障与物理穿透实操手册（针对 isTrusted、文件上传沙箱、React/Vue 状态脱节、Portal/虚拟滚动 4 大硬墙的标准操作方案与代码）。
- [onboarding.md](references/onboarding.md)：已有资料复用、首次补充、模板字段与来源范围。
- [screening-playbook.md](references/screening-playbook.md)：各平台入口、资格、筛选与去重。
- [application-playbook.md](references/application-playbook.md)：填表、上传、验证、提交及断点。
- [platform-troubleshooting.md](references/platform-troubleshooting.md)：遮挡、状态重置、CDP 故障与有限恢复。
- [form-assist.md](references/form-assist.md)：form_assist.py 快照绑定批量填写。
- [session-management.md](references/session-management.md)：登录状态复用与观察台账。
- [safety-gates.md](references/safety-gates.md)：授权、敏感资料、重复提交与看板边界（隔离铁律、验证码边界、外部依赖白名单、回写规则的真源汇聚地）。
- 本机工具（`work/tools/`）：`gate_log.py` 闸门1/3 留痕 · `ckpt_lint.py` 断点校验/归一/接管清单 · `applied_index.py` 公司级去重索引 · `profile_sync.py` 档案三源检查。
- [看板API手册.md](../auto-resume-submit/references/看板API手册.md)：秋招看板直写与查询 REST API 完整规范。
- `D:\auto-delivery\resume-autofill\SELF_LEARNING_LOOP.md`：填表自检闭环——判据优先级、落层判定、3 轮终止、冷启动复验（§3 第 9.5 步）与台账。
- [profile.template.json](scripts/profile.template.json)：没有可复用档案时才使用；空值表示未知。
