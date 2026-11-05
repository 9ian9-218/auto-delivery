# -*- coding: utf-8 -*-
"""store.py — 本机看板的数据层（SQLite，零第三方依赖）。

设计要点（决策记录见 map #2 / #7）：
- 存储用 SQLite：stdlib 自带、单文件、可事务、可查询；不引入 ORM。
- 旧看板的数据形态照抄（字段名、键集、apply_link 恒为 object 或 ""），
  但纠正两处怪异行为：applications 一律按 date 降序；company 查询回 matched_company。
- status_category 是看板的展示语义，与 work/ckpt.schema.json 的 6 态流程语义是两套东西，不要混用。
"""
import json
import os
import sqlite3
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company TEXT NOT NULL, position TEXT NOT NULL, status TEXT NOT NULL,
  date TEXT, stage_date TEXT, n INTEGER DEFAULT 1,
  UNIQUE(company, position)
);
CREATE TABLE IF NOT EXISTS jobs (
  company TEXT PRIMARY KEY, industry TEXT, batch TEXT, date TEXT,
  direction TEXT, status TEXT, applied TEXT, applied_at TEXT
);
CREATE TABLE IF NOT EXISTS codes (
  company TEXT, grp TEXT, code TEXT, ref_only INTEGER DEFAULT 0,
  PRIMARY KEY(company, code)
);
CREATE TABLE IF NOT EXISTS unapplied (
  company TEXT PRIMARY KEY, industry TEXT, batch TEXT, date TEXT,
  direction TEXT, code TEXT, source TEXT, excluded INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ended (
  company TEXT, batch TEXT, date TEXT, PRIMARY KEY(company, batch, date)
);
CREATE TABLE IF NOT EXISTS rules (
  company TEXT, field TEXT, rule TEXT, PRIMARY KEY(company, field, rule)
);
CREATE TABLE IF NOT EXISTS exams (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company TEXT, kind TEXT, when_ TEXT, place TEXT, link TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS links (
  company TEXT PRIMARY KEY, url TEXT, code TEXT, note TEXT, updated TEXT
);
CREATE TABLE IF NOT EXISTS notices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company TEXT, text TEXT, created_at TEXT, read INTEGER DEFAULT 0
);
"""

PROGRESS_KEYS = ("笔试", "测评", "AI面", "面试")
FAIL_KEYS = ("挂", "未通过", "淘汰", "不合适", "已结束", "终止")
OFFER_KEYS = ("offer", "Offer", "OFFER", "录用", "意向书")


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today():
    return datetime.now().strftime("%Y-%m-%d")


def connect(db_path):
    d = os.path.dirname(os.path.abspath(db_path))
    if d:
        os.makedirs(d, exist_ok=True)
    con = sqlite3.connect(db_path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def status_category(s):
    s = (s or "").strip()
    if not s:
        return "other"
    if any(k in s for k in OFFER_KEYS):
        return "offer"
    if any(k in s for k in FAIL_KEYS):
        return "failed"
    if any(k in s for k in PROGRESS_KEYS):
        return "active"
    if "投递" in s or "已投" in s:
        return "applied"
    return "other"


def is_progressed(s):
    return any(k in (s or "") for k in PROGRESS_KEYS)


def _rows(con, sql, args=()):
    return [dict(r) for r in con.execute(sql, args).fetchall()]


def _exam_rows(con, where="", args=()):
    rows = _rows(con, "SELECT id, company, kind, when_, place, link, note FROM exams" + where +
                 " ORDER BY when_", args)
    return [{"id": r["id"], "company": r["company"], "kind": r["kind"], "when": r["when_"],
             "place": r["place"], "link": r["link"], "note": r["note"]} for r in rows]


# ---------------------------------------------------------------- 读取
def applications(con, status=None, company=None, direction=None, limit=100, offset=0):
    lim = 1 if int(limit) <= 0 else min(int(limit), 500)   # 契约：limit<=0 钳到 1，不是回落默认
    off = max(int(offset), 0)
    where, args = [], []
    if status:
        where.append("status = ?"); args.append(status)
    if company:
        where.append("company LIKE ?"); args.append("%" + company + "%")
    if direction:
        where.append("position LIKE ?"); args.append("%" + direction + "%")
    w = (" WHERE " + " AND ".join(where)) if where else ""
    total = con.execute("SELECT COUNT(*) FROM applications" + w, args).fetchone()[0]
    rows = _rows(con, "SELECT * FROM applications" + w +
                 " ORDER BY date DESC, id DESC LIMIT ? OFFSET ?", args + [lim, off])
    return total, lim, off, [app_row(con, r) for r in rows]


def job_of(con, company):
    r = con.execute("SELECT * FROM jobs WHERE company = ?", (company,)).fetchone()
    return dict(r) if r else None


def code_of(con, company):
    r = con.execute("SELECT * FROM codes WHERE company = ? ORDER BY ref_only LIMIT 1",
                    (company,)).fetchone()
    return dict(r) if r else None


def link_of(con, company):
    r = con.execute("SELECT * FROM links WHERE company = ?", (company,)).fetchone()
    if not r:
        return ""
    return {k: r[k] for k in r.keys() if k != "company" and r[k] not in (None, "")}


def exams_of(con, company):
    return _exam_rows(con, " WHERE company = ?", (company,))


def app_row(con, a):
    job = job_of(con, a["company"]) or {}
    code = code_of(con, a["company"]) or {}
    return {
        "company": a["company"],
        "position": a["position"],
        "status": a["status"],
        "status_category": status_category(a["status"]),
        "date": a["date"],
        "stageDate": a["stage_date"],
        "n": a["n"],
        "industry": job.get("industry", ""),
        "batch": job.get("batch", ""),
        "referral_code": code.get("code", ""),
        "apply_link": link_of(con, a["company"]),   # 恒为 object 或 ""，永不为 null
        "exams": exams_of(con, a["company"]),
        "applied_at": job.get("applied_at", "") or a["date"],
    }


def company(con, name):
    exact = _rows(con, "SELECT * FROM applications WHERE company = ? ORDER BY date DESC", (name,))
    if exact:
        matched, rows = name, exact
    else:
        like = _rows(con, "SELECT * FROM applications WHERE company LIKE ? ORDER BY date DESC",
                     ("%" + name + "%",))
        if not like:
            return None
        names = list(dict.fromkeys(r["company"] for r in like))
        matched = names[0]
        rows = [r for r in like if r["company"] == matched]
    return {
        "ok": True,
        "company": matched,
        "query": name,
        "matched_company": matched,          # 纠正：把命中的公司显式回给调用方
        "candidates": list(dict.fromkeys([matched])),
        "applications": [app_row(con, r) for r in rows],
        "job_info": job_of(con, matched) or {},
        "referral": code_of(con, matched) or {},
        "link": link_of(con, matched),
        "exams": exams_of(con, matched),
    }


def unapplied(con, direction=None, company=None, industry=None,
              limit=50, offset=0, exclude_applied=True):
    lim = 1 if int(limit) <= 0 else min(int(limit), 200)
    off = max(int(offset), 0)
    where, args = ["excluded = 0"], []
    if direction:
        where.append("direction LIKE ?"); args.append("%" + direction + "%")
    if company:
        where.append("company LIKE ?"); args.append("%" + company + "%")
    if industry:
        where.append("industry = ?"); args.append(industry)
    if exclude_applied:
        where.append("company NOT IN (SELECT DISTINCT company FROM applications)")
    w = " WHERE " + " AND ".join(where)
    total = con.execute("SELECT COUNT(*) FROM unapplied" + w, args).fetchone()[0]
    rows = _rows(con, "SELECT * FROM unapplied" + w + " ORDER BY date DESC LIMIT ? OFFSET ?",
                 args + [lim, off])
    return total, lim, off, [{k: r[k] for k in r if k != "excluded"} for r in rows]


def exams(con):
    return _exam_rows(con)


def notices(con, limit=30):
    lim = int(limit)
    if lim == 0:
        rows = _rows(con, "SELECT * FROM notices ORDER BY created_at DESC")
    else:
        rows = _rows(con, "SELECT * FROM notices ORDER BY created_at DESC LIMIT ?",
                     (lim if lim > 0 else 1,))
    unread = con.execute("SELECT COUNT(*) FROM notices WHERE read = 0").fetchone()[0]
    return unread, [{"company": r["company"], "text": r["text"], "at": r["created_at"]} for r in rows]


def stats(con):
    rows = con.execute("SELECT company, status FROM applications").fetchall()
    cats = [status_category(r["status"]) for r in rows]
    return {
        "n_app": len(rows),
        "n_company": con.execute("SELECT COUNT(DISTINCT company) FROM applications").fetchone()[0],
        "n_pos": con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],
        "n_unapplied": con.execute("SELECT COUNT(*) FROM unapplied WHERE excluded = 0").fetchone()[0],
        "failed": cats.count("failed"),
        "active": cats.count("active"),
        "offer": cats.count("offer"),
        "progressed": sum(1 for r in rows if is_progressed(r["status"])),
    }


# ---------------------------------------------------------------- 写入
def create_application(con, company, position, status="已投递", date=None, n=1):
    date = date or today()
    cur = con.execute(
        "INSERT OR IGNORE INTO applications(company, position, status, date, stage_date, n) "
        "VALUES(?,?,?,?,?,?)", (company, position, status, date, date, max(int(n or 1), 1)))
    con.commit()
    created = cur.rowcount > 0
    row = con.execute("SELECT * FROM applications WHERE company=? AND position=?",
                      (company, position)).fetchone()
    return created, app_row(con, dict(row))


def update_application(con, company, position=None, status=None, date=None, n=None):
    where, args = "company = ?", [company]
    if position:
        where += " AND position = ?"; args.append(position)
    row = con.execute("SELECT * FROM applications WHERE " + where +
                      " ORDER BY date DESC LIMIT 1", args).fetchone()
    if not row:
        return None
    con.execute("UPDATE applications SET status=?, date=?, stage_date=?, n=? WHERE id=?",
                (status or row["status"], date or row["date"], date or row["stage_date"],
                 int(n) if n is not None else row["n"], row["id"]))
    con.commit()
    return app_row(con, dict(con.execute("SELECT * FROM applications WHERE id=?",
                                         (row["id"],)).fetchone()))


def delete_application(con, company, position=None):
    where, args = "company = ?", [company]
    if position:
        where += " AND position = ?"; args.append(position)
    cur = con.execute("DELETE FROM applications WHERE " + where, args)
    con.commit()
    return cur.rowcount


def upsert_job(con, company, **kw):
    existing = job_of(con, company)
    base = existing or {}
    merged = {k: kw.get(k, base.get(k) or "") for k in
              ("industry", "batch", "date", "direction", "status", "applied", "applied_at")}
    con.execute(
        "INSERT INTO jobs(company, industry, batch, date, direction, status, applied, applied_at) "
        "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(company) DO UPDATE SET "
        "industry=excluded.industry, batch=excluded.batch, date=excluded.date, "
        "direction=excluded.direction, status=excluded.status, applied=excluded.applied, "
        "applied_at=excluded.applied_at",
        (company, merged["industry"], merged["batch"], merged["date"], merged["direction"],
         merged["status"], merged["applied"], merged["applied_at"]))
    con.commit()
    return existing is None, job_of(con, company)


def add_exam(con, company, kind, when, place="", link="", note=""):
    dup = con.execute("SELECT id FROM exams WHERE company=? AND kind=? AND when_=?",
                      (company, kind, when)).fetchone()
    if dup:
        return False, dup["id"]
    cur = con.execute("INSERT INTO exams(company, kind, when_, place, link, note) "
                      "VALUES(?,?,?,?,?,?)", (company, kind, when, place, link, note))
    con.commit()
    return True, cur.lastrowid


def remove_exam(con, exam_id=None, company=None):
    if exam_id is not None:
        cur = con.execute("DELETE FROM exams WHERE id = ?", (exam_id,))
    else:
        cur = con.execute("DELETE FROM exams WHERE company = ?", (company,))
    con.commit()
    return cur.rowcount


def exclude_unapplied(con, company):
    cur = con.execute("UPDATE unapplied SET excluded = 1 WHERE company = ?", (company,))
    con.commit()
    return cur.rowcount


# ---------------------------------------------------------------- 迁移
# ---------------------------------------------------------------- 页面数据
def blob(con):
    """一次性导出看板渲染所需的 8 个集合 + stats（形状对齐旧看板的页面 DATA）。"""
    apps = [{"company": r["company"], "position": r["position"], "status": r["status"],
             "date": r["date"], "stageDate": r["stage_date"], "n": r["n"]}
            for r in _rows(con, "SELECT * FROM applications ORDER BY date DESC, id DESC")]
    jobs = [{k: r[k] for k in ("company", "industry", "batch", "date", "direction",
                               "status", "applied", "applied_at")}
            for r in _rows(con, "SELECT * FROM jobs ORDER BY date DESC, company")]
    codes = [{"company": r["company"], "group": r["grp"], "code": r["code"],
              "refOnly": bool(r["ref_only"])}
             for r in _rows(con, "SELECT * FROM codes ORDER BY company")]
    unap = [{k: r[k] for k in ("company", "industry", "batch", "date", "direction", "code", "source")}
            for r in _rows(con, "SELECT * FROM unapplied WHERE excluded = 0 ORDER BY date DESC")]
    ended = [[r["company"], r["batch"], r["date"]]
             for r in _rows(con, "SELECT * FROM ended ORDER BY date DESC")]
    rules = [[r["company"], r["field"], r["rule"]]
             for r in _rows(con, "SELECT * FROM rules ORDER BY company")]
    exam_rows = [{"company": r["company"], "kind": r["kind"], "when": r["when_"],
                  "place": r["place"], "link": r["link"], "note": r["note"]}
                 for r in _rows(con, "SELECT company, kind, when_, place, link, note FROM exams ORDER BY when_")]
    link_rows = {r["company"]: {k: r[k] for k in ("url", "code", "note", "updated")}
                 for r in _rows(con, "SELECT * FROM links ORDER BY company")}
    st = stats(con)
    cats = [status_category(r["status"]) for r in _rows(con, "SELECT status FROM applications")]
    failed_co = len({r["company"] for r in _rows(con, "SELECT company, status FROM applications")
                     if status_category(r["status"]) == "failed"})
    st["failed_co"] = failed_co
    return {"apps": apps, "jobs": jobs, "codes": codes, "unapplied": unap,
            "ended": ended, "rules": rules, "exams": exam_rows, "links": link_rows,
            "stats": st, "updated": now(), "today": today()}


def import_snapshot(con, path):
    """把 board_data.json（旧看板的页面渲染 blob）导入本机库，返回各表计数。"""
    d = json.load(open(path, encoding="utf-8"))
    counts = {}
    for a in d.get("apps", []):
        con.execute("INSERT OR IGNORE INTO applications(company, position, status, date, stage_date, n) "
                    "VALUES(?,?,?,?,?,?)",
                    (a.get("company", ""), a.get("position", ""), a.get("status", ""),
                     a.get("date", ""), a.get("stageDate", a.get("date", "")),
                     int(a.get("n") or 1)))
    counts["applications"] = len(d.get("apps", []))
    for j in d.get("jobs", []):
        con.execute("INSERT OR REPLACE INTO jobs(company, industry, batch, date, direction, status, "
                    "applied, applied_at) VALUES(?,?,?,?,?,?,?,?)",
                    (j.get("company", ""), j.get("industry", ""), j.get("batch", ""),
                     j.get("date", ""), j.get("direction", ""), j.get("status", ""),
                     str(j.get("applied", "")), j.get("applied_at", "")))
    counts["jobs"] = len(d.get("jobs", []))
    for c in d.get("codes", []):
        con.execute("INSERT OR IGNORE INTO codes(company, grp, code, ref_only) VALUES(?,?,?,?)",
                    (c.get("company", ""), c.get("group", ""), c.get("code", ""),
                     1 if c.get("refOnly") else 0))
    counts["codes"] = len(d.get("codes", []))
    for u in d.get("unapplied", []):
        con.execute("INSERT OR IGNORE INTO unapplied(company, industry, batch, date, direction, "
                    "code, source) VALUES(?,?,?,?,?,?,?)",
                    (u.get("company", ""), u.get("industry", ""), u.get("batch", ""),
                     u.get("date", ""), u.get("direction", ""), u.get("code", ""),
                     u.get("source", "")))
    counts["unapplied"] = len(d.get("unapplied", []))
    for e in d.get("ended", []):
        if isinstance(e, list) and len(e) >= 3:
            con.execute("INSERT OR IGNORE INTO ended(company, batch, date) VALUES(?,?,?)",
                        (e[0], e[1], e[2]))
    counts["ended"] = len(d.get("ended", []))
    for r in d.get("rules", []):
        if isinstance(r, list) and len(r) >= 3:
            con.execute("INSERT OR IGNORE INTO rules(company, field, rule) VALUES(?,?,?)",
                        (r[0], r[1], r[2]))
    counts["rules"] = len(d.get("rules", []))
    for x in d.get("exams", []):
        con.execute("INSERT INTO exams(company, kind, when_, place, link, note) VALUES(?,?,?,?,?,?)",
                    (x.get("company", ""), x.get("kind", ""), x.get("when", ""),
                     x.get("place", ""), x.get("link", ""), x.get("note", "")))
    counts["exams"] = len(d.get("exams", []))
    for name, v in (d.get("links") or {}).items():
        if isinstance(v, dict):
            con.execute("INSERT OR REPLACE INTO links(company, url, code, note, updated) "
                        "VALUES(?,?,?,?,?)",
                        (name, v.get("url", ""), v.get("code", ""), v.get("note", ""),
                         v.get("updated", "")))
    counts["links"] = len(d.get("links") or {})
    con.commit()
    return counts
