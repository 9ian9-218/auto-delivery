#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 mattpocock/skills 来源、尚未分组的技能补进「mata pocock」分组。

真源是 `~/.agents/.skill-lock.json`（v3）：每个技能的 `source` 字段就是安装来源。
按 source == "mattpocock/skills" 反推归属，比按文体猜测可靠。

写的是面板自己的显示配置：
    ~/.dsh/skills/.system/skill-viewer/groups.json
只动分组成员，不改任何技能目录。

用法
----
    python work/tools/group_mattpocock.py status
    python work/tools/group_mattpocock.py apply
    python work/tools/group_mattpocock.py apply --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SOURCE = "mattpocock/skills"
GROUP_NAME = "Matt Pocock"
SCOPE = "global"


def dsh_home() -> Path:
    home = os.environ.get("DSH_HOME", "").strip()
    return Path(home).expanduser() if home else Path.home() / ".dsh"


def agents_home() -> Path:
    env = os.environ.get("DSH_AGENTS_HOME", "").strip()
    return Path(env).expanduser() if env else Path.home() / ".agents"


def groups_file() -> Path:
    return dsh_home() / "skills" / ".system" / "skill-viewer" / "groups.json"


def lock_file() -> Path:
    return agents_home() / ".skill-lock.json"


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def on_disk(name: str) -> bool:
    d = agents_home() / "skills" / name
    return d.is_dir() and ((d / "SKILL.md").is_file() or (d / "SKILL.md.disabled").is_file())


def collect() -> dict:
    lock = load_json(lock_file())["skills"]
    groups = load_json(groups_file())["groups"]

    target_id = next((gid for gid, g in groups.items() if g.get("name") == GROUP_NAME), None)
    if target_id is None:
        raise SystemExit(f'分组 "{GROUP_NAME}" 不存在于 {groups_file()}')

    members = list(groups[target_id].get("scopes", {}).get(SCOPE, []))
    owned = sorted(n for n, meta in lock.items() if meta.get("source") == SOURCE and on_disk(n))
    missing_lock = sorted(n for n, meta in lock.items() if meta.get("source") == SOURCE and not on_disk(n))

    # 其它分组里的归属：一个技能可以同时属于多个分组（groupsForSkill 返回数组），
    # 但用户要的是「未分组的」那些，所以默认跳过已在别组的人。
    elsewhere = {}
    for gid, group in groups.items():
        if gid == target_id:
            continue
        for name in group.get("scopes", {}).get(SCOPE, []):
            elsewhere.setdefault(name, []).append(group.get("name", gid))

    return {
        "target_id": target_id,
        "groups": groups,
        "members": members,
        "owned": owned,
        "elsewhere": elsewhere,
        "missing_lock": missing_lock,
    }


def cmd_status() -> int:
    info = collect()
    members = info["members"]
    elsewhere = info["elsewhere"]
    to_add = [n for n in info["owned"] if n not in members and n not in elsewhere]
    shared = [n for n in info["owned"] if n not in members and n in elsewhere]

    print(f"分组配置 : {groups_file()}")
    print(f"来源真源 : {lock_file()}  (source == {SOURCE})")
    print(f"分组     : {GROUP_NAME}  ({info['target_id']})")
    print("-" * 74)
    print(f"该来源在锁内且磁盘存在 : {len(info['owned'])} 个")
    print(f"已在组内               : {len(members)} 个")
    print(f"待加入（完全未分组）   : {len(to_add)} 个")
    for n in to_add:
        print(f"   + {n}")
    if shared:
        print(f"\n已在其它分组、本组不含 : {len(shared)} 个")
        for n in shared:
            print(f"   ~ {n}  -> {', '.join(elsewhere[n])}")
    if info["missing_lock"]:
        print(f"\n锁内有记录但磁盘无目录（无法分组）：{', '.join(info['missing_lock'])}")
    return 0


def cmd_apply(dry_run: bool, include_shared: bool) -> int:
    info = collect()
    members = info["members"]
    elsewhere = info["elsewhere"]
    todo = [
        n
        for n in info["owned"]
        if n not in members and (include_shared or n not in elsewhere)
    ]
    shared = [n for n in info["owned"] if n not in members and n in elsewhere]
    if not todo:
        print("无需改动：该来源的技能已全部在组内。")
        if shared and not include_shared:
            print("（另有 %d 个已在其它分组，加 --include-shared 可一并并入）" % len(shared))
        return 0

    new_members = members + todo
    groups = info["groups"]
    groups[info["target_id"]].setdefault("scopes", {})[SCOPE] = new_members

    print(f"分组 {GROUP_NAME}: {len(members)} -> {len(new_members)} 个成员")
    for n in todo:
        print(f"   + {n}")
    if shared and not include_shared:
        print(f"\n跳过（已在其它分组）: {', '.join(shared)}")
        print("需要一并对齐 mattpocock 归属就加 --include-shared。")

    if dry_run:
        print("\n[dry-run] 未写入。")
        return 0

    target = groups_file()
    payload = {"version": 1, "groups": groups}
    tmp = target.with_name(target.name + f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, target)
    print(f"\n已写入 {target}（{len(new_members)} 个成员）")
    print("面板刷新即可看到（分组是纯显示配置，不需要重启 DSH）。")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="把 mattpocock/skills 来源的未分组技能并入「mata pocock」分组")
    ap.add_argument("action", choices=["status", "apply"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--include-shared", action="store_true", help="把已在其它分组的同名技能也并进来")
    args = ap.parse_args(argv)
    return cmd_status() if args.action == "status" else cmd_apply(args.dry_run, args.include_shared)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
