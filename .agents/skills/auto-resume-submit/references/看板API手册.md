> # 📌 项目铁律（D:\default 项目 · 2026-10-28 用户明确指示）
>
> **本项目只允许使用 8898 端口的秋招看板：http://100.73.185.103:8898（board key qiuzhao，工具前缀 qiuzhao_*）。**
> **严禁使用 28898 端口看板（http://47.116.208.4:28898, board key qiuzhi）** —— 不得连接、读取或写入，任何形式都不行。
> 本文所有涉及 :28898 / qiuzhi 的段落仅为文档原文，一律不适用本项目；实际调用一律走 :8898。
> 本地客户端 scripts/qiuzhao_api.py 已做硬拦截：URL 含 28898 或 oard="qiuzhi" 直接抛 ValueError。
>
> 下列做法在本项目中被禁止：
> - 自己 openpyxl 改 Excel（绕开锁/备份/刷新，次日 cron 覆盖）
> - 通过看板助手对话记账（POST /api/agent/chat 已 410 禁用）
>
> ---
# 看板 API 手册（外部 Agent 专用）

> 版本 1.4.0 · 2026-10-28 · 适用：**秋招看板** `:8898`、**求职看板** `:28898`
>
> 这份文档是给**其他 Agent / 脚本**看的完整说明书：读数据、记投递、改状态、登笔面试、改内推码、排未投递，
> 全部直连 HTTP 接口，**不需要**走看板自己的对话 Agent，也**不要**自己 openpyxl 改 Excel。
>
> 机器可读版：`GET /api/agent/info`（端点表 + function-calling 工具定义）
> 本文在线版：`GET /api/agent/manual`（纯 Markdown）

**读文档的顺序**：§1 搞清楚两套看板 → §3 找接口 → §4 认字段 → §5 照抄写请求 → §6 未投递专题 → §9 抄现成配方。

---

## 1. 两套看板速览

| 项 | 秋招看板 | 求职看板 |
|---|---|---|
| Base URL | `http://100.73.185.103:8898`（Tailscale 内网） | `http://47.116.208.4:28898`（公网） |
| board key | `qiuzhao` | `qiuzhi` |
| 主表（唯一真源） | `秋招报告/秋招情报.xlsx` | `求职报告/求职情报.xlsx` |
| 内推链接 | `data/内推链接.json` | `data/qiuzhi/内推链接.json` |
| 未投递切片（派生） | `秋招报告/未投递岗位_YYYYMMDD.xlsx` | `求职报告/未投递岗位_YYYYMMDD.xlsx` |
| 写备份 | `秋招报告/.backups/api-*.xlsx` | `求职报告/.backups/api-*.xlsx` |
| 看板提醒 | `data/看板提醒.jsonl` | `data/qiuzhi/看板提醒.jsonl` |
| 工具名前缀 | `qiuzhao_*` | `qiuzhi_*` |
| 服务 | `qiuzhao-web.service` | `qiuzhi-web.service` |

两套看板的工作表结构**完全一致**（`招聘岗位` / `内推汇总` / `已结束招聘` / `规则配置` / `考试安排` / `投递记录`），
接口形状也完全一致 —— 换个 base URL 就能复用代码。

**⚠️ 两套严格隔离**：数据目录、备份、提醒、未投递切片各自独立，生成器与写层都有目录级校验（见 §6.3）。
**绝不**跨端口读写，**绝不**把秋招数据往求职看板灌。

**鉴权**：默认关闭。若运维建了 `data/.web_token`（求职侧 `data/qiuzhi/.web_token`），所有 `/api/agent/*`
需要带 `X-QZ-Token: <token>` 或 `Authorization: Bearer <token>`（也接受 `?token=`），否则 `401 {"error":"unauthorized"}`。

**其它约定**：请求/响应 `application/json; charset=utf-8`；时区 CST(UTC+8)；`date` 不传即今天。

---

## 2. 30 秒上手

```bash
BASE=http://100.73.185.103:8898        # 求职看板换 http://47.116.208.4:28898

# 看大盘（人读的 Markdown）
curl -s "$BASE/api/agent/overview?format=text"

# 记一次投递
curl -s -X POST $BASE/api/agent/applications -H 'Content-Type: application/json' \
  -d '{"company":"腾讯","position":"后台开发","status":"已投递"}'

# 改状态（约面 / 笔试挂 / offer …）— 阶段更新自动盖今天
curl -s -X PATCH $BASE/api/agent/applications -H 'Content-Type: application/json' \
  -d '{"company":"腾讯","position":"后台开发","status":"面试中"}'

# 查某家公司
curl -s "$BASE/api/agent/company?name=腾讯"
```

