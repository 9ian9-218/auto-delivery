# -*- coding: utf-8 -*-
"""Thin CDP client for the local Chrome (127.0.0.1:9222) — used to drive the
resume-autofill extension's isolated-world RFA.agent API on real ATS pages."""
import json
import os
import time
import urllib.request

import websocket  # websocket-client

CHROME = "http://127.0.0.1:9222"
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
EXT_ID = "eajmkkpobflamjdieginndohgehfklcj"


def _get(path, method="GET"):
    req = urllib.request.Request(CHROME + path, method=method)
    with _OPENER.open(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def version():
    return _get("/json/version")


def targets():
    return _get("/json/list")


def find(query, kind="page"):
    for t in targets():
        if t.get("type") != kind:
            continue
        u = t.get("url", "")
        if query in u:
            return t
    return None


def new_tab(url="about:blank"):
    return _get("/json/new?" + urllib.parse.quote(url, safe=":/?=&%#"), method="PUT")


class CDP:
    def __init__(self, ws_url, timeout=30):
        self.ws = websocket.create_connection(ws_url, timeout=timeout,
                                              max_size=64 * 1024 * 1024,
                                              suppress_origin=True)
        self._id = 0

    def send(self, method, params=None, timeout=None):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method,
                                 "params": params or {}}))
        while True:
            if timeout:
                self.ws.settimeout(timeout)
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def js(self, expr, context_id=None, timeout=60, await_promise=True):
        p = {"expression": expr, "returnByValue": True,
             "awaitPromise": await_promise, "userGesture": True}
        if context_id is not None:
            p["contextId"] = context_id
        r = self.send("Runtime.evaluate", p, timeout=timeout)
        if r.get("exceptionDetails"):
            d = r["exceptionDetails"]
            txt = d.get("text", "")
            exc = d.get("exception", {}).get("description", "")
            raise RuntimeError(f"JS error: {txt} {exc}"[:2000])
        return r.get("result", {}).get("value")

    def contexts(self):
        out = []
        for ev in [self.send("Runtime.enable", {})] if False else []:
            pass
        return out

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def page_ws(target):
    return target["webSocketDebuggerUrl"]


def open_page(url, wait=3.0, match=None):
    """Create/attach a tab at url; returns (CDP, target)."""
    tgt = None
    if match:
        tgt = find(match)
    if not tgt:
        tgt = new_tab(url)
        time.sleep(wait)
        tgt = find(url) or tgt
    else:
        c = CDP(page_ws(tgt))
        c.send("Page.enable")
        c.send("Page.navigate", {"url": url})
        c.close()
        time.sleep(wait)
        tgt = find(match) or find(url) or tgt
    c = CDP(page_ws(tgt))
    c.send("Page.enable")
    c.send("Runtime.enable")
    return c, tgt


def wait_page(c, timeout=25, needle=None):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            st = c.js("document.readyState")
            if st == "complete":
                if not needle or needle in (c.js("location.href") or ""):
                    return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


def navigate(c, url, wait=3.0):
    c.send("Page.navigate", {"url": url})
    time.sleep(wait)
    wait_page(c)


def shot(c, path):
    r = c.send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
    import base64
    with open(path, "wb") as f:
        f.write(base64.b64decode(r["data"]))
    return path


import urllib.parse  # noqa: E402  (used by new_tab)
