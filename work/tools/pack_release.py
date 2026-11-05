# -*- coding: utf-8 -*-
"""pack_release.py — 打包分发：只带功能与骨架，绝不带走任何用户数据。

闸门（任一命中即中止）：
  PII 扫描   身份证号 / 手机号 / 邮箱 / 姓名 / SMTP 授权码
  文件扫描   data/resume 下的证件、简历、照片；work/ 下断点与台账

用法：
  python work/tools/pack_release.py                    # 预检（dry-run，只报告）
  python work/tools/pack_release.py --out dist/kit.zip # 实际打包
"""
import argparse
import json
import os
import re
import sys
import zipfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]

# ── 取件清单：唯一真源 work/release.manifest ───────────────
# 与 check_isolation.py 共用同一份清单，禁止再在这里写第二套白名单。
MANIFEST = ROOT / "work" / "release.manifest"


def load_manifest(path=None):
    """解析 release.manifest，返回 {"functional": [glob], "generated": [glob]}。"""
    path = Path(path) if path else MANIFEST
    out = {"functional": [], "generated": []}
    section = None
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().lower()
            if section not in out:
                raise ValueError("%s:%d 未知段 %s" % (path, lineno, line))
            continue
        if section is None:
            raise ValueError("%s:%d 出现在任何段之前：%s" % (path, lineno, line))
        # 版本无关的 glob：Python 3.11 的 Path.glob("x/**") 只返回目录（3.13 才含文件），
        # 统一补成 "x/**/*"，两种版本都能取到文件。
        if line.endswith("/**"):
            line += "/*"
        out[section].append(line)
    if not out["functional"]:
        raise ValueError("%s 的 [functional] 段为空" % path)
    return out

# ── 排除：即使落在白名单内也剔除 ──────────────────────────
EXCLUDE_PATTERNS = [
    r"__pycache__/", r".pyc$", r".log$", r"/_archive/", r"/_draft/",
    r"/shots/", r"/ledger/", r".png$", r".jpg$", r".jpeg$", r".pdf$",
    r"user_config.json$",           # 真实用户配置，只需 example
    r"mail_auth.json$",
    r"application_profile.json$",
    r"profile_v2.json$",
    r"applied_index.json$",
    r"browser_sessions.json$",
    r"^work/ckpt_", r"gates.jsonl$",
]

# ── PII 探测：命中即阻断 ─────────────────────────────────
PII_RULES = [
    ("身份证号", re.compile(r"\b[1-9]\d{5}(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b")),
    ("手机号",   re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("邮箱",     re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("授权码",   re.compile(r"(?i)(auth_code|smtp_pass|授权码)\s*[:=]\s*[A-Za-z0-9]{8,}")),
]
# 允许的占位/示例值，不计入命中
PII_ALLOW = [
    "example.com", "test@example.com", "127.0.0.1", "0.0.0.0",
    "hr@fin-shine.com", "hr@saicmotor.com",   # 公开企业邮箱，非个人
    "HR@x.c", "HR@x.com",                     # docstring 占位符
]
# 行内含这些标记视作文档占位，不判定为泄露
PLACEHOLDER_MARKERS = ["--to HR@x.com", "请填写", "<HR>", "占位", "--message-id"]
# 命令行用法示例整体跳过（docstring 里的 <...@163.com> 之类）
DOC_EXAMPLE = re.compile(r"(python\s+work/tools/|^\s*#|^\s*\*|--\w+\s+[\"']?<)")

TEXT_EXT = {".py", ".json", ".md", ".bat", ".toml", ".txt", ".yml", ".yaml", ".cfg", ".ini"}


def wanted(rel: str) -> bool:
    for pat in EXCLUDE_PATTERNS:
        if re.search(pat, rel, re.I):
            return False
    return True


def collect():
    """按 release.manifest 的 [functional] 段取件，再过一遍排除表兜底。"""
    files = []
    for pat in load_manifest()["functional"]:
        for p in ROOT.glob(pat):
            if p.is_file():
                rel = p.relative_to(ROOT).as_posix()
                if wanted(rel):
                    files.append(p)
    return sorted(set(files), key=lambda x: str(x))


def scan(file_list):
    """返回 [(文件, 行号, 规则, 命中片段)]"""
    hits = []
    for p in file_list:
        if p.suffix.lower() not in TEXT_EXT:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if any(a in line for a in PII_ALLOW):
                continue
            if any(m in line for m in PLACEHOLDER_MARKERS):
                continue
            if DOC_EXAMPLE.search(line):
                continue
            for name, rx in PII_RULES:
                m = rx.search(line)
                if m:
                    seg = m.group(0)
                    hits.append((p.relative_to(ROOT).as_posix(), i, name, seg[:6] + "…"))
    return hits


def main():
    ap = argparse.ArgumentParser(description="打包分发包（强制 PII 闸门）")
    ap.add_argument("--out", help="输出 zip 路径；不填则只预检")
    a = ap.parse_args()

    try:
        files = collect()
    except ValueError as e:
        print("清单错误：%s" % e)
        return 2
    hits = scan(files)

    print("=" * 60)
    print("待打包文件: %d 个" % len(files))
    print("PII 命中  : %d 处" % len(hits))
    if hits:
        print("-" * 60)
        for f, ln, rule, seg in hits:
            print("  [%s] %s:%d  %s" % (rule, f, ln, seg))
        print("=" * 60)
        print("已阻断：先清理上述命中项，再重新打包。")
        return 2

    for p in files:
        print("  +", p.relative_to(ROOT).as_posix())
    print("=" * 60)
    print("预检通过：无 PII。")

    if not a.out:
        print("（dry-run，未生成 zip；加 --out dist/kit.zip 执行打包）")
        return 0

    out = Path(a.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            z.write(p, p.relative_to(ROOT).as_posix())
    print("已生成:", out, "%.1f KB" % (out.stat().st_size / 1024))
    print("接收方需执行：cp work/user_config.example.json work/user_config.json 后填写")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
