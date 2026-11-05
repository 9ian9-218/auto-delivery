# -*- coding: utf-8 -*-
"""Inspect and fill an explicit, snapshot-bound plan. Never clicks save/submit.

inspect --tab-id ID --context JOB_CSS [--frame CSS] [--out private.json]
fill --tab-id ID --context JOB_CSS --plan private.json [--frame CSS] [--apply] [--out result.json]
Default fill is a dry run. Candidate values belong in private ignored work files.
"""
import argparse
import hashlib
import json
import mimetypes
from pathlib import Path
import sys
import time

COLLECT = r'''const path = e => {
  if (e.id && document.querySelectorAll('#'+CSS.escape(e.id)).length===1) return '#'+CSS.escape(e.id);
  const a=[];
  for (;e && e.nodeType===1;e=e.parentElement) {
    const tag=e.tagName.toLowerCase();
    const n=Array.from(e.parentElement?.children||[e]).filter(x=>x.tagName===e.tagName).indexOf(e)+1;
    a.unshift(tag+':nth-of-type('+n+')');
  } return a.join(' > ');
};
const fields=Array.from(document.querySelectorAll('input,textarea,select,[role="combobox"],[contenteditable="true"]')).map(e=>{
  const tag=e.tagName.toLowerCase(), type=(e.type||'').toLowerCase();
  const label=(e.labels?.[0]?.textContent||e.getAttribute('aria-label')||e.placeholder||'').trim().slice(0,160);
  const secret=type==='hidden'||type==='password'||e.autocomplete==='one-time-code'||/password|captcha|验证码|短信码|身份证|证件号/i.test(label+' '+e.name+' '+e.id);
  const section=e.closest('fieldset,section,[role="group"]');
  const context=(section?.querySelector('legend,h1,h2,h3,h4,[role="heading"]')?.textContent||'').trim().slice(0,100);
  const custom=e.getAttribute('role')==='combobox'||e.hasAttribute('aria-haspopup')||['list','both'].includes(e.getAttribute('aria-autocomplete'));
  return {selector:path(e),tag,type,label,name:e.name||'',context,secret,custom,
    required:!!e.required||e.getAttribute('aria-required')==='true',readonly:!!e.readOnly,disabled:!!e.disabled||e.matches(':disabled'),
    visible:!!(e.getClientRects().length&&e.getBoundingClientRect().width&&e.getBoundingClientRect().height)&&getComputedStyle(e).visibility!=='hidden',
    multiple:!!e.multiple,accept:e.accept||'',options:tag==='select'?Array.from(e.options).map(o=>({text:o.text,value:o.value,disabled:o.disabled})):[],
    raw:secret?null:type==='file'?Array.from(e.files||[]).map(f=>({name:f.name,size:f.size})):['checkbox','radio'].includes(type)?e.checked:e.value??null};
});
const forms=Array.from(document.forms);
const layout_text=forms.length?forms.map(f=>f.innerText).join('\n--form--\n'):document.body.innerText;
return {url:location.href,layout_text,fields,frames:Array.from(document.querySelectorAll('iframe,frame')).map(e=>({selector:path(e)}))};'''


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def snapshot(tab, scope=None, frame='', context=''):
    raw = (scope or tab).run_js(COLLECT)
    target = None
    if context:
        target = tab.run_js('const es=document.querySelectorAll(arguments[0]); if(es.length!==1)throw new Error("Target context must be unique"); const e=es[0],r=e.getBoundingClientRect(),s=getComputedStyle(e); if(!e.getClientRects().length||!r.width||!r.height||s.visibility==="hidden"||s.display==="none"||s.opacity==="0")throw new Error("Target context is hidden"); const t=e.innerText?.trim(); if(!t)throw new Error("Target context must contain visible text"); return t;', context)
    fields = []
    for data in raw['fields']:
        field = dict(data)
        value = field.pop('raw')
        field['signature'] = digest(field)
        field['has_value'] = None if field['secret'] else value is not False and value not in (None, '', [])
        field['value_hash'] = None if field['secret'] else digest(value)
        fields.append(field)
    result = {'tab_id': tab.tab_id, 'page_key': digest(tab.url), 'document_key': digest(raw['url']),
              'frame': frame, 'layout_key': digest(raw['layout_text']), 'target_selector': context, 'target_key': digest(target) if target else None, 'fields': fields, 'frames': raw['frames']}
    result['snapshot_key'] = digest(result)
    return result


