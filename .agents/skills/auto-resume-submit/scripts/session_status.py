# -*- coding: utf-8 -*-
"""Login observation ledger, not a credential store.

Commands: doctor | list | mark --site https://tenant.example --state ... --basis ...
Mark only after observing the current official account/login page. Never stores
cookies, tokens, passwords or phone/account identifiers.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import ntpath
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urlsplit


def origin(url):
    p = urlsplit(url)
    if p.scheme not in ('https', 'http') or not p.hostname or p.username or p.password or p.query or p.fragment:
        raise ValueError('Use a credential-free site URL without query or fragment')
    host = p.hostname.lower()
    if ':' in host:
        host = '[' + host + ']'
    port = p.port
    suffix = '' if port is None or (p.scheme, port) in [('https', 443), ('http', 80)] else ':' + str(port)
    return p.scheme + '://' + host + suffix


def profile_key(check):
    if not all(check.get(k) for k in ('actual_path', 'browser_name', 'profile_directory')):
        raise ValueError('Cannot bind login state to an unknown browser profile')
    parts = [check['browser_name'].lower(), ntpath.normcase(ntpath.normpath(check['actual_path'])), ntpath.normcase(check['profile_directory'])]
    return hashlib.sha256(json.dumps(parts).encode('utf-8')).hexdigest()


def resolve_profile(browser, check):
    """Read only Profile Path from an owned background version tab; no credentials."""
    probe = browser.new_tab('chrome://version', background=True)
    try:
        path = probe.ele('css:#profile_path', timeout=3).text.strip()
        if ntpath.normcase(ntpath.dirname(path)) != ntpath.normcase(ntpath.normpath(check.get('actual_path') or '')):
            raise ValueError('Browser profile root changed; inspect the browser again')
        return {**check, 'profile_directory': ntpath.basename(path)}
    finally:
        # Close only this new internal inspection tab, never an existing user tab.
        probe.close()


def read_registry(path):
    if not path.exists():
        return {'version': 1, 'observations': []}
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('version') != 1 or not isinstance(data.get('observations'), list):
        raise ValueError('Unrecognized session ledger; refusing to overwrite')
    return data


def record(path, site, tenant, key, state, basis):
    if tenant and not re.fullmatch(r'[A-Za-z0-9_.-]{1,120}', tenant):
        raise ValueError('Tenant is a site identifier, not an account or token')
    if {'logged_in': 'account_page', 'expired': 'login_page', 'unknown': 'check_unavailable'}.get(state) != basis:
        raise ValueError('Login observation needs its corresponding page evidence')
    item = {'origin': origin(site), 'tenant': tenant, 'profile_key': key, 'state': state, 'basis': basis,
            'observed_at': datetime.now(timezone.utc).isoformat()}
    data = read_registry(path)
    data['observations'] = [r for r in data['observations'] if (r['origin'], r['tenant'], r['profile_key']) != (item['origin'], tenant, key)] + [item]
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as out:
            name = out.name
            os.chmod(name, 0o600)
            json.dump(data, out, ensure_ascii=False, indent=2)
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)
    return item


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['doctor', 'list', 'mark'])
    p.add_argument('--site')
    p.add_argument('--tenant', default='')
    p.add_argument('--state', choices=['logged_in', 'expired', 'unknown'])
    p.add_argument('--basis', choices=['account_page', 'login_page', 'check_unavailable'])
    args = p.parse_args()
    if args.command == 'mark' and not all([args.site, args.state, args.basis]):
        p.error('mark requires --site, --state and --basis')
    import attach
    import preflight
    cfg = attach.config()
    root = preflight.find_project_root(cfg)
    check = preflight.check_browser_profile(root)
    if args.command == 'doctor':
        print(json.dumps(check, ensure_ascii=False, indent=2))
        return
    path = attach.native_path(cfg.get('workspace_root', cfg['browser_project_root'])) / 'work/browser_sessions.json'
    with attach.shared_lease(cfg['browser_service']) as lease_check:
        browser = attach.connect(attach.default_address(cfg))
        check = resolve_profile(browser, check)
        lease_check()
        key = profile_key(check)
        if args.command == 'mark':
            item = record(path, args.site, args.tenant, key, args.state, args.basis)
            result = {'last_observation': item, 'recheck_required': True}
        else:
            result = {'observations': [r for r in read_registry(path)['observations'] if r['profile_key'] == key], 'recheck_required': True}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'ok': False, 'error_type': type(error).__name__}), file=sys.stderr)
        sys.exit(2)
