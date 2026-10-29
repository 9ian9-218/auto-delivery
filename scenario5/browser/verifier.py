import re
from typing import List, Dict, Any, Tuple


class PhysicalVerifier:
    """真实物理终态校验器：以物理页面指标断言操作成功或死循环"""

    @staticmethod
    def check_mutation(prev_fingerprint: str, curr_fingerprint: str) -> bool:
        """检查页面是否发生实际的物理突变"""
        return prev_fingerprint != curr_fingerprint

    @staticmethod
    def verify_done(
        goal: str,
        url: str,
        title: str,
        items: List[Dict[str, Any]],
        step_count: int
    ) -> Tuple[bool, str]:
        """
        验证是否达到真实交付终态。
        返回: (是否确认完成, 校验原因或阻碍说明)
        """
        # 1. 如果步数过少（如仅 0 步就报 DONE），判定未完成
        if step_count == 0:
            return False, "尚未执行任何物理操作，判定未完成"

        # 2. 检查页面中是否包含典型的错误/阻断/人机验证标志
        blocked_keywords = [
            "验证码", "安全验证", "人机验证", "行为验证", "滑动验证",
            "captcha", "cloudflare", "challenge", "404 not found",
            "502 bad gateway", "503 service", "页面不存在"
        ]
        combined_text = (title + " " + " ".join([i.get("text", "") for i in items[:40]])).lower()
        url_lower = url.lower()

        for kw in blocked_keywords:
            if kw in combined_text or kw in url_lower:
                return False, f"物理终态核验拦截：页面触发阻断标志「{kw}」"

        # 检查 URL 是否有明确阻断重定向
        if any(bad_domain in url_lower for bad_domain in ["wappass.baidu.com", "challenge", "captcha"]):
            return False, "物理终态核验拦截：重定向至安全风控拦截页"

        # 3. 目标语义与页面信息的软对齐检查
        target = re.sub(r"^(?:搜索|查找|查询|打开|进入|点击|填写|输入)\s*", "", goal.strip())
        goal_tokens = [w for w in target.replace("，", " ").replace("。", " ").split() if len(w) > 1]
        matched_tokens = [t for t in goal_tokens if t.lower() in combined_text or t.lower() in url_lower]
        if not matched_tokens:
            return False, "物理终态核验拦截：目标未出现在页面或URL中 (命中指标: 0 个匹配词)"
        return True, f"物理终态核验通过 (命中指标: {len(matched_tokens)} 个匹配词)"
