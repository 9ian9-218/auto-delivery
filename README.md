# 场景 5：双轨协同浏览器自动化 Agent (Dual-track Browser Agent)

本项目是基于《Codex × Jev × Laya 使用报告》中**场景 5（受限网页操作 / 双轨协同浏览器自动化）**在 Windows 环境下的完整落地工程。

**多机快速部署**：Git clone（或解压）后双击 `setup.bat` 一键完成环境搭建、依赖安装与模型下载；随后双击 `start_all.bat` 即可使用。详见下文 [📦 部署到其他电脑](#-部署到其他电脑)。

---

## 🌟 核心特性

1. **双轨快慢路径 (Fast/Slow Path)**：
   - **快轨 (≤50ms)**：负责 90% 以上高频离散动作（`CLICK`、`SELECT`、`SCROLL` 等）的单请求联合决策，无自回归 Token 解码开销；支持 Jev API、本地 Laya 服务以及内置智能启发式决策。
   - **慢轨 (按需接入)**：仅在需要键入复杂文本（`TYPE_TEXT`）或任务受阻（`BLOCKED` 自愈）时唤醒 Codex / 通用大模型。
2. **真实物理终态校验 (Physical Verifier)**：
   - 杜绝传统小模型的“假完成”幻觉，以 DOM 突变位移、页面关键特征与网络终态做严格闭环断言。
3. **CDP 原生免驱动 (Zero-Driver)**：
   - 默认无缝接管本机 **Microsoft Edge** (`msedge.exe`)，也可通过 `BROWSER_PATH` 一键切换 Chrome，无需额外下载 WebDriver。
4. **交互过程直观可视**：
   - 默认开启有头模式，执行点击和输入时目标元素带有高亮红框与光晕特效，人机协作清晰可见。
5. **GPU 加速推理（自动适配）**：
   - Laya-Browser 微调模型（约 650MB）默认加载至 NVIDIA GPU（CUDA 12.8），无显卡时自动回退 CPU，决策服务 `http://127.0.0.1:8791/v1/decide`。

---

## 📦 部署到其他电脑

**前置要求**：Windows 10/11、Python 3.10+（勾选 Add to PATH）、Edge 浏览器（Chrome 亦支持）；NVIDIA 显卡可选（用于 GPU 加速）。

### 方式 1：从 GitHub 克隆（推荐）
```bash
git clone https://github.com/<你的用户名>/scenario5-browser-agent.git
cd scenario5-browser-agent
```
然后双击 **`setup.bat`**，脚本将自动完成：
1. 检测 Python / uv，创建 `.venv` 虚拟环境并安装全部依赖；
2. 询问是否安装 GPU (CUDA 12.8) 版 PyTorch（有 NVIDIA 显卡建议选 Y）；
3. 生成 `.env` 本地配置（基于模板）；
4. 从 hf-mirror 镜像下载 Laya-Browser 微调模型（约 650MB，已存在自动跳过）；
5. 运行冒烟自检验证环境。

完成后双击 **`start_all.bat`**（GPU 模型服务 + Agent 一起拉起）或 **`run.bat`**（纯规则模式，最轻量）。

### 方式 2：离线压缩包
将发布附件中的 `scenario5-browser-agent.zip` 解压到任意目录，同样双击 `setup.bat` 即可（模型权重通过脚本在线下载，保持压缩包轻量）。

> **提示**：即使跳过模型下载（或在无网络环境），内置启发式规则层仍可独立驱动浏览器完成常规自动化任务。

---

## ☁️ 发布到 GitHub（首次上传）

本仓库已初始化 Git 并完成首次提交，模型权重已通过 `.gitignore` 排除（保持仓库轻量）。在 GitHub 网页创建一个**空仓库**后，在本目录执行：

```bash
git remote add origin https://github.com/<你的用户名>/scenario5-browser-agent.git
git push -u origin main
```

或在装有 GitHub CLI 的机器上一条命令完成建仓+推送：
```bash
gh repo create scenario5-browser-agent --private --source . --push
```


---

## 🚀 极速上手 (两步使用)

### 方式 1：双击一键运行（推荐）
在文件管理器中，直接双击运行本目录下的 **`run.bat`**。
脚本将自动挂载 `.venv` 虚拟环境并启动彩色交互控制台。

### 方式 2：命令行运行
在当前目录的终端中执行：
```bash
# 1. 激活虚拟环境 (Git Bash)
source .venv/Scripts/activate

# 2. 启动交互式控制台
python runner.py
```

或者使用单行命令直接执行指定任务：
```bash
python runner.py --url https://www.baidu.com --goal "搜索2026年最新科技动态"
```

---

## ⚙️ 模型与运行配置 (`.env`)

编辑根目录下的 `.env` 文件可灵活切换决策后端：

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `BROWSER_PATH` | 自动探测（优先 Edge，Chrome 兜底） | 浏览器可执行文件路径 |
| `HEADLESS` | `false` | `true` 为后台无头静默，`false` 为桌面可见窗口 |
| `FAST_PATH_MODE` | `auto` | `auto`（优先 Jev -> 本地Laya服务 -> 本地规则）、`laya_local`（直接进程内加载已下载模型）、`laya`、`jev`、`heuristic` |
| `TYPESAFE_API_KEY` | *(留空)* | 若使用云端 Jev，填写 TypeSafe API Key |
| `LAYA_BASE_URL` | `http://127.0.0.1:8791/v1` | 若使用本地微调 Laya HTTP 服务端口 |
| `SLOW_PATH_API_KEY` | *(留空)* | 慢轨大模型 API Key（支持 OpenAI / DeepSeek / 兼容接口） |
| `SLOW_PATH_BASE_URL` | `https://api.openai.com/v1` | 慢轨大模型 API Base URL |
| `SLOW_PATH_MODEL` | `gpt-4o-mini` | 慢轨模型名称 |

---

## 🤖 本地微调模型 (Laya-Browser) 与 GPU 推理

已为您将微调权重下载至本目录：`models/laya-browser/` (约 650MB)，且推理后端已升级为 **CUDA 12.8 版 PyTorch**，模型自动加载至 GPU（NVIDIA GTX 1660 Ti）运行，GPU 不可用时自动回退 CPU。

提供两种使用方式：

### 方式 1：双击启动独立 HTTP 微服务（推荐）
双击运行本目录下的 **`start_laya_server.bat`**：
- 自动检测并使用 GPU（控制台会显示「GPU 加速已启用」）；
- 在本地启动决策服务：`http://127.0.0.1:8791/v1/decide`（同时兼容 `/v1/systemone`）；
- 此时运行 `run.bat`，Agent 快轨将自动探活并调用该 GPU 模型参与决策。

### 方式 2：一键全部启动（模型服务 + Agent 一起拉起）
双击运行 **`start_all.bat`**：
- 自动在新窗口启动 GPU 模型服务（约 20 秒完成加载）；
- 随后自动打开浏览器 Agent 交互控制台；
- 在控制台输入网址与任务即可开始自动化。

### 方式 3：纯进程内直接加载推理（免服务）
修改 `.env` 中的：
```ini
FAST_PATH_MODE=laya_local
```
启动 `python runner.py` 时无需单独开服务，主程序直接在内存中加载 GPU 模型执行决策。

### Agent 如何在浏览器操作时使用该模型？
运行 `run.bat` 后，Agent 每一步的决策流程为：
1. **感知页面**：提取当前页面所有可见控件并打标；
2. **快轨决策**：`.env` 为 `auto`（默认）时，自动探测本地 `8791` 端口——GPU 模型服务在线即参与决策（模型结论与规则层一致时直接采纳；分歧时由规则层护航、以目标语义验证择优）；服务不在线则自动回退纯规则模式，不影响使用；
3. **慢轨按需介入**：仅在需要生成输入文本或任务受阻自愈时调用大模型 API；
4. **物理终态核验**：执行后校验 DOM 真实变化与完成状态，并内置死循环熔断保护。

> **能力边界提示**：该微调模型以英文浏览器任务训练为主（官方基准 typed-decisions 准确率 0.766），在中文信息流密集页面（如百度首页）泛化有限。`auto` 集成模式正是为此设计——规则层保证中文固定站点的确定性，GPU 模型贡献英文/结构化页面的泛化决策。

---

## 📂 代码目录结构

```text
D:\default\
├── setup.bat                   # ⭐ 新机一键部署（环境+依赖+模型下载+自检）
├── start_all.bat               # ⭐ 一键启动（GPU 模型服务 + 浏览器 Agent）
├── run.bat                     # 仅启动浏览器 Agent（规则模式）
├── download_model.py           # 模型权重下载脚本（镜像优先，已存在自动跳过）
├── start_laya_server.bat/.py   # 本地微调模型 GPU 推理服务（端口 8791）
├── runner.py                   # 命令行交互主程序
├── pyproject.toml              # 项目定义与依赖
├── .env.example                # 配置模板（setup.bat 自动复制为 .env）
├── .gitignore                  # 排除模型权重/虚拟环境/本地配置
├── test_smoke.py               # 健康检查与冒烟测试脚本
├── models/                     # 模型存放目录（部署时自动下载，不入库）
│   └── laya-browser/           # cklxx/laya-browser 完整权重与代码
└── scenario5/                  # 核心实现包
    ├── config.py               # 环境配置与浏览器探测
    ├── browser/
    │   ├── driver.py           # 浏览器驱动器（免驱动接管、高亮反馈、点击输入）
    │   ├── observer.py         # 页面提取器（可见控件提取、DOM 打标、抗漂移指纹）
    │   └── verifier.py         # 物理终态校验器（DOM 突变位移、完成断言）
    ├── decision/
    │   ├── schemas.py          # 动作原语规范 (ActionType, ActionChoice)
    │   ├── fast_path.py        # 快轨决策路由（Jev / 本地Laya / 启发式 + 集成裁决）
    │   └── slow_path.py        # 慢轨生成器（Codex / LLM 文本填充与故障自愈）
    └── agent.py                # 双轨主状态机协调器（感知→决策→执行→核验→熔断）
```
