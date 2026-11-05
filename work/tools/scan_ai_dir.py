# -*- coding: utf-8 -*-
"""scan_ai_dir.py — 取消行业排除，只按「AI Agent / AI 应用」方向筛查全池。

判据（用户 2026-11-03 明确：不按行业排除，只按方向）：
  命中 = Agent / 智能体 / Multi-Agent、AI 应用、大模型（应用/工程/落地）、RAG、MCP、
         LLM 应用、人工智能、AI 平台、知识库、智能问答、Prompt / 工作流
  硬排除 = 纯算法研究（预训练/微调/视觉/导航/规控/感知）、推理加速与算子（CUDA/TensorRT/vLLM）、
         端侧部署与量化剪枝、硬件（射频/天线/模拟IC/FPGA/电源/结构/机械）、非技术岗
  地区 = 北京 base 不投（除非同时含沪杭深宁苏蓉穗）
  行业 = 不参与筛选（本轮取消）
"""
import json
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(_HERE, '..', '..'))
d = json.load(open(os.path.join(ROOT, 'work', '_archive', '20261103', 'board_data.json'), encoding='utf-8'))


def norm(s):
    return re.sub(r'[\s　()（）]', '', str(s or ''))


HIT = re.compile(
    r'Agent|智能体|AI\s*应用|AI应用|大模型|RAG|MCP|LLM|人工智能|AI\s*平台|AI平台|'
    r'知识库|智能问答|Prompt|工作流|AI\s*中台|AI\s*工程')
BAD = re.compile(
    r'推理加速|算子|CUDA|TensorRT|vLLM|SGLang|量化剪枝|端侧部署|模型压缩|'
    r'预训练|算法研究|视觉算法|图像算法|导航定位|SLAM|规控|感知算法|'
    r'射频|天线|模拟IC|版图|工艺|结构设计|机械设计|嵌入式硬件|FPGA|电源|'
    r'销售|营销|财务|法务|行政|人力|采购|品质|生产|美术|策划|柜员|客户经理|'
    r'商务拓展|市场|运营|管培生|培训生')

ex_ind = set()
for r in d['rules']:
    if isinstance(r, list) and r and r[0] == '未投递清单排除行业':
        ex_ind.update(x.strip() for x in re.split(r'[、，,/]', str(r[1])) if x.strip())

ex_unapp = set()
for r in d['rules']:
    if isinstance(r, list) and r and r[0] == '未投递清单排除公司':
        for x in re.split(r'[、，,/]', str(r[1])):
            if x.strip():
                ex_unapp.add(norm(x))
ex_co = set(ex_unapp)
for r in d['rules']:
    if isinstance(r, list) and r and r[0] == '排除公司':
        ex_co.add(norm(r[1]))

ended, ended_bad = {}, {}
for e in d['ended']:
    if isinstance(e, list) and len(e) >= 2:
        note = str(e[2]) if len(e) > 2 else ''
        ended.setdefault(norm(e[0]), []).append(str(e[1]) + ' / ' + note[:50])
        if any(k in note or k in str(e[1]) for k in ('不投递', '无合适岗位', '不符合', '无匹配')):
            ended_bad.setdefault(norm(e[0]), []).append(note[:60])

apps = {}
for a in d['apps']:
    apps.setdefault(norm(a.get('company')), []).append(
        (a.get('position'), a.get('date'), a.get('status')))

ck = {}
for f in os.listdir(os.path.join(ROOT, 'work')):
    if f.startswith('ckpt_') and f.endswith('.json'):
        try:
            c = json.load(open(os.path.join(ROOT, 'work', f), encoding='utf-8'))
            ck[norm(c.get('company'))] = (c.get('state'), str(c.get('position'))[:44],
                                          str(c.get('reason'))[:70])
        except Exception:
            pass

unapp = {u['company'] for u in d['unapplied']}

buckets = {'可入清单': [], '已在清单': [], '已投递': [], '已归档判不投': [],
           '公司级排除': [], '有断点': [], '北京base': [], '红线方向': []}

for j in d['jobs']:
    co, ind = j.get('company'), j.get('industry') or ''
    dirn = str(j.get('direction') or '')
    st = str(j.get('status') or '')
    if st and not any(k in st for k in ('待投递', '未投递', '待办', '待沟通', '未沟通')):
        continue
    if not HIT.search(dirn):
        continue
    n = norm(co)
    rec = {'company': co, 'industry': ind, 'batch': str(j.get('batch')),
           'date': str(j.get('date')), 'direction': dirn}
    if co in unapp:
        buckets['已在清单'].append(rec); continue
    if n in apps:
        buckets['已投递'].append(dict(rec, detail=apps[n])); continue
    if n in ended_bad:
        buckets['已归档判不投'].append(dict(rec, detail=ended_bad[n])); continue
    if BAD.search(dirn) and not re.search(r'Agent|智能体|AI\s*应用|AI应用|大模型', dirn):
        buckets['红线方向'].append(rec); continue
    if '北京' in dirn and not re.search(r'上海|杭州|深圳|南京|苏州|成都|广州', dirn):
        buckets['北京base'].append(rec); continue
    if n in ck:
        buckets['有断点'].append(dict(rec, detail=ck[n])); continue
    if n in ex_co:
        buckets['公司级排除'].append(rec); continue
    buckets['可入清单'].append(rec)

for k, v in buckets.items():
    print('=' * 70)
    print('%s：%d' % (k, len(v)))
    for r in sorted(v, key=lambda x: x['date'], reverse=True):
        extra = ''
        if 'detail' in r:
            extra = ' | ' + str(r['detail'])[:80]
        print('  %-11s %-22s %-7s %s' % (r['date'], r['company'][:22], r['industry'], extra))
        print('       %s' % r['direction'][:100])
