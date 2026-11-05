#!/usr/bin/env node
// notify_dashboard.mjs — 看板结果回写（已升级为直写 REST API，无需看板助手）
//
// 用法:
//   node notify_dashboard.mjs --company 腾讯 --position 后台开发 [--status 已投递] [--date 2026-10-28] [--link https://...]
//   node notify_dashboard.mjs "公司=腾讯；岗位=后台开发；方式=官网直投；投递日期=2026-10-28"
//   node notify_dashboard.mjs "公司=腾讯；岗位=后台开发；投递日期=2026-10-28"（可解析出公司才直写）

const DEFAULT_URL = "http://100.73.185.103:8898";
const base = process.env.QIUZHAO_URL || DEFAULT_URL;
if (base.includes("28898")) {
  console.error("【项目铁律拦截】本项目下仅允许访问 8898 端口看板，严禁访问 28898 端口！");
  process.exit(1);
}
const token = process.env.QIUZHAO_TOKEN || process.env.QIUZHAO_AUTH_KEY || "";

const args = process.argv.slice(2);
if (args.length === 0) {
  console.error("用法: node notify_dashboard.mjs --company <公司> --position <岗位> [...] 或传入自然语言字符串");
  process.exit(1);
}

const headers = {
  "Content-Type": "application/json; charset=utf-8",
  "Accept": "application/json",
  ...(token ? { "X-QZ-Token": token, "Authorization": `Bearer ${token}` } : {})
};

// 解析 CLI 参数
let company = "";
let position = "";
let status = "已投递";
let date = "";
let link = "";
let rawText = "";

for (let i = 0; i < args.length; i++) {
  if (args[i] === "--company" && i + 1 < args.length) company = args[++i];
  else if (args[i] === "--position" && i + 1 < args.length) position = args[++i];
  else if (args[i] === "--status" && i + 1 < args.length) status = args[++i];
  else if (args[i] === "--date" && i + 1 < args.length) date = args[++i];
  else if (args[i] === "--link" && i + 1 < args.length) link = args[++i];
  else rawText += (rawText ? " " : "") + args[i];
}

// 如果未传 --company，尝试从文本中解析 "公司=xxx；岗位=yyy" 或 "公司=xxx;岗位=yyy"
if (!company && rawText) {
  const mComp = rawText.match(/公司\s*[:=]\s*([^\s；;]+)/);
  const mPos = rawText.match(/岗位\s*[:=]\s*([^\s；;]+)/);
  const mDate = rawText.match(/(?:投递日期|日期)\s*[:=]\s*([^\s；;]+)/);
  const mLink = rawText.match(/(?:快速查看链接|链接|URL)\s*[:=]\s*([^\s；;]+)/i);
  if (mComp) company = mComp[1].trim();
  if (mPos) position = mPos[1].trim();
  if (mDate) date = mDate[1].trim();
  if (mLink && mLink[1] !== "无") link = mLink[1].trim();
}

async function recordDirect() {
  const payload = {
    company,
    position: position || undefined,
    status,
    date: date || undefined,
    render: true,
    notify: true
  };
  const res = await fetch(`${base}/api/agent/applications`, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(15000)
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) {
    throw new Error(data.error || `HTTP ${res.status}`);
  }
  if (link) {
    try {
      await fetch(`${base}/api/agent/jobs`, {
        method: "POST",
        headers,
        body: JSON.stringify({ company, apply_link: link, render: false, notify: false }),
        signal: AbortSignal.timeout(10000)
      });
    } catch (_) {}
  }
  return data;
}

try {
  if (company) {
    const res = await recordDirect();
    console.log(`[ok] 看板直写成功：${company} - ${position || "岗位"}（${status}）`);
    if (res.changes && res.changes.length > 0) {
      console.log("变更明细:", res.changes.join("；"));
    }
  } else {
    // chat 端点已 410 废弃，无法再降级对话；解析不出公司就如实失败
    console.error("未能从输入解析出公司（--company）。/api/agent/chat 已 410 废弃，无对话降级。");
    console.error("请显式传 --company <公司> --position <岗位> [--status --date --link] 重试。");
    if (rawText) console.error("原始输入:", rawText);
    process.exit(1);
  }
} catch (e) {
  console.error("NOTIFY_FAILED:", e.message, "— 请稍后重试或手动更新看板");
  process.exit(2);
}
