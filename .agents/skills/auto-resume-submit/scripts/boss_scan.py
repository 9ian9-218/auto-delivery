# -*- coding: utf-8 -*-
"""boss_scan.py — BOSS 直聘秋招岗位扫描（只留 2027 届/实习，剔除社招）

为什么不直接调 API？
  BOSS 的 `wapi/zpgeek/search/joblist.json` 连续请求会返回 **code:37（风控）**，
  冷却时间很长。走 UI 页面 DOM 更稳，等价于真人浏览。

用法:
  python boss_scan.py --query "AI Agent" --max 30
  python boss_scan.py --query "大模型" --city "上海" --degree 硕士
  python boss_scan.py --list-only          # 只看已抓到的数据

判据（秋招硬约束）：
  `jobExperience` 字段必须含 在校/应届/实习/学生/毕业 之一，
  其余（1-3年/3-5年/5-10年/经验不限）一律视为社招丢弃。
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
WORK = Path(__file__).resolve().parent.parent / "work"
WORK.mkdir(exist_ok=True)

CAMPUS_KEYS = ("在校", "应届", "实习", "学生", "毕业")
SOCIAL_RE = re.compile(r"\d+-\d+年|\d+年以上")
OUT = WORK / "boss_jobs.json"


def load_saved():
    if OUT.exists():
        return json.loads(OUT.read_text(encoding="utf-8"))
    return []


def save(items):
    OUT.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


def is_campus(job) -> bool:
    """BOSS 的 jobExperience 形如「在校/应届」「3-5年」「经验不限」。"""
    exp = (job.get("e") or "").strip()
    if SOCIAL_RE.search(exp):
        return False
    return any(k in exp for k in CAMPUS_KEYS)


def scan(query: str, city: str = "", degree: str = "", limit_pages: int = 1,
         page_size: int = 50, sleep: float = 3.0):
    from DrissionPage import ChromiumPage
    p = ChromiumPage("127.0.0.1:9222")
    tabs = [t for t in p.get_tabs() if "zhipin.com" in (t.url or "")]
    if not tabs:
        raise SystemExit("未找到 BOSS 标签页，请先打开 https://www.zhipin.com/web/geek/jobs")
    t = tabs[-1]
    t.set.load_mode.eager()

    from urllib.parse import quote
    url = f"https://www.zhipin.com/web/geek/jobs?query={quote(query)}"
    if city:
        url += f"&city={quote(city)}"
    if degree:
        url += f"&degree={quote(degree)}"
    print(f"[打开] {url}")
    t.get(url)
    time.sleep(8)

    js = """return [].slice.call(document.querySelectorAll('ul li, .job-card-wrapper, [class*=job-card]'))
  .map(function(e){
      var tx=(e.textContent||'').trim().replace(/\\s+/g,' ');
      if(tx.length<40||tx.length>400) return null;
      var a=e.querySelector('a[href*="job_detail"]');
      var m=tx.match(/([\\d]+-[\\d]+K·[\\d]+薪|[\\d]+-[\\d]+元\\/天)/);
      var exp=tx.match(/(在校\\/应届|经验不限|[0-9]+-[0-9]+年|[0-9]+年以上|应届生)/);
      var deg=tx.match(/(博士|硕士|本科|大专|中专|高中)/);
      var city=(tx.match(/[\\u4e00-\\u9fa5]{2,4}·[\\u4e00-\\u9fa5]{2,8}区/)||[])[0]||'';
      return {raw:tx.slice(0,240), href:a?a.href:'', pay:m?m[1]:'', exp:exp?exp[1]:'',
              deg:deg?deg[1]:'', city:city};
  }).filter(Boolean);"""
    rows = t.run_js(js) or []
    out = []
    for r in rows:
        if not is_campus({"e": r.get("exp", "")}):
            continue
        out.append(r)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", default="AI Agent")
    ap.add_argument("--city", default="")
    ap.add_argument("--degree", default="")
    ap.add_argument("--list-only", action="store_true")
    a = ap.parse_args()

    saved = load_saved()
    if a.list_only:
        print(f"已保存 {len(saved)} 个秋招岗位：")
        for j in saved:
            print(f"  {j.get('n','')[:34]:36} @{(j.get('c') or ''):6} | "
                  f"{j.get('e','')}/{j.get('dg','')} | {(j.get('b') or '')[:18]}")
        return 0

    got = scan(a.query, a.city, a.degree)
    print(f"\n[扫描] {a.query} → 命中 {len(got)} 个秋招岗位（已剔除社招）")
    for j in got[:25]:
        print(f"  {j['raw'][:96]}")
    merged = {j.get("href") or j["raw"][:40]: j for j in saved}
    for j in got:
        merged[j.get("href") or j["raw"][:40]] = j
    save(list(merged.values()))
    print(f"\n已保存至 {OUT}（累计 {len(merged)}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())