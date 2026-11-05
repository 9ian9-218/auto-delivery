# -*- coding: utf-8 -*-
"""611 站点操作helpers：真实鼠标点击、原生键盘选择、卡片编辑与保存。

合成事件在这个站点（jQuery 委托 + 自有校验模型）上不可靠：
- 直接改 el.value 只动 DOM，模型不变；
- 下拉必须用键盘（Home/ArrowDown）产生原生 change 才会写入模型；
- 「保存」是 a[name=btnSave]，必须真实鼠标点击。
"""
import json
import sys
import time

sys.path.insert(0, 'work/rfa')
import native_driver as N

KEYS = {
    'ArrowDown': 40, 'ArrowUp': 38, 'Home': 36, 'End': 35, 'Enter': 13, 'Tab': 9,
}


class Site:
    def __init__(self):
        self.ws, self.send, self.ev, self.tgt = N.connect()
        self.cid = N.find_ctx(self.ev)
        if self.cid is None:
            raise RuntimeError('扩展上下文未找到')

    # ---------- 基础 ----------
    def js(self, body, await_promise=False, timeout=60):
        r = self.ev(body, self.cid, await_promise=await_promise, timeout=timeout)
        if isinstance(r, dict) and '__error' in r:
            raise RuntimeError(str(r['__error'])[:200])
        return r

    def mouse(self, x, y):
        for t in ('mousePressed', 'mouseReleased'):
            self.send('Input.dispatchMouseEvent',
                      {'type': t, 'x': int(x), 'y': int(y), 'button': 'left', 'clickCount': 1})
        time.sleep(0.25)

    def key(self, name, times=1):
        for _ in range(times):
            for t in ('keyDown', 'keyUp'):
                self.send('Input.dispatchKeyEvent',
                          {'type': t, 'key': name, 'code': name,
                           'windowsVirtualKeyCode': KEYS[name],
                           'nativeVirtualKeyCode': KEYS[name]})
            time.sleep(0.08)

    def center(self, finder_js):
        """返回某元素中心坐标。先滚入视口并等滚动稳定，再取坐标。

        站点启用了平滑滚动：scrollIntoView 之后立即读 rect 会拿到滚动途中的
        旧坐标，点击就会落偏（曾因此误点到「删除」）。所以必须等稳定后重读。
        """
        self.ev("""(() => {
          const el = %s;
          if (el) el.scrollIntoView({block: 'center'});
          return 1;
        })()""" % finder_js, self.cid)
        time.sleep(0.45)
        pos = self.ev("""return (() => {
          const el = %s;
          if (!el) return null;
          const r = el.getBoundingClientRect();
          if (!r.width && !r.height) return null;
          return {x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2)};
        })()""" % finder_js, self.cid)
        if isinstance(pos, dict) and '__error' in pos:
            return None
        return pos

    def hit_is(self, x, y, finder_js):
        """命中校验：该坐标上的元素必须是目标本身或其后代。"""
        r = self.ev("""return (() => {
          const el = %s;
          const at = document.elementFromPoint(%d, %d);
          if (!el || !at) return {ok: false, why: 'missing'};
          return {ok: el === at || el.contains(at) || at.contains(el),
                  hit: at.tagName + '|' + ((at.innerText || '').trim().slice(0, 10))};
        })()""" % (finder_js, int(x), int(y)), self.cid)
        return r

    def click_el(self, finder_js, wait=0.4, retries=3):
        """带命中校验的点击：坐标落偏时重取，绝不盲点。"""
        for _ in range(retries):
            pos = self.center(finder_js)
            if not pos or pos.get('y') is None:
                return False
            if pos['y'] < 8 or pos['y'] > 2000:
                time.sleep(0.3)
                continue
            hit = self.hit_is(pos['x'], pos['y'], finder_js)
            if isinstance(hit, dict) and hit.get('ok'):
                self.mouse(pos['x'], pos['y'])
                time.sleep(wait)
                return True
            time.sleep(0.4)
        return False

    # ---------- 文本 ----------
    def type_text(self, finder_js, text):
        """点进输入框 → 全选 → 原生输入覆盖。"""
        if not self.click_el(finder_js, wait=0.2):
            return False
        self.send('Input.dispatchKeyEvent',
                  {'type': 'keyDown', 'key': 'a', 'code': 'KeyA',
                   'windowsVirtualKeyCode': 65, 'modifiers': 2})
        self.send('Input.dispatchKeyEvent',
                  {'type': 'keyUp', 'key': 'a', 'code': 'KeyA',
                   'windowsVirtualKeyCode': 65, 'modifiers': 2})
        time.sleep(0.1)
        self.send('Input.insertText', {'text': text})
        time.sleep(0.25)
        return True

    # ---------- 下拉 ----------
    def focus_el(self, finder_js):
        return self.ev("""return (() => {
          const el = %s;
          if (!el) return null;
          el.scrollIntoView({block: 'center'});
          el.focus();
          return {idx: el.selectedIndex, n: el.options ? el.options.length : 0};
        })()""" % finder_js, self.cid)

    def selected_text(self, finder_js):
        return self.ev("""return (() => {
          const el = %s;
          if (!el) return null;
          return el.options ? (el.options[el.selectedIndex] || {}).text : null;
        })()""" % finder_js, self.cid)

    def select_option(self, finder_js, want):
        """原生键盘把下拉选到目标项：Home 归位 → 逐项 ArrowDown。"""
        info = self.focus_el(finder_js)
        if not info:
            return {'ok': False, 'reason': 'no-select'}
        self.key('Home', 1)
        time.sleep(0.1)
        for i in range(info['n'] + 2):
            cur = self.selected_text(finder_js)
            if str(cur).strip() == want:
                return {'ok': True, 'text': cur, 'steps': i}
            self.key('ArrowDown', 1)
            time.sleep(0.06)
        cur = self.selected_text(finder_js)
        return {'ok': False, 'reason': 'no-option', 'text': cur, 'want': want}

    # ---------- 卡片 ----------
    def edit_card(self, keyword):
        """点击含 keyword 的卡片上的「编辑」。"""
        js = """(() => {
          const key = %s;
          for (const e of document.querySelectorAll('button,a,span,div')) {
            if (e.children.length || (e.innerText || '').trim() !== '编辑') continue;
            let box = e;
            for (let i = 0; i < 7 && box.parentElement; i++) {
              box = box.parentElement;
              if ((box.innerText || '').length > 60) break;
            }
            if (!(box.innerText || '').includes(key)) continue;
            return e;
          }
          return null;
        })()""" % json.dumps(keyword, ensure_ascii=False)
        ok = self.click_el(js, wait=1.5)
        return ok

    def save_card(self):
        """真实鼠标点 a[name=btnSave]（教育/工作/项目等卡片编辑器顶部的保存）。"""
        js = """(() => {
          const list = [...document.querySelectorAll('a[name=btnSave]')]
             .filter(a => a.getBoundingClientRect().width > 0);
          if (!list.length) return null;
          return list.sort((a, b) =>
             a.getBoundingClientRect().top - b.getBoundingClientRect().top)[0];
        })()"""
        ok = self.click_el(js, wait=3.0)
        return ok

    def cancel_card(self):
        js = """(() => {
          const list = [...document.querySelectorAll('a,span,button')]
             .filter(e => e.children.length === 0 && (e.innerText || '').trim() === '取消')
             .filter(e => e.getBoundingClientRect().width > 0);
          if (!list.length) return null;
          return list.sort((a, b) =>
             a.getBoundingClientRect().top - b.getBoundingClientRect().top)[0];
        })()"""
        return self.click_el(js, wait=1.0)

    def card_action(self, keyword, action):
        """在含 keyword 的卡片容器内点击指定动作（editItem / delItem / btnSave / cancelItem）。

        必须用 closest('.eduhistory_drmmbnew') 限定到单张卡片：向上遍历 innerText
        会把整段教育背景都算进来，导致匹配到别的卡片。
        """
        js = """(() => {
          const key = %s, act = %s;
          for (const card of document.querySelectorAll('.eduhistory_drmmbnew')) {
            if (!(card.innerText || '').includes(key)) continue;
            for (const a of card.querySelectorAll('a[name=' + act + ']')) {
              if (a.getBoundingClientRect().width) return a;
            }
          }
          return null;
        })()""" % (json.dumps(keyword, ensure_ascii=False), json.dumps(action))
        return self.click_el(js, wait=2.2, retries=2)

    def editor_btns(self):
        return self.ev("return document.querySelectorAll('a[name=btnSave]').length;", self.cid)

    def editor_school(self):
        return self.ev("""return (() => {
          const vis = (el) => { const r = el.getBoundingClientRect(); return !!(r.width || r.height); };
          const el = [...document.querySelectorAll('input')]
            .filter(x => /SchoolName/.test(x.name || '') && vis(x))[0];
          return el ? el.value : null;
        })()""", self.cid)

    def card_text(self, keyword):
        return self.ev("""return (() => {
          const key = %s;
          const t = document.body.innerText || '';
          const i = t.indexOf(key);
          return i < 0 ? null : t.slice(Math.max(0, i - 60), i + 320).replace(/\\n{2,}/g, '\\n');
        })()""" % json.dumps(keyword, ensure_ascii=False), self.cid)
