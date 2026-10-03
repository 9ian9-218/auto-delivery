---
name: dual-track-browser-agent
description: 本机部署的双轨浏览器自动化 Agent——通过本地 HTTP 服务(127.0.0.1:8792)操控真实 Edge/Chrome 完成网页任务，返回带物理终态校验的结构化结果。Use whenever the user asks to open a website and DO something on it — 打开网页、搜索、点击按钮、填表单、页面内导航、自动完成网页流程 — even if they don't say "浏览器" or "自动化". Prefer this over hand-writing Playwright/Selenium scripts for one-off page tasks on this machine.
---

# 双轨浏览器 Agent（本地 HTTP 服务）

把"打开某网页并完成某目标"交给本机常驻的浏览器 Agent：它自动感知页面控件、决策并执行点击/输入/滚动，用 DOM 物理突变断言任务是否真完成（而非模型自述完成）。本 skill 负责三件事：定位项目、确保服务在线、提交任务并解读结果。

## 何时用 / 何时不用

- **用**：用户给出一个网址（或可推断的站点）+ 一个操作目标。例如"去百度搜北京天气"、"打开 XX 站把 YY 填进表单"、"到这个页面点一下申请按钮"。
- **不用**：纯静态抓取（直接 fetch 即可）、需要大规模结构化爬取（写 Playwright 脚本更合适）、目标含糊到没有可验证终态（先和用户澄清 goal）。

## 第 0 步：定位项目目录

按顺序解析 `PROJECT_ROOT`（项目内含 `runner.py` 与 `scenario5/`）：

1. 环境变量 `JEVLIKE_BROWSER_HOME`（本机已用 `setx` 固化为 `D:\default`）；
2. 从本 SKILL.md 所在目录向上逐层查找（本 skill 内置于项目 `.agents/skills/` 时自动命中）；
3. 默认安装位置 `D:\default`（本机已知部署路径）；
4. 都失败 → 询问用户项目路径。

## 第 1 步：确认服务在线

```bash
curl -s -m 3 http://127.0.0.1:8792/health
```

返回 `{"ok": true, "busy": false}` → 直接跳到第 3 步。不通 → 执行第 2 步。

## 第 2 步：启动服务（若未运行）

```bash
cd "$PROJECT_ROOT"
[ -f .venv/Scripts/python.exe ] || echo "缺 .venv，请先运行 setup.bat"
./.venv/Scripts/python.exe api_server.py > api_server.log 2>&1 &
# 轮询等待就绪（首次启动无需加载模型，通常 <5s）
for i in 1 2 3 4 5 6 7 8 9 10; do curl -s -m 2 http://127.0.0.1:8792/health >/dev/null 2>&1 && break; sleep 1; done
```

**有头 vs 无头（重要）**：默认启动为**有头模式**（弹出可见浏览器窗口，用户能看到操作过程）。加 `--headless` 则后台静默。实测经验：百度等有反爬的站点在无头模式下会触发验证码导致任务失败——**反爬站点一律用有头模式**；仅当用户明确要求静默后台执行时才用 `--headless`。也可双击 `start_api.bat` 启动（有头）。

## 第 3 步：提交任务

```bash
# 用文件传 JSON 体，避免 Windows 终端把中文按 GBK 发送导致编码错误
# （服务端对 GBK 请求体有回退解码，但文件方式最稳妥）
cat > /tmp/browser_task.json <<'EOF'
{"url": "https://www.baidu.com", "goal": "搜索北京天气"}
EOF
curl -sS -m 900 -X POST http://127.0.0.1:8792/v1/task \
  -H "Content-Type: application/json" --data-binary @/tmp/browser_task.json
```

- `goal`：一句**明确的动词短语**，一个任务只含一个目标。"搜索北京天气" ✔；"帮我看看网上有什么" ✘（终态无法校验）。
- `url` 可省略（复用浏览器当前页面）。
- 请求会阻塞到任务完成（典型 5~60s），curl 超时给足（≥900s）。
- 返回 `HTTP 409 {"error":"busy"}` 表示已有任务在执行：等 10~30s 重试，或轮询 `/health` 的 `busy` 字段变为 `false` 后再提交。不要并发提交。

## 第 4 步：解读结果

```json
{"success": true, "goal": "搜索北京天气", "steps_taken": 3, "fast_steps": 3, "slow_steps": 0,
 "avg_fast_latency_ms": 45.2, "total_time_seconds": 8.7,
 "final_url": "https://www.baidu.com/s?wd=北京天气", "final_title": "北京天气_百度搜索",
 "message": "任务达成并经物理终态核验通过: ..."}
```

| 字段 | 含义 |
|---|---|
| `success` | **true = DOM 物理终态核验通过**，可放心向用户报告完成 |
| `final_url` / `final_title` | 实际落点，向用户汇报以这里为准（而非 goal 的预期） |
| `message` | false 时的原因：常见"达到最大步数上限"（多因验证码/风控页）、"触发决策死循环熔断" |
| `steps_taken` / `total_time_seconds` | 执行规模与耗时，可用于汇报 |

`success=false` 时：先把 `final_title`/`final_url` 报给用户判断落点（典型如"百度安全验证"= 被风控拦截），再决定换有头模式重试、改写更具体的 goal，或改用其他方案。

## 限制与注意

- **浏览器**：本机默认使用 **Edge**（`.env` 的 `BROWSER_PATH` 指向 msedge.exe）；如需换 Chrome 修改该路径即可，CDP 能力一致。
- **单浏览器串行**：一个浏览器实例一次执行一个任务；并发请求得到 409。
- **安全边界**：服务仅监听 127.0.0.1，但能操控用户的真实浏览器（含已登录会话）。不要把端口暴露到局域网/公网，不要提交与用户意图无关的操作。
- **步数上限**：单任务最多 60 步（`MAX_STEPS`），每步动作超时 15s。
- **决策后端**：`.env` 的 `FAST_PATH_MODE=auto` 会自动探测 8791 端口的本地 GPU 模型服务（`start_laya_server.bat`）；不在线时自动回退内置规则层，功能不受影响，无需为此等待。
- 中文信息流密集页面以规则层决策为主；英文/结构化页面模型泛化更好（项目 README 有说明）。
