# -*- coding: utf-8 -*-
"""browser_task.py — 向本地浏览器服务(8792)提交一个任务并等结果

为什么要这个封装（三个实战坑）：
1. Windows 终端把中文 JSON 按 GBK 发送会导致编码错误 → 这里在Python 侧
   构造请求体并显式 utf-8 编码，不依赖终端。
2. 服务单浏览器串行，繁忙时返回 409 → 自动指数退避重试，不并发。
3. 投递场景要能"成功但落点可疑"的二次校验 → 支持 --expect-url / --expect-text，
   返回里给出 verified 字段，避免只看 success:true 就汇报完成。

用法:
  python browser_task.py --goal "在招聘页查找2027届AI应用开发岗位并停在岗位列表页" \
                          --url "https://career.xxx.com/campus" [--expect-text 岗位]

  python browser_task.py --goal "..." --timeout 1200 --raw     # 不做落点校验
"""
import argparse
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

SKILL_DIR = Path(__file__).resolve().parent.parent


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
                "browser_service": c.browser_service,
                "task_timeout_seconds": c.task_timeout_seconds,
                "dashboard_url": c.get("dashboard_url"),
            }
    with open(SKILL_DIR / "config.json", encoding="utf-8") as f:
        return json.load(f)


CFG = _load_cfg()
BASE = CFG["browser_service"]


def wait_idle(max_wait: int = 120) -> bool:
    """等浏览器服务空闲。"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            with opener.open(f"{BASE}/health", timeout=3) as r:
                if json.loads(r.read().decode()).get("busy") is False:
                    return True
        except Exception:
            return False
        time.sleep(3)
    return False


def submit(goal: str, url: str | None, timeout: int):
    body = {"goal": goal}
    if url:
        body["url"] = url
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")  # 显式 utf-8，绕开终端 GBK
    req = urllib.request.Request(
        f"{BASE}/v1/task", data=raw,
        headers={"Content-Type": "application/json; charset=utf-8"}, method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def verify(result: dict, expect_url: str | None, expect_text: str | None) -> dict:
    """物理落点校验：URL 命中 + 页面文本命中才算真完成。"""
    import re
    issues = []
    final_url = (result.get("final_url") or "")
    title = (result.get("final_title") or "")
    msg = (result.get("message") or "")
    if not result.get("success"):
        issues.append(f"浏览器自报未达成: {msg}")
    if expect_url and expect_url not in final_url:
        issues.append(f"落点 URL 不含期望串 '{expect_url}'（实际 {final_url[:120]}）")
    for bad in ("安全验证", "验证码", "captcha", "登录"):
        if bad in title or bad in final_url:
            issues.append(f"疑似被拦截：{title or final_url[:120]}")
    # 手册铁律：命中指标 0 个 → success:true 不可信（agent 可能把整句 goal 当输入了）
    m = re.search(r"命中指标[:：]\s*(\d+)", msg)
    if m and int(m.group(1)) == 0:
        issues.append(
            "命中指标为 0，success:true 不可信——常见于 agent 把整句 goal 当成输入文本"
            f"（当前标题：{title[:60]}）。改写 goal 为纯目标内容后重试"
        )
    if expect_text and result.get("matched_keywords", 0) == 0 and result.get("success"):
        issues.append("未命中期望文本，需以页面实际内容复核")
    return {
        "verified": not issues,
        "issues": issues,
        "final_url": final_url,
        "final_title": title,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--goal", required=True, help="一个明确的动词短语，一个任务一个目标")
    p.add_argument("--url", default=None, help="起始页；省略则复用浏览器当前页面")
    p.add_argument("--timeout", type=int, default=CFG["task_timeout_seconds"])
    p.add_argument("--expect-url", default=None, help="期望落点包含的串")
    p.add_argument("--expect-text", default=None, help="期望页面出现的关键词")
    p.add_argument("--max-retry", type=int, default=4, help="409 busy 时的重试次数")
    p.add_argument("--raw", action="store_true", help="跳过落点校验，原样返回")
    a = p.parse_args()

    if not a.expect_text and not a.raw and not a.expect_url:
        p.error("至少给 --expect-url / --expect-text 之一，或显式加 --raw 跳过校验")

    last = None
    for attempt in range(1, a.max_retry + 1):
        if not wait_idle():
            print(f"[warn] 服务持续繁忙，已等待仍idle失败", file=sys.stderr)
        try:
            result = submit(a.goal, a.url, a.timeout)
            last = result
            if "error" in result and result.get("error") == "busy":
                print(f"[retry {attempt}] 服务忙，等待后重试", file=sys.stderr)
                time.sleep(min(10 * attempt, 30))
                continue
            break
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")
            if e.code == 409:
                print(f"[retry {attempt}] 409 busy: {body[:120]}", file=sys.stderr)
                time.sleep(min(10 * attempt, 30))
                continue
            print(json.dumps({"ok": False, "http_status": e.code, "body": body[:500]},
                             ensure_ascii=False, indent=2))
            return 2
        except Exception as e:
            print(f"[error] 请求失败: {e}", file=sys.stderr)
            return 3

    if last is None:
        print(json.dumps({"ok": False, "error": "重试耗尽，服务一直忙"}, ensure_ascii=False))
        return 4

    out = {"ok": True, "result": last}
    if not a.raw:
        out["check"] = verify(last, a.expect_url, a.expect_text)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("check", {}).get("verified", True) else 5


if __name__ == "__main__":
    sys.exit(main())