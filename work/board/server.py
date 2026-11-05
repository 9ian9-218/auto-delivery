# -*- coding: utf-8 -*-
"""server.py — 本机看板 HTTP 服务（stdlib only，零第三方依赖）。

与旧看板 :8898 的 /api/agent/* 同形，让 scripts/qiuzhao_api.py 只改 base_url 即可运行。
差异与理由见 work/board/README.md（形状照抄、歧义纠正）。

启动：
    python work/board/server.py --port 8898 --db data/board.db
    python work/board/server.py --seed work/_archive/20261103/board_data.json   # 首次导入
"""
import argparse
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))          # 仓库根（由本文件位置推导）
STATIC = os.path.join(HERE, "static")
DEFAULT_DB = os.path.join(ROOT, "data", "board.db")

sys.path.insert(0, HERE)
import store  # noqa: E402

CON = None
TOKEN = ""


def overview_payload(con):
    st = store.stats(con)
    total, _, _, recent = store.applications(con, limit=10)
    unread, notice_rows = store.notices(con, limit=5)
    lines = [
        "# 投递概览",
        "",
        "- 投递记录：%d 条，覆盖 %d 家公司" % (st["n_app"], st["n_company"]),
        "- 岗位库：%d 条；未投递：%d 条" % (st["n_pos"], st["n_unapplied"]),
        "- 进行中：%d；已挂：%d；Offer：%d" % (st["active"], st["failed"], st["offer"]),
        "",
        "## 最近投递",
    ]
    for r in recent:
        lines.append("- %s | %s | %s | %s" % (r["date"], r["company"], r["position"], r["status"]))
    return {
        "ok": True,
        "stats": st,
        "recent": recent,
        "exams": store.exams(con),
        "notices": {"unread": unread, "items": notice_rows},
        "total_applications": total,
        "summary_markdown": "\n".join(lines),
        "generated_at": store.now(),
    }


def render_board_html():
    """把实时数据注入模板：一个字面量 __DATA__ → 当前库的 8 个集合。"""
    tpl_path = os.path.join(STATIC, "template.html")
    tpl = open(tpl_path, encoding="utf-8").read()
    payload = json.dumps(store.blob(CON), ensure_ascii=False).replace("</", "<\\/")
    return tpl.replace("__DATA__", payload)


def endpoints_table():
    return [
        {"method": "GET", "path": "/api/agent/overview", "desc": "统计 / 近期动态 / 考试 / 提醒"},
        {"method": "GET", "path": "/api/agent/applications", "desc": "投递记录分页"},
        {"method": "GET", "path": "/api/agent/company", "desc": "公司全貌（name 必填）"},
        {"method": "GET", "path": "/api/agent/unapplied", "desc": "未投递清单"},
        {"method": "GET", "path": "/api/agent/exams", "desc": "笔面日程"},
        {"method": "GET", "path": "/api/agent/notices", "desc": "提醒"},
        {"method": "GET", "path": "/api/agent/info", "desc": "端点表（=/schema=/openapi.json）"},
        {"method": "GET", "path": "/api/agent/manual", "desc": "本机实现说明（Markdown）"},
        {"method": "POST", "path": "/api/agent/applications", "desc": "记投递（幂等）"},
        {"method": "POST", "path": "/api/agent/applications/update", "desc": "改状态（PATCH 的同义路由）"},
        {"method": "PATCH", "path": "/api/agent/applications", "desc": "改状态 / 日期 / 岗位数"},
        {"method": "DELETE", "path": "/api/agent/applications", "desc": "删记录（confirm:true）"},
        {"method": "POST", "path": "/api/agent/jobs", "desc": "新增/改岗位条目"},
        {"method": "POST", "path": "/api/agent/exams", "desc": "登记笔试/面试/测评"},
        {"method": "DELETE", "path": "/api/agent/exams", "desc": "删场次（confirm:true）"},
        {"method": "DELETE", "path": "/api/agent/unapplied", "desc": "排除未投递公司（confirm:true）"},
        {"method": "POST", "path": "/api/agent/render", "desc": "刷新（本机即时，等价空操作）"},
    ]


