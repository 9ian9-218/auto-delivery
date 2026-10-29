"""
双轨浏览器 Agent HTTP 任务服务（供其他 Agent / 程序调用）
- GET  /health   : 探活 {ok, busy}
- POST /v1/task  : 执行一个浏览器任务 {"url": ..., "goal": ...} → execute_task 结果 JSON
- POST /v1/lease : 固定 DOM 工具获取/释放共享任务锁；崩溃后租约自动过期

任务串行执行（单浏览器实例），繁忙时立即返回 409 由调用方稍后重试；
浏览器在首个任务到达时才启动，并在多个任务间复用。
仅监听 127.0.0.1：本服务可操控本机真实浏览器，切勿绑定 0.0.0.0 或暴露到局域网。
"""
import json
import sys
import argparse
import threading
import secrets
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

from scenario5.config import settings
from scenario5.browser.driver import BrowserDriver
from scenario5.agent import DualTrackAgent


def log_step(step: int, choice, desc: str):
    track = "快轨" if choice.is_fast_path else "慢轨"
    print(f"[step {step:02d}][{track} {choice.elapsed_ms:.1f}ms] {choice.action.value} -> {desc}", flush=True)


class TaskService:
    """单浏览器实例 + 串行任务锁；浏览器延迟到首个任务时启动"""

    def __init__(self, headless=None):
        self._headless = headless  # None=跟随 .env, True/False=命令行覆盖
        self._agent: DualTrackAgent | None = None
        self._lock = threading.Lock()
        self._lease_guard = threading.Lock()
        self._lease_token = None
        self._lease_timer = None

    @property
    def busy(self) -> bool:
        return self._lock.locked()

    def acquire_lease(self, ttl_seconds=240):
        """Share the task lock with fixed DOM workers, including crash expiry."""
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 1 <= ttl_seconds <= 240:
            return 400, {"error": "ttl_seconds must be an integer from 1 to 240"}
        with self._lease_guard:
            if not self._lock.acquire(blocking=False):
                return 409, {"error": "busy"}
            token = secrets.token_urlsafe(24)
            self._lease_token = token
            self._lease_timer = threading.Timer(ttl_seconds, self.release_lease, args=(token,))
            self._lease_timer.daemon = True
            self._lease_timer.start()
            return 200, {"ok": True, "token": token, "ttl_seconds": ttl_seconds}

    def release_lease(self, token):
        with self._lease_guard:
            if not token or token != self._lease_token:
                return 409, {"error": "lease_not_owned_or_expired"}
            self._lease_token = None
            self._lease_timer.cancel()
            self._lease_timer = None
            self._lock.release()
            return 200, {"ok": True}

    def run(self, goal: str, start_url):
        if not self._lock.acquire(blocking=False):
            return 409, {"error": "busy", "message": "已有任务正在执行，请稍后重试", "retry_after_seconds": 5}
        try:
            if self._agent is None:
                print("[init] 首个任务到达，正在启动浏览器...", flush=True)
                driver = BrowserDriver(headless=self._headless)
                self._agent = DualTrackAgent(driver=driver, on_step_callback=log_step)
                print(f"[init] 浏览器就绪: {driver.get_title()} ({driver.get_url()})", flush=True)
            result = self._agent.execute_task(goal=goal, start_url=start_url)
            print(f"[done] success={result['success']} steps={result['steps_taken']} "
                  f"time={result['total_time_seconds']}s url={result['final_url']}", flush=True)
            return 200, result
        except Exception as e:
            print(f"[error] {type(e).__name__}: {e}", flush=True)
            self._agent = None
            return 500, {"error": f"{type(e).__name__}: {e}"}
        finally:
            self._lock.release()

    def close(self):
        """Detach automation on shutdown; keep the user browser and logins alive."""
        if self._agent is not None:
            try:
                self._agent.driver.detach()
            except Exception:
                pass
            self._agent = None


def make_handler(service: TaskService):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body):
            data = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/health":
                self._send(200, {"ok": True, "service": "dual-track-browser-agent", "busy": service.busy})
            else:
                self._send(404, {"error": f"unknown path {self.path}"})

        def do_POST(self):
            if self.path not in ("/v1/task", "/v1/lease"):
                self._send(404, {"error": f"unknown path {self.path}"})
                return
            try:
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}"
                try:
                    body = json.loads(raw.decode("utf-8"))
                except UnicodeDecodeError:
                    # Windows 终端/curl 可能以 GBK 发送中文请求体，回退解码
                    body = json.loads(raw.decode("gbk"))
                if self.path == "/v1/lease":
                    if body.get("action") == "acquire":
                        code, payload = service.acquire_lease(body.get("ttl_seconds", 240))
                    elif body.get("action") == "release":
                        code, payload = service.release_lease(body.get("token"))
                    else:
                        code, payload = 400, {"error": "lease action must be acquire or release"}
                    self._send(code, payload)
                    return
                goal = str(body.get("goal") or "").strip()
                if not goal:
                    self._send(400, {"error": "missing 'goal'"})
                    return
                code, payload = service.run(goal, body.get("url"))
                self._send(code, payload)
            except json.JSONDecodeError as e:
                self._send(400, {"error": f"invalid JSON: {e}"})
            except Exception as e:
                self._send(500, {"error": f"{type(e).__name__}: {e}"})

    return Handler


def main():
    parser = argparse.ArgumentParser(description="Dual-track Browser Agent Task Service")
    parser.add_argument("--port", type=int, default=8792, help="服务监听端口 (默认: 8792)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="监听地址 (默认: 127.0.0.1，请勿改为对外开放)")
    parser.add_argument("--headless", action="store_true", help="无头静默模式（不指定则跟随 .env 的 HEADLESS）")
    args = parser.parse_args()

    service = TaskService(headless=True if args.headless else None)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(service))
    print("=" * 60)
    print(" 双轨浏览器 Agent 任务服务")
    print(f" 地址: http://{args.host}:{args.port}")
    print(f" 接口: GET /health | POST /v1/task {{\"url\":..., \"goal\":...}}")
    print(f" 无头模式: {'是' if args.headless else f'跟随 .env (HEADLESS={settings.HEADLESS})'}")
    print("=" * 60, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[exit] 正在断开浏览器控制并退出（保留窗口和登录态）...", flush=True)
    finally:
        service.close()


if __name__ == "__main__":
    sys.exit(main())
