# -*- coding: utf-8 -*-
"""lift_industry_block.py — 让「行业排除」不再拦住 AI 方向岗位。

背景：看板规则配置没有写接口（API 手册 §3.2 无规则端点，网页规则页只读），
但 `industry` 是岗位行的可写字段。按用户 2026-11-03 要求「不按行业排除，只按 AI Agent/AI 应用方向」，
这里把「方向明确是 AI Agent / AI 应用、且原行业在排除名单里」的岗位行 industry 改为「科技」，
等价于对这批行取消行业过滤；原始 industry 全部备份到 work/industry_backup.json 可随时回滚。

用法：
  python work/tools/lift_industry_block.py --dry-run
  python work/tools/lift_industry_block.py --apply
  python work/tools/lift_industry_block.py --rollback
"""
import argparse
import json
import os
import re
import sys
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def _board_base():
    v = os.environ.get("QIUZHAO_API_URL", "").strip()
    if v:
        return v
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from user_config import cfg as _c
        return str(_c.dashboard_url)
    except Exception:                                          # noqa: BLE001
        return "http://127.0.0.1:8898"


BASE = _board_base()
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
DATA = os.path.join(ROOT, "work", "_archive", "20261103", "board_data.json")
BAK = os.path.join(ROOT, "work", "industry_backup.json")

# 只放行方向明确写了 AI Agent / AI 应用 的行（禁止纯算法/算子/推理加速）
STRONG = re.compile(r'AI\s*Agent|Agent开发|智能体|AI\s*应用|AI应用')
# 放宽档：聚合方向里出现人工智能/大模型/AI 也算（--generic）
GENERIC = re.compile(r'人工智能|大模型|AI\s*软件|AI软件|AI\s*工程|AI工程|AI\s*平台|AI平台')
# 明确红线，绝不因取消行业排除而放进来
RED = re.compile(r'算子|推理加速|CUDA|TensorRT|量化剪枝|端侧部署|芯片设计|视觉算法|导航定位|'
                 r'SLAM|射频|算法工程师|算法研究|大模型算法|模型训练')


def api(method, path, payload):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method=method,
    )
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with op.open(req, timeout=40) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def load():
    return json.load(open(DATA, encoding="utf-8"))


def targets(generic=False):
    d = load()
    ex_ind = set()
    for r in d["rules"]:
        if isinstance(r, list) and r and r[0] == "未投递清单排除行业":
            ex_ind.update(x.strip() for x in re.split(r"[、，,/]", str(r[1])) if x.strip())
    out = []
    for j in d["jobs"]:
        ind = j.get("industry") or ""
        dirn = str(j.get("direction") or "")
        if ind not in ex_ind:
            continue
        if not STRONG.search(dirn) and not (generic and GENERIC.search(dirn)):
            continue
        if RED.search(dirn):
            continue
        out.append({"company": j["company"], "industry_old": ind,
                    "industry_new": "科技", "direction": dirn,
                    "batch": j.get("batch"), "date": j.get("date")})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rollback", action="store_true")
    ap.add_argument("--generic", action="store_true",
                    help="同时放行聚合方向里含 人工智能/大模型/AI平台 的行")
    a = ap.parse_args()

    if a.rollback:
        baks = json.load(open(BAK, encoding="utf-8"))
        for b in baks["rows"]:
            api("POST", "/api/agent/jobs", {"company": b["company"], "industry": b["industry_old"],
                                            "render": False})
            print("  [ROLLBACK] %-22s -> %s" % (b["company"][:22], b["industry_old"]))
        print(api("POST", "/api/agent/render", {}).get("render", {}).get("tail"))
        return 0

    rows = targets(generic=a.generic)
    print("方向明确为 AI Agent / AI 应用、但被行业规则挡住的行：%d\n" % len(rows))
    for r in rows:
        print("  %-24s %-6s→科技  %-11s %s" % (r["company"][:24], r["industry_old"],
                                               str(r["date"]), r["direction"][:56]))
    if a.dry_run or not a.apply:
        print("\n[dry-run] 未写入")
        return 0

    old = {}
    if os.path.isfile(BAK):
        old = {b["company"]: b for b in json.load(open(BAK, encoding="utf-8"))["rows"]}
    ok = 0
    for r in rows:
        res = api("POST", "/api/agent/jobs", {
            "company": r["company"], "industry": "科技", "render": False})
        if res.get("ok"):
            ok += 1
            old[r["company"]] = r
            print("  [OK] %-24s %s" % (r["company"][:24], "; ".join(res.get("changes", []))[:50]))
        else:
            print("  [FAIL] %-24s %s" % (r["company"][:24], res.get("error")))

    json.dump({"generated_at": "2026-11-03T23:10:00+08:00", "rows": list(old.values())},
              open(BAK, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n备份原 industry -> %s" % BAK)
    print(api("POST", "/api/agent/render", {}).get("render", {}).get("tail"))
    print("成功 %d/%d" % (ok, len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
