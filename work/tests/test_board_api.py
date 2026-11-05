# -*- coding: utf-8 -*-
"""test_board_api.py — 本机看板 /api/agent/* 的端到端回归（不碰真实数据、不连外网）。

跑法：python work/tests/test_board_api.py
"""
import http.client
import json
import os
import sys
import tempfile
import threading
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "work", "board"))

import server  # noqa: E402
import store   # noqa: E402

SNAPSHOT = {
    "apps": [
        {"company": "甲公司", "position": "后端开发", "status": "已投递", "date": "2026-10-01", "stageDate": "2026-10-01", "n": 1},
        {"company": "乙公司", "position": "算法", "status": "面试中", "date": "2026-10-05", "stageDate": "2026-10-05", "n": 1},
        {"company": "丙公司", "position": "测试", "status": "笔试挂", "date": "2026-10-09", "stageDate": "2026-10-09", "n": 2},
    ],
    "jobs": [{"company": "甲公司", "industry": "科技", "batch": "27届", "date": "2026-09-01", "direction": "后端", "status": "", "applied": "", "applied_at": ""}],
    "codes": [{"company": "甲公司", "group": "技术", "code": "ABC123", "refOnly": False}],
    "unapplied": [
        {"company": "丁公司", "industry": "制造", "batch": "27届", "date": "2026.10.02", "direction": "研发", "code": "", "source": "岗位库"},
        {"company": "戊公司", "industry": "科技", "batch": "27届", "date": "2026.10.03", "direction": "测试", "code": "", "source": "岗位库"},
    ],
    "ended": [], "rules": [],
    "exams": [{"company": "乙公司", "kind": "面试", "when": "2026-10-20 10:00", "place": "线上", "link": "", "note": ""}],
    "links": {"甲公司": {"url": "https://example.com/a", "code": "ABC123", "note": "", "updated": "2026-10-01"}},
}


def start(token=""):
    tmp = tempfile.mkdtemp(prefix="board-")
    db = os.path.join(tmp, "board.db")
    snap = os.path.join(tmp, "snap.json")
    json.dump(SNAPSHOT, open(snap, "w", encoding="utf-8"), ensure_ascii=False)
    con = store.connect(db)
    counts = store.import_snapshot(con, snap)
    con.close()
    httpd = server.build("127.0.0.1", 0, db, token)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1], counts