三条铁律先记住：
1. **写操作都直接落 Excel 并刷新网页**，返回体 `changes` 说明改了什么；`ok:false` 时带 `error`。
2. **写默认 `render:true`（约 2~3s）**。批量写先传 `render:false`，最后调一次 `POST /api/agent/render`。
3. **重复调用是安全的**：岗位文本相同不会重复插行，考试按「公司+类型+时间」幂等，排除公司幂等。

---

## 3. 接口总表

### 3.1 读接口

| 方法 | 路径 | 关键参数 | 返回 |
|---|---|---|---|
| GET | `/api/agent/overview` | `format=json\|text` | 统计 / 近期动态 / 考试 / 未读提醒 / `summary_markdown` |
| GET | `/api/agent/applications` | `status`, `company`, `direction`, `limit`(≤500，默认100), `offset` | `{ok,total,limit,offset,items[]}` |
| GET | `/api/agent/company` | `name` **必填** | 该公司投递记录 + 岗位信息 + 内推码 + 链接 + 考试；查不到 404 |
| GET | `/api/agent/unapplied` | `direction`, `company`, `industry`, `limit`(≤200，默认50), `offset`, `exclude_applied`(默认true) | 未投递清单（见 §6） |
| GET | `/api/agent/exams` | — | 全部笔试/面试/测评安排 |
| GET | `/api/agent/notices` | `limit`(默认30) | 看板提醒（未读数 + 列表） |
| GET | `/api/agent/info` | — | 端点表 + function-calling 工具定义（= `/api/agent/schema`、`/api/agent/openapi.json`） |
| GET | `/api/agent/manual` | — | 本文（Markdown） |

`status` 取值：`active`（在流程）/ `failed`（已挂）/ `progressed`（笔面试中）/ `all` / 具体状态名（如 `面试中`、`笔试挂`）。

### 3.2 写接口

| 方法 | 路径 | 作用 | 必须 |
|---|---|---|---|
| POST | `/api/agent/applications` | 记投递 / 同家再投一个岗（§5.1） | `company` |
| POST | `/api/agent/applications/update` | 同 PATCH 的同义路由（不支持 PATCH 的库用这个） | `company` |
| PATCH | `/api/agent/applications` | 改已有记录的状态/日期/岗位数（§5.2） | `company` |
| DELETE | `/api/agent/applications` | 删录错的条目（§5.3） | `company` + `confirm:true` |
| POST | `/api/agent/jobs` | 新增/改公司岗位条目、内推码、投递链接（§5.4） | `company` |
| POST | `/api/agent/exams` | 登记笔试/面试/测评（§5.5） | `company`+`kind`+`when` |
| DELETE | `/api/agent/exams` | 删考完/作废的场次（§5.6） | `company` + `confirm:true` |
| DELETE | `/api/agent/unapplied` | 从未投递清单排除公司（§6.4） | `company` + `confirm:true` |
| POST | `/api/agent/render` | 只刷新网页（批量写收尾） | — |

### 3.3 已废弃（调用返回 410，别再接）

`POST/GET /api/agent/chat`、`GET /api/agent/history`、`POST /api/agent/abort`、`POST /api/agent/reset`
—— 看板 Agent 对话只在网页侧边栏里用；外部一律走上面两张表的接口。

---

## 4. 读接口字段字典

### 4.1 `applications` 单条

```json
{"company":"国能日新",
 "position":"Agent开发工程师-27届(J10372) + 开发工程师-27届(J10371)",
 "status":"已投递","status_category":"active",
 "date":"2026-10-28","stageDate":"2026-10-28","n":2,
 "industry":"科技","batch":"27届秋招正式批","referral_code":"",
 "apply_link":{"url":"https://…","source":"官方校招系统","note":"…","updated":"2026-10-16"},
 "exams":[{"company":"…","kind":"笔试","when":"2026-10-29 19:00","place":"线上","link":"","note":"…"}]}
```

| 字段 | 说明 |
|---|---|
| `status_category` | 服务端归一化分类：`active` / `failed` / `other`，别自己判 |
| `stageDate` | 「阶段更新」日期：状态一变即盖当天，否则沿用旧值（空则退到投递日） |
| `n` | 岗位数（一行可代表多个岗位） |
| `apply_link` | 可能是**字符串**，也可能是**对象**（`url` + 可选 `source/note/alias/updated`）—— 取值时先判类型 |
| `exams` | 该公司的考试安排数组 |

### 4.2 `unapplied` 单条

```json
{"company":"福建链动星图网络科技有限公司",
 "industry":"上海 浦东 陆家嘴 · 智联招聘","batch":"社招 · 适配度68",
 "date":"2026-10-28","direction":"内容安全治理风控｜资质合规审核",
 "code":"","remark":"待投递","source":"智联招聘","active":"2026-10-28",
 "link":"","apply_link":"https://…"}
```

