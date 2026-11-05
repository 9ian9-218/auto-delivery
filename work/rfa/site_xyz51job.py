# -*- coding: utf-8 -*-
"""xyz.51job.com 校招简历确认页（consumer/pc/resume/index）站点助手。

页面模式：区块（基本信息/教育经历/语言能力/IT技能/实习经验/项目经验/竞赛经历/自我评价）
的「添加/编辑」按钮打开 Element-UI 弹窗，真实输入控件只在弹窗内。
与 site611.py 同定位：JS 定位 + 合成点击（Vue 响应）驱动弹窗开关，
弹窗内的字段填写走 RFA agent（loop.py scan/run 在弹窗打开时进行），保存后回读校验。

注意：
- 页面有多个同源标签时，loop.py/attach.py 一律用 `ctmid=<值>` 作 --url 片段精确锁定。
- 修改志愿页（consumer/pc/volunteer/index）的「修改」按钮也是 .custom-button，
  按区块定位时必须先验证按钮属于目标区块，防止误入志愿页。
"""
import json
import time

SECTION_NAMES = ['基本信息', '教育经历', '语言能力', 'IT技能', '实习经验', '项目经验', '竞赛经历', '自我评价']

# 在目标区块容器内找「添加/编辑」按钮：向上爬 ancestor，验证兄弟链里出现区块标题
JS_CLICK_SECTION = """return (() => {
  const want = %s, act = %s;
  const btns = [...document.querySelectorAll('.custom-button, .right')].filter(e => {
    if (!e.offsetParent) return false;
    const t = e.textContent.trim();
    return t === act || t === '添加' || t === '编辑';
  });
  for (const b of btns) {
    let ctx = b.parentElement;
    for (let i = 0; i < 7 && ctx; i++) {
      const own = ctx.textContent || '';
      const names = names_in(own);
      if (names.length === 1 && names[0] === want) {
        // 该容器只含这一个区块标题 → 属于目标区块；再确认它不含其他 .custom-button 兄弟区块
        b.scrollIntoView({block: 'center'});
        const before = location.href;
        b.click();
        return {clicked: true, btn: b.textContent.trim(), url_before: before};
      }
      ctx = ctx.parentElement;
    }
  }
  return {clicked: false};
  function names_in(t) { return ['基本信息','教育经历','语言能力','IT技能','实习经验','项目经验','竞赛经历','自我评价'].filter(n => t.includes(n)); }
})()"""

JS_OPEN_DIALOG = """return (() => {
  const ws = [...document.querySelectorAll('.el-dialog__wrapper')].filter(w => getComputedStyle(w).display !== 'none' && w.querySelector('.el-dialog'));
  return JSON.stringify(ws.map(w => {
    const fields = [...w.querySelectorAll('input,textarea')].map(i => ({
      tag: i.tagName, type: i.type || '', ph: i.placeholder || '',
      label: (i.closest('.el-form-item') ? (i.closest('.el-form-item').querySelector('label') || {}).textContent || '' : ''),
      required: !!(i.closest('.el-form-item') && i.closest('.el-form-item').classList.contains('is-required')),
      val: String(i.value == null ? '' : i.value).slice(0, 12)
    }));
    const customs = [...w.querySelectorAll('.el-select,.el-cascader,.el-date-editor,.el-radio-group,.el-checkbox-group')].map(s => ({
      kind: (s.className || '').toString().split(' ')[0],
      label: (s.closest('.el-form-item') ? (s.closest('.el-form-item').querySelector('label') || {}).textContent || '' : ''),
      required: !!(s.closest('.el-form-item') && s.closest('.el-form-item').classList.contains('is-required')),
      cur: s.textContent.trim().slice(0, 30)
    }));
    return {fields, customs, buttons: [...w.querySelectorAll('button')].map(b => b.textContent.trim()).filter(Boolean).slice(0, 8)};
  }));
})()"""

JS_DIALOG_SAVE = """return (() => {
  const w = [...document.querySelectorAll('.el-dialog__wrapper')].find(x => getComputedStyle(x).display !== 'none' && x.querySelector('.el-dialog'));
  if (!w) return {saved: false, why: 'no dialog'};
  const btn = [...w.querySelectorAll('button')].find(b => /^(确\\s*定|保\\s*存|提\\s*交)$/.test(b.textContent.trim()));
  if (!btn) return {saved: false, why: 'no save button'};
  btn.click();
  return {saved: true, btn: btn.textContent.trim()};
})()"""

JS_SECTION_ROWS = """return (() => {
  const want = %s;
  for (const b of document.querySelectorAll('.custom-button,.right')) {
    if (!b.offsetParent) continue;
    let ctx = b.parentElement;
    for (let i = 0; i < 7 && ctx; i++) {
      const names = ['基本信息','教育经历','语言能力','IT技能','实习经验','项目经验','竞赛经历','自我评价'].filter(n => (ctx.textContent || '').includes(n));
      if (names.length === 1 && names[0] === want) {
        const cards = ctx.querySelectorAll('.card, .item, [class*=card], [class*=item]');
        const txt = ctx.textContent;
        return {section: want, blocks: cards.length, hasEmpty: /请填写|请至少/.test(txt), len: txt.length};
      }
      ctx = ctx.parentElement;
    }
  }
  return null;
})()"""


def click_section_add(ev, section, action='添加'):
    """打开目标区块的添加/编辑弹窗。ev(tab) 为页面求值函数（native_driver.ev 或 DrissionPage run_js 包装）。"""
    r = ev(JS_CLICK_SECTION % (json.dumps(section, ensure_ascii=False), json.dumps(action, ensure_ascii=False)))
    return r


def open_dialog_fields(ev):
    """盘点当前打开的弹窗字段。"""
    return json.loads(ev(JS_OPEN_DIALOG))


def dialog_save(ev):
    """点击弹窗底部保存/确定。"""
    return ev(JS_DIALOG_SAVE)


def section_rows(ev, section):
    """区块内卡片数与空态标记。"""
    return ev(JS_SECTION_ROWS % json.dumps(section, ensure_ascii=False))


def wait_dialog(ev, timeout=6):
    """轮询等弹窗出现，返回字段盘点或 None。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        d = open_dialog_fields(ev)
        if d:
            return d
        time.sleep(0.6)
    return None


def dialog_closed(ev, timeout=6):
    """等弹窗关闭（保存生效）。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not open_dialog_fields(ev):
            return True
        time.sleep(0.6)
    return False
