#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 DSH 自带的 office 七件套改造成「面板可开关」的文件技能。

问题
----
office / office-docx / office-pptx / office-xlsx / office-render /
office-recalculate / office-export-pdf 是 bundled 技能：
  - 由 @deepseek-ai/dsh-skill-office 在进程内注册，source = "bundled"；
  - 桌面端由 @deepseek-ai/dsh-desktop-host 无条件 ctx.plugin 挂载，
    cordis.patch.yml 里没有可 disabled 的 id；
  - dsh-skill-mcp-panel 的卡片开关判据是 editable = source !== "bundled"
    且 assertEditable 要求有可写 path —— 所以这七张卡只显示「开启」静态标签。

解法
----
技能注册表同一层内按 rank 去重，**小者胜**：bundled = 600，用户根
~/.dsh/skills = 400。把这七份 SKILL.md 复制进用户根后：
  - 用户根那份顶掉 bundled（bundled 只留一行 shadow 警告日志）；
  - 面板看到的 provider = filesystem、source = user-dsh、path 可写，
    于是卡片从「静态标签」变成真正的开关；
  - 开关动作 = 把 SKILL.md 改名 SKILL.md.disabled，宿主 watcher 热感知。

三份要跑 LibreOffice 的技能（render / recalculate / export-pdf）在原实现里
是 `get()` 时动态追加 CLI 绝对路径的；落到磁盘后必须把这段**烘焙进去**，
否则关掉 bundled 就丢了路径。

用法
----
    python work/tools/office_skills_panelize.py install           # 落盘七份（保留已有关/开状态）
    python work/tools/office_skills_panelize.py install --disable-all
    python work/tools/office_skills_panelize.py status
    python work/tools/office_skills_panelize.py enforce --all
    python work/tools/office_skills_panelize.py enable office-xlsx
    python work/tools/office_skills_panelize.py remove            # 彻底还原为 bundled

脚本只在 ~/.dsh/skills 下动带 MARKER 的文件；用户自建的技能一律不碰。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

MARKER = "<!-- dsh-office-panelized: managed by office_skills_panelize.py -->"

SKILL_NAMES = [
    "office",
    "office-docx",
    "office-pptx",
    "office-xlsx",
    "office-render",
    "office-recalculate",
    "office-export-pdf",
]

# 需要烘焙 LibreOffice Kit 绝对路径的三份
RUNTIME_SKILLS = {"office-render", "office-recalculate", "office-export-pdf"}

ASSET_CANDIDATES = [
    Path(r"E:/dsh/resources/app/dsh/node_modules/@deepseek-ai/dsh-skill-office/assets"),
    Path(r"E:/dsh/resources/app/runtime/office-skills"),
]

NODE_CANDIDATES = [
    Path.home() / ".dsh/dsh-runtimes/dsh-primary-runtime/dependencies/node/bin/node.exe",
    Path(r"E:/dsh/resources/app/runtime/primary-runtime/dependencies/node/bin/node.exe"),
]

CLI_CANDIDATES = [
    Path(r"E:/dsh/resources/app/dsh/node_modules/@deepseek-ai/libreoffice-kit/lib/cli.js"),
    Path(r"E:/dsh/resources/app.asar.unpacked/node_modules/@deepseek-ai/libreoffice-kit/lib/cli.js"),
]


def user_skill_root() -> Path:
    home = os.environ.get("DSH_HOME", "").strip()
    return (Path(home).expanduser() if home else Path.home() / ".dsh") / "skills"


def first_existing(paths: list[Path], what: str) -> Path:
    for p in paths:
        if p.exists():
            return p
    raise SystemExit(f"{what} 未找到，候选：\n  " + "\n  ".join(str(p) for p in paths))


def resolve_runtime() -> dict[str, str]:
    node = first_existing(NODE_CANDIDATES, "打包 Node")
    cli = first_existing(CLI_CANDIDATES, "LibreOffice Kit cli.js")
    return {"node": node.as_posix(), "cli": cli.as_posix()}


def runtime_block(rt: dict[str, str]) -> str:
    payload = json.dumps({"libreofficeKit": rt}, indent=2)
    return (
        "\n\n## Installed LibreOffice Kit\n\n"
        "Use these absolute paths for every LibreOffice Kit command. "
        "Pass the CLI entry as the first argument to Node.\n\n" + payload
    )


def skill_dir(root: Path, name: str) -> Path:
    return root / name


def skill_file(root: Path, name: str) -> Path:
    return skill_dir(root, name) / "SKILL.md"


def disabled_file(root: Path, name: str) -> Path:
    return skill_dir(root, name) / "SKILL.md.disabled"


def is_managed(root: Path, name: str) -> bool:
    for f in (skill_file(root, name), disabled_file(root, name)):
        if f.is_file():
            try:
                return MARKER in f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return False
    return False


def state_of(root: Path, name: str) -> str:
    if skill_file(root, name).is_file():
        return "managed+enabled" if is_managed(root, name) else "foreign"
    if disabled_file(root, name).is_file():
        return "managed+disabled" if is_managed(root, name) else "foreign+disabled"
    return "absent"