| 字段 | 说明 |
|---|---|
| `direction` | 岗位方向，**已清洗**：只会有 `内容安全治理风控` / `商家治理` / `业务运营支持` / `待分类`（求职侧；秋招侧是原始岗位方向文本） |
| `title` | **真实岗位名**（求职侧从脏串里拆出来的，如 `阿迪达斯营运助理（上海）`；多岗位用 ` / ` 连接） |
| `raw_direction` | 主表里的原文（排障/审计用；`dirty=false` 时为空） |
| `dirty` | `true` = 主表那一行是拼接/异常形态（多段、混入标签、或没命中方向词表） |
| `code` / `remark` | 内推码 / 备注（公司上限或人工写的「未投原因」） |
| `source` | 岗位来源平台（`BOSS直聘`/`智联招聘`/`前程无忧`/`岗位表`） |
| `active` | 最近在招日期 |
| `apply_link` | 内推链接 json 优先，其次切片里的直链；**可能是字符串，也可能是对象**（`{"url","note","updated"}`），取值先判类型 |

### 4.3 `overview`

`{ok, stats{n_app,n_company,n_pos,active,failed,failed_co,progressed,status_breakdown}, recent_applications[≤8],
exams[], unread_notices_count, unread_notices[], updated, summary_markdown}`

`?format=text` 直接返回 `summary_markdown`（Markdown 纯文本，适合直接转给用户看）。

### 4.4 其它

- `GET /api/agent/company?name=X`：`{ok, company, applications[], job_info, referral_code, apply_link, exams[]}`，
  公司名是**子串匹配**（查「腾讯」也会带出「腾讯音乐」）。
- `GET /api/agent/exams`：`{ok,total,items[{company,kind,when,place,link,note}]}`。
- `GET /api/agent/notices`：`{ok,unread,items[{id,ts,text,source,key,read}]}`，`source` 为 `api`/`qiuzhao`/`qiuzhi` 等。

---

## 5. 写接口详解

### 5.0 通用规则（所有写接口都适用）

- 统一返回：成功 `{"ok": true, …}` + 200；校验失败 `{"ok": false, "error": "…"}` + 400；鉴权 401；未知路由 404。
- 每次写都会：**加文件锁**（与 cron 同步脚本共用）→ 备份 `.backups/api-<时间>.xlsx` → 草稿文件原子替换 → 同步相关工作表
  → 可选重生成网页 → 写一条看板提醒（`source: api`）。
- `render`（默认 `true`）重生成网页，约 2~3s；`notify`（默认 `true`）写不写铃铛提醒。
- 公司名匹配：忽略空格/括号/连字符/大小写（`TP-LINK` == `TPLINK`），并套用仓库别名表（`柠檬趣微`→`柠檬微趣`）。
  命中多家返回 400 + `candidates`，写全名重试。
- `changes` = 改了哪些单元格的人话描述；`warnings` = 「次日 cron 同步会清掉它」的风险提示（命中归档/排除行业时出现）。

### 5.1 `POST /api/agent/applications` 记投递

| 字段 | 必填 | 说明 |
|---|---|---|
| `company` | ✅ | 公司名（`name` 也可） |
| `position` | | 投递岗位，缺省用「招聘岗位」页的岗位方向 |
| `status` | | 不传时：新记录=`已投递`，已有记录=**保持原状态**（再投一个岗不会把 `面试中` 打回 `已投递`） |
| `date` | | `2026-10-28` / `2026.10.28` / `2026/10/28`，默认今天 |
| `stage_date` | | 阶段更新日期，默认按规则（状态变了盖今天） |
| `n` | | 岗位数，默认按岗位文本推断（`+` `/` `→` 计数） |
| `mode` | | `auto`(默认，已有岗位用 `A + B` 追加) / `append` / `replace` |
| `allow_create` | | 「招聘岗位」页没这家时是否新建行（批次记 `外部录入`），默认 `true` |
| `industry`/`batch`/`job_direction` | | 新建行时顺带写入 |
| `render`/`notify` | | 见 5.0 |

```json
{"ok":true,"company":"腾讯","position":"AI应用工程师 + 后台开发","status":"已投递",
 "date":"2026-10-28","n":2,"stage_date":"2026-10-28",
 "record_row":15,"job_row":1420,"job_created":false,"action":"updated",
 "changes":["招聘岗位.投递岗位 AI应用工程师 → AI应用工程师 + 后台开发","投递记录: 更新（第 15 行）"],
 "backup":"…/秋招报告/.backups/api-20261028-013000.xlsx",
 "render":{"ok":true,"seconds":2.0,"tail":"… | 公司 340 / 投递 342 条"}}
```

### 5.2 `PATCH /api/agent/applications` 改已有投递

| 字段 | 说明 |
|---|---|
| `company` | ✅ |
| `position` | 定位用（不传则取该公司唯一那条） |
| `status` | 新状态；一改就自动把「阶段更新」盖今天 |
| `date` / `stage_date` / `n` | 投递日期 / 阶段更新日期 / 岗位数 |
| `allow_create` | `true` 则等价于 POST（不存在就新建），默认 `false` |

