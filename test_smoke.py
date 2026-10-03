"""
Scenario 5 冒烟测试
1. 模块完整性与单元决策校验
2. 真实浏览器 CDP 轻量加载与动作链路校验
"""
import sys
import time
from scenario5.config import settings
from scenario5.decision.schemas import ActionChoice, ActionType, Observation
from scenario5.decision.fast_path import FastPathRouter
from scenario5.decision.slow_path import SlowPathAgent
from scenario5.browser.driver import BrowserDriver
from scenario5.browser.observer import DOMObserver
from scenario5.browser.verifier import PhysicalVerifier


def test_unit_decision():
    print("[1/3] 测试快慢轨决策引擎...")
    router = FastPathRouter()
    slow = SlowPathAgent()

    fake_items = [
        {"id": 0, "tag": "input", "type": "text", "text": "搜索框", "placeholder": "请输入搜索词"},
        {"id": 1, "tag": "button", "type": "submit", "text": "百度一下"}
    ]
    fake_obs = Observation(
        url="https://www.baidu.com",
        title="百度一下，你就知道",
        fingerprint="abc123456",
        items=fake_items,
        compact_view="[0] <input>: 搜索框\n[1] <button>: 百度一下"
    )

    # 1. 测试输入意图
    choice = router.decide(goal="搜索北京天气", obs=fake_obs, history=[])
    assert choice.action == ActionType.TYPE_TEXT, f"预期 TYPE_TEXT，实际得到 {choice.action}"
    assert choice.target_id == 0, f"预期命中输入框 0，实际得到 {choice.target_id}"
    print(f"  ✔ 快轨决策响应时间: {choice.elapsed_ms:.2f} ms，命中: {choice.action.value} -> [{choice.target_id}]")

    # 2. 测试慢轨文本提取
    text = slow.generate_input_text(goal="搜索北京天气", target_item=fake_items[0], obs=fake_obs)
    assert "北京天气" in text, f"预期提取出 '北京天气'，实际得到 '{text}'"
    print(f"  ✔ 慢轨文本提取成功: '{text}'")


def test_physical_verifier():
    print("[2/3] 测试物理终态校验器...")
    verifier = PhysicalVerifier()
    ok, reason = verifier.verify_done(
        goal="搜索北京天气",
        url="https://www.baidu.com/s?wd=北京天气",
        title="北京天气_百度搜索",
        items=[{"text": "北京今日气温 20度"}],
        step_count=2
    )
    assert ok, f"物理终态核验失败: {reason}"
    print(f"  ✔ 物理终态校验成功: {reason}")


def test_browser_e2e():
    print("[3/3] 测试真实浏览器 (Edge/Chrome) 轻量驱动与 DOM 感知 (Headless 快速冒烟)...")
    driver = BrowserDriver(headless=True)
    try:
        # 打开本地空白或轻量导航
        driver.navigate("https://example.com")
        title = driver.get_title()
        url = driver.get_url()
        print(f"  ✔ 成功打开页面: {title} ({url})")

        observer = DOMObserver(driver)
        items, fp, compact = observer.capture_snapshot()
        print(f"  ✔ DOM 观察器捕获控件数: {len(items)}, 页面指纹: {fp}")
        assert len(items) > 0, "未能提取到页面交互控件"
        print(f"  ✔ 示例控件: [{items[0]['id']}] <{items[0]['tag']}>: {items[0]['text']}")
    finally:
        driver.close()
        print("  ✔ 浏览器已安全关闭")


if __name__ == "__main__":
    test_unit_decision()
    test_physical_verifier()
    test_browser_e2e()
    print("\n🎉 全部冒烟测试通过！")
