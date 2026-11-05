# -*- coding: utf-8 -*-
"""check_isolation.py — 「用户数据 / 项目功能」隔离自检（L1 + L2 + L3）。

判据三层（背景与结论见 work/DATA_ISOLATION.md）：

  L1 版本库层
     - git 追踪的文件必须全部落在 work/release.manifest 的 [functional] 段里；
     - 追踪文件与待分发文件里不得出现身份证号 / 手机号 / 个人邮箱 / SMTP 授权码。

  L2 分发包层
     - pack_release 的取件清单（同一个 manifest）与 PII 闸门必须通过。

  L3 运行期层
     - 功能代码里不得写死本机绝对路径（盘符 + 用户目录 / 项目目录）；
     - 敏感数据文件名（mail_auth.json / user_config.json / application_profile.json /
       profile_v2.json）只允许出现在已 import user_config 的文件里，或登记在豁免表。

用法（仓库根执行）：
  python work/tools/check_isolation.py             # 常规自检；未入库的功能文件记为 WARN
  python work/tools/check_isolation.py --strict    # 基线提交后使用：未入库即失败
  python work/tools/check_isolation.py --json      # 机器可读

退出码：0 通过 / 1 有失败项 / 2 用法或环境错误。
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "work" / "release.manifest"

sys.path.insert(0, str(ROOT / "work" / "tools"))
import pack_release  # noqa: E402  复用它的 PII 规则与扫描器，不复制第二套指纹

# ── L3：写死的本机路径 ────────────────────────────────────
HARDCODED_RULES = [
    ("本机用户目录", re.compile(r"[A-Za-z]:[\\/]+Users[\\/]", re.I)),
    ("本机工作区路径", re.compile(r"[A-Za-z]:[\\/]+(auto-delivery|resume-autofill)\b", re.I)),
]
HARDCODED_EXT = {".py", ".js", ".bat", ".cmd", ".ps1"}
HARDCODED_SKIP = "# noqa: isolation"

# ── L3：绕过 user_config 的第二配置源 ────────────────────
SEAM_RULE = re.compile(
    r"(mail_auth\.json|user_config\.json|application_profile\.json|profile_v2\.json)")
SEAM_IMPORT = re.compile(r"^\s*(from|import)\s+user_config\b|\buser_config\.(cfg|load)\b", re.M)
# 豁免必须写清理由：改这里等于放松 L3，请在 PR/提交说明里同步
SEAM_EXEMPT = {
    "work/tools/user_config.py": "配置解析器本身，就是那个唯一入口",
    "work/tools/pack_release.py": "只在排除规则里出现这些文件名，从不读取",
    "work/tools/check_isolation.py": "自检脚本本身",
    "work/tools/profile_sync.py": "档案三源比对工具：只读比对，路径按仓库根约定推导（已知缺口，未纳入本次改造）",
    ".agents/skills/auto-resume-submit/scripts/qiuzhao_api.py":
        "看板客户端：只读 user_config 的 dashboard_url 一个字段，且必须能脱离仓库单独运行，故不 import work/tools 的模块",
}

# ── L1：必须被忽略 / 必须可追踪 的代表性路径 ──────────────
MUST_BE_IGNORED = [
    "work/user_config.json",
    "work/mail_auth.json",
    "work/application_profile.json",
    "work/rfa/profile_v2.json",
    "work/ckpt_示例公司.json",
    "work/gates.jsonl",
    "work/_draft/邮件正文.txt",
    "work/shot_示例.png",
    "data/resume/简历-示例.pdf",
    "resume-autofill/ledger/x.jsonl",
    "re-niuke/package.json",
]
MUST_BE_TRACKABLE = [
    ".gitignore",
    "work/release.manifest",
    "work/tools/check_isolation.py",
    "work/mail_auth.example.json",
    ".agents/skills/campus-apply-pipeline/SKILL.md",
]


# 解析器只有一份：pack_release.load_manifest。打包与自检共用同一套语义。
load_manifest = pack_release.load_manifest


def expand(root, patterns):
    """展开 glob；返回 ({相对 posix 路径: 命中的 glob}, [空 glob])。"""
    root = Path(root)
    found, empty = {}, []
    for pat in patterns:
        hits = [p for p in root.glob(pat) if p.is_file()]
        if not hits:
            empty.append(pat)
        for p in hits:
            found[p.relative_to(root).as_posix()] = pat
    return found, empty


def tracked(root=ROOT):
    """git 追踪的文件（posix 相对路径）。"""
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError("git ls-files 失败：%s" % proc.stderr.decode("utf-8", "replace")[:200])
    raw = proc.stdout.decode("utf-8", "replace")
    return [x for x in raw.split("\0") if x]


def ignored_paths(rels, root=ROOT):
    """批量问 git：这些路径里哪些被 .gitignore 挡住。

    manifest 的 glob 会扫到 __pycache__ 这类构建产物，它们本来就不该入库，
    不能算作「功能文件未追踪」。
    """
    if not rels:
        return set()
    proc = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "--stdin", "-z"],
        input=("\0".join(rels) + "\0").encode("utf-8"),
        capture_output=True, check=False,
    )
    return {x for x in proc.stdout.decode("utf-8", "replace").split("\0") if x}


def scan_hardcoded(paths, root=ROOT):
    """返回 [(相对路径, 行号, 规则名, 片段)]。"""
    hits = []
    for p in paths:
        p = Path(p)
        if p.suffix.lower() not in HARDCODED_EXT:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if HARDCODED_SKIP in line:
                continue
            for name, rx in HARDCODED_RULES:
                m = rx.search(line)
                if m:
                    hits.append((p.relative_to(root).as_posix(), i, name, m.group(0)[:40]))
    return hits


def scan_seam(paths, root=ROOT):
    """返回 [(相对路径, 行号, 片段)]：引用了敏感文件名却没用 user_config。"""
    hits = []
    for p in paths:
        p = Path(p)
        rel = p.relative_to(root).as_posix()
        if p.suffix.lower() != ".py" or rel in SEAM_EXEMPT:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if SEAM_IMPORT.search(text):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            m = SEAM_RULE.search(line)
            if m:
                hits.append((rel, i, m.group(1)))
    return hits


def ignore_verdict(root=ROOT):
    """逐条跑 git check-ignore，返回 (未拦住, 被误拦)。"""
    def ignored(rel):
        return subprocess.run(
            ["git", "-C", str(root), "check-ignore", "-q", rel],
            capture_output=True, check=False,
        ).returncode == 0

    leak = [p for p in MUST_BE_IGNORED if not ignored(p)]
    blocked = [p for p in MUST_BE_TRACKABLE if ignored(p)]
    return leak, blocked


def main(argv=None):
    ap = argparse.ArgumentParser(description="用户数据 / 项目功能 隔离自检")
    ap.add_argument("--strict", action="store_true", help="未入库的功能文件也判失败（基线提交后用）")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    a = ap.parse_args(argv)

    try:
        man = load_manifest()
        func, empty = expand(ROOT, man["functional"])
        gen, _ = expand(ROOT, man["generated"])
        trk = tracked()
        # __pycache__ 等被忽略的构建产物不算「功能文件未入库」
        func = {k: v for k, v in func.items() if k not in ignored_paths(list(func))}
    except (OSError, ValueError, RuntimeError) as e:
        print("自检无法开始：%s" % e)
        return 2

    func_paths = [ROOT / rel for rel in sorted(func)]
    trk_paths = [ROOT / rel for rel in trk]

    out_of_manifest = sorted(set(trk) - set(func))
    not_tracked = sorted(set(func) - set(trk))
    gen_tracked = sorted(set(trk) & set(gen))
    pii_tracked = pack_release.scan([ROOT / r for r in trk]) if trk else []
    pii_func = pack_release.scan(func_paths)
    rel_files = pack_release.collect()
    pii_release = pack_release.scan(rel_files)
    hard = scan_hardcoded(func_paths + trk_paths)
    seam = scan_seam(func_paths)
    leak, blocked = ignore_verdict()

    fail = []
    fail += [("OUT_OF_MANIFEST", r) for r in out_of_manifest]
    fail += [("GENERATED_TRACKED", r) for r in gen_tracked]
    fail += [("EMPTY_GLOB", g) for g in empty]
    fail += [("PII_TRACKED", "%s:%d %s" % (f, n, k)) for f, n, k, s in pii_tracked]
    fail += [("PII_MANIFEST", "%s:%d %s" % (f, n, k)) for f, n, k, s in pii_func]
    fail += [("PII_RELEASE", "%s:%d %s" % (f, n, k)) for f, n, k, s in pii_release]
    fail += [("HARDCODED_PATH", "%s:%d %s" % (f, n, k)) for f, n, k, s in hard]
    fail += [("SEAM_BYPASS", "%s:%d %s" % (f, n, s)) for f, n, s in seam]
    fail += [("IGNORE_LEAK", p) for p in leak]
    fail += [("IGNORE_TOO_STRICT", p) for p in blocked]
    warn = [("NOT_TRACKED", r) for r in not_tracked]
    if a.strict:
        fail += warn
        warn = []

    summary = {
        "manifest": {"functional_globs": len(man["functional"]), "files": len(func),
                     "generated_globs": len(man["generated"]), "empty_globs": empty},
        "git": {"tracked": len(trk), "out_of_manifest": len(out_of_manifest),
                "generated_but_tracked": len(gen_tracked)},
        "pii": {"tracked": len(pii_tracked), "manifest": len(pii_func),
                "release": len(pii_release)},
        "l3": {"hardcoded_paths": len(hard), "seam_bypass": len(seam)},
        "ignore": {"leak": leak, "too_strict": blocked},
        "fail": fail,
        "warn": warn,
        "ok": not fail,
    }

    if a.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if not fail else 1

    print("=" * 64)
    print("隔离自检 · 用户数据 / 项目功能")
    print("-" * 64)
    print("  真源清单    work/release.manifest  [functional] %d 条 → %d 个文件"
          % (len(man["functional"]), len(func)))
    print("  git 追踪    %d 个文件（越界 %d，可重生成却入库 %d）"
          % (len(trk), len(out_of_manifest), len(gen_tracked)))
    print("  L1 PII      追踪 %d 处 / 功能文件 %d 处" % (len(pii_tracked), len(pii_func)))
    print("  L2 分发     %d 个文件待打包，PII 命中 %d 处" % (len(rel_files), len(pii_release)))
    print("  L3 代码     写死本机路径 %d 处 / 绕过 user_config %d 处"
          % (len(hard), len(seam)))
    print("  忽略规则    该拦未拦 %d 条 / 误拦 %d 条" % (len(leak), len(blocked)))
    if warn:
        print("-" * 64)
        print("  告警：%d 个功能文件尚未入库（基线提交后用 --strict 复检）" % len(warn))
        for kind, item in warn[:5]:
            print("    ~ %s %s" % (kind, item))
        if len(warn) > 5:
            print("    ~ …另有 %d 个" % (len(warn) - 5))
    if fail:
        print("-" * 64)
        print("失败项 %d 条：" % len(fail))
        for kind, item in fail:
            print("    x %-20s %s" % (kind, item))
        print("=" * 64)
        print("结论：未通过")
        return 1
    print("=" * 64)
    print("结论：通过（0 失败%s）" % ("，0 告警" if not warn else "，%d 条告警" % len(warn)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
