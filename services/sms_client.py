"""
SMS Client 模块 —— 供 Agent 自动化脚本调用的轻量客户端
使用标准库 urllib，零外部依赖。

使用示例:
    from sms_client import wait_for_verification_code, get_latest_sms_id

    # 1. 点击“发送验证码”前，记录当前最后一条短信 ID（防止读取到上一次的历史验证码）
    baseline_id = get_latest_sms_id()

    # 2. 模拟网页点击“发送验证码”
    # driver.click('#send-code-btn')

    # 3. 阻塞等待最新短信验证码（最多等 60 秒）
    code = wait_for_verification_code(timeout=60, since_id=baseline_id)
    if code:
        print(f"成功拿到验证码: {code}")
        # driver.input('#code-input', code)
    else:
        print("超时未收到验证码")
"""

import sys
import json
import time
import urllib.request
import urllib.error
from urllib.parse import urlencode

DEFAULT_SERVICE_URL = "http://127.0.0.1:8099"


def is_service_online(base_url: str = DEFAULT_SERVICE_URL, timeout: float = 2.0) -> bool:
    """检查短信接收服务是否在线"""
    try:
        url = f"{base_url.rstrip('/')}/health"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("ok") is True
    except Exception:
        return False


def get_latest_sms_id(base_url: str = DEFAULT_SERVICE_URL) -> int:
    """获取当前服务中最新一条短信的 ID，用于标记'发送前'的时间基准点"""
    try:
        url = f"{base_url.rstrip('/')}/sms/latest?timeout=0&max_age=3600"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("found"):
                return data.get("id", 0)
    except Exception:
        pass
    return 0


def wait_for_verification_code(
    timeout: float = 60.0,
    max_age: float = 180.0,
    since_id: int = 0,
    base_url: str = DEFAULT_SERVICE_URL
) -> str | None:
    """
    长轮询等待短信验证码到达

    :param timeout: 最大等待时间（秒），默认 60 秒
    :param max_age: 验证码允许的最大新鲜度（秒），默认 180 秒（3分钟以内收到的短信）
    :param since_id: 仅接收 ID 大于该值的短信（通常传点击发送前通过 get_latest_sms_id() 获取的值）
    :param base_url: 短信服务地址，默认 http://127.0.0.1:8099
    :return: 验证码字符串（如 '849201'），超时返回 None
    """
    params = {
        "timeout": min(timeout, 60.0),
        "max_age": max_age,
        "since_id": since_id
    }
    url = f"{base_url.rstrip('/')}/sms/latest?{urlencode(params)}"
    start_time = time.time()

    while (time.time() - start_time) < timeout:
        remaining = timeout - (time.time() - start_time)
        if remaining <= 0:
            break

        # 每次请求的最长等待为剩余时间
        req_timeout = min(remaining + 1.0, 30.0)
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=req_timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("found") and data.get("code"):
                    return str(data["code"])
        except urllib.error.URLError:
            # 如果服务端临时未启动或连接断开，休眠后重试
            time.sleep(1.0)
        except Exception:
            time.sleep(1.0)

    return None


def get_recent_messages(limit: int = 10, base_url: str = DEFAULT_SERVICE_URL) -> list:
    """获取最近收到的短信列表"""
    try:
        url = f"{base_url.rstrip('/')}/sms/list?limit={limit}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("records", [])
    except Exception as e:
        print(f"获取短信列表失败: {e}", file=sys.stderr)
        return []


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="SMS Client CLI")
    parser.add_argument("--check", action="store_true", help="检查服务是否在线")
    parser.add_argument("--wait", type=float, default=0, help="等待新验证码 (秒)")
    parser.add_argument("--list", action="store_true", help="查看最近接收到的短信")
    args = parser.parse_args()

    if args.check:
        online = is_service_online()
        print(f"服务状态: {'[在线]' if online else '[离线]'}")
    elif args.list:
        msgs = get_recent_messages()
        print(f"最近短信数量: {len(msgs)}")
        for m in msgs:
            print(f"- [{m.get('received_at_str')}] 发件人: {m.get('sender')} | 验证码: {m.get('code')} | 内容: {m.get('content')}")
    elif args.wait > 0:
        print(f"正在等待最新验证码到达 (最多等待 {args.wait} 秒)...")
        code = wait_for_verification_code(timeout=args.wait)
        if code:
            print(f"✅ 获取到验证码: {code}")
        else:
            print("❌ 超时未收到验证码。")
    else:
        parser.print_help()