- 记录不存在 → 400 `{"ok":false,"error":"投递记录里没有【X】","hint":"…","candidates":[…]}`。
- `position` 匹配不到 → 返回该公司所有记录（`records[]`）供挑选。
- 改状态会同时改「招聘岗位.投递状态」和「内推汇总.投递状态」，否则次日 cron 重建会覆盖回去（接口已代做）。

### 5.3 `DELETE /api/agent/applications` 撤销录错的条目

```bash
curl -s -X DELETE $BASE/api/agent/applications -H 'Content-Type: application/json' \
  -d '{"company":"腾讯","position":"后台开发","confirm":true}'
```

- **必须** `confirm:true`（投递历史只增不减是铁律，防手滑）。
- 只用于撤销**录错**的记录；公司挂了请改状态（`笔试挂`/`终止`），不要删。
- API 自动建的「外部录入」岗位行会一并删；原有岗位行只清空投递列（状态/岗位/时间）。

### 5.4 `POST /api/agent/jobs` 新增/修改公司岗位条目

| 字段 | 说明 |
|---|---|
| `company` | ✅ |
| `industry`/`batch`/`direction`/`date` | 行业/批次/岗位方向/更新日期 |
| `status` | 投递状态；**给了就同步投递记录 + 内推汇总**（等价于改状态） |
| `applied`/`applied_at` | 投递岗位/投递时间 |
| `referral_code` | 内推码 → 写「内推汇总」（没这家就新建） |
| `apply_link` | 投递链接 → 写内推链接 json（看板公司名旁「去投递 ↗」） |
| `create` | 公司不在岗位表时是否新建，默认 `true` |

> 只改状态请用 5.2 的 PATCH，语义更准（不碰岗位信息）。

### 5.5 `POST /api/agent/exams` 登记笔试/面试/测评

```json
{"company":"腾讯","kind":"面试","when":"2026-11-02 15:00",
 "place":"线上腾讯会议","link":"https://meeting.example.com/x",
 "note":"必答项：摄像头/麦克风","status":"面试通知"}
```

| 字段 | 说明 |
|---|---|
| `company` | ✅ |
| `kind` | ✅ `笔试`/`面试`/`测评`/`AI面` 等 |
| `when` | ✅ `2026-11-02 15:00`、`预计2026-10-31（以链接为准）` 都行 |
| `place`/`link`/`note` | 平台地点/考场链接/备注（**不写密码、通行证号**） |
| `status` | 同时把投递状态改成该值（`笔试通知`/`面试通知`），并盖阶段更新 |

幂等键 = 公司 + 类型 + 时间：重复提交只更新 `place/link/note`，不会插两行。

### 5.6 `DELETE /api/agent/exams` 删已考完/作废的场次

`kind`/`when` 省略则删该公司**全部**场次。**必须** `confirm:true`。
看板只保留「未完成」的场次；考完/挂了的历史以投递记录状态为准。

### 5.7 `POST /api/agent/render` 只刷新网页

```json
{"ok":true,"render":{"ok":true,"seconds":2.0,"tail":"… | 公司 340 / 投递 342 条","stderr":null}}
```

会先重算该看板的未投递切片，再生成 HTML（两套看板各自只碰自己的目录）。

### 5.8 `DELETE /api/agent/unapplied` 从未投递清单移除公司

见 §6.4（这是「未投递」专属写接口，不影响投递记录）。

---

## 6. 未投递清单专题（2026-10-28 重构后）

### 6.1 数据流：主表是唯一真源，切片是派生缓存

```
主表（秋招/求职情报.xlsx）
├── 招聘岗位   ── 未投递候选
├── 投递记录   ── 已投递公司（交叉核对，防漏标）
├── 规则配置   ── 排除公司/行业/批次、公司上限、过期截止
├── 已结束招聘 ── 归档封锁 + 用户判定「不投递」
└── 内推汇总   ── 内推码
        │
        ├─ tools/unapplied_gen.py compute()  ← 读取层每次都调（内存现算，改规则立即生效）
        └─ build() → 未投递岗位_YYYYMMDD.xlsx（派生切片：网页导出 / 人工翻表用）
```

含义：
- `GET /api/agent/unapplied` 的结果**不依赖切片是否重生成**；改「规则配置」后下一次请求就是新结果。
- 切片由 `tools/unapplied_gen.py` 生成，`qiuzhao_html.py` / `qiuzhi_html.py` 渲染前都会先重算（内容没变就不重写）。
- 想让外部 Excel 也拿到最新清单：`POST /api/agent/render`，或直接
  `python3 tools/unapplied_gen.py --board qiuzhao|qiuzhi`。

### 6.2 收录 / 排除规则（顺序即优先级）

