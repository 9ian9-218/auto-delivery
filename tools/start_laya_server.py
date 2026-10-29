"""
启动本地 Laya 浏览器微调模型 HTTP 兼容服务
- /v1/decide     : 官方 decide() 管线 (推荐, 场景 5 Agent 使用)
- /v1/systemone  : TypeSafe 兼容端点
默认自动检测并使用 GPU（CUDA），不可用时自动回退 CPU
"""
import json
import sys
import argparse
import threading
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

# 添加模型目录到系统路径
model_dir = Path(__file__).resolve().parent / "models" / "laya-browser"
sys.path.insert(0, str(model_dir))

from laya_browser import LayaBrowser


def pick_device(requested: str) -> str:
    """自动设备选择：默认优先 CUDA，不可用则回退 CPU"""
    if requested != "auto":
        return requested
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
    except ImportError:
        pass
    return "cpu"


def make_handler(lb: LayaBrowser):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body):
            data = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            # 探活端点
            self._send(200, {"ok": True, "model": "cklxx/laya-browser"})

        def do_POST(self):
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                if self.path == "/v1/decide":
                    self._send(200, lb.decide(body["page"], goal=body["goal"], history=body.get("history", [])))
                elif self.path == "/v1/systemone":
                    self._send(200, lb.systemone(body))
                else:
                    self._send(404, {"error": f"unknown path {self.path}"})
            except Exception as e:
                self._send(400, {"error": f"{type(e).__name__}: {e}"})

    return Handler


def main():
    parser = argparse.ArgumentParser(description="Laya Browser Local Model Server")
    parser.add_argument("--port", type=int, default=8791, help="服务监听端口 (默认: 8791)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="监听地址 (默认: 127.0.0.1)")
    parser.add_argument("--device", type=str, default="auto", help="计算设备 auto/cpu/cuda (默认: auto 优先GPU)")
    args = parser.parse_args()

    device = pick_device(args.device)
    print(f"==================================================")
    print(f" 正在加载本地 Laya 浏览器微调模型: {model_dir}")
    print(f" 计算设备: {device.upper()}" + (" (GPU 加速已启用)" if device == "cuda" else " (CPU 模式)"))
    print(f" 服务端点: http://{args.host}:{args.port}/v1/decide")
    print(f"==================================================")

    lb = LayaBrowser.from_pretrained(str(model_dir), device=device)
    print(f"✔ 模型已加载至 {device.upper()}，服务就绪！正在监听请求...")

    server = ThreadingHTTPServer((args.host, args.port), make_handler(lb))
    server.serve_forever()


if __name__ == "__main__":
    main()
