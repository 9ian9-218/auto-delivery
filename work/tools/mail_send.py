# -*- coding: utf-8 -*-
"""mail_send.py — 163 邮箱投递（SMTP_SSL），复用 work/mail_auth.json 授权码。

用法（项目根执行）：
  python work/tools/mail_send.py check
  python work/tools/mail_send.py send --to HR@x.com --company "X公司" \
      --subject "..." --body-file work/_draft/x.txt --attach <简历PDF路径> \
      --ckpt work/ckpt_X.json
  （--attach 省略时默认取 work/user_config.json 里 resume.pdf 指向的简历）

约定：
- 授权码只从 work/mail_auth.json 读，不进 git（work/* 已 gitignore）。
- 发送成功必须回写断点 state=awaiting_verification + state_raw=smtp_accepted + message_id。
- 只发一封；--dry-run 只打印信封不发送。
"""
import argparse
import json
import mimetypes
import os
import smtplib
import ssl
import sys
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

# 用户态隔离：授权码文件位置从 user_config 读，缺省回退 work/mail_auth.json
try:
    import sys as _sys
    _sys.path.insert(0, os.path.join(ROOT, "work", "tools"))
    from user_config import cfg as _ucfg
    AUTH = str(_ucfg.resolve(_ucfg.get("mail", "auth_file", default="work/mail_auth.json")))
    DEFAULT_ATTACH = str(_ucfg.path_or_none("resume", "pdf") or "")
except Exception as _e:  # noqa: BLE001  配置缺失时保持旧行为，但不再静默
    AUTH = os.path.join(ROOT, "work", "mail_auth.json")
    DEFAULT_ATTACH = ""
    print("[warn] 未能从 user_config 解析 mail.auth_file（%s），回退 %s" % (_e, AUTH),
          file=sys.stderr)


def load_auth():
    with open(AUTH, encoding="utf-8") as f:
        cfg = json.load(f)
    for k in ("smtp_host", "smtp_port", "account", "auth_code"):
        if not cfg.get(k):
            raise SystemExit("mail_auth.json 缺少字段 %s" % k)
    return cfg


def connect(cfg, timeout=120):
    ctx = ssl.create_default_context()
    s = smtplib.SMTP_SSL(cfg["smtp_host"], int(cfg["smtp_port"]), timeout=timeout, context=ctx)
    s.login(cfg["account"], cfg["auth_code"])
    return s


def cmd_check(_a):
    cfg = load_auth()
    print("account  = %s" % cfg["account"])
    print("endpoint = %s:%s (ssl=%s)" % (cfg["smtp_host"], cfg["smtp_port"], cfg.get("smtp_ssl")))
    s = connect(cfg)
    print("login    = OK (235 authentication successful)")
    s.quit()
    return 0


def build_message(cfg, to, subject, body, attaches, cc=None):
    msg = EmailMessage()
    msg["From"] = formataddr((cfg.get("from_name") or cfg["account"], cfg["account"]))
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=cfg["account"].split("@")[-1])
    msg.set_content(body)
    for path in attaches:
        if not os.path.isfile(path):
            raise SystemExit("附件不存在：%s" % path)
        ctype, _ = mimetypes.guess_type(path)
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        with open(path, "rb") as f:
            msg.add_attachment(f.read(), maintype=maintype, subtype=subtype,
                               filename=os.path.basename(path))
    return msg


OUTBOX = os.path.join(ROOT, "work", "mail_outbox.jsonl")


def append_outbox(rec):
    os.makedirs(os.path.dirname(OUTBOX), exist_ok=True)
    with open(OUTBOX, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def update_ckpt(path, company, to, message_id, subject, attachments, position=None):
    data = {}
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    data.setdefault("company", company)
    if position:
        data["position"] = position
    data["channel"] = "邮箱"
    data["recipient"] = to
    data["message_id"] = message_id
    data["state"] = "awaiting_verification"
    data["state_raw"] = "smtp_accepted"
    data["needs_human"] = None
    data["subject"] = subject
    data["attachments"] = [os.path.basename(p) for p in attachments]
    data["dashboard_state"] = data.get("dashboard_state") or "not_written"
    data["schema_version"] = data.get("schema_version", 2)
    data["proof"] = {"smtp": "235 authentication successful; message accepted with Message-ID",
                     "message_id": message_id}
    data["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    if path:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
            f.write("\n")
    return data


def cmd_send(a):
    cfg = load_auth()
    body = a.body or ""
    if a.body_file:
        with open(a.body_file, encoding="utf-8") as f:
            body = f.read()
    attaches = a.attach or ([DEFAULT_ATTACH] if DEFAULT_ATTACH else [])
    msg = build_message(cfg, a.to, a.subject, body, attaches, a.cc)
    print("From    : %s" % msg["From"])
    print("To      : %s" % msg["To"])
    print("Subject : %s" % msg["Subject"])
    print("Msg-ID  : %s" % msg["Message-ID"])
    print("Attach  : %s" % ", ".join(os.path.basename(p) for p in attaches))
    print("Body    : %d chars" % len(body))
    if a.dry_run:
        print("[dry-run] 未发送")
        return 0
    s = connect(cfg)
    try:
        refused = s.send_message(msg, from_addr=cfg["account"], to_addrs=[x.strip() for x in a.to.split(",")])
    finally:
        s.quit()
    if refused:
        print("[warn] 部分收件人被拒：%s" % refused, file=sys.stderr)
        return 3
    print("SENT OK  %s" % msg["Message-ID"])
    append_outbox({
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "message_id": msg["Message-ID"],
        "from": cfg["account"],
        "to": a.to,
        "company": a.company,
        "position": a.position,
        "subject": a.subject,
        "attachments": [os.path.basename(p) for p in attaches],
        "result": "smtp_accepted",
    })
    if a.ckpt or a.company:
        rec = update_ckpt(a.ckpt, a.company or "", a.to, msg["Message-ID"],
                          a.subject, attaches, a.position)
        print("CKPT    : %s -> state=%s" % (a.ckpt or "(未写)", rec["state"]))
    return 0


def main():
    ap = argparse.ArgumentParser(description="163 邮箱投递")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")

    sp = sub.add_parser("send")
    sp.add_argument("--to", required=True)
    sp.add_argument("--cc", default=None)
    sp.add_argument("--company", default=None)
    sp.add_argument("--position", default=None)
    sp.add_argument("--subject", required=True)
    sp.add_argument("--body", default="")
    sp.add_argument("--body-file", default=None)
    sp.add_argument("--attach", action="append", default=None)
    sp.add_argument("--ckpt", default=None)
    sp.add_argument("--dry-run", action="store_true")

    a = ap.parse_args()
    return {"check": cmd_check, "send": cmd_send}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
