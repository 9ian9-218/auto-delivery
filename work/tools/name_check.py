# -*- coding: utf-8 -*-
"""name_check.py — 检查一批候选公司名是否命中「排除公司/未投递清单排除公司/已归档/已投递」。"""
import json
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(_HERE, '..', '..'))
_BOARD = os.path.join(ROOT, 'work', '_archive', '20261103', 'board_data.json')
if not os.path.isfile(_BOARD):
    raise SystemExit('缺少看板快照 %s（历史导出件，不属于项目功能）' % _BOARD)
d = json.load(open(_BOARD, encoding='utf-8'))


def norm(s):
    return re.sub(r'[\s　()（）]', '', str(s or ''))


ex_unapp, ex_co = set(), set()
for r in d['rules']:
    if not isinstance(r, list) or len(r) < 2:
        continue
    if r[0] == '未投递清单排除公司':
        for x in re.split(r'[、，,/]', str(r[1])):
            if x.strip():
                ex_unapp.add(norm(x)); ex_co.add(norm(x))
    elif r[0] == '排除公司':
        ex_co.add(norm(r[1]))

ended = {norm(e[0]) for e in d['ended'] if isinstance(e, list) and len(e) >= 2}
apps = {norm(a['company']) for a in d['apps']}
jobs = {norm(j['company']) for j in d['jobs']}

NAMES = sys.argv[1:] or [
    '埃芯半导体', '百图生科', '国药集团上海医疗器械', '好太太集团', '中恒博瑞',
    '银河航天', '索恩格电动', '光羽芯辰', '鼎益科技', '宁德博发', '中国航空工业集团',
]
for n in NAMES:
    k = norm(n)
    flags = []
    if k in ex_unapp:
        flags.append('清单排除')
    if k in ex_co:
        flags.append('排除公司')
    if k in ended:
        flags.append('已归档')
    if k in apps:
        flags.append('已投递')
    if k in jobs:
        flags.append('已有岗位行')
    print('%-24s %s' % (n, '、'.join(flags) or '★ 干净'))
