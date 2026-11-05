# -*- coding: utf-8 -*-
"""提交后回读：URL、正文、是否有成功提示。"""
import sys
import time

sys.path.insert(0, 'work/rfa')
import native_driver as N

time.sleep(3)
ws, send, ev, tgt = N.connect(url_part='611.zhiye.com')
print('tab url:', tgt['url'])
cid = N.find_ctx(ev, tries=30)
print('ctx:', cid)
print('url:', ev('return location.href;', cid))
print('\n=== 正文前 900 ===')
print(ev('return (document.body.innerText || "").slice(0, 900);', cid, await_promise=True))
