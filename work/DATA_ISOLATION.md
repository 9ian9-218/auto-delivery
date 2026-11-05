# 数据与功能隔离说明

本项目的判据只有一句：**功能进版本库、进分发包；用户数据一律不进**。
三层的检查器是 `work/tools/check_isolation.py`，清单真源是 `work/release.manifest`。

## 一、三层判据

| 层 | 判什么 | 谁保证 |
|---|---|---|
| **L1 版本库层** | git 追踪的文件必须全部落在 `release.manifest` 的 `[functional]` 段里；追踪文件里不得出现身份证号 / 手机号 / 个人邮箱 / SMTP 授权码 | `check_isolation.py` + `.gitignore` |
| **L2 分发包层** | `pack_release.py` 按同一份 manifest 取件，再过 PII 闸门；命中即中止 | `pack_release.py` |
| **L3 运行期层** | 功能代码不得写死本机绝对路径；敏感数据文件名只能出现在已 import `user_config` 的文件里，或在豁免表中登记理由 | `check_isolation.py` |

不做的一层：**用户数据物理搬出仓库根**。原因是投递流程脚本大量按仓库根推导路径（`Path(__file__).parents[2]`、`sys.path.insert(0, 'work/rfa')`），搬出去等于改流程。

## 二、两类东西放在哪

| 类别 | 位置 | 进版本库 | 进分发包 |
|---|---|---|---|
| 代码、schema、模板、单测、文档 | `work/tools/`、`work/tests/`、`work/rfa/*.py`、`work/*.example.json`、`work/ckpt.schema.json`、`AGENTS.md`、`docs/` | ✅ | ✅ |
| 流程定义与看板客户端 | `.agents/skills/campus-apply-pipeline/`、`.agents/skills/auto-resume-submit/`（**不含**其 `work/`） | ✅ | ✅ |
| **用户真实配置** | `work/user_config.json` | ❌ | ❌ |
| **邮箱授权码** | `work/mail_auth.json` | ❌ | ❌ |
| **身份档案** | `work/application_profile.json`、`work/rfa/profile_v2.json` | ❌ | ❌ |
| **简历与证件** | `data/resume/`、`data/photo/` | ❌ | ❌ |
| **断点 / 闸门台账 / 去重索引 / 发件台账** | `work/ckpt_*.json`、`work/gates.jsonl`、`work/applied_index.json`、`work/mail_outbox.jsonl` | ❌ | ❌ |
| **草稿、截图、归档** | `work/_draft/`、`work/shot_*.png`、`work/rfa/shots/`、`work/_archive/` | ❌ | ❌ |
| **可重生成数据** | `data/*.json`（岗位池抓取，6 个文件） | ❌ | ❌ |
| **外部项目** | `resume-autofill/`（独立 git，无 remote）、`re-niuke/`（牛客扩展逆向产物） | ❌ | ❌ |
| **站点登录 cookie** | 浏览器 profile（`--user-data-dir`），不落项目 | ❌ | ❌ |

> `work/*` 整体不追踪，放行的只有 manifest 里列的几类；截图、断点、台账还有**二级防护**规则，防止被整棵放行的目录带回来。

## 三、加一个功能文件要改哪里

1. 文件写进 `work/tools/` 或 `work/rfa/`（或 manifest 已覆盖的目录）；
2. 在 `work/release.manifest` 的 `[functional]` 段补一行 glob（**唯一真源**，打包与自检都读它）；
3. 如果它在 `work/` 根或新目录，还要在 `.gitignore` 补对应放行；
4. 跑 `python work/tools/check_isolation.py --strict`，必须 0 失败。

漏了第 2 步 → 自检报 `OUT_OF_MANIFEST`；漏了第 3 步 → 报 `IGNORE_TOO_STRICT`。不必靠记性。

## 四、新用户接入

### 1. 填配置

```bash
cp work/user_config.example.json work/user_config.json
```

必填：`workspace_root`、`browser_project_root`、`dashboard_url`（仅 8898）、
`user.name/phone/email`、`user.target_grad_year`、`user.target_titles`、`user.excluded_roles`、
`user.preferred_cities`、`resume.pdf/docx`。

### 2. 放简历与证件

按 `user_config.json` 里 `resume` 各键指向的路径放入文件，建议命名：

```
data/resume/简历-<姓名>-硕士.pdf
data/resume/身份证_正面.jpg / 身份证_背面.jpg
data/resume/证件照.png
data/photo/生活照.jpg
```

### 3. 配邮箱（可选，走邮件渠道时才需要）

```bash
cp work/mail_auth.example.json work/mail_auth.json
```

字段 `smtp_host` / `smtp_port` / `account` / `auth_code`。`auth_code` 是 163 邮箱设置里生成的授权码，不是登录密码。
`mail_send.py` 与 `mail_verify.py` 都从 `user_config.json` 的 `mail.auth_file` 取路径，缺配置时回退老路径并**打印告警**（不再静默）。

### 4. 建档案

`work/application_profile.json` 与 `work/rfa/profile_v2.json` 是用户态档案，需按新用户重建；
三源一致性检查：`python work/tools/profile_sync.py check`。

### 5. 登录各招聘平台

登录态在浏览器 profile 里，不随包传递；`work/browser_sessions.json` 记录观察结果。

## 五、自检与验收

```bash
python work/tools/check_isolation.py            # 常规自检（未入库功能文件记为告警）
python work/tools/check_isolation.py --strict   # 基线提交后用：功能文件未入库即失败
python work/tools/check_isolation.py --json     # 机器可读
python work/tests/test_isolation.py             # 判据自身的单测（9 组）
python work/tools/pack_release.py               # 分发预检（不产 zip）
python work/tools/pack_release.py --out dist/kit.zip
```

退出码：`0` 通过 / `1` 有失败项 / `2` 用法或环境错误。

## 六、已知边界（不是遗漏，是明确不做）

- **`profile_sync.py` 未走 `user_config`**：它按仓库根约定直接读三份档案，属于只读比对工具；已在
  `check_isolation.py` 的 `SEAM_EXEMPT` 里登记理由。要收口得改流程脚本，不在本次范围。
- **`work/_archive/` 里有 11 个一次性脚本硬编码了姓名与证件号**：目录已被忽略、也不进包，泄露面为零；
  按"只标记不删"处理——删掉会丢掉复盘依据，脱敏改写会造出"看着能跑其实跑不通"的脚本。
- **`resume-autofill/` 是独立 git 仓库且没有 remote**：不能做 submodule，也不搬动（搬动等于替它做版本决策）。
  它的 `ledger/`、`shots/`、`artifacts/` 由它自己的 `.gitignore` 挡住，外层整目录排除。

## 七、切勿

- 不要把 `work/user_config.json`、`work/mail_auth.json`、`data/resume/` 提交或发给他人；
- 不要用别人的 `applied_index.json`（去重会基于他人历史，导致误判漏投）；
- 不要为了"能打包"把用户数据塞进 `[functional]`——那会让 L1 和 L2 同时失守；
- 浏览器 profile 目录含全部登录态，等同于凭证。
