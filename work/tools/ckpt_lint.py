# -*- coding: utf-8 -*-
"""ckpt_lint.py — 投递断点校验与归一（只读默认，--migrate 才写）。

契约：work/ckpt.schema.json
用途：让「27 个断点 105 个键 10 种状态」收敛成可机读的 6 态词表，
      从而能回答「今天几家待人工 / 几家待核验 / 几家真投了」。

用法：
  python work/tools/ckpt_lint.py                # 只报告
  python work/tools/ckpt_lint.py --json         # 机器可读
  python work/tools/ckpt_lint.py --migrate      # 补规范键 + 归一并备份原件
  python work/tools/ckpt_lint.py --pending      # 输出待人工/待核验清单
退出码：0 = 全部合规；1 = 有不合规（--migrate 后重跑应为 0）。
"""
import argparse
import json
import os
import shutil
import sys
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
WORK = os.path.join(ROOT, "work")
SCHEMA_PATH = os.path.join(WORK, "ckpt.schema.json")


def load_schema():
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


def ckpt_files():
    return sorted(p for p in (os.path.join(WORK, n) for n in os.listdir(WORK))
                  if os.path.basename(p).startswith("ckpt_") and p.endswith(".json"))


def read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def canonify(rec, schema):
    """补规范键（不覆盖已有值），返回 (新记录, 补了哪些键)。"""
    added = []
    for canon, aliases in schema["key_aliases"].items():
        if rec.get(canon) in (None, "", []):
            for a in aliases:
                if rec.get(a) not in (None, "", []):
                    rec[canon] = rec[a]
                    added.append(canon)
                    break
    if rec.get("attempt_id") in (None, ""):
        rec["attempt_id"] = "a-" + str(rec.get("company") or "unknown")
        added.append("attempt_id")
    if rec.get("updated_at") in (None, ""):
        rec["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        added.append("updated_at")
    raw_state = rec.get("state")
    mapped = schema["state_map"].get(raw_state)
    if mapped:
        rec["state_raw"] = raw_state
        rec["state"] = mapped["state"]
        if mapped.get("needs_human") and not rec.get("needs_human"):
            rec["needs_human"] = mapped["needs_human"]
        added.append("state")
    elif raw_state in (None, ""):
        rec["state"] = schema.get("defaults", {}).get("missing_state", "draft")
        added.append("state")
    raw_dash = rec.get("dashboard_state")
    dash_map = schema.get("dashboard_map", {})
    if raw_dash in dash_map:
        rec["dashboard_state_raw"] = raw_dash
        rec["dashboard_state"] = dash_map[raw_dash]
        added.append("dashboard_state")
    if not rec.get("dashboard_state"):
        rec["dashboard_state"] = "not_written"
        added.append("dashboard_state")
    rec["schema_version"] = schema["schema_version"]
    return rec, added


def check(rec, schema, fname):
    problems = []
    for k in schema["required"]:
        if rec.get(k) in (None, "", []):
            problems.append("MISSING:" + k)
    st = rec.get("state")
    if st and st not in schema["states"]:
        problems.append("STATE_DRIFT:%s" % st)
    ds = rec.get("dashboard_state")
    if ds and ds not in schema["dashboard_states"]:
        problems.append("DASHBOARD_DRIFT:%s" % ds)
    if st != "submitted" and ds == "recorded":
        problems.append("ILLEGAL:非 submitted 却已写看板")
    return problems


NEED_HUMAN_HINT = {
    "captcha_slider": "滑块拼图：保留标签页交用户拖拽（agent 不代拖）",
    "captcha_point": "点选型：可经可信点击逐格完成，完成后必须截图核对选中态再确认",
    "signature": "手写签名：用户本人在页面签",
    "missing_field": "缺必填：先把字段名+缺失原因报给用户，拿到值再填",
    "other": "其他接管：按断点里的 reason 处理",
}


def handoff(rows):
    """把散在各断点的待人工项聚成一张清单，供用户一次做完。"""
    pending = [r for r in rows if r.get("state") == "needs_input"]
    verify = [r for r in rows if r.get("state") == "awaiting_verification"]
    out = {"generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
           "needs_input": [], "awaiting_verification": []}
    for r in pending:
        out["needs_input"].append({
            "company": r.get("company"), "position": r.get("position"),
            "needs_human": r.get("needs_human"), "reason": r.get("reason"),
            "job_url": r.get("job_url"), "file": r["file"],
            "hint": NEED_HUMAN_HINT.get(r.get("needs_human") or "other",
                                        NEED_HUMAN_HINT["other"])})
    for r in verify:
        out["awaiting_verification"].append({
            "company": r.get("company"), "position": r.get("position"),
            "job_url": r.get("job_url"), "file": r["file"],
            "hint": "去官网应聘记录核实是否已提交；证实未提交才可按原授权重试"})
    path = os.path.join(WORK, "pending_human.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("待人工 %d 家 · 待核验 %d 家 → %s\n" % (len(out["needs_input"]),
                                                len(out["awaiting_verification"]), path))
    for r in out["needs_input"]:
        print("  %-26s %-12s %s" % ((r["company"] or r["file"])[:26],
                                    r["needs_human"] or "-", r["hint"]))
    if out["awaiting_verification"]:
        print("\n待核验：")
        for r in out["awaiting_verification"]:
            print("  %-26s %s" % ((r["company"] or r["file"])[:26], r["hint"]))
    return path


