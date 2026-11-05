# -*- coding: utf-8 -*-
"""filter_unapplied_ai.py — 把看板未投递清单按「AI Agent / AI 应用」方向分档，
生成可直接照做的清单。看板接口没有方向白名单，只能精确匹配，所以分档在本地做。

分档：
  A 明确命中  = Agent / 智能体 / Multi-Agent / AI 应用 / 大模型应用 / RAG / MCP / LLM 应用
  B 聚合待核  = 方向是「研发、营销、技术等」这类聚合串，里面出现 AI/大模型/人工智能 字样，
                必须点进 JD 才能定，不能直接投
  C 非 AI     = 聚合串里没有任何 AI 字样，按当前方向规则不投

用法：python work/tools/filter_unapplied_ai.py
输出：work/unapplied_ai_filtered.md
"""
import json
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(_HERE, '..', '..'))
DATA = os.path.join(ROOT, 'work', '_archive', '20261103', 'board_data.json')
OUT = os.path.join(ROOT, 'work', 'unapplied_ai_filtered.md')

A = re.compile(r'Agent|智能体|Multi-?Agent|AI\s*应用|AI应用|大模型应用|RAG|MCP|LLM\s*应用|'
               r'AI\s*Agent|智能问答|知识库|Prompt')
B = re.compile(r'人工智能|大模型|AI\s*软件|AI软件|AI\s*平台|AI平台|AI\s*工程|AI工程师|AI')
CITY = re.compile(r'上海|杭州|深圳|南京|苏州|成都|广州|北京')


def bucket(direction):
    d = str(direction or '')
    if A.search(d):
        return 'A'
    if B.search(d):
        return 'B'
    return 'C'


def main():
    d = json.load(open(DATA, encoding='utf-8'))
    rows = []
    for u in d['unapplied']:
        rows.append({
            'company': u['company'], 'industry': u.get('industry'),
            'batch': u.get('batch'), 'date': u.get('date'),
            'direction': str(u.get('direction') or ''),
            'tier': bucket(u.get('direction')),
        })
    rows.sort(key=lambda r: (r['tier'], str(r['date'])), reverse=False)

    buckets = {'A': [], 'B': [], 'C': []}
    for r in rows:
        buckets[r['tier']].append(r)

    lines = ['# 未投递清单 · 按 AI Agent / AI 应用 方向分档', '',
             '生成时间 2026-11-03 · 来源看板 :8898 `/api/agent/unapplied`', '',
             '判定：只看方向，不看行业（行业排除本轮已按用户要求绕过）。', '',
             '---', '']
    titles = {'A': '## A · 明确命中 AI Agent / AI 应用（可直接进入投递流程）',
              'B': '## B · 聚合方向含 AI 字样（必须点开 JD 核对主体职责）',
              'C': '## C · 非 AI 方向（当前规则不投）'}
    for k in ('A', 'B', 'C'):
        lines.append(titles[k])
        lines.append('')
        if not buckets[k]:
            lines.append('（无）')
            lines.append('')
            continue
        lines.append('| 公司 | 行业 | 更新日 | 方向 |')
        lines.append('|---|---|---|---|')
        for r in buckets[k]:
            lines.append('| %s | %s | %s | %s |' % (
                r['company'], r['industry'] or '-', r['date'],
                r['direction'].replace('|', '/')[:80]))
        lines.append('')
    lines += ['---', '',
              '## 数量', '',
              '- A 明确命中：%d' % len(buckets['A']),
              '- B 聚合待核：%d' % len(buckets['B']),
              '- C 非 AI：%d' % len(buckets['C']),
              '- 合计：%d' % len(rows), '']

    open(OUT, 'w', encoding='utf-8').write('\n'.join(lines))
    for k in ('A', 'B', 'C'):
        print('[%s] %d' % (k, len(buckets[k])))
        for r in buckets[k]:
            print('   %-26s %-8s %s' % (r['company'][:26], r['industry'] or '-',
                                        r['direction'][:56]))
    print('\n写入', OUT)


if __name__ == '__main__':
    main()
