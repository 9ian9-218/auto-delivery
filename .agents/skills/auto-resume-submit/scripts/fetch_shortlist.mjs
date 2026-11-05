#!/usr/bin/env node
// 从秋招指挥中心页面提取内嵌 DATA，筛选出适合 AI Agent / AI 应用开发方向的未投递公司清单。
// 用法:
//   node fetch_shortlist.mjs                    # 默认输出前 20 家（JSON）
//   node fetch_shortlist.mjs --top 10 --md      # markdown 表格
//   node fetch_shortlist.mjs --all              # 含 B 档（纯软件研发，非 AI）
//   node fetch_shortlist.mjs --file page.html   # 用已下载的页面离线解析
//   node fetch_shortlist.mjs --url http://...   # 覆盖 dashboard 地址
//   node fetch_shortlist.mjs --out shortlist.json

import fs from "node:fs";

const DEFAULT_URL = "http://100.73.185.103:8898";
// 项目铁律：本项目只允许 8898 端口秋招看板，严禁 28898 求职看板
if ((process.env.QIUZHAO_URL || "").includes("28898")) {
  console.error("【项目铁律拦截】本项目下仅允许访问 8898 端口看板，严禁访问 28898 端口！");
  process.exit(1);
}

function parseArgs(argv) {
  const a = { top: 20, md: false, all: false, includeStale: false };
  for (let i = 2; i < argv.length; i++) {
    const k = argv[i];
    if (k === "--top") a.top = parseInt(argv[++i], 10) || 20;
    else if (k === "--md") a.md = true;
    else if (k === "--all") a.all = true;
    else if (k === "--include-stale") a.includeStale = true;
    else if (k === "--url") a.url = argv[++i];
    else if (k === "--file") a.file = argv[++i];
    else if (k === "--out") a.out = argv[++i];
  }
  return a;
}

// 从 HTML 里抽出 `const DATA = {...}`：字符串感知的花括号配对，避免模板字符串/正则里的花括号干扰
function extractData(html) {
  const marker = "const DATA";
  const i = html.indexOf(marker);
  if (i < 0) throw new Error("页面里找不到 const DATA（dashboard 结构可能变了）");
  let j = html.indexOf("=", i) + 1;
  while (/\s/.test(html[j])) j++;
  if (html[j] !== "{") throw new Error("const DATA 后面不是对象字面量");
  let depth = 0, inStr = null, end = -1;
  for (let k = j; k < html.length; k++) {
    const c = html[k];
    if (inStr) {
      if (c === "\\") k++;
      else if (c === inStr) inStr = null;
    } else if (c === '"' || c === "'" || c === "`") inStr = c;
    else if (c === "{") depth++;
    else if (c === "}") { depth--; if (depth === 0) { end = k + 1; break; } }
  }
  if (end < 0) throw new Error("const DATA 对象没有闭合");
  return JSON.parse(html.slice(j, end));
}

const STRONG_RE = /agent|智能体|AI应用|大模型|LLM|AIGC|生成式|AI开发|AI全栈|AI研发/i;
const MEDIUM_RE = /\bai\b|AI技术|AI产品|人工智能|算法|NLP/i;
const GENERIC_RE = /软件|研发|开发|后端|全栈|服务端|Java|Golang|C\+\+/i;

function tierOf(direction, industry) {
  const s = `${direction || ""} ${industry || ""}`;
  if (STRONG_RE.test(s)) return "S";
  if (MEDIUM_RE.test(s)) return "A";
  if (GENERIC_RE.test(s)) return "B";
  return null;
}

function parseCnDate(s) {
  // "2026.09.30" / "2026-09-30" / "2026/09/30"
  const m = /(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})/.exec(s || "");
  if (!m) return null;
  return new Date(+m[1], +m[2] - 1, +m[3]);
}

function daysBetween(a, b) {
  return Math.round((a - b) / 86400000);
}

