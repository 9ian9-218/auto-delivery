# -*- coding: utf-8 -*-
"""gate_log.py — 闸门 1 / 闸门 3 留痕（append-only JSONL）。

为什么需要：三道闸门里只有闸门 2 有代码可证（`loop.py gate` 的截图哈希 + 复核 + 台账）。
闸门 1（授权）和闸门 3（提交同意）现在只存在于对话里，事后无法证明「确实拿到过同意」。
本工具把它们变成一行不可改写的记录。

用法（项目根执行）：
  # 闸门1：用户授权了哪几家、几家、原话
  python work/tools/gate_log.py gate1 --companies "泰康资产,中控技术" --count 2 \
      --quote "这两家可以投"

  # 闸门3：提交前复述状态并拿到同意（建议绑定断点文件）
  python work/tools/gate_log.py gate3 --ckpt work/ckpt_中控技术.json \
      --quote "确认提交"

  python work/tools/gate_log.py gate1 --companies "某公司" --deny --quote "先别投"
  python work/tools/gate_log.py show            # 今天
  python work/tools/gate_log.py show --all

约定：`by` 只能是 user；agent 不得代签。退出码 2 = 参数或前置不成立。
"""
import argparse
import json
import os
import sys
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
LOG = os.path.join(ROOT, "work", "gates.jsonl")


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def append(rec):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def rows():
    if not os.path.isfile(LOG):
        return []
    out = []
    with open(LOG, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:                              # noqa: BLE001
                    pass
    return out


def need_quote(gate, quote):
    if not quote or len(quote.strip()) < 2:
        print("[%s] 必须带 --quote <用户原话>：留痕的价值就在于能复述原话" % gate, file=sys.stderr)
        return False
    return True


def cmd_gate1(a):
    if not need_quote("gate1", a.quote):
        return 2
    comps = [c.strip() for c in (a.companies or "").split(",") if c.strip()]
    if not comps and not a.deny:
        print("gate1 需要 --companies 或 --deny", file=sys.stderr)
        return 2
    rec = {"ts": now_iso(), "gate": "gate1", "by": "user",
           "decision": "denied" if a.deny else "granted",
           "companies": comps, "count": a.count if a.count is not None else len(comps),
           "user_quote": a.quote.strip()[:300]}
    append(rec)
    print("已留痕 gate1 %s：%d 家 ｜ %s" % (rec["decision"], len(comps), LOG))
    if not a.deny and len(comps) > rec["count"]:
        print("[warn] 列了 %d 家但 count=%d，按较严的 count 执行" % (len(comps), rec["count"]),
              file=sys.stderr)
    return 0


def cmd_gate3(a):
    if not need_quote("gate3", a.quote):
        return 2
    ckpt = {}
    if a.ckpt:
        try:
            with open(a.ckpt, encoding="utf-8") as f:
                ckpt = json.load(f)
        except Exception as e:                                 # noqa: BLE001
            print("读不到断点 %s：%s" % (a.ckpt, e), file=sys.stderr)
            return 2
    company = ckpt.get("company") or a.company
    if not company:
        print("gate3 需要 --ckpt 或 --company", file=sys.stderr)
        return 2

    universe = rows()
    granted = [r for r in universe
               if r.get("gate") == "gate1" and r.get("decision") == "granted"
               and any(company == c or company in c or c in company
                       for c in r.get("companies", []))]
    if not granted:
        print("[gate3] 该公司的 gate1 授权未留痕；先跑 gate1 --companies \"%s\" "
              "--quote \"<用户原话>\"。本次不写记录。" % company, file=sys.stderr)
        return 2

    rec = {"ts": now_iso(), "gate": "gate3", "by": "user",
           "decision": "denied" if a.deny else "approved",
           "company": company, "position": ckpt.get("position") or a.position,
           "ckpt_state": ckpt.get("state"), "job_url": ckpt.get("job_url"),
           "gate1_ts": granted[-1]["ts"], "user_quote": a.quote.strip()[:300]}
    if a.deny:
        append(rec)
        print("已留痕 gate3 denied：%s（停在可提交状态）" % company)
        return 0
    if ckpt and ckpt.get("state") not in (None, "draft", "needs_input",
                                          "awaiting_verification", "blocked"):
        print("[gate3] 断点 state=%s，不是可提交状态（应为 draft/needs_input 之后的就绪态）；"
              "先核对再提交。" % ckpt.get("state"), file=sys.stderr)
        return 2
    append(rec)
    print("已留痕 gate3 approved：%s / %s（gate1 @ %s）→ %s"
          % (company, rec["position"] or "-", rec["gate1_ts"], LOG))
    print("现在可以提交一次；结果未知先查官网记录，不重投。")
    return 0


def cmd_show(a):
    list_ = rows()
    day = datetime.now().astimezone().strftime("%Y-%m-%d")
    if not a.all:
        list_ = [r for r in list_ if str(r.get("ts", "")).startswith(day)]
    if not list_:
        print("今天还没有闸门记录（--all 看全部）")
        return 0
    for r in list_:
        who = r.get("companies") or r.get("company") or ""
        if isinstance(who, list):
            who = ",".join(who)
        print("%s  %-5s %-8s %-28s %s"
              % (r.get("ts"), r.get("gate"), r.get("decision"), str(who)[:28],
                 str(r.get("user_quote") or "")[:40]))
    return 0


def main():
    ap = argparse.ArgumentParser(description="闸门 1/3 留痕")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g1 = sub.add_parser("gate1", help="用户授权岗位与数量")
    g1.add_argument("--companies", default="")
    g1.add_argument("--count", type=int, default=None)
    g1.add_argument("--quote", default="")
    g1.add_argument("--deny", action="store_true")

    g3 = sub.add_parser("gate3", help="提交前同意")
    g3.add_argument("--ckpt", default=None)
    g3.add_argument("--company", default=None)
    g3.add_argument("--position", default=None)
    g3.add_argument("--quote", default="")
    g3.add_argument("--deny", action="store_true")

    sh = sub.add_parser("show")
    sh.add_argument("--all", action="store_true")

    a = ap.parse_args()
    return {"gate1": cmd_gate1, "gate3": cmd_gate3, "show": cmd_show}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