1. **状态**：招聘岗位「投递状态」为空，或含 `待投递`/`未投递`/`待办`/`待沟通`/`未沟通` → 候选；
   含 `已投递`/`测评`/`笔试`/`AI面`/`面试`/`offer`/`录用`/`挂`/`淘汰`/`不合适`/`终止`/`无匹配`/`不投递`/`评估`/`放弃` → 一律排除。
   **其它未知状态也排除**（宁可漏列，不把已处理的列回来）。
2. 规则配置 `未投递清单排除行业`（等于本行行业）→ 排除。
3. 规则配置 `排除批次`（批次含关键词，如各种人才计划）→ 排除。
4. 规则配置 `未投递清单排除公司`（归一化全等，`、，,/` 分隔）→ 排除。
5. 「已结束招聘」里判定不可投（备注含 `不投递`/`无合适岗位`/`不符合`/`无匹配`）或该 (公司, 批次) 已归档 → 排除。
6. 规则配置 `过期未投递截止`（更新日期早于截止，且不在 `过期豁免`）→ 排除。
7. 与「投递记录」冲突（该公司已有投递）→ 排除；**例外**：批次或方向含 `顶尖人才计划`/`前程无忧`/`51job`/`待办`
   的多通道岗位照旧列出（不算占用同一次数）。
- `公司上限` 写进切片的「公司上限/备注」列；已有切片里人工写的备注（如 `未投原因：触发验证码`）会**继承**过来。

### 6.3 两套看板严格隔离（谁都不会写对方）

- 生成器只有一份 `tools/unapplied_gen.py`，配置只从 `qiuzhao_write.BOARDS[board]` 解析，`--board` 决定读写谁。
- 三道校验：① 生成器拒绝把产物写进**别的看板目录**（抛 `ValueError`）；
  ② 写层 `_regen_unapplied()` 再校验生成器回报的 `out` 是否在本看板目录；
  ③ 单元自测 `python3 tools/unapplied_selftest.py` 用目录 mtime 快照证明「A 重生成不碰 B」。
- 提醒、备份、锁文件、内推链接 json 全部按 board 各自一套。

### 6.4 `DELETE /api/agent/unapplied` 排除公司

把公司追加进**本看板**「规则配置 → 未投递清单排除公司」，再重生成该看板目录下的切片。
两套看板**都会返回 `regen: true`**。

| 字段 | 必填 | 说明 |
|---|---|---|
| `company` | ✅ | 必须与「招聘岗位」页写法一致（归一化**全等**，子串不算） |
| `confirm` | ✅ | 必须 `true` |
| `render`/`notify` | | 见 5.0 |

```json
{"ok":true,"company":"某公司","action":"excluded","regen":true,
 "regen_info":{"ok":true,"board":"qiuzhao","out":"…/秋招报告/未投递岗位_20261028.xlsx",
               "count":59,"changed":true},
 "backup":"…/秋招报告/.backups/api-20261028-221356.xlsx",
 "render":{"ok":true,"seconds":2.0,"tail":"…"}}
```

- **幂等**：已排除过 → `{"ok":true,"action":"already_excluded","message":"【某公司】已在排除列表中"}`（仍 200）。
- **只影响未投递视图**：投递记录、招聘岗位、内推码、内推链接一律不动。想标记「挂了/不投了」请用 5.2 改 `status`。
- `regen` 只是「切片文件有没有刷新」；即使为 `false`（例如生成器超时），读取层现算也会立刻生效，重试即可。
- 判重范围 = 全部同名「未投递清单排除公司」行的并集（历史追加形成多行），但只追加到第一行。
- 反向操作：从「规则配置」里手工删掉该条目（本接口没有恢复端点）。
- 只想临时看「含已投递公司的池子」：`GET /api/agent/unapplied?exclude_applied=false`
  （**规则配置的排除照旧生效**；只放行「状态是待投递但该公司另有一个岗已投」的行，实测求职侧 110 → 115）。

### 6.5 求职侧「岗位方向」脏数据（2026-10-28）

求职看板的 `招聘岗位.岗位方向` 这一列被外部爬虫写成了拼接串（`标签；方向｜岗位名`），
例如 `Power BI；业务运营支持｜阿迪达斯营运助理（上海）`、`内容安全治理风控｜仓储运营`。
爬虫还把「判不出方向」的情况兜底成 `内容安全治理风控`，导致按方向筛选完全不可用。

**看板侧的处理（读的时候就拆干净，不改主表）**——实现在 `tools/position_text.py`：

| 做法 | 说明 |
|---|---|
| 按 `；` 分段、段内按 `｜` 切 | 左边=方向候选，右边=岗位名候选；多段表示多个岗位 |
| 丢标签 | 纯英文（`Power BI`）、学历（`中专/中技`）、时间福利（`双休/早九晚五`）、`(待确认)` 占位、`文本类` 分类词 |
| 方向判定 | ① 最后一段的方向若在可信词表（`业务运营支持`/`商家治理`）→ 采用；② 否则按岗位名关键词分类；③ 还判不出 → **`待分类`**（`内容安全治理风控` 只在这行没有任何岗位名时才沿用） |
| 不改主表 | 读取层/切片/网页都干净；存量数据回修要显式跑 `tools/position_clean.py --apply` |

