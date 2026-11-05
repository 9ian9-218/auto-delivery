# AGENTS.md — 本仓库工作约定

## 浏览器操作（优先级高于一切默认做法）

**任何需要打开网页、点击、填表、上传附件的任务，优先使用 `dual-track-browser-agent` skill**，
它通过本机 `http://127.0.0.1:8792` 操控真实 Chrome/Edge，并返回带物理终态校验的结构化结果。

顺序：

1. 先用 `dual-track-browser-agent`（skill 里给出的接口）。
2. 只有在它做不到、或需要 CDP 原生能力（如 `DOM.setFileInputFiles`、`Input.insertText`
   这类必须 isTrusted 的输入）时，才退回直接连 `127.0.0.1:9222` 的 CDP 脚本。
3. 退回 CDP 时在回复里说明原因，不要静默切换。

## 简历投递（resume-autofill）

- **投递总流程唯一入口**：`campus-apply-pipeline` skill 及其 `references/pipeline.md`（流程图 + 阶段-真源映射）。三道闸门为硬性人工决策点：闸门1 岗位授权 / 闸门2 交付门 / 闸门3 提交同意。
- 档案真源：`work/application_profile.json`（75+ 条已确认事实，含家庭成员）
- 填表档案：`work/rfa/profile_v2.json`（扩展 `setProfile` 用，已含 family/projects.duty/thesis 等）
- 可复用驱动：`work/rfa/` 下 `native_driver.py`（CDP+扩展隔离世界）、`cdp.py`、`site611.py`、`attach_clean_upload.py`、`submit.py`、`after_submit.py`；历史一次性脚本在 `work/_archive/`
- 一次性脚本一律写进 `work/_archive/<日期>/`，不要堆在 `work/` 根目录
- **填表强制流程（双轨协作）**：扩展（Extension）定位为 L1 辅助加速器（秒级覆盖 70%~80% 常规标准字段）；遇 4 道硬墙（`isTrusted` 原生事件、文件上传沙箱、React/Vue 虚拟 DOM 脱节、Portal 浮层/虚拟滚动）时，由 Agent 使用 CDP 进行 L2 物理注入与状态穿透修障（操作规范见 `campus-apply-pipeline/references/cdp-form-remediation.md`）。机械执行 `resume-autofill/tools/loop.py` 辅助初填与探针回读。
- **交付门（闸门2）物理终态复核**：废除“必须 100% 纯扩展冷启动截图”的僵化限制。交付门以“页面真实 DOM 终态完整（必填项覆盖、站点红字校验为 0、经历区块行数与简历严格对齐、简历等附件已挂载）+ 最终整页截图复核”为准，通过后方可进入闸门3。单独复验与修障遵循双轨协作流。**注意**：废除的是“必须由扩展从头到尾填完”，不是冷启动复验本身——`loop.py gate` 要求 `state.coldStart.pageWasEmpty/ok` 为真且冷启动截图哈希与 `finalShot` 一致，缺一项即 `NO_COLD_START`（真源见 `resume-autofill/tools/loop.py` 的 `gate_reasons`）。
- **闸门留痕**：闸门1 授权写 `gate_log.py gate1 --companies ... --count N --quote "<用户原话>"`；闸门3 同意写 `gate_log.py gate3 --ckpt work/ckpt_<公司>.json --quote "<用户原话>"`；台账 `work/gates.jsonl`，无 gate1 记录时 gate3 拒绝。闸门2 `loop.py gate` 三态 `delivered`(0)/`rejected`(2)/`overridden`(3)
- **断点契约**：`work/ckpt.schema.json`（6 态词表 + 键别名）；`python work/tools/ckpt_lint.py` 校验（0 不合规才算干净），`--handoff` 生成 `work/pending_human.json` 接管清单，一次交给用户处理
- **去重**：`python work/tools/applied_index.py build` → `check <公司>`（看板 8898 + 断点，只读）；不再依赖 `C:\Users` 下的历史黑名单
- **档案三源**：事实 `work/application_profile.json` / 填表 `work/rfa/profile_v2.json` / 扩展运行态；改填表源必须重跑 `launch_debug --profile work/rfa/profile_v2.json`，检查 `python work/tools/profile_sync.py check`
- **`pipeline.py` 不提交任何东西**：`submit` 只产出 `work/submit_queue.json` 待进场清单；`notify` 只回写带 `verified:true + proof` 的记录，未核验一律拒收
- **邮箱渠道（163 SMTP 直投）**：凭据 `work/mail_auth.json`（授权码，已 gitignore）；发信 `python work/tools/mail_send.py send --to <HR> --company <公司> --subject <主题> --body-file <txt> --attach <pdf> --ckpt work/ckpt_<公司>.json`，成功后自动回写断点 `state=awaiting_verification / state_raw=smtp_accepted` 并追加台账 `work/mail_outbox.jsonl`；核验 `python work/tools/mail_verify.py find --message-id <ID>`（IMAP 已发送箱）与 `bounce`（退信）。附件先用命名规则复制到 `work/_draft/姓名-学校-专业-学历-岗位.pdf`

## 数据与功能隔离

- **真源**：`work/DATA_ISOLATION.md`（说明与判据）+ `work/release.manifest`（“什么是功能”的唯一清单，打包与自检共用）。
- **自检**：`python work/tools/check_isolation.py` 查 L1 版本库 / L2 分发包 / L3 运行期三层；基线提交后用 `--strict`，要求功能文件全部入库。
- **单测**：`python work/tests/test_isolation.py`。
- **规则**：功能进版本库 + 进分发包；用户数据（断点、台账、档案、凭证、草稿、截图、`data/`）一律不入库不入包。新增功能文件必须同时改 `release.manifest` 与 `.gitignore` 放行清单，否则自检报 `OUT_OF_MANIFEST`。
- **两个外部项目**：`resume-autofill/`（独立 git，无 remote）与 `re-niuke/`（牛客扩展逆向产物）整目录排除，不属于本仓库功能。

## Agent skills

### Issue tracker

GitHub Issues in `9ian9-218/jevlike_broswer`, driven by the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five triage roles (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`), plus the separate `wayfinder:` label family (`map`/`research`/`prototype`/`grilling`/`task`). See `docs/agents/triage-labels.md`.

### Domain docs

single-context — one root `GLOSSARY.md` and `docs/adr/`. See `docs/agents/domain.md`.

## 提交类动作

投递/提交等不可撤销动作，必须先向用户复述当前状态并拿到明确同意再执行。