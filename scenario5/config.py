import os
import shutil
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件（如果存在）
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def find_browser_path() -> str:
    """自动探测本机浏览器路径：优先 Edge，Chrome 作为兜底"""
    # 显式指定的通用路径优先（.env: BROWSER_PATH）
    env_path = os.getenv("BROWSER_PATH") or os.getenv("CHROME_PATH")
    if env_path and os.path.exists(env_path):
        return env_path

    # Edge 优先（Chromium 内核，CDP 能力一致）
    edge_candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
    ]
    for path in edge_candidates:
        if os.path.exists(path):
            return path

    # Chrome 兜底
    chrome_candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for path in chrome_candidates:
        if os.path.exists(path):
            return path

    which_browser = shutil.which("msedge") or shutil.which("chrome") or shutil.which("google-chrome")
    if which_browser:
        return which_browser

    return r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


class Settings:
    # 浏览器参数
    BROWSER_PATH: str = find_browser_path()
    REMOTE_DEBUG_PORT: int = int(os.getenv("REMOTE_DEBUG_PORT", "9222"))
    # 浏览器用户数据目录：固定到稳定路径，登录态（cookie）可跨浏览器重启/电脑重启保留。
    # 留空则回退 DrissionPage 默认的 %TEMP%\DrissionPage\userData\<port>（会被系统清临时文件清掉）
    USER_DATA_PATH: str = os.getenv("USER_DATA_PATH", "")
    HEADLESS: bool = os.getenv("HEADLESS", "false").lower() in ("true", "1", "yes")
    HIGHLIGHT_ELEMENT: bool = os.getenv("HIGHLIGHT_ELEMENT", "true").lower() in ("true", "1", "yes")
    HIGHLIGHT_DURATION: float = float(os.getenv("HIGHLIGHT_DURATION", "0.3"))

    # 快轨决策配置 (auto | laya_local | laya | jev | heuristic)
    FAST_PATH_MODE: str = os.getenv("FAST_PATH_MODE", "auto")
    LOCAL_MODEL_PATH: str = os.getenv("LOCAL_MODEL_PATH", str(Path(__file__).resolve().parent.parent / "models" / "laya-browser"))
    TYPESAFE_API_KEY: str = os.getenv("TYPESAFE_API_KEY", "")
    TYPESAFE_BASE_URL: str = os.getenv("TYPESAFE_BASE_URL", "https://api.typesafe.ai/v1")
    LAYA_BASE_URL: str = os.getenv("LAYA_BASE_URL", "http://127.0.0.1:8791/v1")

    # 慢轨生成配置 (Codex / OpenAI 兼容接口)
    SLOW_PATH_API_KEY: str = os.getenv("SLOW_PATH_API_KEY") or os.getenv("OPENAI_API_KEY", "")
    SLOW_PATH_BASE_URL: str = os.getenv("SLOW_PATH_BASE_URL", "https://api.openai.com/v1")
    SLOW_PATH_MODEL: str = os.getenv("SLOW_PATH_MODEL", "gpt-4o-mini")

    # 状态机超参数
    MAX_STEPS: int = int(os.getenv("MAX_STEPS", "60"))
    STEP_DELAY: float = float(os.getenv("STEP_DELAY", "0.5"))


settings = Settings()