def read_body(assets: Path, name: str) -> str:
    raw = (assets / name / "SKILL.md").read_text(encoding="utf-8")
    # 落盘版把 marker 插在 frontmatter 之后，正文之前，保持 frontmatter 可解析
    if not raw.startswith("---"):
        return raw + "\n" + MARKER + "\n"
    end = raw.find("\n---", 3)
    if end < 0:
        return raw + "\n" + MARKER + "\n"
    head = raw[: end + 4]
    body = raw[end + 4 :].lstrip("\n")
    return head + "\n" + MARKER + "\n\n" + body


def cmd_install(root: Path, names: list[str], disable_all: bool) -> int:
    assets = first_existing(ASSET_CANDIDATES, "office 技能资产目录")
    rt = resolve_runtime()
    block = runtime_block(rt)
    root.mkdir(parents=True, exist_ok=True)
    print(f"资产目录 : {assets.as_posix()}")
    print(f"目标根   : {root.as_posix()}")
    print(f"node     : {rt['node']}")
    print(f"cli      : {rt['cli']}")
    print("-" * 72)

    for name in names:
        existing = state_of(root, name)
        if existing.startswith("foreign"):
            print(f"[skip] {name}: 用户自建技能已占用该名字（{existing}），未覆盖")
            continue
        was_disabled = disabled_file(root, name).is_file() and existing != "absent"
        target = skill_dir(root, name)
        # 复制整棵技能目录（office 含 references/sidecar.md）
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(assets / name, target)
        body = read_body(assets, name)
        if name in RUNTIME_SKILLS:
            body += block
        sf = skill_file(root, name)
        sf.write_text(body, encoding="utf-8")

        disable_now = disable_all if disable_all else was_disabled
        if disable_now:
            df = disabled_file(root, name)
            if df.exists():
                df.unlink()
            sf.rename(df)
        print(f"[ok  ] {name:<22} -> {'SKILL.md.disabled (关闭)' if disable_now else 'SKILL.md (开启)'}")
    return 0


def cmd_enforce(root: Path, names: list[str], enabled: bool) -> int:
    rc = 0
    for name in names:
        st = state_of(root, name)
        if not st.startswith("managed"):
            print(f"[skip] {name}: {st}")
            rc = 1
            continue
        sf, df = skill_file(root, name), disabled_file(root, name)
        if enabled and df.is_file():
            sf.exists() and sf.unlink()
            df.rename(sf)
            print(f"[on  ] {name}")
        elif not enabled and sf.is_file():
            df.exists() and df.unlink()
            sf.rename(df)
            print(f"[off ] {name}")
        else:
            print(f"[--  ] {name}: 已是目标状态")
    return rc


def cmd_status(root: Path, names: list[str]) -> int:
    print(f"技能根目录 : {root.as_posix()}")
    print(f"{'技能':<24}{'状态':<22}{'备注'}")
    print("-" * 72)
    on = off = 0
    for name in names:
        st = state_of(root, name)
        note = ""
        if st == "managed+enabled":
            on += 1
            note = "面板可开关 · 当前开启"
        elif st == "managed+disabled":
            off += 1
            note = "面板可开关 · 当前关闭"
        elif st == "foreign":
            on += 1
            note = "用户自建同名技能（脚本不碰）"
        elif st == "foreign+disabled":
            off += 1
            note = "用户自建同名技能（已停用）"
        else:
            note = "未落盘 —— 仍是 bundled，面板只显示静态标签"
        print(f"{name:<24}{st:<22}{note}")
    print("-" * 72)
    print(f"共 {len(names)} 个：开启 {on}，关闭 {off}，未落盘 {len(names) - on - off}")
    return 0


def cmd_remove(root: Path, names: list[str]) -> int:
    for name in names:
        if not is_managed(root, name):
            print(f"[skip] {name}: 非本脚本管理，保留")
            continue
        d = skill_dir(root, name)
        shutil.rmtree(d)
        print(f"[rm  ] {name} -> 已删除，回退为 bundled")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="把 DSH 自带 office 技能改造成面板可开关的文件技能")
    ap.add_argument("action", choices=["install", "status", "enforce", "enable", "disable", "remove"])
    ap.add_argument("skills", nargs="*", help="技能名；install/status/remove 缺省=全部七个")
    ap.add_argument("--all", action="store_true", help="enforce 时作用于全部七个")
    ap.add_argument("--disable-all", action="store_true", help="install 后立即全部关闭")
    args = ap.parse_args(argv)

    root = user_skill_root()

    if args.action in ("enable", "disable"):
        names = args.skills or (list(SKILL_NAMES) if args.all else [])
        if not names:
            print("enable/disable 需要技能名，或用 --all", file=sys.stderr)
            return 2
        bad = [n for n in names if n not in SKILL_NAMES]
        if bad:
            print(f"未知技能: {', '.join(bad)}", file=sys.stderr)
            return 2
        return cmd_enforce(root, names, args.action == "enable")

    if args.action == "enforce":
        names = list(SKILL_NAMES) if args.all else args.skills
        if not names:
            print("enforce 需要 --all 或技能名", file=sys.stderr)
            return 2
        return cmd_enforce(root, names, args.all)

    names = args.skills or list(SKILL_NAMES)
    bad = [n for n in names if n not in SKILL_NAMES]
    if bad:
        print(f"未知技能: {', '.join(bad)}", file=sys.stderr)
        return 2

    if args.action == "install":
        return cmd_install(root, names, args.disable_all)
    if args.action == "status":
        return cmd_status(root, names)
    return cmd_remove(root, names)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
