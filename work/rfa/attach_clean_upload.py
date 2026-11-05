# -*- coding: utf-8 -*-
"""从零开始按行上传三个附件：先全清，再逐行「点上传→试 input→校验→失败回滚」。"""
import json
import os
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve()
for _p in _HERE.parents:
    if (_p / "work" / "tools" / "user_config.py").is_file():
        sys.path.insert(0, str(_p / "work" / "tools"))
        break
sys.path.insert(0, str(_HERE.parent))

from user_config import cfg
from site611 import Site

FILES = {
    '简历附件': str(cfg.path('resume', 'pdf')),
    '本科成绩单': str(cfg.path('resume', 'transcript_bachelor')),
    '生活照': str(cfg.path('resume', 'life_photo')),
}
ROWS = tuple(FILES)
S = Site()


def values():
    return json.loads(S.ev("""return JSON.stringify((() => {
      const want = %s;
      const out = {};
      for (const label of document.querySelectorAll('label')) {
        const txt = (label.innerText || '').replace(/\\s|：/g, '').trim();
        if (!want.includes(txt)) continue;
        const li = label.closest('li');
        const h = li ? li.querySelector('input[type=hidden]') : null;
        out[txt] = h ? String(h.value || '') : '';
      }
      return out;
    })())""" % json.dumps(list(ROWS), ensure_ascii=False), S.cid))


def del_row(row):
    S.ev("""return (() => {
      const want = %s;
      for (const label of document.querySelectorAll('label')) {
        if ((label.innerText || '').replace(/\\s|：/g, '').trim() !== want) continue;
        const li = label.closest('li');
        if (!li) continue;
        const ds = [...li.querySelectorAll('a,span')]
          .filter(e => (e.innerText || '').trim() === '删除');
        ds.forEach(d => d.click());
        return ds.length;
      }
      return 0;
    })()""" % json.dumps(row, ensure_ascii=False), S.cid)
    time.sleep(1.8)
    S.ev("""return (() => {
      for (const b of document.querySelectorAll('button,a,span,div')) {
        const t = (b.innerText || '').trim();
        if (!/^(确定|确认)$/.test(t)) continue;
        if (!b.getBoundingClientRect().width) continue;
        b.click(); return 'ok';
      }
      return 'none';
    })()""", S.cid)
    time.sleep(1.0)


def click_upload(row):
    return S.ev("""return (() => {
      const want = %s;
      for (const label of document.querySelectorAll('label')) {
        if ((label.innerText || '').replace(/\\s|：/g, '').trim() !== want) continue;
        const li = label.closest('li');
        const btn = li ? li.querySelector('a.uploadfile') : null;
        if (!btn) return 'no btn';
        btn.click(); return 'clicked';
      }
      return 'no row';
    })()""" % json.dumps(row, ensure_ascii=False), S.cid)


def set_file(idx, path):
    doc = S.send('DOM.getDocument', {'depth': -1})
    root = doc['root']['nodeId']
    ids = S.send('DOM.querySelectorAll', {'nodeId': root,
                                          'selector': 'input[type=file]'})['nodeIds']
    if idx >= len(ids):
        return False
    S.send('DOM.setFileInputFiles', {'files': [path], 'nodeId': ids[idx]})
    time.sleep(6)
    return True


print('初始:', values())
print('\n-- 全部清空 --')
for r in ROWS:
    del_row(r)
print('清空后:', values())

for row in ROWS:
    path = FILES[row]
    done = False
    for attempt in range(3):
        before = values()
        click_upload(row)
        for idx in range(3):
            set_file(idx, path)
            now = values()
            if now.get(row) and now.get(row) != before.get(row):
                wrong = [x for x in ROWS if x != row and now.get(x) and not before.get(x)]
                for w in wrong:
                    del_row(w)
                print('[%s] input[%d] OK%s' % (row, idx, ('（清掉误填 %s）' % wrong) if wrong else ''))
                done = True
                break
            junk = [x for x in ROWS if x != row and now.get(x) and not before.get(x)]
            for j in junk:
                del_row(j)
        if done:
            break
        print('[%s] 第 %d 轮失败，重试' % (row, attempt + 1))
    if not done:
        print('[%s] 最终失败' % row)

print('\n最终:', values())
