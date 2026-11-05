# -*- coding: utf-8 -*-
"""applied_index.py — 公司级去重索引（看板 + 本地断点 + 手工补录 → 一份可查的表）。

背景：历史黑名单 work/applied_companies.json（430+ 家）与 work/check_applied.py 已不在本工作区，
去重只剩「看板 live 查询 + 26 个自由格式断点」。本工具把三源合成一张索引，
让「这家我投过吗」变成一次本地查询，而不是一轮翻文件。

用法（项目根执行）：
  python work/tools/applied_index.py build            # 拉看板 + 合断点，写 work/applied_index.json
  python work/tools/applied_index.py build --offline  # 不查看板，只用本地断点
  python work/tools/applied_index.py check 腾讯 招商金控
  python work/tools/applied_index.py list --status submitted

铁律：只读看板（8898），不写；--offline 时连网络都不碰。
退出码：check 命中 1 家以上 = 1（便于脚本判重），全未命中 = 0。
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
WORK = os.path.join(ROOT, "work")
INDEX = os.path.join(WORK, "applied_index.json")
LOCAL = os.path.join(WORK, "applied_index.local.json")
SCRIPTS = os.path.join(ROOT, ".agents", "skills", "auto-resume-submit", "scripts")


def norm(name):
    """公司名归一：去空白/中英文括号/连字符/点号，转小写（看板侧同规则）。"""
    s = str(name or "")
    s = re.sub(r"[\s（）()【】\[\]<>《》、,，.。\-_/\\|·:：]", "", s)
    return s.lower()


def alias_of(name):
    """括号里的简称也是别名：「招商局集团（招商金控）」→ 招商金控。"""
    return [m for m in re.findall(r"[（(]([^）)]{2,20})[）)]", str(name or ""))]


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                          # noqa: BLE001
        return default if default is not None else {}


def pull_dashboard():
    sys.path.insert(0, SCRIPTS)
    import qiuzhao_api
    c = qiuzhao_api.get_client()
    items, offset, total = [], 0, None
    while True:
        page = c.get_applications(status="all", limit=200, offset=offset)
        batch = page.get("items") or []
        total = page.get("total", len(items))
        items.extend(batch)
        offset += len(batch)
        if not batch or len(items) >= total or offset > 2000:
            break
    return items, total


def build(offline=False):
    sources = {"dashboard": "skipped", "ckpt": 0}
    dash = []
    if not offline:
        try:
            dash, _ = pull_dashboard()
            sources["dashboard"] = "ok:%d" % len(dash)
        except Exception as e:                                 # noqa: BLE001
            sources["dashboard"] = "failed:%s" % type(e).__name__
    companies = {}

    def put(name, entry):
        k = norm(name)
        if not k:
            return
        rec = companies.setdefault(k, {"display": name, "aliases": set(), "records": []})
        if len(name) > len(rec["display"]):
            rec["display"] = name
        rec["records"].append(entry)
        for a in alias_of(name):
            rec["aliases"].add(a)

    for it in dash:
        put(it.get("company"), {"src": "dashboard", "status": it.get("status"),
                               "position": it.get("position"), "date": it.get("date")})

    for fn in sorted(os.listdir(WORK)):
        if not (fn.startswith("ckpt_") and fn.endswith(".json")):
            continue
        rec = load_json(os.path.join(WORK, fn), {})
        if not rec:
            continue
        sources["ckpt"] += 1
        put(rec.get("company"), {"src": "ckpt", "file": fn,
                                "status": rec.get("state"),
                                "needs_human": rec.get("needs_human"),
                                "position": rec.get("position"),
                                "dashboard_state": rec.get("dashboard_state")})

    for name, status in (load_json(LOCAL, {}) or {}).items():
        put(name, {"src": "local", "status": status})

    out = {"generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
           "sources": sources,
           "count": len(companies),
           "companies": {}}
    for k, rec in companies.items():
        st = {r.get("status") for r in rec["records"] if r.get("status")}
        # 有已投/面试记录即视为已投；只有本地断点状态则照抄
        if any(str(s).startswith(("已投递", "面试", "笔试", "测评", "offer", "Offer")) for s in st):
            overall = "applied"
        elif "submitted" in st:
            overall = "applied"
        elif st & {"needs_input", "awaiting_verification", "draft"}:
            overall = "in_progress"
        elif st & {"skipped"}:
            overall = "excluded"
        elif st & {"blocked"}:
            overall = "blocked"
        else:
            overall = "unknown"
        out["companies"][k] = {"display": rec["display"], "aliases": sorted(rec["aliases"]),
                               "overall": overall, "local_states": sorted(map(str, st)),
                               "records": rec["records"]}

    with open(INDEX, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("索引 %d 家 · 看板 %s · 断点 %d 个 → %s"
          % (len(companies), sources["dashboard"], sources["ckpt"], INDEX))
    return out


def check(names):
    idx = load_json(INDEX)
    comps = idx.get("companies") or {}
    if not comps:
        print("还没有索引，先跑：python work/tools/applied_index.py build", file=sys.stderr)
        return 2
    hits = 0
    for n in names:
        k = norm(n)
        found = [(kk, v) for kk, v in comps.items()
                 if k and (k in kk or kk in k
                           or any(norm(a) == k or k in norm(a) for a in v.get("aliases", [])))]
        if not found:
            print("%-24s 未命中（可投）" % n)
            continue
        hits += 1
        for _, v in found:
            print("%-24s 命中 → %s [%s] %s" % (n, v["display"], v["overall"],
                                              "/".join(x for x in v["local_states"] if x)))
    return 1 if hits else 0


def main():
    ap = argparse.ArgumentParser(description="公司级去重索引")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--offline", action="store_true")
    c = sub.add_parser("check")
    c.add_argument("names", nargs="+")
    ls = sub.add_parser("list")
    ls.add_argument("--status", default=None)
    a = ap.parse_args()

    if a.cmd == "build":
        build(a.offline)
        return 0
    if a.cmd == "check":
        return check(a.names)
    idx = load_json(INDEX)
    rows = [(k, v) for k, v in (idx.get("companies") or {}).items()
            if not a.status or v.get("overall") == a.status]
    for k, v in sorted(rows, key=lambda x: x[1]["display"]):
        print("%-30s %-14s %s" % (v["display"][:30], v["overall"], "/".join(v["local_states"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
