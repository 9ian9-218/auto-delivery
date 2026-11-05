#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""qiuzhao_api.py — 秋招看板 Agent API 客户端（直写 REST + 查询封装层）

【项目铁律（2026-10-28）】
- 本项目下**仅允许访问 8898 端口的秋招看板**（http://100.73.185.103:8898）。
- **严禁使用 28898 端口看板**（求职看板），代码层已施加硬拦截。

根据 2026-10-28 看板 API 规范升级：
1. 【直写操作】不再依赖看板 Agent 对话！新增 direct REST API：
   - 记录投递：POST /api/agent/applications (record_application)
   - 修改投递：PATCH /api/agent/applications (update_application)
   - 删除撤销：DELETE /api/agent/applications (remove_application)
   - 岗位/内推：POST /api/agent/jobs (upsert_job)
   - 考试日程：POST /api/agent/exams (add_exam)
   - 删除日程：DELETE /api/agent/exams (remove_exam)
   - 刷新看板：POST /api/agent/render (render)
   直写操作原子修改 Excel 并触发备份，耗时 ~0.3s，比对话接口（20s+）快几十倍。
2. 【查询接口】
   - 大盘概览：GET /api/agent/overview
   - 投递记录：GET /api/agent/applications
   - 公司全貌：GET /api/agent/company
   - 未投岗位：GET /api/agent/unapplied
   - 笔面日程：GET /api/agent/exams
   - 看板提醒：GET /api/agent/notices
   - 机器元数据：GET /api/agent/info
   - Markdown手册：GET /api/agent/manual
3. 【对话降级】chat() 方法仅为兼容保留，端点已 410 废弃；CLI `chat` 子命令直接拒绝。全部改走直写接口。
4. 【v1.3.0 新增（2026-10-28 手册核对）】
   - 未投递分页：GET /api/agent/unapplied 支持 offset / exclude_applied（默认 true）
   - 排除未投递公司：DELETE /api/agent/unapplied（幂等，须 confirm:true）
   - 机器元数据：GET /api/agent/info（= /schema = /openapi.json）
   - 已废弃 410：/api/agent/chat、/history、/abort、/reset —— 全部改走直写接口
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# 解决 Windows 控制台默认 GBK 编码输出 Emoji 或特殊字符报错问题
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

DEFAULT_QIUZHAO_URL = "http://100.73.185.103:8898"
# 严禁端口黑名单：本项目仅使用 8898 端口秋招看板，严禁使用 28898 端口
FORBIDDEN_PORTS = ("28898",)

# 绕过系统代理：100.x 是 Tailscale 内网地址，走本地代理会连接失败
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _find_token(explicit_token: Optional[str] = None) -> str:
    """寻找鉴权 Token，依次检查参数、环境变量和本地文件。"""
    if explicit_token:
        return explicit_token.strip()
    for env_key in ("QIUZHAO_AUTH_KEY", "QIUZHAO_API_TOKEN", "QIUZHAO_TOKEN"):
        val = os.environ.get(env_key, "").strip()
        if val:
            return val
    # 尝试查找本地 .web_token
    token_file = Path("data/.web_token")
    try:
        if token_file.is_file():
            return token_file.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""


