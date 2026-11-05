# -*- coding: utf-8 -*-
"""pipeline.py — 自动投递流水线编排器

把 skill 的 5 个步骤串成一条可执行链路，每一步都可独立跑、可断点续跑：

  step1  拉清单    node fetch_shortlist.mjs --top N --out shortlist.json
  step2  挑选      按档位排序，输出待处理公司（附入选理由）
  step3  核实岗位  对每家用 WebSearch/WebFetch 核实（由 agent 执行，脚本只给待办清单）
  step4  排队      生成待进场清单（**本脚本不投递**；投递按 campus-apply-pipeline 三道闸门逐单执行）
  step5  回写      notify：只接受官网核验成功的记录（verified + proof），否则拒收

安全设计：**本脚本没有任何提交能力**。历史版本的 `--submit` 只打印不可逆提交文案、
`notify` 会直接把 result.json 写成「已投递」，两条都是绕过三道闸门的后门，已封堵：
`--submit` 只产出 `work/submit_queue.json` 待进场清单；`notify` 对未核验记录一律拒收。

用法:
  python pipeline.py status [--start]           # 等价于 preflight（--start 才启动 8792）
  python pipeline.py shortlist --top 8          # 拉清单+挑选，落盘 shortlist.json
  python pipeline.py plan                       # 打印 step3 待核实清单
  python pipeline.py submit --only "公司A,公司B"  # 生成待进场清单（不提交）
  python pipeline.py notify --file result.json  # 回写**已核验**的投递记录
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

SKILL_DIR = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_DIR / "scripts"
WORK = SKILL_DIR / "work"
WORK.mkdir(exist_ok=True)


def _load_cfg():
    """优先 work/tools/user_config.py，回退旧 config.json。"""
    for parent in Path(__file__).resolve().parents:
        cand = parent / "work" / "tools" / "user_config.py"
        if cand.is_file():
            import importlib.util
            spec = importlib.util.spec_from_file_location("_ad_user_config", cand)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            c = mod.load()
            return {
                "dashboard_url": c.get("dashboard_url"),
                "target_grad_year": c.target_grad_year,
                "default_pick_count": c.default_pick_count,
                "browser_service": c.browser_service,
            }
    with open(SKILL_DIR / "config.json", encoding="utf-8") as f:
        return json.load(f)


CFG = _load_cfg()


def node_path() -> str:
    """优先用 PATH 里的 node；不在 PATH 时读 NODE_BIN（不 glob C:\\Users）。"""
    cands = ["node"]
    env_bin = os.environ.get("NODE_BIN", "").strip()
    if env_bin:
        cands.insert(0, env_bin)
    for cand in cands:
        try:
            out = subprocess.run([cand, "-v"], capture_output=True, text=True, timeout=10)
            if out.returncode == 0:
                return cand
        except Exception:                                      # noqa: BLE001
            continue
    raise SystemExit("NEED_NODE：不在 PATH 时请设 NODE_BIN=<node 绝对路径>")


def run(cmd: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=kw.pop("timeout", 300), **kw)


def step_shortlist(top: int) -> dict:
    out_file = WORK / "shortlist.json"
    r = run([node_path(), str(SCRIPTS / "fetch_shortlist.mjs"),
             "--top", str(top), "--url", CFG["dashboard_url"], "--out", str(out_file)])
    if r.returncode != 0:
        print(f"[fail] 清单拉取失败: {r.stderr.strip()[:400]}", file=sys.stderr)
        return {}
    data = json.loads(out_file.read_text(encoding="utf-8"))
    meta, sl = data.get("meta", {}), data.get("shortlist", [])
    print(f"[ok] 拉取成功: dashboard 更新 {meta.get('dashboard_updated')} · "
          f"未投递 {meta.get('total_unapplied')} 家 → 匹配 {meta.get('matched')} 家，取前 {len(sl)} 家")
    print(f"     清单已落盘: {out_file}")
    if meta.get("stats"):
        print(f"     过滤统计: {json.dumps(meta['stats'], ensure_ascii=False)}")
    # 挑选：S 档优先，其次新鲜度
    picked = sorted(sl, key=lambda c: (c["tier"] != "S", c.get("stale", False)))
    (WORK / "picked.json").write_text(
        json.dumps({"picked_at": meta.get("fetched_at"), "companies": picked},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] 挑选结果已落盘: {WORK / 'picked.json'}（{len(picked)} 家）")
    return {"meta": meta, "picked": picked}


def step_plan() -> list:
    pf = WORK / "picked.json"
    if not pf.exists():
        print("还没有清单，先跑: python pipeline.py shortlist", file=sys.stderr)
        return []
    picked = json.loads(pf.read_text(encoding="utf-8"))["companies"]
    print("\n# 待核实岗位清单（step3：逐家进官网/内推核实）\n")
    for i, c in enumerate(picked, 1):
        ref = c.get("referral") or {}
        print(f"{i}. **{c['company']}** [{c['tier']}档{'⚠️数据过期' if c.get('stale') else ''}]")
        print(f"   - 行业: {c.get('industry','')} | 批次: {c.get('batch','')}")
        print(f"   - 方向: {c.get('direction','')[:70]}")
        print(f"   - 内推: {ref.get('url') or '无'}")
        print(f"   - 入选理由: {c['tier']}档强相关方向"
              + ("、有内推链接优先" if ref.get("url") else "")
              + ("" if not c.get("stale") else "、⚠️采集日期超14天务必官网核实批次"))
        print()
    print("核实判据（全部满足才投）: 岗位名含 Agent/AI应用/大模型应用/LLM应用/AI开发；"
          f"面向 {CFG['target_grad_year']} 届；批次未截止；投递方式明确。")
    print("邮箱投递的批次只记录不自动发邮件。")
    return picked


def step_submit(only: str | None) -> dict:
    """生成待进场清单。**不提交任何东西**——提交只能按三道闸门逐单执行。"""
    pf = WORK / "picked.json"
    if not pf.exists():
        print("没有 picked.json，先跑 shortlist", file=sys.stderr)
        return {}
    picked = json.loads(pf.read_text(encoding="utf-8"))["companies"]
    targets = [c for c in picked if not only or c["company"] in only.split(",")]
    if not targets:
        print("没有匹配的目标公司", file=sys.stderr)
        return {}

    queue = {"generated_at": __import__("datetime").datetime.now().astimezone()
             .isoformat(timespec="seconds"), "count": len(targets), "targets": []}
    for c in targets:
        ref = c.get("referral") or {}
        queue["targets"].append({
            "company": c["company"], "tier": c.get("tier"),
            "entry": ref.get("url") or "需先站内查找",
            "state": "queued",
            "gate1": "not_granted",
        })
    out = WORK / "submit_queue.json"
    out.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[ok] 待进场清单已写入 {out}（{len(targets)} 家），未做任何提交")
    print("     每家按 campus-apply-pipeline 投递序列执行：")
    print("     ① 闸门1 用户授权岗位与数量 → ② 打开投递页核对岗位 ID →"
          " ③ RFA 闭环 0–10 步 → ④ 闸门2 `loop.py gate` → ⑤ 闸门3 复述+同意 → ⑥ 提交取证")
    print("     中间状态写 work/ckpt_<公司>.json（schema: work/ckpt.schema.json），"
          "官网核验成功后才回写看板。")
    return queue


def step_notify(result_file: str) -> None:
    """只回写**官网核验成功**的记录。未核验一律拒收，不给第二条路。"""
    pf = Path(result_file)
    if not pf.exists():
        print(f"找不到 {pf}", file=sys.stderr)
        return
    data = json.loads(pf.read_text(encoding="utf-8"))
    recs = data.get("records", [])
    if not recs:
        print("result.json 里没有 records，无需回写")
        return

    accepted, rejected = [], []
    for r in recs:
        proof = r.get("proof") or {}
        has_proof = bool(proof.get("application_id") or proof.get("record_url")
                         or proof.get("submitted_at"))
        if r.get("verified") is True and has_proof:
            accepted.append(r)
        else:
            rejected.append(r)

    if rejected:
        print(f"[拒收] {len(rejected)} 条记录没有官网核验证据（verified=true + proof），不回写：",
              file=sys.stderr)
        for r in rejected:
            print(f"   - {r.get('company')} / {r.get('position')}"
                  f"  verified={r.get('verified')!r} proof={bool(r.get('proof'))}", file=sys.stderr)
        print("   先按 application-playbook §5 核验官网应聘记录，补 "
              '{"verified": true, "proof": {"application_id": "...", "record_url": "..."}} 后重跑。',
              file=sys.stderr)
        print("   中间状态只写 work/ckpt_<公司>.json，不进看板。", file=sys.stderr)
    if not accepted:
        print("没有可回写的记录；本次不写看板。")
        return

    sys.path.insert(0, str(SCRIPTS))
    import qiuzhao_api
    client = qiuzhao_api.get_client()
    ok_count, fail_count = 0, 0
    for r in accepted:
        comp = r.get("company")
        pos = r.get("position")
        date = (r.get("proof") or {}).get("submitted_at") or r.get("date")
        link = (r.get("proof") or {}).get("record_url") or r.get("url")
        if not comp:
            continue
        try:
            res = client.record_application(
                company=comp,
                position=pos,
                status="已投递",
                date=date,
                render=False,
                notify=True,
            )
            if link:
                try:
                    client.upsert_job(company=comp, apply_link=link, render=False, notify=False)
                except Exception:
                    pass
            ok_count += 1
            print(f"[ok] 直写记录成功: {comp} - {pos or '默认岗位'}")
        except Exception as e:                                  # noqa: BLE001
            fail_count += 1
            print(f"[fail] 直写记录失败 {comp}: {e}", file=sys.stderr)

    if ok_count > 0:
        print("正在触发看板重新渲染...")
        try:
            client.render()
            print("[ok] 看板渲染刷新完成")
        except Exception as e:                                  # noqa: BLE001
            print(f"[warn] 看板渲染触发失败: {e}", file=sys.stderr)
    print(f"回写统计: 成功 {ok_count} 条，失败 {fail_count} 条，拒收 {len(rejected)} 条")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status").add_argument("--start", action="store_true",
                                         help="8792 未在线时启动 api_server（默认只检查）")
    s1 = sub.add_parser("shortlist"); s1.add_argument("--top", type=int, default=CFG["default_pick_count"])
    sub.add_parser("plan")
    s2 = sub.add_parser("submit"); s2.add_argument("--only", default=None)
    s2.add_argument("--submit", action="store_true",
                    help="已停用：本脚本不提交任何东西，仅生成待进场清单")
    s3 = sub.add_parser("notify"); s3.add_argument("--file", default=str(WORK / "result.json"))
    a = p.parse_args()

    if a.cmd == "status":
        cmd = [sys.executable, str(SCRIPTS / "preflight.py")] + (["--start"] if a.start else [])
        r = run(cmd, timeout=300)
        print(r.stdout or r.stderr)
        return r.returncode
    if a.cmd == "shortlist":
        step_shortlist(a.top)
        return 0
    if a.cmd == "plan":
        step_plan()
        return 0
    if a.cmd == "submit":
        if a.submit:
            print("[notice] --submit 已停用：本脚本没有提交能力，"
                  "投递只能按三道闸门逐单执行。已忽略该参数。")
        step_submit(a.only)
        return 0
    if a.cmd == "notify":
        step_notify(a.file)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())