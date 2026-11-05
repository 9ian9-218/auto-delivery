---
name: auto-resume-submit
description: 校园招聘岗位清单和自动投递兼容入口：复用秋招看板、岗位搜索评分及既有 BOSS、应届生、国聘和企业官网流程；仅在用户授权的范围内申请，并核实官网结果。
---

# 自动投递简历兼容入口

此入口保留原来的看板客户端和渠道，不另外定义一套互相冲突的投递规则。**先读取并执行 [`campus-apply-pipeline`](../campus-apply-pipeline/SKILL.md)**；其筛选、资料、授权、去重、填表、提交和核验规则适用于本入口。招聘平台经验见该技能的 `references/`，旧环境工具说明见本目录 [`references/submit-playbook.md`](references/submit-playbook.md)。

## 范围与资料

- 搜索、评分或列清单仅做只读操作；已授权投递任务可跨轮次继续；当前指令的岗位、公司和数量限制优先，未明确数量不从配置推断批量授权。
- 范围、目录隔离、档案真源（`workspace_root/work/application_profile.json`）与授权规则一律以 [`campus-apply-pipeline`](../campus-apply-pipeline/SKILL.md) 及 [safety-gates.md](../campus-apply-pipeline/references/safety-gates.md) 为准，本文不复述。
- 本技能的存在价值：看板直写客户端（下节）+ 本机脚本索引（[submit-playbook.md](references/submit-playbook.md)）。

## 环境与填表

只查清单时不启动浏览器服务。脚本用法见 [submit-playbook.md](references/submit-playbook.md) 脚本索引；填表、断点与回写规则以 [`campus-apply-pipeline`](../campus-apply-pipeline/SKILL.md) 投递序列及 [application-playbook.md](../campus-apply-pipeline/references/application-playbook.md) 为准，自检闭环见 `D:\auto-delivery\resume-autofill\SELF_LEARNING_LOOP.md`。

## 可执行的填表与登录辅助

- `scripts/attach.py`：精确标签选择、共享任务锁、只接管已运行浏览器；同 URL 多标签不会随意选最后一个。
- `scripts/form_assist.py`：盘点控件，按标签、岗位上下文和表单快照绑定的计划批量填写普通输入、原生 select 和单文件输入，并回读检查；默认 dry-run，实际执行加 `--apply`。细节按主技能的 [form-assist.md](../campus-apply-pipeline/references/form-assist.md)，自定义日期/下拉仍走正常界面。
- `scripts/session_status.py`：诊断实际目录、按实际 profile/企业租户记录登录观察；不保存凭据，历史观察须重新核实。详见 [session-management.md](../campus-apply-pipeline/references/session-management.md)。

## 看板直写与查询工具

自 2026-10-28 起，看板已提供直写 REST API，**无需告知看板助手对话即可直接操作与修改**（直接原子落盘 Excel 并自动备份，耗时约 0.3s；对话接口 `chat` 已 410 废弃，不再作为降级）。

通过本技能目录的 `scripts/qiuzhao_api.py` 进行直写与查询（**项目铁律：仅允许访问 8898 端口秋招看板，严禁使用 28898 端口**）：

1. **查询大盘与记录**：
   - 概览：`python scripts/qiuzhao_api.py overview --text`
   - 投递记录：`python scripts/qiuzhao_api.py apps --status active -n 20`
   - 指定公司（公司名**子串匹配**）：`python scripts/qiuzhao_api.py company 腾讯`
   - 未投推荐（可分页 / 可含同公司已投）：`python scripts/qiuzhao_api.py unapplied --direction 后台开发 -n 50 --offset 0`
   - 笔面日程：`python scripts/qiuzhao_api.py exams`

2. **直写记录与状态流转**（官网核验成功后才写入）：
   ```bash
   # 记录投递（新增岗位）
   python scripts/qiuzhao_api.py record 腾讯 后台开发 --status 已投递 --date 2026-10-28
   # 修改状态（约面/笔试挂/offer 等，阶段更新自动盖今天）
   python scripts/qiuzhao_api.py update 腾讯 --position 后台开发 --status 面试中
   # 登记笔试/面试/测评日程
   python scripts/qiuzhao_api.py exam 腾讯 面试 "2026-11-02 15:00" --place 线上 --status 面试通知
   # 维护内推码与投递链接
   python scripts/qiuzhao_api.py job 腾讯 --referral-code ABC123 --apply-link https://example.com/apply
   # 撤销录错的条目（必须显式加 --confirm；公司挂了请改状态而非删除）
   python scripts/qiuzhao_api.py remove 腾讯 --position 后台开发 --confirm
   # 从未投递清单排除公司（幂等，只影响未投递视图）
   python scripts/qiuzhao_api.py exclude-unapplied 某公司 --yes
   # 批量导入：每条加 --no-render，最后统一 python scripts/qiuzhao_api.py render
   ```

或在 Python 中调用 `from scripts.qiuzhao_api import get_client; c = get_client(); c.record_application(...)`，或兼容调用 `qiuzhao_api.record_submission(...)`（内部已切换为直写 API）。写入前查重，记录发起状态；超时先回读确认再决定是否补记，绝不为补看板重新申请。详细端点与状态词表见 [`references/看板API手册.md`](references/看板API手册.md) 与 [`references/data-sources.md`](references/data-sources.md)。

**使用要点**：写操作默认 `render:true`（2~4s），批量写入先关 render 再统一刷一次；重复调用幂等；返回体看 `changes` / `warnings`；公司名匹配忽略空格/括号/连字符/大小写，命中多家返回 `candidates` 需写全名；`apply_link` 可能是字符串也可能是对象，取值先判类型。
**已废弃（410，别再接）**：`/api/agent/chat`、`/history`、`/abort`、`/reset` —— 一律改用上面对应的直写接口。