def call(port, method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    c.request(method, path, payload, h)
    r = c.getresponse()
    raw = r.read().decode("utf-8")
    c.close()
    try:
        return r.status, json.loads(raw)
    except ValueError:
        return r.status, raw


def test_overview_and_stats():
    httpd, port, counts = start()
    try:
        assert counts["applications"] == 3, counts
        st, d = call(port, "GET", "/api/agent/overview")
        assert st == 200 and d["ok"], d
        assert d["stats"]["n_app"] == 3, d["stats"]
        assert d["stats"]["failed"] == 1 and d["stats"]["active"] == 1, d["stats"]
        st, txt = call(port, "GET", "/api/agent/overview?format=text")
        assert st == 200 and isinstance(txt, str) and "投递概览" in txt, txt
    finally:
        httpd.shutdown()


def test_limit_clamping_and_offset():
    httpd, port, _ = start()
    try:
        _, d = call(port, "GET", "/api/agent/applications?limit=0")
        assert d["limit"] == 1 and len(d["items"]) == 1, d     # limit<=0 钳到 1
        _, d = call(port, "GET", "/api/agent/applications?limit=9999")
        assert d["limit"] == 500, d
        _, d = call(port, "GET", "/api/agent/applications?offset=99")
        assert d["items"] == [] and d["total"] == 3, d         # offset 越界返回空 items
        _, d = call(port, "GET", "/api/agent/applications?offset=-5")
        assert d["offset"] == 0, d
        dates = [r["date"] for r in d["items"]]
        assert dates == sorted(dates, reverse=True), dates      # 纠正：一律 date 降序
    finally:
        httpd.shutdown()


def test_company_lookup():
    httpd, port, _ = start()
    try:
        st, d = call(port, "GET", "/api/agent/company?name=" + quote("甲公司"))
        assert st == 200 and d["company"] == "甲公司", d
        assert d["matched_company"] == "甲公司", d
        assert d["applications"][0]["referral_code"] == "ABC123", d
        assert isinstance(d["applications"][0]["apply_link"], dict), d   # 恒为 object
        st, d = call(port, "GET", "/api/agent/company?name=" + quote("不存在的公司"))
        assert st == 404 and d["ok"] is False, (st, d)
        st, d = call(port, "GET", "/api/agent/company")
        assert st == 404, st                                  # 缺参 404（契约）
    finally:
        httpd.shutdown()


def test_write_paths_idempotent():
    httpd, port, _ = start()
    try:
        st, d = call(port, "POST", "/api/agent/applications", {"company": "己公司", "position": "前端"})
        assert st == 200 and d["created"] is True, d
        st, d = call(port, "POST", "/api/agent/applications", {"company": "己公司", "position": "前端"})
        assert d["created"] is False and d["action"] == "noop", d
        st, d = call(port, "PATCH", "/api/agent/applications", {"company": "己公司", "status": "面试中"})
        assert d["row"]["status_category"] == "active", d
        st, d = call(port, "POST", "/api/agent/applications", {"position": "缺公司"})
        assert st == 400, (st, d)
        st, d = call(port, "DELETE", "/api/agent/applications", {"company": "己公司"})
        assert st == 400, (st, d)                             # 没有 confirm 不放行
        st, d = call(port, "DELETE", "/api/agent/applications", {"company": "己公司", "confirm": True})
        assert st == 200 and d["deleted"] == 1, d
    finally:
        httpd.shutdown()


def test_exams_and_unapplied():
    httpd, port, _ = start()
    try:
        st, d = call(port, "POST", "/api/agent/exams",
                     {"company": "乙公司", "kind": "面试", "when": "2026-10-20 10:00"})
        assert st == 200 and d["created"] is False, d          # 幂等：同公司+类型+时间
        st, d = call(port, "POST", "/api/agent/exams",
                     {"company": "乙公司", "kind": "笔试", "when": "2026-10-21 10:00"})
        assert d["created"] is True, d
        st, d = call(port, "GET", "/api/agent/unapplied")
        assert d["total"] == 2, d                              # 甲乙丙已投，丁戊未投
        st, d = call(port, "DELETE", "/api/agent/unapplied", {"company": "丁公司", "confirm": True})
        assert d["excluded"] == 1, d
        _, d = call(port, "GET", "/api/agent/unapplied")
        assert d["total"] == 1, d
    finally:
        httpd.shutdown()


def test_page_injects_live_data():
    """首页必须是模板实时注入：数据在、__DATA__ 不残留、标题可读。"""
    httpd, port, _ = start()
    try:
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.request("GET", "/")
        r = c.getresponse()
        html = r.read().decode("utf-8")
        c.close()
        assert r.status == 200, r.status
        assert "<title>投递看板</title>" in html, "标题未替换"
        assert "__DATA__" not in html, "仍有未注入的 __DATA__ 占位"
        assert "甲公司" in html, "示例数据未注入"
        assert 'id="statCards"' in html and 'id="navBar"' in html, "模板骨架缺失"
    finally:
        httpd.shutdown()


def test_auth_and_info():
    httpd, port, _ = start(token="s3cret")
    try:
        st, d = call(port, "GET", "/api/agent/overview")
        assert st == 401, (st, d)
        st, d = call(port, "GET", "/api/agent/overview", headers={"X-QZ-Token": "s3cret"})
        assert st == 200, st
        st, d = call(port, "GET", "/api/agent/info", headers={"X-QZ-Token": "s3cret"})
        assert d["version"] == "1.4.0" and len(d["endpoints"]) >= 15, d
        st, d = call(port, "GET", "/api/agent/manual", headers={"X-QZ-Token": "s3cret"})
        assert st == 200 and isinstance(d, str) and "api/agent" in d, d
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
        print("ok  %s" % fn.__name__)
    print("PASS  board API %d 组" % len(tests))
