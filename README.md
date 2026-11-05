# auto-delivery · 校招投递工作台

一个人也能跑起来的校招投递工作台：**本机看板 + 浏览器填表 + 断点台账 + 三道人工闸门**。
仓库里只有功能，没有个人数据、凭证与内网地址。

## 它是什么

| 模块 | 作用 | 位置 |
|---|---|---|
| 本机看板 | 投递记录、未投递清单、笔面日程；REST 接口与旧看板 v1.4.0 同形 | \`work/board/\` |
| 投递流程 | 选岗核实 → 闸门1 授权 → 填表 → 闸门2 交付门 → 闸门3 提交同意 → 登记 | \`.agents/skills/campus-apply-pipeline/\` |
| 填表自检 | 扩展 + CDP 双轨填表，交付门按 DOM 终态与冷启动证据判 | \`resume-autofill/\`（外部项目，见下） |
| 断点与台账 | 每家公司一份 \`ckpt_<公司>.json\`，6 态状态机；闸门签字写 \`gates.jsonl\` | \`work/\`（不入库） |
| 隔离自检 | L1 版本库 / L2 分发包 / L3 运行期三层判据，一条命令查完 | \`work/tools/check_isolation.py\` |

## 快速开始

\`\`\`bash
git clone <this-repo> && cd auto-delivery

# 1. 建用户配置（模板里全是占位符）
cp work/user_config.example.json work/user_config.json
#    填 workspace_root / user.* / resume.*

# 2. 起本机看板（首次带 --seed 导入示例数据）
python work/board/server.py --seed work/board/example_snapshot.json
#    浏览器打开 http://127.0.0.1:8898/

# 3. 自检
python work/tools/check_isolation.py
python work/tests/test_isolation.py
python work/tests/test_board_api.py
\`\`\`

## 目录

\`\`\`
AGENTS.md                 # 工作约定（投递流程、隔离规则）
work/board/               # 本机看板：store.py / server.py / static/index.html
work/tools/               # 断点校验、闸门留痛、去重索引、配置解析、隔离自检、打包
work/rfa/                 # CDP 驱动与站点配方（填表/上传/提交的物理通道）
work/tests/               # 离线回归（不连浏览器、不碰真实数据）
work/release.manifest     # 「什么是功能」的唯一清单，打包与自检共用
docs/agents/              # issue tracker / triage / domain 约定
.agents/skills/           # 两个流程 skill（pipeline 定义与看板客户端）
\`\`\`

## 需要你自己准备的东西

- **简历与证件**：放进 \`data/resume/\`（该目录不入库）。
- **浏览器登录态**：登录态在浏览器 profile 里，不随包传递。
- **填表扩展**：\`resume-autofill/\` 是独立仓库（有自己的 git），本仓库按外部项目对待，不追踪其内容。
- **邮箱渠道（可选）**：\`cp work/mail_auth.example.json work/mail_auth.json\` 后填 SMTP 授权码。

## 数据与功能隔离

仓库只带功能。断点、台账、档案、凭证、截图、\`data/\` 一律不入库、不进分发包：

\`\`\`bash
python work/tools/check_isolation.py --strict   # 0 失败才算干净
python work/tools/pack_release.py               # 分发预检（含 PII 闸门）
\`\`\`

判据与边界见 [work/DATA_ISOLATION.md](work/DATA_ISOLATION.md)。

## 边界

- 投递是**不可撤销**动作：三道闸门都是硬性人工决策点，工具不会替你点提交。
- 本仓库不含任何招聘平台的凭据；登录态由你自己的浏览器持有。

## 许可

MIT，见 [LICENSE](LICENSE)。
