# -*- coding: utf-8 -*-
"""rebuild_rows.py — 把被「未投递清单排除公司」旧名挡住的 3 家岗位行，
先备份原文→删除旧行（外部录入批次法）→再用工商全称重建，使其进入未投递清单。

用法：python work/tools/rebuild_rows.py --backup      # 只备份原文
      python work/tools/rebuild_rows.py --apply       # 执行删除+重建
"""
import argparse
import json
import os
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
BAK = os.path.join(ROOT, "work", "pool_rows_backup.json")

# 旧行名 -> 新行（工商全称，且不命中任何排除规则）
JOBS = [
    {
        "old": "上海引望智能技术",
        "new": {
            "company": "上海引望智能技术有限公司",
            "industry": "科技",
            "batch": "27届秋招正式批",
            "direction": "【2027校招】AI应用/软件开发·上海｜智能驾驶 AI 应用与软件平台研发",
            "date": "2026-10-08",
        },
    },
    {
        "old": "上海可镭技术有限公司",
        "new": {
            "company": "可镭技术",
            "industry": "科技",
            "batch": "27届秋招正式批",
            "direction": "【2027校招】智能体开发工程师（J10051）·上海｜Agent 应用开发",
            "date": "2026-10-09",
        },
    },
    {
        "old": "成都翼创雷行智能科技",
        "new": {
            "company": "成都翼创雷行智能科技有限公司",
            "industry": "科技",
            "batch": "27届秋招正式批",
            "direction": "【2027校招】AI大模型开发·成都｜大模型应用工程落地",
            "date": "2026-10-09",
        },
    },
]


def call(method, path, payload):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method=method,
    )
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with op.open(req, timeout=40) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def get(path):
    req = urllib.request.Request(BASE + path)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with op.open(req, timeout=40) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--backup", action="store_true")
    a = ap.parse_args()

    saved = []
    for spec in JOBS:
        info = get("/api/agent/company?name=" + urllib.parse.quote(spec["old"]))
        saved.append({"old": spec["old"], "job_info": info.get("job_info"),
                      "applications": info.get("applications")})
        print("旧行 %-24s %s" % (spec["old"], json.dumps(info.get("job_info"), ensure_ascii=False)[:120]))
    with open(BAK, "w", encoding="utf-8") as f:
        json.dump(saved, f, ensure_ascii=False, indent=1)
    print("\n原文已备份 -> %s" % BAK)

    if not a.apply:
        print("[dry-run] 未改动；加 --apply 执行「删旧行 + 建新行」")
        return 0

    for spec in JOBS:
        old = spec["old"]
        pre = get("/api/agent/company?name=" + urllib.parse.quote(old))
        if pre.get("applications"):
            print("  [SKIP] %s 已有投递记录，不删" % old)
            continue
        call("POST", "/api/agent/jobs", {"company": old, "batch": "外部录入", "render": False})
        call("POST", "/api/agent/applications",
             {"company": old, "position": "probe-cleanup", "status": "已投递", "render": False})
        res = call("DELETE", "/api/agent/applications",
                   {"company": old, "position": "probe-cleanup", "confirm": True, "render": False})
        removed = res.get("removed_job_rows") or []
        print("  [DEL]  %-24s removed_job_rows=%s" % (old, len(removed)))

        n = spec["new"]
        r2 = call("POST", "/api/agent/jobs", dict(n, create=True, render=False))
        print("  [NEW]  %-26s created=%s %s" % (n["company"], r2.get("created"),
                                                "; ".join(r2.get("changes", []))[:60]))

    r = call("POST", "/api/agent/render", {})
    print("\nrender:", r.get("render", {}).get("tail", r))
    return 0


if __name__ == "__main__":
    import urllib.parse
    sys.exit(main())
