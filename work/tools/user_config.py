# -*- coding: utf-8 -*-
"""user_config.py — 用户态配置的唯一入口（把「项目功能」与「用户数据」隔离）。

设计原则：
  项目功能（代码、schema、工具）可以随包分发；
  用户数据（身份、简历、投递记录、cookie、邮箱授权码）一律不进代码，
  只从 work/user_config.json 与 data/ 读取。

查找顺序（先命中先用）：
  1. 环境变量 AUTO_DELIVERY_HOME 指定的项目根
  2. 从本文件向上找含 work/tools 的目录
  3. 当前工作目录

配置文件：<root>/work/user_config.json
  不存在时回退到旧版 .agents/skills/auto-resume-submit/config.json（兼容期），
  并给出 DEPRECATED 警告；两处都没有则报错并提示复制模板。

用法：
    from user_config import cfg
    phone = cfg.user("phone")
    pdf   = cfg.path("resume", "pdf")
"""
import json
import os
import sys
import warnings
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

TEMPLATE_NAME = "user_config.example.json"
CONFIG_NAME = "user_config.json"


def find_root() -> Path:
    """定位项目根：环境变量 > 向上找 work/tools > 当前目录。"""
    env = os.environ.get("AUTO_DELIVERY_HOME", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    here = Path(__file__).resolve()
    for parent in [here.parent] + list(here.parents):
        if (parent / "work" / "tools").is_dir():
            return parent
    return Path.cwd().resolve()


ROOT = find_root()
CONFIG_PATH = ROOT / "work" / CONFIG_NAME
LEGACY_PATH = ROOT / ".agents" / "skills" / "auto-resume-submit" / "config.json"


class UserConfigError(SystemExit):
    pass


class Config:
    """用户配置的只读视图。缺项一律报错并提示模板，绝不静默用默认值。"""

    def __init__(self, data: dict, root: Path, source: Path):
        self._d = data or {}
        self.root = root
        self.source = source

    def get(self, *keys, default=None):
        cur = self._d
        for k in keys:
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur

    @staticmethod
    def _is_placeholder(v) -> bool:
        """模板占位符 <...> 视同未填，避免把 <真实姓名> 当成真实值。"""
        if not isinstance(v, str):
            return False
        s = v.strip()
        return bool(s) and s.startswith("<") and s.endswith(">")

    def need(self, *keys):
        val = self.get(*keys)
        if self._is_placeholder(val):
            val = None
        if val in (None, "", [], {}):
            dotted = ".".join(str(k) for k in keys)
            raise UserConfigError(
                "缺少用户配置项 %s\n"
                "  配置文件: %s\n"
                "  模板:     %s\n"
                "  处理: 复制模板为 %s 后填写该项"
                % (dotted, self.source, self.root / "work" / TEMPLATE_NAME, CONFIG_NAME)
            )
        return val

    def user(self, key, default=None):
        return self.get("user", key, default=default)

    def path(self, section, key) -> Path:
        raw = self.need(section, key)
        return self.resolve(raw)

    def is_set(self, *keys) -> bool:
        """配置项是否真的填了（占位符算未填）。"""
        v = self.get(*keys)
        if self._is_placeholder(v):
            return False
        return v not in (None, "", [], {})

    def resolve(self, raw) -> Path:
        if self._is_placeholder(raw):
            raise UserConfigError(
                "配置项仍是模板占位 %r，请改成真实路径（模板见 work/%s）" % (raw, TEMPLATE_NAME)
            )
        s = str(raw).replace("<workspace>", str(self.root))
        if "<" in s and ">" in s:
            raise UserConfigError(
                "配置项还有未替换的占位符 %r，请改成真实值（模板见 work/%s）" % (raw, TEMPLATE_NAME)
            )
        p = Path(s).expanduser()
        if not p.is_absolute():
            p = self.root / p
        return p

    def path_or_none(self, section, key):
        raw = self.get(section, key)
        if not raw or self._is_placeholder(raw):
            return None
        return self.resolve(raw)

    @property
    def dashboard_url(self) -> str:
        return self.need("dashboard_url")

    @property
    def browser_service(self) -> str:
        return self.get("browser_service", default="http://127.0.0.1:8792")

    @property
    def browser_project_root(self) -> str:
        return self.get("browser_project_root", default="")

    @property
    def browser_debug_port(self) -> int:
        return int(os.environ.get("REMOTE_DEBUG_PORT") or self.get("browser_debug_port", default=9222))

    @property
    def target_grad_year(self) -> int:
        return int(self.get("user", "target_grad_year", default=0) or 0)

    @property
    def task_timeout_seconds(self) -> int:
        return int(self.get("limits", "task_timeout_seconds", default=900))

    @property
    def default_pick_count(self) -> int:
        return int(self.get("limits", "default_pick_count", default=5))

    def _path_ok(self, section, key) -> bool:
        """路径项是否可用：已填、非占位符、且文件真实存在。"""
        try:
            p = self.path_or_none(section, key)
        except SystemExit:
            return False
        return bool(p) and p.exists()

    def summary(self) -> dict:
        has = self.is_set
        return {
            "source": str(self.source),
            "has_user_name": has("user", "name"),
            "has_phone": has("user", "phone"),
            "has_email": has("user", "email"),
            "has_dashboard": has("dashboard_url"),
            "has_resume_pdf": self._path_ok("resume", "pdf"),
        }


_CFG = None


def load(reload: bool = False) -> Config:
    global _CFG
    if _CFG is not None and not reload:
        return _CFG

    if CONFIG_PATH.is_file():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            _CFG = Config(json.load(f), ROOT, CONFIG_PATH)
        return _CFG

    if LEGACY_PATH.is_file():
        warnings.warn(
            "正在读取旧版配置 %s。请迁移到 %s（模板见 work/%s）。"
            % (LEGACY_PATH, CONFIG_PATH, TEMPLATE_NAME),
            DeprecationWarning,
            stacklevel=2,
        )
        with open(LEGACY_PATH, encoding="utf-8") as f:
            legacy = json.load(f)
        mapped = {
            "workspace_root": legacy.get("workspace_root"),
            "browser_project_root": legacy.get("browser_project_root"),
            "browser_service": legacy.get("browser_service"),
            "dashboard_url": legacy.get("dashboard_url"),
            "user": {
                "phone": legacy.get("login_phone"),
                "target_grad_year": legacy.get("target_grad_year"),
            },
            "resume": {"pdf": legacy.get("resume_pdf"), "docx": legacy.get("resume_docx")},
            "limits": {
                "task_timeout_seconds": legacy.get("task_timeout_seconds"),
                "default_pick_count": legacy.get("default_pick_count"),
            },
        }
        _CFG = Config(mapped, ROOT, LEGACY_PATH)
        return _CFG

    raise UserConfigError(
        "未找到用户配置。\n"
        "  期望位置: %s\n"
        "  模板:     %s\n"
        "  处理: 复制模板并填写（该文件存放个人身份、简历路径等，切勿提交版本库）"
        % (CONFIG_PATH, ROOT / "work" / TEMPLATE_NAME)
    )


class _Lazy:
    def __getattr__(self, item):
        return getattr(load(), item)

    def __getitem__(self, item):
        return load().get(item)

    def __repr__(self):
        return "<UserConfig lazy>"


cfg = _Lazy()


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="检查用户配置是否就绪")
    ap.add_argument("--json", action="store_true", help="输出 JSON 摘要")
    a = ap.parse_args()
    try:
        c = load(reload=True)
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        raise SystemExit(2)
    if a.json:
        print(json.dumps(c.summary(), ensure_ascii=False, indent=2))
    else:
        print("配置来源:", c.source)
        for k, v in c.summary().items():
            if k != "source":
                print("  %-18s %s" % (k, "OK" if v else "缺失"))