def expected_value(field, operation):
    value = operation.get('value')
    if not isinstance(value, str) or not value:
        raise ValueError('Each operation needs a nonempty confirmed string value')
    if any(0xE000 <= ord(c) <= 0xF8FF for c in value):
        raise ValueError('Browser key codes are not accepted as field values')
    if field['secret'] or field['readonly'] or field['disabled'] or field['custom']:
        raise ValueError('Sensitive, read-only, disabled or custom controls require separate handling')
    if not field['visible'] and field['type'] != 'file':
        raise ValueError('Target is not visible')
    if field['tag'] == 'select' and not field['multiple']:
        options = [o for o in field['options'] if o['text'] == value and not o['disabled']]
        if len(options) != 1:
            raise ValueError('Select option text must have exactly one enabled match')
        return options[0]['value']
    if field['tag'] == 'input' and field['type'] == 'file' and not field['multiple']:
        path = Path(value)
        if not path.is_file():
            raise ValueError('Attachment file does not exist')
        allowed = [s.strip().lower() for s in field['accept'].split(',') if s.strip()]
        mime = mimetypes.guess_type(path.name)[0] or ''
        if allowed and not any((s.startswith('.') and path.suffix.lower() == s) or mime == s or (s.endswith('/*') and mime.startswith(s[:-1])) for s in allowed):
            raise ValueError('Attachment type is outside the input accept list')
        return [{'name': path.name, 'size': path.stat().st_size}]
    if field['tag'] == 'textarea' or (field['tag'] == 'input' and field['type'] in ('text','email','tel','url','number','search')):
        if field['tag'] == 'input' and any(c in value for c in '\r\n\t'):
            raise ValueError('Single-line fields cannot contain keyboard control characters')
        return value
    raise ValueError('Unsupported control; use the normal platform UI')


def validate_plan(current, plan):
    if not current.get('target_selector') or not current.get('target_key'):
        raise ValueError('A current visible company/job context selector is required before filling')
    for key in ('tab_id', 'page_key', 'document_key', 'frame', 'target_selector', 'target_key', 'snapshot_key'):
        if plan.get(key) != current[key]:
            raise ValueError('Plan does not match this tab, document or current form state')
    operations = plan.get('operations')
    if not isinstance(operations, list) or not 1 <= len(operations) <= 32:
        raise ValueError('A plan needs 1 to 32 explicit field operations')
    fields = {f['selector']: f for f in current['fields']}
    seen, prepared = set(), []
    for op in operations:
        selector = op.get('selector')
        field = fields.get(selector)
        if selector in seen or not field or op.get('signature') != field['signature']:
            raise ValueError('Each target needs one unique selector and matching field signature')
        seen.add(selector)
        expected = digest(expected_value(field, op))
        # Filename and size do not establish attachment content identity.
        unchanged = field['type'] != 'file' and field['value_hash'] == expected
        if field['has_value'] and not unchanged and op.get('overwrite') is not True:
            raise ValueError('Existing value differs; explicit correction is required')
        prepared.append((field, op, expected, unchanged))
    return prepared