注意两个坑（已处理）：
- **先剥括号再判分隔符**：`风控审核专员（年终奖+过节费）` 里的 `+` 不能当拼接符用（括号内的分隔符一律忽略）；
- **`?direction=` 同时匹配方向与 `title`**，所以搜 `仓储运营` 也能命中，不是只能搜词表值。

相关工具：`python3 tools/position_clean.py [--board qiuzhi] [--apply]`（干跑报告 → `--apply` 才写回，
写回走写层的锁 + 备份 + 原子替换，并把值改成 `方向｜岗位名`）。自测：
`python3 tools/unapplied_selftest.py` 第 0 节；秋招侧（`:8898`）没有词表配置，方向原样保留、不受影响。

---

## 7. 数据语义与铁律

1. **Excel 是唯一真源**。`投递状态/投递岗位/投递时间` 记在「招聘岗位」页；「投递记录」页由 cron 每天从它重建。
   所以改状态必须同时落到两处 —— 写接口已经代做，**别自己 openpyxl 改**（绕开锁/备份/刷新，次日被覆盖）。
2. **投递历史只增不减**。重建时全部保留，公司被排除/改名/下架都不丢；撤销只能走 5.3（`confirm:true`）。
3. **阶段更新**：状态一变 → 盖今天；否则保留旧值（旧值为空退到投递日）。
4. **岗位数**：一行可代表多个岗位，`+`/`/`/`→` 分隔计数（`C++` 不算分隔），显式 `N/N` 标记优先。
5. **提前批/顶尖人才计划**：投递记录里的岗位文本会自动带 `（27届秋招提前批）` 之类后缀，用于区分同公司多批次。
6. **状态词表**（照抄，别自创）：
   - 在流程：`已投递` `测评通知` `测评完成` `笔试通知` `笔试完成` `AI面完成` `面试通知` `约一面` `面试中` `offer`
   - 已挂：`简历挂` `笔试挂` `测评挂` `一面挂` `二面挂` `面试挂` `已淘汰` `不合适` `终止` `挂`
   - 「在流程/已挂」按**公司**统计：一家多个志愿，只要有一个没挂就算在流程。
7. **归档与规则**：`已结束招聘` 的 (公司,批次) 同步时会被移除；`规则配置` 的排除行业/公司、公司上限同样生效。
   写接口遇到这类公司会返回 `warnings`（意思是今晚 cron 可能清掉，要长期保留先去改表）。
8. **备份与并发**：每次写留 `.backups/api-<时间>.xlsx`（滚动 30 份），cron 另有每日快照（最多 14 天）；
   写操作与 cron 共用 `.xlsx.lock`，串行，等锁上限 30s，单次写约 0.3s（不含 render）。

---

## 8. 四种调用方式（挑一个）

### 8.1 curl
见 §2 / §5 / §9。

### 8.2 Python SDK（仓库内，零依赖）

```python
from tools.qiuzhao_agent_api import QiuzhaoAgentClient

c = QiuzhaoAgentClient()                                         # 默认秋招 8898
# c = QiuzhaoAgentClient(base_url="http://47.116.208.4:28898")   # 求职看板

c.get_overview()["summary_markdown"]
c.get_applications(status="active", company="腾讯")
c.get_company("顺丰科技")
c.get_unapplied(direction="后端", limit=20, exclude_applied=True)
c.record_application("腾讯", "后台开发", status="已投递")
c.update_application("腾讯", position="后台开发", status="面试中")
c.upsert_job("腾讯", referral_code="ABC123", apply_link="https://example.com/apply")
c.add_exam("腾讯", "面试", "2026-11-02 15:00", place="线上", status="面试通知")
c.delete_exam("腾讯", kind="面试", confirm=True)
c.remove_application("腾讯", position="录错的岗位", confirm=True)
c.remove_unapplied("某公司", confirm=True)
```

Token 自动取 `QIUZHAO_AUTH_KEY` / `QIUZHAO_API_TOKEN` 环境变量或 `data/.web_token`；
`QIUZHAO_API_URL` 可改默认 base URL。HTTP 不通时**只读接口**会自动回退到读本地 Excel。

### 8.3 CLI（走 HTTP）

