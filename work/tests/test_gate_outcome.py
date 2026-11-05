# -*- coding: utf-8 -*-
"""交付门三态回归：delivered / rejected / overridden。

对应 SELF_LEARNING_LOOP §5.1 与 loop.py cmd_gate。
用 pytest 或直接 `python work/tests/test_gate_outcome.py` 都能跑。
不连浏览器、不读写真实 ledger：全部在临时目录里构造 state + review + 截图。
"""
import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AUTOFILL_ROOT = os.environ.get("RESUME_AUTOFILL_ROOT", os.path.join(_REPO, "resume-autofill"))
LOOP = os.path.join(AUTOFILL_ROOT, "tools", "loop.py")
TZ = timezone(timedelta(hours=8))


def load_loop(ledger_dir):
    spec = importlib.util.spec_from_file_location("rfa_loop_under_test", LOOP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.LEDGER_DIR = ledger_dir
    mod.SHOT_DIR = os.path.join(ledger_dir, "shots")
    return mod


def build(tmp, *, checks_ok=True):
    """造一份可交付的 state+review；checks_ok=False 时故意缺一项视觉复核。"""
    shot_dir = os.path.join(tmp, "shots")
    os.makedirs(shot_dir, exist_ok=True)
    shot_path = os.path.join(shot_dir, "run-final.png")
    with open(shot_path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"fixture-bytes")
    sha = hashlib.sha256(open(shot_path, "rb").read()).hexdigest()

    taken = datetime(2026, 11, 1, 20, 15, 0, tzinfo=TZ)
    state = {
        "run": "r-fixture-1", "site": "fixture.zhiye.com", "rounds": 1,
        "clean": True, "learn_failed": False, "left": [],
        "rowPlan": [{"section": "educations", "label": "教育经历", "rowShaped": True,
                     "profileRecords": 2, "domRows": 2, "gap": 0}],
        "finalShot": {"path": shot_path, "sha256": sha, "fullPage": True,
                      "takenAt": taken.isoformat(timespec="seconds")},
        # 交付门的冷启动硬条件（loop.py gate_reasons）：刷新后空页 + 扩展自己填 + 同一张截图
        "coldStart": {"pageWasEmpty": True, "ok": True, "site": "fixture.zhiye.com",
                      "reasons": [], "shot": {"path": shot_path, "sha256": sha}},
    }
    checks = {"requiredFilled": True, "noRedText": True,
              "choiceStates": True, "rowStructure": True}
    if not checks_ok:
        checks["noRedText"] = False
    review = {
        "run": "r-fixture-1", "shot": "run-final.png", "sha256": sha,
        "reviewedAt": (taken + timedelta(minutes=5)).isoformat(timespec="seconds"),
        "checks": checks, "sectionRows": {"educations": 2},
        "anomalies": [], "notes": "fixture",
    }
    sp = os.path.join(tmp, "state.json")
    rp = os.path.join(tmp, "review.json")
    json.dump(state, open(sp, "w", encoding="utf-8"), ensure_ascii=False)
    json.dump(review, open(rp, "w", encoding="utf-8"), ensure_ascii=False)
    return sp, rp


def ledger_rows(ledger_dir):
    rows = []
    for name in os.listdir(ledger_dir):
        if not name.endswith(".jsonl"):
            continue
        with open(os.path.join(ledger_dir, name), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


def run_case(name, *, checks_ok, override=False):
    tmp = tempfile.mkdtemp(prefix="gate-")
    ledger = os.path.join(tmp, "ledger")
    os.makedirs(ledger, exist_ok=True)
    sp, rp = build(tmp, checks_ok=checks_ok)
    mod = load_loop(ledger)
    args = [rp, sp]
    if override:
        args += ["user", "站点字典缺苏州科达，用户确认可推进"]
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = mod.cmd_gate(*args)
    rows = ledger_rows(ledger)
    assert len(rows) == 1, f"{name}: 台账应写 1 行，实际 {len(rows)}"
    row = rows[0]
    # stdout = 一段 JSON 结论 + 一行人话；只取 JSON 那一段
    text = buf.getvalue()
    out, _ = json.JSONDecoder().raw_decode(text[text.index("{"):])
    return name, code, row, out


def test_matrix():
    got = {}
    for name, kw in (
        ("clean", dict(checks_ok=True)),
        ("reject", dict(checks_ok=False)),
        ("override", dict(checks_ok=False, override=True)),
    ):
        got[name] = run_case(name, **kw)

    # 1) 干净 → delivered，exit 0，deliverable true
    _, code, row, out = got["clean"]
    assert code == 0, f"clean exit={code}"
    assert row["outcome"] == "delivered", row["outcome"]
    assert out["deliverable"] is True and out["reasons"] == []

    # 2) 视觉复核缺项 → rejected，exit 2，绝不能记成 skipped/delivered
    _, code, row, out = got["reject"]
    assert code == 2, f"reject exit={code}"
    assert row["outcome"] == "rejected", row["outcome"]
    assert row["override"] is None
    assert "CHECKLIST_MISSING:noRedText" in row["reasons"]
    assert out["deliverable"] is False

    # 3) 用户签字覆盖 → overridden，exit 3，reasons 仍全量留证
    _, code, row, out = got["override"]
    assert code == 3, f"override exit={code}"
    assert row["outcome"] == "overridden", row["outcome"]
    assert row["override"]["by"] == "user"
    assert row["override"]["reason"].startswith("站点字典缺苏州科达")
    assert row["reasons"], "覆盖不得清空 reasons"
    assert out["deliverable"] is False, "覆盖不等于过门"

    # 4) 三态之外不存在 gate 的 skipped
    assert {r[2]["outcome"] for r in got.values()} == {
        "delivered", "rejected", "overridden"}


def test_override_only_user():
    """agent 不得代签：--override-by 只接受 user（走 main 的入口校验）。"""
    tmp = tempfile.mkdtemp(prefix="gate-cli-")
    os.makedirs(os.path.join(tmp, "ledger"), exist_ok=True)
    sp, rp = build(tmp, checks_ok=False)
    mod = load_loop(os.path.join(tmp, "ledger"))
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = mod.main(["gate", "--review", rp, "--state", sp, "--override-by", "agent"])
    assert code == 2
    assert "只接受 user" in buf.getvalue()
    assert not os.listdir(os.path.join(tmp, "ledger")) or \
        all(not n.endswith(".jsonl") for n in os.listdir(os.path.join(tmp, "ledger"))), \
        "被拒绝的代签不得写入台账"


if __name__ == "__main__":
    test_matrix()
    test_override_only_user()
    print("PASS  gate 三态 + 代签拦截（4 组断言）")