MANUAL = """# 本机看板 · /api/agent/* 说明

本服务是「秋招看板」的本机替代实现，接口形状对齐 v1.4.0。

## 与旧看板的差异（已知且有意）

1. **排序**：applications 一律按 date 降序（旧看板实测有 77 处违反）。
2. **公司查询**：命中不唯一时返回 matched_company 与 candidates（旧看板取首个子串命中，
   且 job_info 与 apply_link 可能指向不同公司）。
3. **存储**：SQLite（data/board.db），不再写 Excel，因此没有备份文件与行号语义；
   render 恒返回 ok。
4. **提醒**：notices 由本地写入，unread 是真实未读数（旧看板 unread_notices 实为最近 5 条）。

## 幂等

- POST /applications：company+position 相同则不再插行（返回 created=false）。
- POST /exams：company+kind+when 相同则不再插行。
- DELETE 类：必须带 confirm:true，否则 400。

## 钳制

- applications.limit 上限 500、默认 100；unapplied.limit 上限 200、默认 50。
- limit<=0 钳到 1（不是回落默认）；offset<0 钳到 0；offset>total 返回空 items。
- notices.limit=0 返回全部。
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "local-board/1.0"

    # ---------------------------------------------------------------- 基础
    def log_message(self, fmt, *args):
        if os.environ.get("BOARD_QUIET"):
            return
        sys.stderr.write("[board] " + (fmt % args) + "\n")

    def _send(self, code, payload, ctype="application/json; charset=utf-8"):
        body = payload if isinstance(payload, bytes) else str(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def _err(self, code, msg, **kw):
        payload = {"ok": False, "error": msg}
        payload.update(kw)
        self._json(code, payload)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        raw = self.rfile.read(n).decode("utf-8", "replace")
        try:
            return json.loads(raw) if raw.strip() else {}
        except ValueError:
            return {"__invalid__": raw}

    def _auth_ok(self):
        if not TOKEN:
            return True
        got = (self.headers.get("X-QZ-Token")
               or (self.headers.get("Authorization") or "").replace("Bearer ", "")
               or "")
        if got.strip() == TOKEN:
            return True
        q = parse_qs(urlparse(self.path).query)
        return (q.get("token") or [""])[0].strip() == TOKEN

    # ---------------------------------------------------------------- GET
    def do_GET(self):
        if not self._auth_ok():
            return self._err(401, "unauthorized")
        u = urlparse(self.path)
        p, q = u.path, parse_qs(u.query)

        if p in ("/", "/index.html"):
            return self._send(200, render_board_html(), "text/html; charset=utf-8")
        if p.startswith("/static/"):
            return self._static(p[len("/static/"):])

        def one(k, d=None):
            return (q.get(k) or [d])[0]

        if p == "/api/agent/overview":
            data = overview_payload(CON)
            if one("format") == "text":
                return self._send(200, data["summary_markdown"], "text/plain; charset=utf-8")
            return self._json(200, data)
        if p == "/api/agent/applications":
            total, lim, off, items = store.applications(
                CON, status=one("status"), company=one("company"), direction=one("direction"),
                limit=one("limit", 100), offset=one("offset", 0))
            return self._json(200, {"ok": True, "total": total, "limit": lim,
                                    "offset": off, "items": items})
        if p == "/api/agent/company":
            name = (one("name") or "").strip()
            if not name:
                return self._err(404, "missing name")
            c = store.company(CON, name)
            if c is None:
                return self._err(404, "company not found", query=name)
            return self._json(200, c)
        if p == "/api/agent/unapplied":
            total, lim, off, items = store.unapplied(
                CON, direction=one("direction"), company=one("company"),
                industry=one("industry"), limit=one("limit", 50), offset=one("offset", 0),
                exclude_applied=(one("exclude_applied", "true").lower() != "false"))
            return self._json(200, {"ok": True, "total": total, "limit": lim,
                                    "offset": off, "items": items})
        if p == "/api/agent/exams":
            return self._json(200, {"ok": True, "items": store.exams(CON)})
        if p in ("/api/notices", "/api/agent/notices"):
            unread, items = store.notices(CON, limit=one("limit", 30))
            return self._json(200, {"ok": True, "unread": unread, "items": items})
        if p in ("/api/agent/info", "/api/agent/schema", "/api/agent/openapi.json"):
            return self._json(200, {"ok": True, "version": "1.4.0", "impl": "local-board",
                                    "endpoints": endpoints_table()})
        if p == "/api/agent/manual":
            return self._send(200, MANUAL, "text/markdown; charset=utf-8")
        return self._err(404, "not found", path=p)

    # ---------------------------------------------------------------- POST
    def do_POST(self):
        if not self._auth_ok():
            return self._err(401, "unauthorized")
        p = urlparse(self.path).path
        b = self._body()
        if "__invalid__" in b:
            return self._err(400, "invalid json")

        if p in ("/api/agent/applications", "/api/agent/applications/update"):
            company = (b.get("company") or "").strip()
            if not company:
                return self._err(400, "missing company")
            if p.endswith("/update"):
                row = store.update_application(CON, company, position=b.get("position"),
                                               status=b.get("status"), date=b.get("date"),
                                               n=b.get("n"))
                if row is None:
                    return self._err(404, "application not found", company=company)
                return self._json(200, {"ok": True, "row": row, "action": "update"})
            position = (b.get("position") or b.get("job") or company).strip()
            created, row = store.create_application(
                CON, company, position, status=b.get("status") or "已投递",
                date=b.get("date"), n=b.get("n") or 1)
            return self._json(200, {"ok": True, "created": created, "row": row,
                                    "action": "create" if created else "noop"})

        if p == "/api/agent/jobs":
            company = (b.get("company") or "").strip()
            if not company:
                return self._err(400, "missing company")
            created, row = store.upsert_job(
                CON, company, industry=b.get("industry"), batch=b.get("batch"),
                date=b.get("date"), direction=b.get("direction"), status=b.get("status"),
                applied=b.get("applied"), applied_at=b.get("applied_at"))
            return self._json(200, {"ok": True, "created": created, "job": row})

        if p == "/api/agent/exams":
            company = (b.get("company") or "").strip()
            if not company or not b.get("kind") or not b.get("when"):
                return self._err(400, "company, kind, when are required")
            created, eid = store.add_exam(CON, company, b.get("kind"), b.get("when"),
                                          b.get("place", ""), b.get("link", ""), b.get("note", ""))
            return self._json(200, {"ok": True, "created": created, "id": eid})

        if p == "/api/notices":
            action = (b.get("action") or "").strip()
            if action in ("read", "clear"):
                CON.execute("UPDATE notices SET read = 1" if action == "clear"
                            else "UPDATE notices SET read = 1")
                CON.commit()
            unread, items = store.notices(CON, limit=30)
            return self._json(200, {"ok": True, "unread": unread,
                                    "items": [{"company": i["company"], "text": i["text"],
                                               "ts": i["at"], "read": False} for i in items]})

        # 旧看板的对话/上传能力在本机版下线，保留端点形状以便前端优雅降级
        if p in ("/api/chat", "/api/abort", "/api/reset", "/api/upload"):
            return self._json(410, {"ok": False, "error": "该能力在本机看板已下线（410）"})

        if p == "/api/agent/render":
            return self._json(200, {"ok": True, "rendered": True, "seconds": 0.0,
                                    "note": "本机服务无 Excel 渲染步骤，render 为空操作"})
        return self._err(404, "not found", path=p)

    # ---------------------------------------------------------------- PATCH / DELETE
    def do_PATCH(self):
        if not self._auth_ok():
            return self._err(401, "unauthorized")
        if urlparse(self.path).path != "/api/agent/applications":
            return self._err(404, "not found")
        b = self._body()
        company = (b.get("company") or "").strip()
        if not company:
            return self._err(400, "missing company")
        row = store.update_application(CON, company, position=b.get("position"),
                                       status=b.get("status"), date=b.get("date"), n=b.get("n"))
        if row is None:
            return self._err(404, "application not found", company=company)
        return self._json(200, {"ok": True, "row": row, "action": "update"})

    def do_DELETE(self):
        if not self._auth_ok():
            return self._err(401, "unauthorized")
        p = urlparse(self.path).path
        b = self._body()
        if b.get("confirm") is not True:          # 契约：DELETE 先校验 confirm
            return self._err(400, "confirm:true required")
        company = (b.get("company") or "").strip()
        if p == "/api/agent/applications":
            if not company:
                return self._err(400, "missing company")
            n = store.delete_application(CON, company, b.get("position"))
            return self._json(200, {"ok": True, "deleted": n})
        if p == "/api/agent/exams":
            n = store.remove_exam(CON, exam_id=b.get("id"), company=company or None)
            return self._json(200, {"ok": True, "deleted": n})
        if p == "/api/agent/unapplied":
            if not company:
                return self._err(400, "missing company")
            n = store.exclude_unapplied(CON, company)
            return self._json(200, {"ok": True, "excluded": n})
        return self._err(404, "not found", path=p)

    # ---------------------------------------------------------------- 静态
    def _static(self, name):
        safe = os.path.normpath(name).lstrip("\\/").replace("..", "")
        path = os.path.join(STATIC, safe)
        if not os.path.isfile(path):
            return self._err(404, "static not found", path=safe)
        ctype = {"html": "text/html; charset=utf-8", "js": "application/javascript; charset=utf-8",
                 "css": "text/css; charset=utf-8"}.get(safe.rsplit(".", 1)[-1], "text/plain")
        with open(path, "rb") as f:
            self._send(200, f.read(), ctype)


def build(host, port, db, token=""):
    global CON, TOKEN
    CON = store.connect(db)
    TOKEN = token or ""
    httpd = ThreadingHTTPServer((host, port), Handler)
    return httpd


def main(argv=None):
    ap = argparse.ArgumentParser(description="本机投递看板（/api/agent/* 同形实现）")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8898)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--seed", help="从 board_data.json 导入初始数据（幂等）")
    ap.add_argument("--token", default=os.environ.get("BOARD_TOKEN", ""))
    a = ap.parse_args(argv)

    if a.seed:
        con = store.connect(a.db)
        counts = store.import_snapshot(con, a.seed)
        print("已导入:", json.dumps(counts, ensure_ascii=False))
        con.close()

    httpd = build(a.host, a.port, a.db, a.token)
    url = "http://%s:%d" % (a.host, a.port)
    print("本机看板已启动: %s   （Ctrl+C 停止）" % url)
    print("API: %s/api/agent/overview" % url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