```bash
python3 tools/qiuzhao_agent_api.py overview --text
python3 tools/qiuzhao_agent_api.py apps --status active -n 20
python3 tools/qiuzhao_agent_api.py company 腾讯
python3 tools/qiuzhao_agent_api.py unapplied --direction 后端 -n 15
python3 tools/qiuzhao_agent_api.py exams / notices / tools
python3 tools/qiuzhao_agent_api.py record 腾讯 后台开发 --status 已投递 --date 2026-10-28
python3 tools/qiuzhao_agent_api.py update 腾讯 --position 后台开发 --status 面试中
python3 tools/qiuzhao_agent_api.py job 腾讯 --referral-code ABC123 --apply-link https://…
python3 tools/qiuzhao_agent_api.py exam 腾讯 面试 "2026-11-02 15:00" --place 线上 --status 面试通知
python3 tools/qiuzhao_agent_api.py exclude-unapplied 某公司 --yes
python3 tools/qiuzhao_agent_api.py --url http://47.116.208.4:28898 apps      # 求职看板
```

### 8.4 仓库内直写（无 HTTP，仅本机脚本）

```bash
python3 tools/qiuzhao_write.py record 腾讯 "后台开发" --status 已投递
python3 tools/qiuzhao_write.py update 腾讯 --position 后台开发 --status 面试中
python3 tools/qiuzhao_write.py job 腾讯 --referral-code ABC123
python3 tools/qiuzhao_write.py exam 腾讯 面试 "2026-11-02 15:00" --place 线上
python3 tools/qiuzhao_write.py remove 腾讯 --position 后台开发 --yes
python3 tools/qiuzhao_write.py exclude-unapplied 某公司 --yes
python3 tools/qiuzhao_write.py --board qiuzhi record 某公司 "某岗位"      # 求职看板
python3 tools/unapplied_gen.py --board qiuzhi                           # 只重生成未投递切片
```

`--board qiuzhao|qiuzhi` 决定操作哪套数据；`--no-render` 跳过网页重生成。

### 8.5 function-calling 工具（`GET /api/agent/info` 里就是这些）

| 工具名（前缀随看板） | 等价接口 |
|---|---|
| `qiuzhao_get_overview` / `qiuzhi_get_overview` | `GET /overview` |
| `qiuzhao_get_applications` / `qiuzhi_get_applications` | `GET /applications` |
| `qiuzhao_get_company` / `qiuzhi_get_company` | `GET /company` |
| `qiuzhao_get_unapplied` / `qiuzhi_get_unapplied` | `GET /unapplied` |
| `qiuzhao_record_application` / `qiuzhi_record_application` | `POST /applications` |
| `qiuzhao_update_application` / `qiuzhi_update_application` | `PATCH /applications` |
| `qiuzhao_update_job` / `qiuzhi_update_job` | `POST /jobs` |
| `qiuzhao_add_exam` / `qiuzhi_add_exam` | `POST /exams` |

---

## 9. 常见任务配方

**① 用户说「我投了 X 公司的 Y 岗」**
```bash
curl -s -X POST $BASE/api/agent/applications -H 'Content-Type: application/json' \
  -d '{"company":"X","position":"Y","status":"已投递"}'
```

**② 约面 / 收到面试通知（顺带登记日程）**
```bash
curl -s -X POST $BASE/api/agent/exams -H 'Content-Type: application/json' \
  -d '{"company":"X","kind":"面试","when":"2026-11-02 15:00","place":"线上","status":"面试通知"}'
```

**③ 笔试挂 / 已淘汰**
```bash
curl -s -X PATCH $BASE/api/agent/applications -H 'Content-Type: application/json' \
  -d '{"company":"X","position":"Y","status":"笔试挂"}'
```

**④ 面试考完，删掉日程里的场次**
```bash
curl -s -X DELETE $BASE/api/agent/exams -H 'Content-Type: application/json' \
  -d '{"company":"X","kind":"面试","confirm":true}'
```

**⑤ 用户给了内推码 / 内推链接**
```bash
curl -s -X POST $BASE/api/agent/jobs -H 'Content-Type: application/json' \
  -d '{"company":"X","referral_code":"ABC123","apply_link":"https://…"}'
```

**⑥ 批量导入 N 家（先不渲染，最后刷一次）**
```python
import json
from tools.qiuzhao_agent_api import QiuzhaoAgentClient

c = QiuzhaoAgentClient()
ok = bad = 0
for r in json.load(open("batch.json")):        # [{"company":"X","position":"Y"}, …]
    res = c.record_application(r["company"], r.get("position"),
                               status=r.get("status"), date=r.get("date"),
                               render=False, notify=False)
    ok, bad = (ok + 1, bad) if res.get("ok") else (ok, bad + 1)
    if not res.get("ok"):
        print("失败:", r, res.get("error"))
c._request("POST", "/api/agent/render", data={})
print(f"成功 {ok} / 失败 {bad}")
```

**⑦ 汇报进度（只读）**
```bash
curl -s "$BASE/api/agent/overview?format=text"
curl -s "$BASE/api/agent/applications?status=active&limit=10"
curl -s "$BASE/api/agent/exams"
```

