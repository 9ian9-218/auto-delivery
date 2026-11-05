# -*- coding: utf-8 -*-
"""原生输入通道驱动：修好队列消费 + 落键后回读校验。

要点：
- 扩展侧 push {el, value} 到 __RFA_NATIVE_INPUT__.queue，立即返回；
- 本模块 peek 队首元素（在隔离世界内聚焦并全选），再用 CDP Input.insertText 落键，
  最后 shift 并回读 input.value 确认真的写进去了。
"""
import json
import sys
import time

sys.path.insert(0, 'work/rfa')
import cdp
import websocket

_CTX_FN = {}

INIT = """
(() => {
  if (globalThis.__RFA_NATIVE_INPUT__) return 'exists';
  globalThis.__RFA_NATIVE_INPUT__ = { queue: [], last: null };
  return 'ready';
})()
"""

PEEK = """return (() => {
const q = globalThis.__RFA_NATIVE_INPUT__;
if (!q || !q.queue.length) return null;
const it = q.queue[0];
if (!it || !it.el || !it.el.isConnected) { q.queue.shift(); return { skip: true }; }
// 可信点击项：返回元素视口坐标，由驱动层用 Input.dispatchMouseEvent 点击
if (it.click) {
  try { it.el.scrollIntoView({ block: 'center' }); } catch (e) {}
  const r = it.el.getBoundingClientRect();
  q.last = it.el;
  return { click: true, x: r.left + r.width / 2, y: r.top + r.height / 2, left: q.queue.length };
}
q.last = it.el;
try { it.el.focus({ preventScroll: true }); if (it.el.select) it.el.select(); } catch (e) {}
return { value: it.value, tag: it.el.tagName, type: it.el.type || '', len: q.queue.length };
})()"""

POP_AND_READ = """return (() => {
const q = globalThis.__RFA_NATIVE_INPUT__;
if (!q || !q.queue.length) return null;
const it = q.queue.shift();
const el = it.el;
if (it.click) {
  try { if (it.__resolve) it.__resolve(true); } catch (e) {}
  return { clicked: true, left: q.queue.length };
}
const got = el && el.isConnected ? String(el.value == null ? '' : el.value) : null;
if (el && el.isConnected) {
  try { el.dispatchEvent(new Event('change', { bubbles: true })); } catch (e) {}
  try { el.dispatchEvent(new Event('blur', { bubbles: false })); } catch (e) {}
}
return { want: it.value, got, left: q.queue.length };
})()"""


def connect(url_part='611.zhiye.com'):
    tgt = next((x for x in cdp.targets() if x.get('type') == 'page' and url_part in x['url']), None)
    if not tgt:
        raise SystemExit('tab not found: ' + url_part)
    ws = websocket.create_connection(tgt['webSocketDebuggerUrl'], timeout=180,
                                     max_size=64 * 1024 * 1024, suppress_origin=True)
    st = {'id': 0}
    events = []

    def send(m, p=None, timeout=120):
        st['id'] += 1
        ws.send(json.dumps({'id': st['id'], 'method': m, 'params': p or {}}))
        t0 = time.time()
        while time.time() - t0 < timeout:
            msg = json.loads(ws.recv())
            # 站点在校验/切换时可能弹阻塞式 alert/confirm：
            # 它会卡住渲染主线程，让所有 Runtime.evaluate 永不返回。
            # 这里一出现就自动接受，避免整个填写流程被一个弹窗冻死。
            if msg.get('method') == 'Page.javascriptDialogOpening':
                try:
                    st['id'] += 1
                    ws.send(json.dumps({'id': st['id'], 'method': 'Page.handleJavaScriptDialog',
                                        'params': {'accept': True}}))
                    print('[dialog] accepted:', str(msg.get('params', {}).get('message'))[:70])
                except Exception:
                    pass
                continue
            if msg.get('method'):
                # 记录执行上下文事件：隔离世界的 contextId 只能从这里拿到
                if msg['method'] in ('Runtime.executionContextCreated',
                                     'Runtime.executionContextDestroyed',
                                     'Runtime.executionContextsCleared'):
                    events.append(msg)
            if msg.get('id') == st['id']:
                if 'error' in msg:
                    raise RuntimeError('%s: %s' % (m, str(msg['error'])[:160]))
                return msg.get('result', {})
        raise RuntimeError(m + ' timeout')

    def list_contexts():
        """让 Chrome 把当前所有执行上下文回放一遍，返回 [{id, origin, name}]。

        重复调用 Runtime.enable 时 Chrome 不会重新回放，所以先 disable 再 enable。
        """
        del events[:]
        try:
            send('Runtime.disable', timeout=10)
        except Exception:
            pass
        try:
            send('Runtime.enable', timeout=20)
        except Exception:
            pass
        out = []
        for e in events:
            p = e.get('params', {})
            c = p.get('context') or {}
            if c.get('id') is not None:
                out.append({'id': c['id'], 'origin': c.get('origin', ''),
                            'name': c.get('name', '')})
        return out

    send.__globals__  # noqa: B018  （保持 send 可被外部引用，不做改写）
    _CTX_FN['fn'] = list_contexts
    send.list_contexts = list_contexts

    def ev(expr, cid, await_promise=False, timeout=180):
        """await_promise=True 时把表达式包成 async IIFE；False 时按原样求值。

        传入的表达式两种写法都支持：
          - 'return await RFA.agent.scan();'   （自动包装）
          - 'globalThis.__X__'                 （已含 return 的会被识别）
        """
        body = expr
        if await_promise:
            body = '(async () => { %s })()' % expr
        elif expr.lstrip().startswith('return '):
            body = '(function(){ %s })()' % expr
        r = send('Runtime.evaluate', {
            'expression': body, 'returnByValue': True,
            'awaitPromise': await_promise, 'contextId': cid}, timeout=timeout)
        if r.get('exceptionDetails'):
            d = r['exceptionDetails']
            return {'__error': (d.get('exception', {}).get('description') or '')[:400]}
        return (r.get('result') or {}).get('value')

    send('Runtime.enable')
    send('Page.enable')
    return ws, send, ev, tgt