def main():
    ap = argparse.ArgumentParser(description="投递断点校验/归一")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--migrate", action="store_true")
    ap.add_argument("--pending", action="store_true", help="只列 needs_input / awaiting_verification")
    ap.add_argument("--handoff", action="store_true", help="生成 work/pending_human.json 接管清单")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    schema = load_schema()
    files = ckpt_files()
    backup_dir = os.path.join(WORK, "_archive",
                              datetime.now().strftime("%Y%m%d-%H%M%S") + "-ckpt-before-migrate")

    report, bad = [], 0
    for path in files:
        name = os.path.basename(path)
        try:
            rec = read(path)
        except Exception as e:                                  # noqa: BLE001
            report.append({"file": name, "problems": ["PARSE_ERROR:%s" % e]})
            bad += 1
            continue
        if a.migrate:
            new, added = canonify(dict(rec), schema)
            if new != rec:
                os.makedirs(backup_dir, exist_ok=True)
                shutil.copy2(path, os.path.join(backup_dir, name))
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(new, f, ensure_ascii=False, indent=2)
                    f.write("\n")
                rec = new
                report.append({"file": name, "migrated": added,
                               "state": rec.get("state")})
                continue
        problems = check(rec, schema, name)
        if problems:
            bad += 1
        report.append({"file": name, "company": rec.get("company"),
                       "state": rec.get("state"), "state_raw": rec.get("state_raw"),
                       "needs_human": rec.get("needs_human"),
                       "dashboard_state": rec.get("dashboard_state"),
                       "problems": problems})

    if a.handoff:
        handoff([r for r in report if "state" in r])
        return 0

    if a.pending:
        rows = [r for r in report if r.get("state") in ("needs_input", "awaiting_verification")]
        for r in rows:
            print("%-26s %-22s %-14s %s" % (r.get("company") or r["file"], r.get("state"),
                                            r.get("needs_human") or "-",
                                            r.get("problems") or "ok"))
        return 0 if not rows else 0

    if a.json:
        print(json.dumps({"files": len(files), "nonconforming": bad,
                          "migrated" if a.migrate else "report": report},
                         ensure_ascii=False, indent=2))
    elif not a.quiet:
        if a.migrate:
            print("迁移 %d 个断点，备份 → %s\n" % (len(files), backup_dir or "（无需备份）"))
            for r in report:
                print("  %-28s %s" % (r["file"], "补 " + ",".join(r.get("migrated") or [])
                                      if r.get("migrated") else "无变化"))
        else:
            print("断点 %d 个，不合规 %d 个" % (len(files), bad))
            for r in report:
                if r.get("problems"):
                    print("  %-28s %s" % (r["file"], "; ".join(r["problems"])))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