**⑧ 录错了要撤销**
```bash
curl -s -X DELETE $BASE/api/agent/applications -H 'Content-Type: application/json' \
  -d '{"company":"X","position":"Y","confirm":true}'
```

**⑨ 这家以后别出现在「未投递」清单里**
```bash
curl -s -X DELETE $BASE/api/agent/unapplied -H 'Content-Type: application/json' \
  -d '{"company":"X","confirm":true}'
# 已排除过 → {"ok":true,"action":"already_excluded"}，重复跑安全
```

**⑩ 看看现在还有什么没投（含投递入口）**
```bash
curl -s "$BASE/api/agent/unapplied?limit=20" | python3 -c "
import json,sys
for i in json.load(sys.stdin)['items']:
    a = i.get('apply_link') or i.get('link') or ''
    url = a.get('url') if isinstance(a, dict) else a      # apply_link 可能是对象
    print(i['company'], '|', i['direction'], '|', url or '(无链接)')"
```

---

## 10. 错误码与排查

| HTTP | 返回 | 原因 / 处理 |
|---|---|---|
| 200 | `{"ok":true,…}` | 成功；看 `changes` / `warnings` |
| 400 | `{"ok":false,"error":"company 不能为空"}` | 缺必填字段 |
| 400 | `{"ok":false,"error":"公司名【中国】匹配到多家：…"}` | 名称太短/歧义 → 写全名，或读 `candidates` |
| 400 | `{"ok":false,"error":"投递记录里没有【X】","hint":"…"}` | PATCH 找不到记录 → 改用 POST，或加 `allow_create:true` |
| 400 | `{"ok":false,"error":"删除投递条目需要 confirm=true…"}` | 删除类接口必须 `confirm:true`（applications / exams / unapplied 同理） |
| 401 | `{"error":"unauthorized"}` | 服务开了鉴权 → 带 `X-QZ-Token` 或 `Authorization: Bearer` |
| 404 | `{"ok":false,"error":"未找到公司【X】的相关信息"}` | 公司名写错，或该公司完全没有档案 |
| 404 | `{"error":"not found"}` | 路径/方法不对（PATCH 只用于 `/applications`、`/jobs`） |
| 410 | `{"ok":false,"error":"此接口已禁用…"}` | 用了废弃的 `/api/agent/chat`、`/history`、`/abort`、`/reset` |
| 500 | `{"ok":false,"render":{…}}` | 看板重生成失败（数据一般已写入）→ 稍后 `POST /api/agent/render` 重试 |
| — | 连接失败 | 秋招只绑 Tailscale（先连 tailnet）；求职是公网端口，确认安全组放行 28898 |

写失败不会半改：备份在 `.backups/api-*.xlsx`，必要时回滚。

---

## 11. 变更记录

- **1.4.0（2026-10-28）未投递「岗位方向」清洗（求职侧）**
  - `GET /api/agent/unapplied` 的 `direction` 改为清洗后的值（词表 3 项 + `待分类`），新增 `title`（真实岗位名）、
    `raw_direction`（原文）、`dirty`（脏数据标记）；`?direction=` 同时匹配方向与岗位名。
  - 拆分逻辑见 `tools/position_text.py`（纯函数、可单测），切片「岗位方向」列写成 `方向｜岗位名`；
    存量数据回修工具 `tools/position_clean.py`（默认干跑）。秋招侧无词表 → 行为完全不变。
- **1.3.0（2026-10-28）未投递清单重构 + 手册整合**
  - 未投递清单改「主表现算」：`GET /api/agent/unapplied` 直接按主表「招聘岗位」+「规则配置」+「投递记录」现算，
    改规则**立即生效**；新增 `exclude_applied`（默认 true）可关掉「已投递公司过滤」。
  - 两套看板共用 `tools/unapplied_gen.py`（`BOARDS` 两侧都接上，`DELETE /api/agent/unapplied` 恒返回真实 `regen`），
    切片降级为派生缓存；`POST /api/agent/render` 会顺带重算切片。目录级隔离 + `tools/unapplied_selftest.py` 自测。
  - `/api/agent/info` 移除已禁用的 `*_chat` 工具定义，`unapplied` 补 `exclude_applied`/`offset` 说明；
    本文合并了原 `docs/AGENT_API.md`（秋招）与 `docs/AGENT_API_求职看板.md`（求职）两套手册。
- **1.2.0（2026-10-28）** 新增 `DELETE /api/agent/unapplied`（幂等，`already_excluded`）。
- **1.1.0（2026-10-28）** 新增写接口：`applications` POST/PATCH/DELETE、`jobs`、`exams` POST/DELETE、`render`；
  两套看板共用写层 `tools/qiuzhao_write.py` + 4 个 function-calling 工具。
- **2026-09 / 10** 读接口上线；`/api/agent/chat` 于 2026-10 起禁用（410），对话回到网页侧边栏。

