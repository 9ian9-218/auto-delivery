# -*- coding: utf-8 -*-
"""profile_sync.py — 档案三源一致性检查（事实源 / 填表源 / 扩展运行态）。

三源是什么：
  1. 事实真源   work/application_profile.json   （confirmed_answers + resume_facts）
  2. 填表源     work/rfa/profile_v2.json        （launch_debug --profile 注入扩展）
  3. 扩展运行态  浏览器扩展 storage              （loop.py 通过 getProfile 读的就是它）

风险：改了 (2) 但没重跑注入，(3) 还是旧值 → `rowPlan.profileRecords` 失真，
      行覆盖判据会把「档案里有的经历」误判成「应该没有」，或反之。

本工具做两件可离线验证的事：
  A. 事实源 vs 填表源 的条数与身份字段是否对得上；
  B. 填表源是否比最近一次 run 更新（新 = 必须重新注入）。

用法：
  python work/tools/profile_sync.py check
  python work/tools/profile_sync.py check --json
退出码：0 = 一致且无需注入；1 = 需处理（见输出）；2 = 档案缺失。
"""
import argparse
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
WORK = os.path.join(ROOT, "work")
FACTS = os.path.join(WORK, "application_profile.json")
V2 = os.path.join(WORK, "rfa", "profile_v2.json")
_DEFAULT_RAF = os.path.join(ROOT, "resume-autofill", "ledger")
LEDGER = os.environ.get("RESUME_AUTOFILL_LEDGER") or (
    os.path.join(os.environ["RESUME_AUTOFILL_ROOT"], "ledger")
    if os.environ.get("RESUME_AUTOFILL_ROOT")
    else _DEFAULT_RAF
)
LAUNCH = "python tools/launch_debug.py --profile work/rfa/profile_v2.json --url <URL>"


def load(path):
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def latest_run_mtime():
    if not os.path.isdir(LEDGER):
        return 0.0
    mts = [os.path.getmtime(os.path.join(LEDGER, n)) for n in os.listdir(LEDGER)
           if n.endswith("-state.json")]
    return max(mts) if mts else 0.0


def count(x):
    return len(x) if isinstance(x, list) else (1 if x else 0)


def main():
    ap = argparse.ArgumentParser(description="档案三源一致性检查")
    ap.add_argument("cmd", choices=["check"])
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    facts = load(FACTS)
    v2 = load(V2)
    if facts is None or v2 is None:
        print("档案缺失：%s / %s" % (FACTS if facts is None else "-", V2 if v2 is None else "-"),
              file=sys.stderr)
        return 2

    rf = facts.get("resume_facts") or {}
    basics = v2.get("basics") or {}
    problems, notes = [], []

    # A. 身份字段
    for k_facts, k_v2 in (("name", "name"), ("phone", "phone"), ("email", "email")):
        fv, vv = rf.get(k_facts), basics.get(k_v2)
        if fv and vv and str(fv).strip() != str(vv).strip():
            problems.append("身份字段不一致 %s: 事实=%r 填表=%r" % (k_facts, fv, vv))

    # B. 经历条数
    pairs = (("education", "educations"), ("internships", "internships"),
             ("projects", "projects"))
    for k_facts, k_v2 in pairs:
        nf, nv = count(rf.get(k_facts)), count(v2.get(k_v2))
        if nf and nv and nf != nv:
            problems.append("条数不一致 %s: 事实=%d 填表=%d" % (k_facts, nf, nv))
        elif nf and not nv:
            problems.append("填表源缺 %s（事实源有 %d 条）" % (k_v2, nf))

    # C. 注入新鲜度
    need_inject = False
    v2_mt, run_mt = os.path.getmtime(V2), latest_run_mtime()
    if run_mt and v2_mt > run_mt + 1:
        need_inject = True
        notes.append("profile_v2.json 比最近一次 run 新 %d 分钟 → 必须先重新注入扩展"
                     % int((v2_mt - run_mt) / 60))
    elif not run_mt:
        notes.append("还没有 ledger/*-state.json，无法判断注入新鲜度（按未知处理）")

    status = "NEEDS_FIX" if problems else ("NEEDS_INJECT" if need_inject else "OK")
    out = {"status": status, "problems": problems, "notes": notes,
           "counts": {"facts_education": count(rf.get("education")),
                      "facts_internships": count(rf.get("internships")),
                      "facts_projects": count(rf.get("projects")),
                      "v2_educations": count(v2.get("educations")),
                      "v2_internships": count(v2.get("internships")),
                      "v2_projects": count(v2.get("projects"))},
           "inject_cmd": LAUNCH,
           "facts_mtime": os.path.getmtime(FACTS), "v2_mtime": v2_mt,
           "latest_run_mtime": run_mt}
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print("档案三源 %s" % status)
        print("  条数：事实 教育%d/实习%d/项目%d ｜ 填表 教育%d/实习%d/项目%d"
              % (out["counts"]["facts_education"], out["counts"]["facts_internships"],
                 out["counts"]["facts_projects"], out["counts"]["v2_educations"],
                 out["counts"]["v2_internships"], out["counts"]["v2_projects"]))
        for p in problems:
            print("  ✗ %s" % p)
        for n in notes:
            print("  · %s" % n)
        if problems or need_inject:
            print("  下一步：改完 profile_v2.json 后必须重新注入 → %s" % LAUNCH)
    return 0 if status == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