async function main() {
  const a = parseArgs(process.argv);
  let html;
  if (a.file) html = fs.readFileSync(a.file, "utf8");
  else {
    const url = a.url || process.env.QIUZHAO_URL || DEFAULT_URL;
    // 项目铁律：只允许 8898 端口秋招看板，严禁 28898 求职看板
    if (String(url).includes("28898")) {
      console.error("【项目铁律拦截】本项目下仅允许访问 8898 端口看板，严禁访问 28898 端口！");
      process.exit(1);
    }
    const res = await fetch(url, { signal: AbortSignal.timeout(20000) });
    if (!res.ok) throw new Error(`dashboard 返回 HTTP ${res.status}`);
    html = await res.text();
  }
  const data = extractData(html);

  const dashToday = data.today || new Date().toISOString().slice(0, 10);
  const today = parseCnDate(dashToday) || new Date();

  // 排除规则：rules 形如 ["排除行业","教培","…"] / ["排除公司","德勤","…"]
  const exIndustries = [], exCompanies = [];
  for (const r of data.rules || []) {
    if (r[0] === "排除行业") exIndustries.push(r[1]);
    else if (r[0] === "排除公司") exCompanies.push(r[1]);
  }

  // 已投递公司（apps 里出现过的公司一律不重复投）
  const appliedCompanies = new Set((data.apps || []).map(x => x.company));
  // 已结束批次的公司
  const endedCompanies = new Set((data.ended || []).map(x => Array.isArray(x) ? x[0] : x.company));

  const links = data.links || {};
  const staleDays = 14;
  const stats = { total: 0, excludedIndustry: 0, excludedCompany: 0, applied: 0, ended: 0, noTier: 0, stale: 0 };
  const picked = [];

  for (const u of data.unapplied || []) {
    stats.total++;
    if (appliedCompanies.has(u.company)) { stats.applied++; continue; }
    if (endedCompanies.has(u.company)) { stats.ended++; continue; }
    if (exIndustries.some(x => (u.industry || "").includes(x))) { stats.excludedIndustry++; continue; }
    if (exCompanies.some(x => u.company.includes(x))) { stats.excludedCompany++; continue; }
    const tier = tierOf(u.direction, u.industry);
    if (!tier) { stats.noTier++; continue; }
    if (tier === "B" && !a.all) { stats.noTier++; continue; }

    const d = parseCnDate(u.date);
    const age = d ? daysBetween(today, d) : null;
    const stale = age !== null && age > staleDays;
    if (stale) stats.stale++;
    if (stale && !a.includeStale && tier !== "S") continue;

    const ref = links[u.company] || null;
    picked.push({
      tier,
      company: u.company,
      industry: u.industry || "",
      batch: u.batch || "",
      date: u.date || "",
      stale,
      direction: u.direction || "",
      referral: ref ? { url: ref.url, code: ref.code || "", note: ref.note || "" } : null,
    });
  }

  const rank = { S: 0, A: 1, B: 2 };
  picked.sort((x, y) =>
    (rank[x.tier] - rank[y.tier]) || (Number(x.stale) - Number(y.stale)) || y.direction.length - x.direction.length
  );
  const shortlist = picked.slice(0, a.top);

  const meta = {
    fetched_at: new Date().toISOString(),
    dashboard_url: a.url || process.env.QIUZHAO_URL || DEFAULT_URL,
    dashboard_updated: data.updated || "",
    dashboard_today: dashToday,
    total_unapplied: stats.total,
    matched: picked.length,
    shown: shortlist.length,
    stats,
    note: "date 字段是清单采集/更新日期，非截止日期；stale=true 表示超过 14 天未更新，投递前需在官网核实是否仍在招",
  };

  const result = { meta, shortlist };

  const out =
    a.md
      ? renderMd(result)
      : JSON.stringify(result, null, 1);

  if (a.out) {
    fs.writeFileSync(a.out, out, "utf8");
    console.error(`已写出 ${a.out}`);
  } else {
    console.log(out);
  }
}

function renderMd({ meta, shortlist }) {
  const lines = [];
  lines.push(`## 未投递公司清单（AI Agent / AI 应用方向）`);
  lines.push(`dashboard 更新: ${meta.dashboard_updated} · 未投递共 ${meta.total_unapplied} 家，匹配 ${meta.matched} 家，展示 ${meta.shown} 家`);
  lines.push(`注: ${meta.note}`);
  lines.push("");
  lines.push(`| # | 档 | 公司 | 行业 | 批次 | 方向 | 内推 | 采集日期 |`);
  lines.push(`|---|---|------|------|------|------|------|----------|`);
  shortlist.forEach((c, i) => {
    lines.push(`| ${i + 1} | ${c.tier}${c.stale ? "⚠️过期?" : ""} | ${c.company} | ${c.industry} | ${c.batch} | ${c.direction.slice(0, 50)} | ${c.referral ? "有" : ""} | ${c.date} |`);
  });
  return lines.join("\n");
}

main().catch(e => { console.error("FAILED:", e.message); process.exit(1); });
