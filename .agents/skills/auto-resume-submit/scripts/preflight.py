# -*- coding: utf-8 -*-
"""preflight.py — 投递前一次性环境自检 + 浏览器服务守护

在任何投递动作之前先跑这个，把"能不能干"变成一份可读的 JSON，
避免做到一半才发现服务没起、简历不在、指挥中心连不上。

用法:
  python preflight.py            # 只检查，不改任何东西
  python preflight.py --start    # 检查 + 若 8792 未在线则自动有头启动并等就绪
  python preflight.py --json     # 只输出 JSON（默认就只输出 JSON）

退出码: 0 = 全部就绪(or仅警告); 1 = 有阻塞项
"""
import json
import ntpath
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

from attach import native_path

sys.stdout.reconfigure(encoding="utf-8")

SKILL_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = SKILL_DIR / "config.json"


def load_config() -> dict:
    """优先 work/tools/user_config.py（用户态与功能隔离），回退同目录 config.json。"""
    for parent in Path(__file__).resolve().parents:
        cand = parent / "work" / "tools" / "user_config.py"
        if cand.is_file():
            import importlib.util
            spec = importlib.util.spec_from_file_location("_ad_user_config", cand)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            c = mod.load()
            return {
                "browser_project_root": c.browser_project_root,
                "browser_service": c.browser_service,
                "workspace_root": c.get("workspace_root", default=str(c.root)),
                "dashboard_url": c.get("dashboard_url") or "",
                "resume_pdf": str(c.path_or_none("resume", "pdf") or ""),
                "resume_docx": str(c.path_or_none("resume", "docx") or ""),
                "login_phone": c.user("phone", default=""),
                "target_grad_year": c.target_grad_year,
                "task_timeout_seconds": c.task_timeout_seconds,
                "default_pick_count": c.default_pick_count,
            }
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


# 项目铁律：本项目只允许 8898 端口秋招看板，严禁 28898 求职看板
FORBIDDEN_PORTS = ("28898",)


def assert_legal_dashboard(url: str) -> str:
    for fp in FORBIDDEN_PORTS:
        if fp in str(url):
            raise SystemExit(
                f"【项目铁律拦截】本项目下仅允许访问 8898 端口看板，严禁访问端口 {fp}（URL: {url}）！"
            )
    return url


def find_project_root(cfg: dict) -> Path:
    """定位 jevlike 浏览器项目：环境变量 > 已知路径 > 从 skill 向上找。"""
    env = os.environ.get("JEVLIKE_BROWSER_HOME", "").strip()
    candidates = []
    if env:
        candidates.append(native_path(env))
    candidates.append(native_path(cfg.get("browser_project_root", "")))
    candidates.append(SKILL_DIR)
    for c in candidates:
        if not c or str(c) == ".":
            continue
        if (c / "api_server.py").exists() and (c / "scenario5").is_dir():
            return c.resolve()
    # 向上逐层兜底
    for base in [SKILL_DIR, Path.cwd()]:
        for p in [base, *base.parents]:
            if (p / "api_server.py").exists() and (p / "scenario5").is_dir():
                return p.resolve()
    return native_path(cfg.get("browser_project_root", ""))


def http_get(url: str, timeout: float = 5.0):
    """返回 (ok, status, body_snippet)。绕过系统代理，直连内网。"""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as r:
            return True, r.status, r.read(200000)
    except urllib.error.HTTPError as e:
        return False, e.code, b""
    except Exception as e:
        return False, 0, str(e).encode("utf-8", "ignore")


def check_browser_service(base: str):
    ok, status, body = http_get(f"{base}/health", timeout=3.0)
    if not ok or status != 200:
        return False, None, f"HTTP {status or '连接失败'}"
    try:
        return True, json.loads(body.decode("utf-8")), "ok"
    except Exception:
        return False, None, "响应非 JSON"


