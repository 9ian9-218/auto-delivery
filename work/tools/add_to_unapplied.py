# -*- coding: utf-8 -*-
"""add_to_unapplied.py — 把选定公司写回看板「招聘岗位」并刷新，使其进入未投递清单。

用法（项目根）：
  python work/tools/add_to_unapplied.py --dry-run
  python work/tools/add_to_unapplied.py --apply

行为：
- 只改「招聘岗位」行的 industry/batch/direction/date/status（status 置空 = 待投递），
  不写投递记录、不碰内推码与投递链接。
- 已存在该公司行则更新，不存在则新建（create=true）。
- 末尾 `POST /api/agent/render` 刷新网页与未投递切片。
"""
import argparse
import json
import os
import sys
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://100.73.185.103:8898"
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
PLAN = os.path.join(ROOT, "work", "pool_additions.json")


def post(path, payload, timeout=40):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    plan = json.load(open(PLAN, encoding="utf-8"))
    rows = plan["rows"]
    print("待写回 %d 家（来源 %s）\n" % (len(rows), plan.get("generated_at", "")))
    for r in rows:
        print("  %-26s %-10s %-22s %s" % (r["company"][:26], r["industry"],
                                          r["batch"], r["direction"][:44]))
    if a.dry_run or not a.apply:
        print("\n[dry-run] 未写入；加 --apply 执行")
        return 0

    ok = 0
    for r in rows:
        payload = {
            "company": r["company"],
            "industry": r["industry"],
            "batch": r["batch"],
            "direction": r["direction"],
            "date": r["date"],
            "create": True,
            "render": False,
        }
        try:
            res = post("/api/agent/jobs", payload)
        except Exception as e:                                  # noqa: BLE001
            print("  [FAIL] %s -> %s" % (r["company"], e))
            continue
        if res.get("ok"):
            ok += 1
            print("  [OK]   %-26s %s" % (r["company"][:26], "; ".join(res.get("changes", []))[:60]))
        else:
            print("  [FAIL] %-26s %s" % (r["company"][:26], res.get("error")))

    res = post("/api/agent/render", {})
    print("\nrender:", res)
    print("写入成功 %d/%d" % (ok, len(rows)))
    return 0 if ok == len(rows) else 3


if __name__ == "__main__":
    sys.exit(main())
