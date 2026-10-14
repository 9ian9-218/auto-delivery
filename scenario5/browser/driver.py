import time
from typing import Optional, Dict, Any
from DrissionPage import ChromiumPage, ChromiumOptions
from scenario5.config import settings


class BrowserDriver:
    """Chrome 浏览器驱动封装（基于 CDP 原生通信，免 webdriver 二进制依赖）"""

    def __init__(self, headless: Optional[bool] = None, port: Optional[int] = None):
        self.headless = settings.HEADLESS if headless is None else headless
        self.port = settings.REMOTE_DEBUG_PORT if port is None else port
        self.page: Optional[ChromiumPage] = None
        self._init_browser()

    def _init_browser(self):
        """初始化并启动或接管 Chrome"""
        co = ChromiumOptions()
        if settings.BROWSER_PATH:
            co.set_browser_path(settings.BROWSER_PATH)
        co.set_local_port(self.port)
        # 固定用户数据目录，避免登录态落在 %TEMP% 被清理
        if getattr(settings, "USER_DATA_PATH", ""):
            co.set_user_data_path(settings.USER_DATA_PATH)
        co.headless(self.headless)
        co.set_argument("--no-first-run")
        co.set_argument("--no-default-browser-check")
        co.set_argument("--disable-search-engine-choice-screen")

        try:
            self.page = ChromiumPage(addr_or_opts=co)
        except Exception as e:
            # 已固定用户数据目录时，绝不回退到 auto_port —— 那会另起一个隔离的临时 profile，
            # 导致登录态与扩展全部丢失（本项目明确禁止）。失败就明确报错。
            if getattr(settings, "USER_DATA_PATH", ""):
                raise RuntimeError(
                    f"浏览器启动/接管失败（已固定 USER_DATA_PATH={settings.USER_DATA_PATH}，"
                    f"禁止回退到临时 profile）: {type(e).__name__}: {e}"
                ) from e
            # 未固定目录时，才允许让 DrissionPage 自动分配端口启动
            co.auto_port()
            self.page = ChromiumPage(addr_or_opts=co)

    def navigate(self, url: str):
        """导航至指定 URL"""
        if not url.startswith("http://") and not url.startswith("https://") and not url.startswith("file://"):
            url = f"https://{url}"
        self.page.get(url)
        time.sleep(settings.STEP_DELAY)

    def get_url(self) -> str:
        """获取当前页面 URL"""
        return self.page.url if self.page else ""

    def get_title(self) -> str:
        """获取当前页面标题"""
        return self.page.title if self.page else ""

    def highlight_element(self, element, duration: Optional[float] = None):
        """在页面上高亮目标元素，增强人机交互直观性"""
        if not settings.HIGHLIGHT_ELEMENT or not element:
            return
        dur = settings.HIGHLIGHT_DURATION if duration is None else duration
        try:
            # 注入高亮样式与撤销定时器
            self.page.run_js("""
                (function(el, dur) {
                    if (!el) return;
                    const prevBorder = el.style.border;
                    const prevOutline = el.style.outline;
                    const prevBoxShadow = el.style.boxShadow;
                    
                    el.style.outline = '3px solid #ff0055';
                    el.style.boxShadow = '0 0 10px rgba(255, 0, 85, 0.8)';
                    
                    setTimeout(() => {
                        try {
                            el.style.outline = prevOutline;
                            el.style.boxShadow = prevBoxShadow;
                        } catch(e) {}
                    }, dur * 1000);
                })(arguments[0], arguments[1]);
            """, element, dur)
        except Exception:
            pass

    def click(self, s5_id: int) -> bool:
        """根据 data-s5-id 属性点击元素"""
        ele = self.page.ele(f"@data-s5-id={s5_id}", timeout=2)
        if not ele:
            return False
        self.highlight_element(ele)
        try:
            ele.click(by_js=False)
        except Exception:
            # 常规点击失败时使用 JS 兜底触发
            ele.click(by_js=True)
        time.sleep(settings.STEP_DELAY)
        return True

    def type_text(self, s5_id: int, text: str, clear: bool = True, press_enter: bool = False) -> bool:
        """在指定元素中填入文本"""
        ele = self.page.ele(f"@data-s5-id={s5_id}", timeout=2)
        if not ele:
            return False
        self.highlight_element(ele)
        if clear:
            try:
                ele.clear()
            except Exception:
                pass
        ele.input(text)
        if press_enter:
            time.sleep(0.1)
            ele.input("\n")
        time.sleep(settings.STEP_DELAY)
        return True

    def select_option(self, s5_id: int, value: str) -> bool:
        """下拉选择"""
        ele = self.page.ele(f"@data-s5-id={s5_id}", timeout=2)
        if not ele:
            return False
        self.highlight_element(ele)
        try:
            ele.select.by_text(value)
            time.sleep(settings.STEP_DELAY)
            return True
        except Exception:
            return False

    def scroll(self, direction: str = "down", distance: int = 400):
        """滚动视口"""
        dy = distance if direction.lower() == "down" else -distance
        self.page.scroll.up(-dy if dy < 0 else 0)
        self.page.scroll.down(dy if dy > 0 else 0)
        time.sleep(settings.STEP_DELAY)

    def screenshot(self, path: str):
        """保存当前页面截图"""
        self.page.get_screenshot(path=path)

    def close(self):
        """关闭浏览器会话"""
        if self.page:
            try:
                self.page.quit()
            except Exception:
                pass
            self.page = None
