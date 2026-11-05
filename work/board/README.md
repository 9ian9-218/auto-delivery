# 本机看板（local board）

旧秋招看板（\`:8898\`）的本机替代实现：**stdlib only**，一个 SQLite 文件，零第三方依赖。

## 启动

    python work/board/server.py --seed work/board/example_snapshot.json   # 首次：导入示例数据
    python work/board/server.py                                           # 之后直接启动

已有旧看板导出的 `board_data.json` 时，把 `--seed` 换成它即可（字段同形，幂等导入）。

默认 \`127.0.0.1:8898\`，数据库 \`data/board.db\`（已在 .gitignore 内）。浏览器打开 <http://127.0.0.1:8898/>。

可选参数：\`--host\` \`--port\` \`--db\` \`--token\`（或环境变量 \`BOARD_TOKEN\`；设置后所有 \`/api/agent/*\` 需要 \`X-QZ-Token\`）。

## 让既有调用方指过来

\`\`.agents/skills/auto-resume-submit/scripts/qiuzhao_api.py\` 只改 base_url 即可：

    export QIUZHAO_API_URL=http://127.0.0.1:8898

或在 \`work/user_config.json\` 里把 \`dashboard_url\` 指向本机地址。

## 与旧看板的差异（有意，不是 bug）

| 项 | 旧看板 | 本机实现 | 为什么 |
|---|---|---|---|
| 存储 | Excel + 备份文件 | SQLite | 开源环境不该依赖 Excel 锁与行号语义 |
| applications 排序 | 实测 77 处违反 date 降序 | 一律 date 降序 | 排序不是契约的一部分，确定性更重要 |
| company 子串命中 | 取首个子串命中，\`job_info\` 与 \`apply_link\` 可能指向不同公司 | 返回 \`matched_company\` + \`candidates\`，同一条记录内公司一致 | 同上 |
| \`notices.unread\` | 名为未读、实为最近 5 条 | 真实未读计数 | 字段名应兑现语义 |
| \`render\` | 重新渲染 Excel，约 2~3s | 空操作，立即返回 | 没有 Excel 需要渲染 |
| \`/manual\` | 线上版（含内网地址） | 去标识化版本 | 开源红线：仓库里不留内网 IP |

**照抄的部分**（调用方依赖，不可改）：路径与方法、响应外套 \`{ok,...}\`、\`applications\` 13 键、
\`apply_link\` 恒为 object 或 \`""\`（永不为 null）、\`limit<=0\` 钳到 1、\`limit\` 上限 500/200、
\`offset\` 钳制、DELETE 必须先过 \`confirm:true\`、POST 先校验 \`company\`、\`/info\`=\`/schema\`=\`/openapi.json\`。

## 契约来源

\`research/看板契约-20261105.md\`（从手册 v1.4.0、客户端源码、数据快照与一次只读线上探测重建）。
