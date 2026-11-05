# -*- coding: utf-8 -*-
"""Existing-browser DOM CLI. `on id:<tab-id>` selects exactly one tab.

Commands: tabs | new <url> | on <id:tab-id or unique URL fragment>
          get|shot|text|js|html|inputs [args]
Uses the configured service lease; never launches or closes a browser.
"""
import contextlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import sys
import time
import urllib.request
from urllib.parse import urlsplit, urlunsplit


def native_path(value):
    """Resolve Windows drive paths under WSL, leaving native paths unchanged."""
    value = str(value)
    if os.name != 'nt' and re.match(r'^[a-zA-Z]:[\\/]', value):
        path = PureWindowsPath(value)
        return Path('/mnt', path.drive[0].lower(), *path.parts[1:])
    return Path(value).expanduser()


def _load_user_config():
    """统一走 work/tools/user_config.py；缺失时回退同目录 config.json（兼容期）。"""
    for parent in Path(__file__).resolve().parents:
        cand = parent / 'work' / 'tools' / 'user_config.py'
        if cand.is_file():
            import importlib.util
            spec = importlib.util.spec_from_file_location('_ad_user_config', cand)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod.load()
    return None


def config():
    ucfg = _load_user_config()
    if ucfg is not None:
        return {
            'browser_project_root': ucfg.browser_project_root,
            'browser_service': ucfg.browser_service,
            'workspace_root': ucfg.get('workspace_root', default=str(ucfg.root)),
            'dashboard_url': ucfg.get('dashboard_url'),
            'resume_pdf': str(ucfg.path_or_none('resume', 'pdf') or ''),
            'resume_docx': str(ucfg.path_or_none('resume', 'docx') or ''),
            'login_phone': ucfg.user('phone', default=''),
            'target_grad_year': ucfg.target_grad_year,
            'task_timeout_seconds': ucfg.task_timeout_seconds,
            'default_pick_count': ucfg.default_pick_count,
        }
    return json.loads((Path(__file__).resolve().parent.parent / 'config.json').read_text(encoding='utf-8'))


def default_address(cfg):
    from dotenv import dotenv_values
    values = dotenv_values(native_path(cfg['browser_project_root']) / '.env')
    port = int(os.environ.get('REMOTE_DEBUG_PORT', values.get('REMOTE_DEBUG_PORT') or '9222'))
    return f'127.0.0.1:{port}'


def local_url(url):
    p = urlsplit(url)
    if p.scheme != 'http' or p.hostname not in ('127.0.0.1', 'localhost') or p.username or p.password:
        raise ValueError('Only a loopback HTTP browser/service endpoint is allowed')
    return url.rstrip('/')


def http_json(url, body=None):
    raw = None if body is None else json.dumps(body).encode('utf-8')
    req = urllib.request.Request(local_url(url), data=raw, headers={'Content-Type': 'application/json'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=5) as response:
        return json.loads(response.read(1000000))


@contextlib.contextmanager
def shared_lease(base):
    """Serialize with /v1/task. Tokens stay in memory; no unlocked fallback."""
    lease = http_json(base.rstrip('/') + '/v1/lease', {'action': 'acquire', 'ttl_seconds': 240})
    token = lease.get('token')
    if not lease.get('ok') or not token:
        raise RuntimeError('Browser lease unavailable')
    deadline = time.monotonic() + min(240, int(lease['ttl_seconds'])) - 15

    def check():
        if time.monotonic() >= deadline:
            raise RuntimeError('Browser lease expired; inspect state before continuing')

    try:
        yield check
    finally:
        try:
            http_json(base.rstrip('/') + '/v1/lease', {'action': 'release', 'token': token})
        except Exception:
            print('Browser lease release unconfirmed; wait for expiry before another worker', file=sys.stderr)


def connect(address):
    """Require an existing CDP endpoint and match its headless mode before attach."""
    version = http_json('http://' + address + '/json/version')
    from DrissionPage import ChromiumOptions, ChromiumPage
    options = ChromiumOptions(read_file=False)
    options.set_address(address).existing_only(True)
    options.headless('headless' in version.get('User-Agent', '').lower())
    page = ChromiumPage(addr_or_opts=options)
    page.set.timeouts(base=3, script=5, page_load=10)
    return page


def pick(page, needle):
    tabs = page.get_tabs()
    if needle.startswith('id:'):
        tabs = [t for t in tabs if t.tab_id == needle[3:]]
    else:
        tabs = [t for t in tabs if needle in (t.url or '')]
    if len(tabs) != 1:
        raise ValueError('Target must match exactly one tab; use id:<tab-id>')
    return tabs[0]


def public_url(url):
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.hostname or '', parts.path, '', ''))


def dump_inputs(tab):
    # No field values: hidden, password and OTP data must not enter generic logs.
    print(json.dumps(tab.run_js('''return Array.from(document.querySelectorAll('input,textarea,select')).map(e => ({
      tag:e.tagName, type:e.type, name:e.name, label:e.labels?.[0]?.textContent.trim().slice(0,60)||e.getAttribute('aria-label')||e.placeholder||'',
      read_only:e.readOnly||e.disabled, visible:!!(e.offsetWidth||e.offsetHeight)
    }));'''), ensure_ascii=False))


def structural_html(tab):
    """Selector-oriented HTML without scripts, form values or arbitrary data attrs."""
    return tab.run_js(r'''const root=document.body.cloneNode(true);
      root.querySelectorAll('script,style,link,meta').forEach(e=>e.remove());
      const keep=new Set(['id','class','role','name','type','placeholder','aria-label','aria-labelledby','aria-required','readonly','required','disabled','for','multiple','accept']);
      [root,...root.querySelectorAll('*')].forEach(e=>{
        for (const a of Array.from(e.attributes)) if(!keep.has(a.name)) e.removeAttribute(a.name);
        if(e.tagName==='TEXTAREA')e.textContent='';
      });
      return root.outerHTML;''')


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    args = sys.argv[1:]
    if not args:
        raise ValueError(__doc__)
    cfg = config()
    with shared_lease(cfg['browser_service']) as check:
        page = connect(default_address(cfg))
        check()
        if args[0] == 'tabs':
            print(json.dumps([{'tab_id': t.tab_id, 'title': t.title[:60], 'url': public_url(t.url)} for t in page.get_tabs()], ensure_ascii=False))
            return
        if args[0] == 'new':
            t = page.new_tab(args[1])
            print(json.dumps({'tab_id': t.tab_id, 'url': public_url(t.url)}, ensure_ascii=False))
            return
        if args[0] != 'on' or len(args) < 3:
            raise ValueError(__doc__)
        tab, op = pick(page, args[1]), args[2]
        if op == 'get':
            tab.get(args[3]); print(public_url(tab.url))
        elif op == 'shot':
            tab.get_screenshot(path=args[3], full_page=len(args) > 4 and args[4] == 'full')
            print('SAVED')
        elif op == 'text':
            print(tab.ele('tag:body').text[:int(args[3]) if len(args) > 3 else 3000])
        elif op == 'js':
            print(json.dumps(tab.run_js(args[3]), ensure_ascii=False, default=str)[:4000])
        elif op == 'html':
            print(structural_html(tab)[:int(args[3]) if len(args) > 3 else 5000])
        elif op == 'inputs':
            dump_inputs(tab)
        else:
            raise ValueError('Unknown DOM operation')


if __name__ == '__main__':
    main()