class QiuzhaoAgentClient:
    """秋招看板 API 客户端（严格绑定 8898 端口）。"""

    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        board: str = "qiuzhao",
    ):
        raw_url = (
            base_url
            or os.environ.get("QIUZHAO_API_URL")
            or os.environ.get("QIUZHAO_URL")
            or DEFAULT_QIUZHAO_URL
        )
        for fp in FORBIDDEN_PORTS:
            if fp in raw_url:
                raise ValueError(
                    f"【项目铁律拦截】本项目下仅允许访问 8898 端口看板，严禁访问端口 {fp}（URL: {raw_url}）！"
                )
        if board == "qiuzhi":
            raise ValueError(
                "【项目铁律拦截】本项目下严禁使用求职看板（28898端口），仅允许使用秋招看板（8898端口）！"
            )

        self.base_url = raw_url.rstrip("/")
        self.board = "qiuzhao"
        self.token = _find_token(token)

    def _headers(self) -> Dict[str, str]:
        h = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        }
        if self.token:
            h["X-QZ-Token"] = self.token
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        payload: Optional[Dict[str, Any]] = None,
        timeout: int = 60,
    ) -> Union[Dict[str, Any], str, List[Any]]:
        url = self.base_url + path
        if params:
            cleaned = {k: v for k, v in params.items() if v is not None}
            if cleaned:
                url += ("&" if "?" in url else "?") + urllib.parse.urlencode(cleaned)

        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        req = urllib.request.Request(
            url, data=data, headers=self._headers(), method=method.upper()
        )
        try:
            with _OPENER.open(req, timeout=timeout) as r:
                body = r.read().decode("utf-8", "replace")
                ct = r.headers.get("Content-Type", "")
                if "text" in ct and not body.strip().startswith(("{", "[")):
                    return body.strip()
                try:
                    return json.loads(body)
                except Exception:
                    return body.strip()
        except urllib.error.HTTPError as e:
            raw_err = e.read().decode("utf-8", "replace")
            try:
                err_json = json.loads(raw_err)
                msg = err_json.get("error") or err_json.get("message") or raw_err
            except Exception:
                msg = raw_err[:300]
            raise RuntimeError(f"HTTP {e.code} ({path}): {msg}")
        except Exception as e:
            raise RuntimeError(f"请求失败 ({method} {url}): {e}")

    # ==================== 读接口 ====================

    def get_overview(self, text: bool = False) -> Union[Dict[str, Any], str]:
        """大盘概览。text=True 返回纯文本 Markdown。"""
        return self._request(
            "GET", "/api/agent/overview", params={"format": "text"} if text else None
        )

    def get_applications(
        self,
        status: Optional[str] = None,
        company: Optional[str] = None,
        direction: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """查询投递记录。

        status 可为 active(在流程) / failed(已淘汰) / progressed(笔面试中) / all 或指定状态。
        """
        return self._request(
            "GET",
            "/api/agent/applications",
            params={
                "status": status,
                "company": company,
                "direction": direction,
                "limit": limit,
                "offset": offset,
            },
        )

    def get_company(self, name: str) -> Dict[str, Any]:
        """查询指定公司全貌（含投递记录、岗位明细、内推码、链接与考试）。"""
        return self._request("GET", "/api/agent/company", params={"name": name})

    def get_unapplied(
        self,
        direction: Optional[str] = None,
        company: Optional[str] = None,
        industry: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """查询未投递岗位清单。"""
        return self._request(
            "GET",
            "/api/agent/unapplied",
            params={
                "direction": direction,
                "company": company,
                "industry": industry,
                "limit": limit,
            },
        )

    def get_exams(self) -> Union[Dict[str, Any], List[Any]]:
        """获取全部笔试/面试/测评安排。"""
        return self._request("GET", "/api/agent/exams")

    def get_unapplied_page(
        self,
        direction: Optional[str] = None,
        company: Optional[str] = None,
        industry: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        exclude_applied: bool = True,
    ) -> Dict[str, Any]:
        """未投递清单分页查询（v1.3.0：offset / exclude_applied）。"""
        return self._request(
            "GET",
            "/api/agent/unapplied",
            params={
                "direction": direction,
                "company": company,
                "industry": industry,
                "limit": limit,
                "offset": offset,
                "exclude_applied": str(bool(exclude_applied)).lower(),
            },
        )

    def remove_unapplied(
        self,
        company: str,
        confirm: bool = True,
        render: bool = True,
        notify: bool = True,
    ) -> Dict[str, Any]:
        """从未投递清单排除公司（DELETE /api/agent/unapplied，幂等）。

        只影响未投递视图；投递记录/岗位/内推码/链接一律不动。
        company 必须与「招聘岗位」页写法一致（归一化全等，子串不算）。
        """
        payload = {
            "company": company,
            "confirm": confirm,
            "render": render,
            "notify": notify,
        }
        return self._request("DELETE", "/api/agent/unapplied", payload=payload)

    def get_notices(self, limit: int = 20) -> Dict[str, Any]:
        """获取看板提醒通知。"""
        return self._request("GET", "/api/agent/notices", params={"limit": limit})

    def get_info(self) -> Dict[str, Any]:
        """获取端点清单与 function-calling 工具定义。"""
        return self._request("GET", "/api/agent/info")

    def get_manual(self) -> str:
        """获取在线 Markdown API 手册。"""
        res = self._request("GET", "/api/agent/manual")
        return str(res)

    # ==================== 写接口（直写，耗时 ~0.3s） ====================

    def record_application(
        self,
        company: str,
        position: Optional[str] = None,
        status: Optional[str] = None,
        date: Optional[str] = None,
        stage_date: Optional[str] = None,
        n: Optional[int] = None,
        mode: str = "auto",
        allow_create: bool = True,
        industry: Optional[str] = None,
        batch: Optional[str] = None,
        job_direction: Optional[str] = None,
        render: bool = True,
        notify: bool = True,
    ) -> Dict[str, Any]:
        """记录一次投递（POST /api/agent/applications）。

        - company: 公司名（必填）
        - position: 投递岗位（缺省用岗位方向）
        - status: 投递状态（默认新建为已投递，同名已有记录则保持原状态）
        - date: 投递日期，默认今天
        - stage_date: 阶段更新日期，默认随状态变化盖今天
        - n: 岗位数
        - mode: auto(默认：同公司多岗位追加为 A + B) / append / replace
        - allow_create: 岗位表无此公司时是否自动建行，默认 True
        - render: 写完后重生成看板 HTML（批量导入可传 False，最后统一调 render）
        - notify: 是否在看板写通知消息
        """
        payload = {
            "company": company,
            "position": position,
            "status": status,
            "date": date,
            "stage_date": stage_date,
            "n": n,
            "mode": mode,
            "allow_create": allow_create,
            "industry": industry,
            "batch": batch,
            "job_direction": job_direction,
            "render": render,
            "notify": notify,
        }
        cleaned = {k: v for k, v in payload.items() if v is not None}
        return self._request("POST", "/api/agent/applications", payload=cleaned)

    def update_application(
        self,
        company: str,
        position: Optional[str] = None,
        status: Optional[str] = None,
        date: Optional[str] = None,
        stage_date: Optional[str] = None,
        n: Optional[int] = None,
        allow_create: bool = False,
        render: bool = True,
        notify: bool = True,
    ) -> Dict[str, Any]:
        """修改已有投递记录（PATCH /api/agent/applications）。

        - company: 公司名（必填）
        - position: 定位岗位（可选，多条记录时定位用）
        - status: 新状态（自动盖今天为阶段更新日期）
        - date: 投递日期
        - stage_date: 指定阶段更新日期
        - allow_create: 为 True 时不存在自动新建（等同于 POST）
        """
        payload = {
            "company": company,
            "position": position,
            "status": status,
            "date": date,
            "stage_date": stage_date,
            "n": n,
            "allow_create": allow_create,
            "render": render,
            "notify": notify,
        }
        cleaned = {k: v for k, v in payload.items() if v is not None}
        return self._request("PATCH", "/api/agent/applications", payload=cleaned)

    def remove_application(
        self,
        company: str,
        position: Optional[str] = None,
        confirm: bool = True,
        render: bool = True,
        notify: bool = True,
    ) -> Dict[str, Any]:
        """撤销录错的投递记录（DELETE /api/agent/applications）。

        注意：必须 confirm=True；如果是招聘挂了/淘汰，请用 update_application 改状态，勿删。
        """
        payload = {
            "company": company,
            "position": position,
            "confirm": confirm,
            "render": render,
            "notify": notify,
        }
        cleaned = {k: v for k, v in payload.items() if v is not None}
        return self._request("DELETE", "/api/agent/applications", payload=cleaned)

    def upsert_job(
        self,
        company: str,
        industry: Optional[str] = None,
        batch: Optional[str] = None,
        direction: Optional[str] = None,
        date: Optional[str] = None,
        status: Optional[str] = None,
        applied: Optional[str] = None,
        applied_at: Optional[str] = None,
        referral_code: Optional[str] = None,
        apply_link: Optional[str] = None,
        create: bool = True,
        render: bool = True,
        notify: bool = True,
    ) -> Dict[str, Any]:
        """新增/修改公司岗位条目与内推信息（POST /api/agent/jobs）。

        - referral_code: 内推码，写「内推汇总」页
        - apply_link: 投递链接，写 data/内推链接.json
        - status: 投递状态，若提供会同时同步投递记录
        """
        payload = {
            "company": company,
            "industry": industry,
            "batch": batch,
            "direction": direction,
            "date": date,
            "status": status,
            "applied": applied,
            "applied_at": applied_at,
            "referral_code": referral_code,
            "apply_link": apply_link,
            "create": create,
            "render": render,
            "notify": notify,
        }
        cleaned = {k: v for k, v in payload.items() if v is not None}
        return self._request("POST", "/api/agent/jobs", payload=cleaned)

    def add_exam(
        self,
        company: str,
        kind: str,
        when: str,
        place: Optional[str] = None,
        link: Optional[str] = None,
        note: Optional[str] = None,
        status: Optional[str] = None,
        render: bool = True,
        notify: bool = True,
    ) -> Dict[str, Any]:
        """登记笔试/面试/测评安排（POST /api/agent/exams）。

        - company: 公司名（必填）
        - kind: 考试类别（笔试 / 面试 / 测评 / AI面 等）
        - when: 考试时间（如 2026-11-02 15:00）
        - place: 地点或会议平台
        - link: 考试/会议链接
        - note: 备注说明（请勿填密码或身份证号）
        - status: 同时把投递状态更新为对应值（如 面试通知 / 笔试通知）
        """
        payload = {
            "company": company,
            "kind": kind,
            "when": when,
            "place": place,
            "link": link,
            "note": note,
            "status": status,
            "render": render,
            "notify": notify,
        }
        cleaned = {k: v for k, v in payload.items() if v is not None}
        return self._request("POST", "/api/agent/exams", payload=cleaned)

    def remove_exam(
        self,
        company: str,
        kind: Optional[str] = None,
        when: Optional[str] = None,
        confirm: bool = True,
        render: bool = True,
        notify: bool = True,
    ) -> Dict[str, Any]:
        """删除已考完或作废的考试场次（DELETE /api/agent/exams）。"""
        payload = {
            "company": company,
            "kind": kind,
            "when": when,
            "confirm": confirm,
            "render": render,
            "notify": notify,
        }
        cleaned = {k: v for k, v in payload.items() if v is not None}
        return self._request("DELETE", "/api/agent/exams", payload=cleaned)

    def render(self) -> Dict[str, Any]:
        """手动触发重新渲染看板 HTML（POST /api/agent/render）。"""
        return self._request("POST", "/api/agent/render", payload={})

    # ==================== 对话接口（非必要不调用） ====================

    def chat(self, message: str, sync: bool = True, timeout: int = 120) -> Dict[str, Any]:
        """与看板内嵌 Agent 对话（POST /api/agent/chat）。

        注意：能用上述直写接口就尽量用直写接口（0.3s vs 20s+）。仅用于复杂自然语言理解。
        """
        return self._request(
            "POST",
            "/api/agent/chat",
            payload={"message": message, "sync": sync, "timeout": timeout},
            timeout=timeout + 30,
        )

    def abort(self) -> Dict[str, Any]:
        """中断看板 Agent 当前回合。"""
        return self._request("POST", "/api/agent/abort", payload={})

    def reset(self) -> Dict[str, Any]:
        """重置看板 Agent 对话上下文。"""
        return self._request("POST", "/api/agent/reset", payload={})


# ---------- 全局单例与向后兼容快捷函数 ----------

_default_client = QiuzhaoAgentClient()


def get_client(url: Optional[str] = None) -> QiuzhaoAgentClient:
    if url:
        return QiuzhaoAgentClient(base_url=url)
    return _default_client


def overview(text: bool = False):
    return _default_client.get_overview(text=text)


def applications(
    status: Optional[str] = None,
    company: Optional[str] = None,
    direction: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    return _default_client.get_applications(
        status=status,
        company=company,
        direction=direction,
        limit=limit,
        offset=offset,
    )


def company(name: str):
    return _default_client.get_company(name=name)


def unapplied(
    direction: Optional[str] = None,
    company: Optional[str] = None,
    industry: Optional[str] = None,
    limit: int = 50,
):
    return _default_client.get_unapplied(
        direction=direction, company=company, industry=industry, limit=limit
    )


def exams():
    return _default_client.get_exams()


def notices(limit: int = 20):
    return _default_client.get_notices(limit=limit)


def info():
    return _default_client.get_info()


def manual():
    return _default_client.get_manual()


def record_application(**kwargs):
    return _default_client.record_application(**kwargs)


def update_application(**kwargs):
    return _default_client.update_application(**kwargs)


def remove_application(**kwargs):
    return _default_client.remove_application(**kwargs)


def upsert_job(**kwargs):
    return _default_client.upsert_job(**kwargs)


def add_exam(**kwargs):
    return _default_client.add_exam(**kwargs)


def remove_exam(**kwargs):
    return _default_client.remove_exam(**kwargs)


def render():
    return _default_client.render()


def remove_unapplied(**kwargs):
    return _default_client.remove_unapplied(**kwargs)


def unapplied_page(**kwargs):
    return _default_client.get_unapplied_page(**kwargs)


def chat(message: str, sync: bool = True, timeout: int = 120):
    return _default_client.chat(message=message, sync=sync, timeout=timeout)


def record_submission(
    company_name: str,
    position: str,
    link: str = "",
    channel: str = "官网直投",
    date: str = "",
    note: str = "",
) -> Dict[str, Any]:
    """快捷记录投递（已升级为直写 REST API，不再依赖看板 Agent 对话）。

    直接调用 POST /api/agent/applications，若提供了 link 则同时记录投递链接。
    """
    res = _default_client.record_application(
        company=company_name,
        position=position,
        status="已投递",
        date=date or None,
    )
    if link:
        try:
            _default_client.upsert_job(
                company=company_name,
                apply_link=link,
                render=False,
                notify=False,
            )
        except Exception:
            pass
    return res


# ---------- CLI 命令行解析 ----------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="秋招看板 Agent API CLI 工具（直写模式 · 仅限 8898 端口）"
    )
    p.add_argument(
        "--url", help="自定义看板地址（必须为 8898 端口；严禁 28898 端口）"
    )
    p.add_argument("--token", help="鉴权 Token（X-QZ-Token）")

    sub = p.add_subparsers(dest="cmd", required=True)

    # 1. overview
    p_ov = sub.add_parser("overview", help="大盘概览")
    p_ov.add_argument("--text", action="store_true", help="返回 Markdown 纯文本")

    # 2. apps
    p_apps = sub.add_parser("apps", help="投递记录检索")
    p_apps.add_argument(
        "--status",
        help="状态过滤：active/failed/progressed/all 或具体状态（如 面试中）",
    )
    p_apps.add_argument("--company", help="公司名过滤")
    p_apps.add_argument("--direction", help="方向过滤")
    p_apps.add_argument("-n", "--limit", type=int, default=50, help="返回条数")
    p_apps.add_argument("--offset", type=int, default=0, help="分页偏移")
    p_apps.add_argument("--json", action="store_true", help="输出完整 JSON")

    # 3. company
    p_comp = sub.add_parser("company", help="指定公司全貌")
    p_comp.add_argument("name", help="公司名称")

    # 4. unapplied
    p_un = sub.add_parser("unapplied", help="未投递推荐岗位")
    p_un.add_argument("--direction", help="岗位方向")
    p_un.add_argument("--company", help="公司名称")
    p_un.add_argument("--industry", help="行业分类")
    p_un.add_argument("-n", "--limit", type=int, default=50)
    p_un.add_argument("--offset", type=int, default=0)
    p_un.add_argument(
        "--include-applied",
        action="store_true",
        help="含「同公司另有一岗已投」的行（关闭 exclude_applied）",
    )

    # 14. exclude-unapplied（从未投递清单排除公司）
    p_exu = sub.add_parser("exclude-unapplied", help="从未投递清单排除公司")
    p_exu.add_argument("company", help="公司名称（须与招聘岗位页写法一致）")
    p_exu.add_argument(
        "--confirm", "--yes", action="store_true", help="确认标志（必须指定）"
    )

    # 5. exams
    sub.add_parser("exams", help="待办笔试/面试日程")

    # 6. notices
    p_not = sub.add_parser("notices", help="看板通知消息")
    p_not.add_argument("-n", "--limit", type=int, default=20)

    # 7. record (直写记录投递)
    p_rec = sub.add_parser("record", help="记录一次投递（直写 Excel，无需 Agent）")
    p_rec.add_argument("company", help="公司名称，或'公司|岗位|链接|渠道'管道格式")
    p_rec.add_argument("position", nargs="?", default=None, help="投递岗位")
    p_rec.add_argument("--status", default="已投递", help="投递状态（默认已投递）")
    p_rec.add_argument("--date", help="投递日期（默认今天）")
    p_rec.add_argument("--stage-date", help="阶段更新日期")
    p_rec.add_argument("--link", help="投递链接（同时写入内推链接库）")
    p_rec.add_argument(
        "--mode",
        choices=["auto", "append", "replace"],
        default="auto",
        help="同公司追加策略",
    )
    p_rec.add_argument(
        "--no-render", action="store_true", help="不重新生成看板网页"
    )

    # 8. update (修改投递状态/信息)
    p_upd = sub.add_parser("update", help="修改投递记录（改状态/日期/岗位）")
    p_upd.add_argument("company", help="公司名称")
    p_upd.add_argument("--position", help="定位岗位名（公司有多岗位时必选）")
    p_upd.add_argument("--status", help="新状态（如 面试中、笔试挂、offer）")
    p_upd.add_argument("--date", help="修改投递日期")
    p_upd.add_argument("--stage-date", help="手动指定阶段更新日期")
    p_upd.add_argument(
        "--no-render", action="store_true", help="不重新生成看板网页"
    )

    # 9. remove (撤销投递)
    p_rem = sub.add_parser("remove", help="撤销录错的投递记录")
    p_rem.add_argument("company", help="公司名称")
    p_rem.add_argument("--position", help="岗位名称")
    p_rem.add_argument(
        "--confirm", "--yes", action="store_true", help="确认删除标志（必须指定）"
    )

    # 10. job (修改/新增公司岗位与内推)
    p_job = sub.add_parser("job", help="修改/新增公司岗位与内推信息")
    p_job.add_argument("company", help="公司名称")
    p_job.add_argument("--referral-code", help="内推码")
    p_job.add_argument("--apply-link", help="投递链接")
    p_job.add_argument("--direction", help="岗位方向")
    p_job.add_argument("--batch", help="批次")
    p_job.add_argument("--industry", help="行业")
    p_job.add_argument("--status", help="同时更新投递状态")

    # 11. exam (登记考试)
    p_ex = sub.add_parser("exam", help="登记笔试/面试/测评安排")
    p_ex.add_argument("company", help="公司名称")
    p_ex.add_argument("kind", help="类型：笔试/面试/测评/AI面")
    p_ex.add_argument("when", help="时间：例如 '2026-11-02 15:00'")
    p_ex.add_argument("--place", help="平台地点")
    p_ex.add_argument("--link", help="会议/考试链接")
    p_ex.add_argument("--status", help="同时同步的投递状态（如 面试通知）")
    p_ex.add_argument("--note", help="备注")

    # 12. remove-exam
    p_rex = sub.add_parser("remove-exam", help="删除已考完或作废的考试安排")
    p_rex.add_argument("company", help="公司名称")
    p_rex.add_argument("--kind", help="考试类型")
    p_rex.add_argument("--when", help="时间")
    p_rex.add_argument(
        "--confirm", "--yes", action="store_true", help="确认删除标志"
    )

    # 13. render
    sub.add_parser("render", help="手动触发重生成看板网页")

    # 14. chat（已废弃：端点 410，仅保留入口给出明确提示）
    p_chat = sub.add_parser("chat", help="【已废弃 410】请改用直写子命令（record/update/job 等）")
    p_chat.add_argument("message", nargs="+", help="对话消息")
    p_chat.add_argument("--async", dest="sync", action="store_false")

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    client = QiuzhaoAgentClient(base_url=args.url, token=args.token)

    try:
        if args.cmd == "overview":
            res = client.get_overview(text=args.text)
            if args.text and isinstance(res, str):
                print(res)
            else:
                print(json.dumps(res, ensure_ascii=False, indent=2))

        elif args.cmd == "apps":
            res = client.get_applications(
                status=args.status,
                company=args.company,
                direction=args.direction,
                limit=args.limit,
                offset=args.offset,
            )
            if args.json or not isinstance(res, dict) or "items" not in res:
                print(json.dumps(res, ensure_ascii=False, indent=2))
            else:
                items = res.get("items", [])
                for it in items:
                    c = it.get("company", "")[:16]
                    p = (it.get("position") or "")[:28]
                    s = it.get("status", "")
                    d = it.get("date", "?")
                    print(f"{d} | {c:<18} | {p:<30} | {s}")
                print(f"\n共 {res.get('total', len(items))} 条（当前显示 {len(items)} 条）")

        elif args.cmd == "company":
            res = client.get_company(name=args.name)
            print(json.dumps(res, ensure_ascii=False, indent=2))

        elif args.cmd == "unapplied":
            res = client.get_unapplied_page(
                direction=args.direction,
                company=args.company,
                industry=args.industry,
                limit=args.limit,
                offset=args.offset,
                exclude_applied=not args.include_applied,
            )
            print(json.dumps(res, ensure_ascii=False, indent=2))

        elif args.cmd == "exams":
            res = client.get_exams()
            print(json.dumps(res, ensure_ascii=False, indent=2))

        elif args.cmd == "notices":
            res = client.get_notices(limit=args.limit)
            print(json.dumps(res, ensure_ascii=False, indent=2))

        elif args.cmd == "record":
            # 兼容管道格式：'公司|岗位|链接|渠道'
            if "|" in args.company and args.position is None:
                parts = [p.strip() for p in args.company.split("|")]
                comp = parts[0]
                pos = parts[1] if len(parts) > 1 else ""
                link = parts[2] if len(parts) > 2 else ""
            else:
                comp = args.company
                pos = args.position
                link = args.link

            res = client.record_application(
                company=comp,
                position=pos,
                status=args.status,
                date=args.date,
                stage_date=args.stage_date,
                mode=args.mode,
                render=not args.no_render,
            )
            if link:
                try:
                    client.upsert_job(
                        company=comp,
                        apply_link=link,
                        render=False,
                        notify=False,
                    )
                except Exception:
                    pass
            print(json.dumps(res, ensure_ascii=False, indent=2))

        elif args.cmd == "update":
            res = client.update_application(
                company=args.company,
                position=args.position,
                status=args.status,
                date=args.date,
                stage_date=args.stage_date,
                render=not args.no_render,
            )
            print(json.dumps(res, ensure_ascii=False, indent=2))

        elif args.cmd == "remove":
            if not args.confirm:
                print(
                    "错误：撤销投递记录必须指定 --confirm 或 --yes 参数（防止误删）",
                    file=sys.stderr,
                )
                return 2
            res = client.remove_application(
                company=args.company,
                position=args.position,
                confirm=True,
            )
            print(json.dumps(res, ensure_ascii=False, indent=2))

        elif args.cmd == "job":
            res = client.upsert_job(
                company=args.company,
                referral_code=args.referral_code,
                apply_link=args.apply_link,
                direction=args.direction,
                batch=args.batch,
                industry=args.industry,
                status=args.status,
            )
            print(json.dumps(res, ensure_ascii=False, indent=2))

        elif args.cmd == "exam":
            res = client.add_exam(
                company=args.company,
                kind=args.kind,
                when=args.when,
                place=args.place,
                link=args.link,
                status=args.status,
                note=args.note,
            )
            print(json.dumps(res, ensure_ascii=False, indent=2))

        elif args.cmd == "remove-exam":
            if not args.confirm:
                print(
                    "错误：删除考试安排必须指定 --confirm 或 --yes 参数",
                    file=sys.stderr,
                )
                return 2
            res = client.remove_exam(
                company=args.company,
                kind=args.kind,
                when=args.when,
                confirm=True,
            )
            print(json.dumps(res, ensure_ascii=False, indent=2))

        elif args.cmd == "exclude-unapplied":
            if not args.confirm:
                print(
                    "错误：从未投递清单排除公司必须指定 --confirm 或 --yes",
                    file=sys.stderr,
                )
                return 2
            res = client.remove_unapplied(company=args.company, confirm=True)
            print(json.dumps(res, ensure_ascii=False, indent=2))

        elif args.cmd == "render":
            res = client.render()
            print(json.dumps(res, ensure_ascii=False, indent=2))

        elif args.cmd == "chat":
            # /api/agent/chat 已 410 废弃（看板API手册 v1.4.0），不再发起请求
            print("【已废弃】/api/agent/chat 端点已 410 下线，chat 子命令不再可用。")
            print("请改用直写子命令：record / update / job / exam / remove 等；")
            print("无法结构化的信息请如实报告给用户，由用户在看板上处理。")
            return 2

    except Exception as e:
        print(f"执行失败: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