def write_field(scope, field, operation, state_unchanged):
    elements = scope.eles('css:' + field['selector'], timeout=1)
    if len(elements) != 1:
        raise ValueError('Field selector is no longer unique')
    element, value = elements[0], operation['value']
    if field['type'] != 'file':
        element.scroll.to_see(center=True)
        if not state_unchanged():
            raise ValueError('Form changed during scroll; inspect again')
        hit = element.run_js('const r=this.getBoundingClientRect(); const e=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2); return e===this||this.contains(e);')
        if not hit:
            raise ValueError('Field is covered; handle the visible overlay normally')
    if field['tag'] == 'select':
        element.select.by_text(value, timeout=1)
    elif field['type'] == 'file':
        element.input(str(Path(value).resolve()))
    else:
        element.input(value, clear=True, by_js=False)
    if field['type'] != 'file':
        element.focus()
        scope.actions.key_down('TAB').key_up('TAB')


def execute_plan(tab, scope, frame, plan, apply=False, check_lease=lambda: None, context=''):
    current = snapshot(tab, scope, frame, context)
    prepared = validate_plan(current, plan)
    results = []
    if not apply:
        return {'ok': True, 'phase': 'dry_run', 'submission_verified': False, 'site_saved_verified': False, 'fields': len(prepared)}
    for field, op, wanted, unchanged in prepared:
        check_lease()
        before = snapshot(tab, scope, frame, context)
        if before['snapshot_key'] != current['snapshot_key']:
            return {'ok': False, 'phase': 'form_changed', 'completed': results, 'submission_verified': False, 'site_saved_verified': False}
        if unchanged:
            results.append({'selector': field['selector'], 'state': 'already_matches'})
            continue
        write_field(scope, field, op, lambda: snapshot(tab, scope, frame, context)['snapshot_key'] == before['snapshot_key'])
        time.sleep(1.0)
        check_lease()
        after = snapshot(tab, scope, frame, context)
        expected = json.loads(json.dumps(before))
        expected.pop('snapshot_key')
        for f in expected['fields']:
            if f['selector'] == field['selector']:
                f['value_hash'], f['has_value'] = wanted, True
        if digest(expected) != after['snapshot_key']:
            return {'ok': False, 'phase': 'readback_or_related_field_changed', 'stopped_at': field['selector'], 'completed': results, 'submission_verified': False, 'site_saved_verified': False}
        results.append({'selector': field['selector'], 'state': 'file_selected' if field['type'] == 'file' else 'written_and_read_back'})
        current = after
    time.sleep(.3)
    if snapshot(tab, scope, frame, context)['snapshot_key'] != current['snapshot_key']:
        return {'ok': False, 'phase': 'changed_after_fill', 'completed': results, 'submission_verified': False, 'site_saved_verified': False}
    return {'ok': True, 'phase': 'fields_checked', 'completed': results, 'submission_verified': False, 'site_saved_verified': False,
            'remaining_required': [f['selector'] for f in current['fields'] if f['required'] and f['has_value'] is False]}


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['inspect', 'fill'])
    p.add_argument('--tab-id', required=True)
    p.add_argument('--frame', default='')
    p.add_argument('--context', default='', help='Unique top-page selector containing the current company/job identity')
    p.add_argument('--plan')
    p.add_argument('--apply', action='store_true')
    p.add_argument('--out')
    args = p.parse_args()
    if args.command == 'fill' and not all([args.plan, args.context]):
        p.error('fill requires --plan and --context')
    import attach
    cfg = attach.config()
    with attach.shared_lease(cfg['browser_service']) as check:
        browser = attach.connect(attach.default_address(cfg))
        tab = attach.pick(browser, 'id:' + args.tab_id)
        scope = tab
        if args.frame:
            if len(tab.eles('css:' + args.frame, timeout=1)) != 1:
                raise ValueError('Frame selector must match exactly once')
            scope = tab.get_frame('css:' + args.frame)
        check()
        result = snapshot(tab, scope, args.frame, args.context) if args.command == 'inspect' else execute_plan(
            tab, scope, args.frame, json.loads(Path(args.plan).read_text(encoding='utf-8')), args.apply, check, args.context)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text + '\n', encoding='utf-8')
    else:
        print(text)
    return 0 if result.get('ok', True) else 2


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        print(json.dumps({'ok': False, 'phase': 'stopped', 'error_type': type(error).__name__}), file=sys.stderr)
        sys.exit(2)