def start_service(root: Path, cfg: dict, wait_s: int = 40) -> tuple[bool, str]:
    """有头模式启动 api_server.py（反爬站点必须可见浏览器）。"""
    venv_py = root / ".venv" / "Scripts" / "python.exe"
    if not venv_py.exists():
        return False, f"缺虚拟环境 {venv_py}，请先运行 setup.bat"
    log = root / "api_server.log"
    try:
        # detached 启动，服务在后台常驻，不随当前 shell 退出
        subprocess.Popen(
            [str(venv_py), "api_server.py"],
            cwd=str(root),
            stdout=open(log, "a", encoding="utf-8"),
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
    except Exception as e:
        return False, f"启动失败: {e}"

    base = cfg["browser_service"]
    deadline = time.time() + wait_s
    while time.time() < deadline:
        time.sleep(1.5)
        ok, data, _ = check_browser_service(base)
        if ok:
            return True, f"已启动并就绪 ({wait_s}s 内)"
    return False, f"启动后 {wait_s}s 仍未就绪，见 {log}"


def check_node():
    """只在 PATH 和用户显式指定的 NODE_BIN 里找 node。

    不再扫描其他用户的目录（跨用户目录扫描违反工作区边界；旧路径已失效）。
    """
    cands = ["node"]
    env_bin = os.environ.get("NODE_BIN", "").strip()
    if env_bin:
        cands.insert(0, env_bin)
    for cand in cands:
        try:
            out = subprocess.run([cand, "-v"], capture_output=True, text=True, timeout=10)
            if out.returncode == 0:
                return True, out.stdout.strip()
        except Exception:                                      # noqa: BLE001
            continue
    return False, "未找到 node（清单脚本需要 Node ≥ 18）；不在 PATH 时请设 NODE_BIN=<绝对路径>"


def check_drission(root: Path):
    venv_py = root / ".venv" / "Scripts" / "python.exe"
    if not venv_py.exists():
        return False, "缺 .venv"
    try:
        out = subprocess.run(
            [str(venv_py), "-c", "import DrissionPage;print(DrissionPage.__version__)"],
            capture_output=True, text=True, timeout=60,
        )
        if out.returncode == 0:
            return True, f"DrissionPage {out.stdout.strip()}"
        return False, (out.stderr or "").strip()[-120:]
    except Exception as e:
        return False, str(e)[:120]


def _browser_option(args, name):
    for i, arg in enumerate(args):
        if arg.startswith(name + "="):
            return arg[len(name) + 1:]
        if arg == name and i + 1 < len(args):
            return args[i + 1]
    return None


def _profile_path(path):
    if ntpath.splitdrive(path)[0] or path.startswith("\\\\"):
        return ntpath.normcase(ntpath.normpath(path))
    return os.path.normcase(os.path.abspath(os.path.expanduser(path)))


def inspect_browser_processes(port, configured, processes):
    """只读比较指定端口的主浏览器进程，不读取 cookie、凭据或标签页。"""
    matches, inaccessible = [], False
    for proc in processes:
        try:
            info = proc.info
            if (info.get("name") or "").lower() not in {
                "chrome.exe", "msedge.exe", "chrome", "chromium", "chromium-browser", "google-chrome"
            }:
                continue
            args = info.get("cmdline")
            if args is None:
                inaccessible = True
                continue
            if any(arg == "--type" or arg.startswith("--type=") for arg in args):
                continue
            if _browser_option(args, "--remote-debugging-port") == str(port):
                matches.append((_browser_option(args, "--user-data-dir"), info["name"].lower(),
                                _browser_option(args, "--profile-directory")))
        except (OSError, RuntimeError, KeyError, AttributeError):
            inaccessible = True
    if not matches:
        return {"status": "unknown" if inaccessible else "not_running", "port": port}
    if len(matches) != 1 or not matches[0][0]:
        return {"status": "unknown", "port": port}
    actual, browser_name, profile_directory = matches[0]
    status = "unconfigured" if not configured else (
        "match" if _profile_path(actual) == _profile_path(configured) else "mismatch"
    )
    return {"status": status, "port": port, "configured_path": configured, "actual_path": actual,
            "browser_name": browser_name, "profile_directory": profile_directory}


def check_browser_profile(root: Path):
    """可选诊断；无法检查时返回 unknown，绝不启动或关闭浏览器。"""
    try:
        import psutil
        from dotenv import dotenv_values
        values = dotenv_values(root / ".env")
        port = int(os.environ.get("REMOTE_DEBUG_PORT", values.get("REMOTE_DEBUG_PORT") or "9222"))
        configured = os.environ.get("USER_DATA_PATH", values.get("USER_DATA_PATH") or "")
        # WSL 进程列表不代表 Windows 主机浏览器，不能据此报告未运行。
        if os.name != "nt" and ntpath.splitdrive(configured)[0]:
            return {"status": "unknown", "port": port, "detail": "请在浏览器所在的 Windows 环境运行检查"}
        return inspect_browser_processes(port, configured, psutil.process_iter(["name", "cmdline"]))
    except Exception as e:
        return {"status": "unknown", "detail": f"无法检查浏览器进程 ({type(e).__name__})"}


def main():
    args = set(sys.argv[1:])
    cfg = load_config()
    root = find_project_root(cfg)
    checks = {}
    blockers = []
    warnings = []

    # 1. 浏览器项目
    proj_ok = (root / "api_server.py").exists() and (root / "scenario5").is_dir()
    checks["browser_project"] = {
        "ok": proj_ok, "root": str(root),
        "detail": "含 api_server.py + scenario5/" if proj_ok else "未找到项目文件",
    }
    if not proj_ok:
        blockers.append("browser_project")

    # 2. Node
    node_ok, node_v = check_node()
    checks["node"] = {"ok": node_ok, "detail": node_v}
    if not node_ok:
        blockers.append("node")

    # 3. 简历
    resume = native_path(cfg["resume_pdf"])
    resume_ok = resume.exists()
    checks["resume"] = {
        "ok": resume_ok, "path": str(resume),
        "size_kb": round(resume.stat().st_size / 1024) if resume_ok else 0,
        "detail": "存在" if resume_ok else "缺失——网申无法上传附件",
    }
    if not resume_ok:
        blockers.append("resume")

    # 4. DrissionPage（精细填表用，可选但强烈建议）
    dp_ok, dp_v = check_drission(root)
    checks["drissionpage"] = {"ok": dp_ok, "detail": dp_v}
    if not dp_ok:
        warnings.append("drissionpage（复杂表单只能靠通用 goal 任务，成功率下降）")

    # 5. 指挥中心（端口铁律校验：只允许 8898，严禁 28898）
    dash = assert_legal_dashboard(cfg["dashboard_url"])
    dash_ok, dash_status, dash_body = http_get(dash, timeout=10.0)
    has_data = b"const DATA" in dash_body
    dash_really_ok = dash_ok and has_data
    checks["dashboard"] = {
        "ok": dash_really_ok, "url": dash,
        "detail": f"HTTP {dash_status}, 内嵌DATA={'有' if has_data else '无'}"
        if dash_ok else f"不可达 HTTP {dash_status}",
    }
    if not dash_really_ok:
        blockers.append("dashboard（清单拉不到；可改用 --url 指向新地址）")

    # 6. 浏览器服务
    base = cfg["browser_service"]
    svc_ok, svc_data, svc_msg = check_browser_service(base)
    svc_started = None
    if not svc_ok and "--start" in args and proj_ok:
        svc_started = start_service(root, cfg)
        if svc_started[0]:
            svc_ok, svc_data, _ = check_browser_service(base)
            svc_msg = svc_started[1]
    checks["browser_service"] = {
        "ok": svc_ok, "url": base, "detail": svc_msg,
        "busy": (svc_data or {}).get("busy"),
        "auto_started": bool(svc_started and svc_started[0]),
    }
    if not svc_ok:
        blockers.append("browser_service（无浏览器则无法点投递入口/填表）")
    elif (svc_data or {}).get("busy"):
        warnings.append("browser_service 正忙（busy=true），提交任务前先等它空闲")

    # 7. 固定配置并不保证已经运行的 CDP 浏览器使用了该目录。
    checks["browser_profile"] = check_browser_profile(root)
    if checks["browser_profile"]["status"] == "mismatch":
        warnings.append("实际浏览器资料目录与配置不一致；保留当前会话，稍后正常启动时再处理")
    elif checks["browser_profile"]["status"] in ("unknown", "not_running", "unconfigured"):
        warnings.append("浏览器身份尚未确认；服务可达不等于已连接目标浏览器或已登录，交互前须核实")

    result = {
        "ready": not blockers,
        "checks": checks,
        "blockers": blockers,
        "warnings": warnings,
        "advice": (
            "环境就绪，可以进入清单→核实→投递流程"
            if not blockers
            else "存在阻塞项，先解决再投递（详见对应 check 的 detail）"
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not blockers else 1


if __name__ == "__main__":
    sys.exit(main())
