# -*- coding: utf-8 -*-
"""mail_verify.py — 经 163 IMAP 核验「已发送」与退信，作为邮件投递的物理证据。

用法：
  python work/tools/mail_verify.py sent --limit 5
  python work/tools/mail_verify.py find --message-id "<...@163.com>"
  python work/tools/mail_verify.py bounce --limit 10
"""
import argparse
import email
import imaplib
import json
import os
import ssl
import sys
from email.header import decode_header, make_header

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

# 用户态隔离：授权码位置与 mail_send 同源（work/user_config.json 的 mail.auth_file）。
# 读不到配置时回退历史路径并告警——不做第二份静默真源。
try:
    sys.path.insert(0, os.path.join(ROOT, "work", "tools"))
    from user_config import cfg as _ucfg
    AUTH = str(_ucfg.resolve(_ucfg.get("mail", "auth_file", default="work/mail_auth.json")))
except Exception as _e:                                        # noqa: BLE001
    AUTH = os.path.join(ROOT, "work", "mail_auth.json")
    print("[warn] 未能从 user_config 解析 mail.auth_file（%s），回退 %s" % (_e, AUTH),
          file=sys.stderr)


def login():
    cfg = json.load(open(AUTH, encoding="utf-8"))
    m = imaplib.IMAP4_SSL("imap.163.com", 993, ssl_context=ssl.create_default_context(), timeout=25)
    m.login(cfg["account"], cfg["auth_code"])
    imaplib.Commands.setdefault("ID", ("AUTH",))
    m._simple_command("ID", '("name" "mail_verify" "version" "1.0")')
    return cfg, m


def dec(v):
    if not v:
        return ""
    try:
        return str(make_header(decode_header(v)))
    except Exception:                                          # noqa: BLE001
        return v


def folder(m, flag):
    typ, boxes = m.list()
    for raw in boxes:
        line = raw.decode("utf-8", "ignore")
        if flag in line:
            name = line.split(' "/" ')[-1].strip().strip('"')
            return name
    return None


def parse(m, num):
    typ, data = m.fetch(num, "(RFC822)")
    msg = email.message_from_bytes(data[0][1])
    atts = []
    for part in msg.walk():
        fn = part.get_filename()
        if fn:
            atts.append(dec(fn))
    return {
        "message_id": msg.get("Message-ID"),
        "date": msg.get("Date"),
        "to": dec(msg.get("To")),
        "subject": dec(msg.get("Subject")),
        "attachments": atts,
    }


def cmd_sent(a):
    cfg, m = login()
    box = folder(m, "\\Sent") or "&XfJT0ZAB-"
    m.select(box)
    typ, data = m.search(None, "ALL")
    nums = data[0].split()[-a.limit:]
    out = []
    for n in reversed(nums):
        rec = parse(m, n)
        out.append(rec)
        print(json.dumps(rec, ensure_ascii=False))
    m.logout()
    return 0


def cmd_find(a):
    cfg, m = login()
    box = folder(m, "\\Sent") or "&XfJT0ZAB-"
    m.select(box)
    typ, data = m.search(None, 'HEADER', 'Message-ID', a.message_id)
    nums = data[0].split()
    print("matches:", len(nums))
    for n in nums:
        print(json.dumps(parse(m, n), ensure_ascii=False))
    m.logout()
    return 0 if nums else 1


def cmd_bounce(a):
    cfg, m = login()
    m.select("INBOX")
    typ, data = m.search(None, 'OR', 'FROM', '"Mail Delivery System"', 'SUBJECT', '"delivery"')
    nums = data[0].split()[-a.limit:]
    print("bounce candidates:", len(nums))
    for n in reversed(nums):
        print(json.dumps(parse(m, n), ensure_ascii=False))
    m.logout()
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sent"); s.add_argument("--limit", type=int, default=5)
    f = sub.add_parser("find"); f.add_argument("--message-id", required=True)
    b = sub.add_parser("bounce"); b.add_argument("--limit", type=int, default=10)
    a = ap.parse_args()
    return {"sent": cmd_sent, "find": cmd_find, "bounce": cmd_bounce}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
