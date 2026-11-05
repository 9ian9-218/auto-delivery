# -*- coding: utf-8 -*-
"""点击「提交申请」→ 处理确认弹层 → 回读投递结果。"""
import json
import sys
import time

sys.path.insert(0, 'work/rfa')
import native_driver as N

ws, send, ev, tgt = N.connect(url_part='611.zhiye.com')
cid = N.find_ctx(ev, tries=20)
send('Page.enable')

pos = ev("""return (() => {
  const cands = [...document.querySelectorAll('a,button,span')]
    .filter(e => (e.innerText || '').trim() === '提交申请')
    .filter(e => e.getBoundingClientRect().width);
  if (!cands.length) return null;
  const el = cands[cands.length - 1];
  el.scrollIntoView({block: 'center'});
  const r = el.getBoundingClientRect();
  return {x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2),
          tag: el.tagName, cls: (el.className || '').toString().slice(0, 30)};
})()""", cid)
print('提交按钮:', pos)
if not pos:
    raise SystemExit('没找到 提交申请')

for t in ('mousePressed', 'mouseReleased'):
    send('Input.dispatchMouseEvent', {'type': t, 'x': pos['x'], 'y': pos['y'],
                                      'button': 'left', 'clickCount': 1})
time.sleep(4)

print('点击后 url:', ev('return location.href;', cid))
print('\n弹层/提示:')
print(ev("""return (() => {
  const out = [];
  for (const el of document.querySelectorAll('div,span,p,button,a')) {
    const t = (el.innerText || '').trim();
    if (!t || t.length > 60) continue;
    if (!/确认|确定|投递|提交|成功|失败|已申请|重复/.test(t)) continue;
    const r = el.getBoundingClientRect();
    if (!r.width) continue;
    out.push(t);
  }
  return [...new Set(out)].slice(0, 10);
})()""", cid, await_promise=True))