def find_ctx(ev, tries=40):
    """定位扩展隔离世界的 contextId。

    旧实现盲扫 1..90 的 contextId，在新版 Chrome 上全部失败
    （未登记的 id 直接报错，隔离世界的 id 也不再是小整数）。
    正确做法：Runtime.enable 之后读 executionContextCreated 事件，
    从中挑 origin 为 chrome-extension:// 的隔离世界。
    """
    expr = 'JSON.stringify({a: (globalThis.RFA ? typeof RFA.agent : null)})'
    fn = _CTX_FN.get('fn')
    if fn is None:
        return None
    for _ in range(tries):
        try:
            ctxs = fn()
        except Exception:
            ctxs = []
        ext_ids = [c['id'] for c in ctxs
                   if str(c.get('origin', '')).startswith('chrome-extension://')]
        for cid in ext_ids:
            try:
                v = ev(expr, cid, timeout=3)
                if '"a":"object"' in str(v or ''):
                    return cid
            except Exception:
                continue
        time.sleep(0.6)
    return None


def consume(send, ev, cid, limit=200, verbose=False):
    """把队列里的请求逐条落键，返回 (处理数, 失败明细)。"""
    n, bad = 0, []
    for _ in range(limit):
        item = ev(PEEK, cid)
        if not item or item.get('__error'):
            break
        if item.get('skip'):
            continue
        if item.get('click'):
            # 可信点击：按隔离世界返回的视口坐标派发真实鼠标事件
            x, y = int(item['x']), int(item['y'])
            send('Input.dispatchMouseEvent', {'type': 'mousePressed', 'x': x, 'y': y,
                                              'button': 'left', 'clickCount': 1})
            send('Input.dispatchMouseEvent', {'type': 'mouseReleased', 'x': x, 'y': y,
                                              'button': 'left', 'clickCount': 1})
            ev(POP_AND_READ, cid)
            n += 1
            continue
        # Input.insertText 会替换当前选区；再补一次以覆盖个别控件忽略首次输入
        send('Input.insertText', {'text': item['value']})
        time.sleep(0.03)
        read = ev(POP_AND_READ, cid)
        if read and read.get('got') is not None and read['got'] != read['want']:
            # 回读不一致：退回合成输入，保证值至少落进 DOM
            ev('const q = globalThis.__RFA_NATIVE_INPUT__; return true;', cid)
            bad.append({'want': read['want'], 'got': read['got']})
        n += 1
        if verbose:
            print('  typed', repr(item['value'])[:40], '->', repr((read or {}).get('got'))[:40])
    return n, bad
