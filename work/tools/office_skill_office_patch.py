#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""给 @deepseek-ai/dsh-skill-office 打一个「用户根影子优先」补丁。

为什么需要
----------
office 七件套是 bundled 技能，永远以 `enabled: true, source: "bundled"` 出现在
注册表里。dsh-skill-mcp-panel 的 list() 是「先注册表、后磁盘扫描，同名跳过」：

    for (const skill of listed) { ...; seen.add(name); }          // bundled 行
    for (const entry of fileEntries) { if (seen.has(name)) continue; ... }  // 被吞掉

于是即使 ~/.dsh/skills/<name>/SKILL.md.disabled 存在（面板扫描器认得，enabled=false），
它也永远排不上号——卡片停在「开启」静态标签，开关点不动。这正是
"这些 skill 在此面板上只显示为开启" 的根因。

补丁做什么
----------
在 skill-office 的 provider.list() 里，跳过「用户根已存在同名影子
（SKILL.md 或 SKILL.md.disabled）」的条目。bundled 不再占位后，面板的磁盘扫描
就能把那一条 enabled=false 的文件条目顶上来，卡片变成真开关。

注意：desktop-host 是 `ctx.plugin(office_exports, ...)` 直接调用的普通对象，
不参与 cordis loader 的 HMR——**改完必须重启 DSH 才生效**。

用法
----
    python work/tools/office_skill_office_patch.py status
    python work/tools/office_skill_office_patch.py apply
    python work/tools/office_skill_office_patch.py revert
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path(
    r"E:/dsh/resources/app/dsh/node_modules/@deepseek-ai/dsh-skill-office/lib/index.js"
)
BACKUP = TARGET.with_suffix(".js.orig-office-shadow-patch")

MARKER = "office-shadow-priority"

IMPORT_OLD = '''import { readFileSync, statSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { dirname, isAbsolute, join, sep } from "node:path";
'''

IMPORT_NEW = '''import { existsSync, readFileSync, statSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { dirname, isAbsolute, join, sep } from "node:path";
import { homedir } from "node:os";
'''

FN_ANCHOR = '''/**
* Register Office skills with resources readable by the script interpreter.
* @param ctx - Context carrying the skill registry.
* @param config - Optional external assets directory for packaged applications.
*/
function apply(ctx, config = {}) {'''

FN_NEW = '''/**
* Names owned by a user-root shadow.
*
* The user skill root (~/.dsh/skills) outranks this bundled provider, so a copy
* there already wins the catalog merge. A DISABLED copy only exists on disk as
* `SKILL.md.disabled`, which no file provider lists — so without this check the
* bundled row keeps reporting `enabled: true` and the management panel shows a
* switch that cannot reach the real state. Skipping the name outright leaves
* the file row as the single, togglable authority.
*/
function shadowedNames() {
\tconst home = typeof process.env.DSH_HOME === "string" ? process.env.DSH_HOME.trim() : "";
\tconst base = home === "" ? join(homedir(), ".dsh") : home === "~" ? homedir() : home;
\tconst names = new Set();
\tfor (const skillName of SKILL_NAMES) {
\t\tconst directory = join(base, "skills", skillName);
\t\tif (existsSync(join(directory, "SKILL.md")) || existsSync(join(directory, "SKILL.md.disabled"))) names.add(skillName);
\t}
\treturn names;
}
/**
* Register Office skills with resources readable by the script interpreter.
* @param ctx - Context carrying the skill registry.
* @param config - Optional external assets directory for packaged applications.
*/
function apply(ctx, config = {}) {'''

LIST_OLD = "\t\tlist: () => Promise.resolve(candidates),"
LIST_NEW = '''\t\tlist: () => {
\t\t\tconst shadowed = shadowedNames();
\t\t\treturn Promise.resolve(candidates.filter((candidate) => !shadowed.has(candidate.name)));
\t\t},'''


def read() -> str:
    return TARGET.read_text(encoding="utf-8")


def state(text: str) -> str:
    if MARKER in text:
        return "patched"
    return "original" if LIST_OLD in text else "unknown"


def cmd_status() -> int:
    if not TARGET.is_file():
        print(f"[missing] {TARGET}")
        return 1
    text = read()
    st = state(text)
    print(f"目标   : {TARGET}")
    print(f"备份   : {BACKUP} {'(存在)' if BACKUP.is_file() else '(无)'}")
    print(f"状态   : {st}")
    if st == "patched":
        print("说明   : 已启用影子优先；重启 DSH 后 bundled 不再遮蔽用户根文件条目")
    elif st == "original":
        print("说明   : 未打补丁；面板会把 office 七件套显示为 bundled「开启」静态标签")
    return 0


def cmd_apply() -> int:
    text = read()
    st = state(text)
    if st == "patched":
        print("[skip] 已是补丁状态")
        return 0
    if st != "original":
        print("[fail] 目标文件不是预期版本，未改动。请人工比对。", file=sys.stderr)
        return 2
    if not BACKUP.is_file():
        shutil.copy2(TARGET, BACKUP)
        print(f"[bak ] 已备份 -> {BACKUP.name}")

    for old, new, label in (
        (IMPORT_OLD, IMPORT_NEW, "imports"),
        (FN_ANCHOR, FN_NEW, "provider helper"),
        (LIST_OLD, LIST_NEW, "list() filter"),
    ):
        if text.count(old) != 1:
            print(f"[fail] 锚点 {label} 命中 {text.count(old)} 次，终止（未写入）", file=sys.stderr)
            return 2
        text = text.replace(old, new)

    # 打标记，便于 status 识别
    text = text.replace(
        "const SKILL_NAMES = [",
        f"// {MARKER}: user-root shadow takes precedence over these bundled rows\nconst SKILL_NAMES = [",
        1,
    )
    TARGET.write_text(text, encoding="utf-8")
    print(f"[ok  ] 补丁已写入（{len(text)} 字节）")
    print("       重启 DSH 后生效：desktop-host 直接 require 该模块，不走 HMR")
    return 0


def cmd_revert() -> int:
    if not BACKUP.is_file():
        print(f"[fail] 无备份可回滚：{BACKUP}", file=sys.stderr)
        return 2
    shutil.copy2(BACKUP, TARGET)
    print(f"[ok  ] 已回滚 -> {TARGET.name}（{TARGET.stat().st_size} 字节）")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="dsh-skill-office 影子优先补丁")
    ap.add_argument("action", choices=["status", "apply", "revert"])
    args = ap.parse_args(argv)
    return {"status": cmd_status, "apply": cmd_apply, "revert": cmd_revert}[args.action]()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
