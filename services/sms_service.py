"""
iPhone 短信与验证码接收服务 (供 Agent / 自动化程序读取)
- 监听端口: 8099 (绑定 0.0.0.0，允许 Tailscale 内网 100.117.106.99 及本机 127.0.0.1 访问)
- POST /sms         : iPhone 快捷指令上报入口 (JSON: sender, content, time)
- GET  /sms/latest  : Agent 读取最新验证码 (支持 long-polling，立即响应最新短信)
- GET  /sms/list    : 查看最近收到的短信列表
- GET  /health      : 探活接口
- POST /sms/clear   : 清空当前缓存
"""

import os
import re
import sys
import json
import time
import argparse
import threading
from urllib.parse import urlparse, parse_qs
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

# 数据持久化日志路径
SMS_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sms_history.jsonl")


def extract_verification_code(text: str) -> str | None:
    """从短信正文中智能提取 4~8 位验证码"""
    if not text:
        return None
    patterns = [
        # 1. 带上下文关键词前缀的验证码
        r'(?:验证码|动态码|校验码|授权码|code|Code|PIN|动态密码)[^\d]{0,10}?([0-9]{4,8})',
        # 2. 带上下文关键词后缀的验证码
        r'([0-9]{4,8})[^\d]{0,10}?(?:为验证码|是验证码|是您的验证码|为您的动态码)',
        # 3. 独立出现的 6 位数字（最常见）
        r'(?<!\d)([0-9]{6})(?!\d)',
        # 4. 独立出现的 4 位数字
        r'(?<!\d)([0-9]{4})(?!\d)',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


class SMSStore:
    """线程安全的短信存储与通知器"""

    def __init__(self, max_records=200):
        self.max_records = max_records
        self.records = []
        self._cv = threading.Condition()

    def add(self, sender: str, content: str, send_time: str = "") -> dict:
        code = extract_verification_code(content)
        record = {
            "id": int(time.time() * 1000),
            "sender": sender.strip(),
            "content": content.strip(),
            "code": code,
            "send_time": send_time.strip(),
            "received_at": time.time(),
            "received_at_str": time.strftime("%Y-%m-%d %H:%M:%S")
        }

        with self._cv:
            self.records.append(record)
            if len(self.records) > self.max_records:
                self.records = self.records[-self.max_records:]
            # 唤醒所有正在等待新验证码的请求 (长轮询)
            self._cv.notify_all()

        # 追加写入本地 jsonl 日志，便于回溯
        try:
            with open(SMS_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"[WARN] 写入日志失败: {e}", flush=True)

        return record

    def get_latest(self, max_age_seconds: float = 300, code_only: bool = True, since_id: int = 0) -> dict | None:
        """获取满足条件的最新的单条记录"""
        now = time.time()
        with self._cv:
            for r in reversed(self.records):
                if since_id and r["id"] <= since_id:
                    continue
                if (now - r["received_at"]) > max_age_seconds:
                    continue
                if code_only and not r["code"]:
                    continue
                return r
        return None

    def wait_for_code(self, timeout: float = 60.0, max_age_seconds: float = 300, since_id: int = 0) -> dict | None:
        """长轮询：如果当前已有新鲜验证码直接返回；否则最多等待 timeout 秒"""
        deadline = time.time() + timeout
        with self._cv:
            while True:
                record = self.get_latest(max_age_seconds=max_age_seconds, code_only=True, since_id=since_id)
                if record:
                    return record
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                self._cv.wait(timeout=min(remaining, 1.0))
        return None

    def list_recent(self, limit: int = 20) -> list:
        with self._cv:
            return list(reversed(self.records[-limit:]))

    def clear(self):
        with self._cv:
            self.records.clear()


STORE = SMSStore()


class SMSHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # 静默常规日志，仅在特定逻辑中打印易读日志
        pass

    def _send_json(self, status_code: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send_json(200, {"status": "ok"})

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/health":
            self._send_json(200, {
                "ok": True,
                "service": "iphone-sms-receiver",
                "total_cached": len(STORE.records)
            })
            return

        if path == "/sms/latest":
            timeout = float(query.get("timeout", [0])[0])
            max_age = float(query.get("max_age", [300])[0])
            since_id = int(query.get("since_id", [0])[0])

            if timeout > 0:
                record = STORE.wait_for_code(timeout=timeout, max_age_seconds=max_age, since_id=since_id)
            else:
                record = STORE.get_latest(max_age_seconds=max_age, code_only=True, since_id=since_id)

            if record:
                self._send_json(200, {
                    "found": True,
                    "code": record["code"],
                    "sender": record["sender"],
                    "content": record["content"],
                    "received_at": record["received_at_str"],
                    "age_seconds": round(time.time() - record["received_at"], 1),
                    "id": record["id"]
                })
            else:
                self._send_json(200, {
                    "found": False,
                    "message": "未找到有效验证码短信"
                })
            return

        if path == "/sms/list":
            limit = int(query.get("limit", [20])[0])
            records = STORE.list_recent(limit=limit)
            self._send_json(200, {
                "count": len(records),
                "records": records
            })
            return

        self._send_json(404, {"error": f"Not Found: {path}"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/sms/clear":
            STORE.clear()
            self._send_json(200, {"status": "ok", "message": "缓存已清空"})
            return

        if path == "/sms":
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw_body = self.rfile.read(length) if length > 0 else b"{}"
                try:
                    data = json.loads(raw_body.decode("utf-8"))
                except UnicodeDecodeError:
                    data = json.loads(raw_body.decode("gbk", errors="ignore"))

                # 兼容不同大小写或键名变体
                sender = str(data.get("sender") or data.get("发件人") or data.get("from") or "Unknown")
                content = str(data.get("content") or data.get("内容") or data.get("body") or data.get("text") or "")
                send_time = str(data.get("time") or data.get("时间") or data.get("date") or "")

                if not content:
                    print("[WARN] 收到一条空短信请求", flush=True)
                    self._send_json(400, {"error": "短信内容为空 (content is required)"})
                    return

                record = STORE.add(sender=sender, content=content, send_time=send_time)
                print(f"\n==================================================", flush=True)
                print(f"[{record['received_at_str']}] 收到来自【{record['sender']}】的短信:", flush=True)
                print(f"  正文: {record['content']}", flush=True)
                if record['code']:
                    print(f"  👉 提取验证码: 【 {record['code']} 】", flush=True)
                else:
                    print(f"  (未检测到 4~8 位数字验证码)", flush=True)
                print(f"==================================================", flush=True)

                self._send_json(200, {
                    "status": "success",
                    "code": record["code"],
                    "id": record["id"],
                    "received_at": record["received_at_str"]
                })
            except Exception as e:
                print(f"[ERROR] 处理短信请求异常: {e}", flush=True)
                self._send_json(500, {"error": str(e)})
            return

        self._send_json(404, {"error": f"Not Found: {path}"})


def run_server(host="0.0.0.0", port=8099):
    server = ThreadingHTTPServer((host, port), SMSHandler)
    print(f"==================================================", flush=True)
    print(f"iPhone 短信验证码接收服务已启动!", flush=True)
    print(f"监听地址: http://{host}:{port}", flush=True)
    print(f"Tailscale 接口地址: http://100.117.106.99:{port}/sms", flush=True)
    print(f"本地测试接口: http://127.0.0.1:{port}/sms", flush=True)
    print(f"查看短信列表: http://127.0.0.1:{port}/sms/list", flush=True)
    print(f"Agent 读取接口: http://127.0.0.1:{port}/sms/latest?timeout=60", flush=True)
    print(f"==================================================", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止。")
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="iPhone SMS Receiver Service")
    parser.add_argument("--host", default="0.0.0.0", help="监听 IP (默认 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8099, help="监听端口 (默认 8099)")
    args = parser.parse_args()

    run_server(host=args.host, port=args.port)
