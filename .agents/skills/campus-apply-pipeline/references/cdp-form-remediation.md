# CDP 疑难表单修障与物理穿透实操手册（cdp-form-remediation）

> **核心定位**：浏览器扩展（Extension）作为 **L1 辅助加速器**，负责在 1~2 秒内快速灌入 70%~80% 的常规标准字段；
> 当遇到现代前端框架的 4 道不可逾越的硬墙时，Agent 依据现场情况切入 **L2 核心修障**，使用 CDP（Chrome DevTools Protocol）进行特权级物理注入、文件挂载与状态穿透，完成表单终态闭环。

---

## 一、 为什么 Extension 无法完成全量填写（4 道硬墙）

1. **`isTrusted` 真实事件防作弊拦截**：
   - Content Script 的 `element.dispatchEvent(new MouseEvent('click'))` 产生的事件必定携带 `event.isTrusted = false`。
   - 现代招聘系统（北森 Phoenix/Classic、Moka、Element UI、Ant Design、极验）的级联下拉、日期选择器、选项卡均监听原生事件，合成事件直接被忽略或触发防作弊拦截。
2. **文件上传安全沙箱封锁**：
   - 浏览器安全策略严格禁止任何页面脚本或扩展向 `<input type="file">` 写入本地硬盘绝对路径。
   - 扩展无法静默挂载简历附件、成绩单或证件照。
3. **React / Vue 虚拟 DOM 与模型脱节（Virtual DOM / v-model）**：
   - 扩展直接改写 HTML DOM（如 `input.value = "xxx"`）只改变了 DOM 属性，未触发 React 合成事件系统（SyntheticEvent）或 Vue 的响应式 setter。
   - 表单提交时，前端框架直接使用内部 state/model 回滚，并报“请填写此项”。
4. **DOM 虚拟渲染与漂浮弹窗（Portal / Overlay）**：
   - 级联城市选择器、部门树、日期面板往往通过 React Portal / Vue Teleport 动态挂载到 `document.body` 根部，脱离表单容器。
   - 虚拟列表（Virtual List）仅在视口范围内渲染 DOM，可视区外的选项根本不存在于 DOM 树中，扩展的简单 CSS 选择器直接失效。

---

## 二、 双轨协作体系架构

```
┌─────────────────────────────────────────────────────────────┐
│                    网申填表双轨协作体系                      │
└─────────────────────────────────────────────────────────────┘
                               │
               ┌───────────────┴───────────────┐
               ▼                               ▼
    【L1 辅助加速层 · 扩展】          【L2 权威穿透层 · CDP】
    (resume-autofill Extension)        (Chrome DevTools Protocol)
    ───────────────────────────        ───────────────────────────
    · 范围：标准文本/textarea/原生select · 范围：4 大硬墙组件与疑难修障
    · 优势：秒级批量灌入，高通量覆盖    · 优势：物理事件、特权沙箱穿透、内存级触发
    · 职责：吃掉 70%~80% 基础体力活    · 职责：文件上传、日期弹层、级联Portal、终态验收
               │                               │
               └───────────────┬───────────────┘
                               ▼
    【终态质量与视觉交付门（Gate 2）】
    · 标准：页面真实 DOM 终态完整 + 必填项有值 + 站点红字为 0 + 经历行数对齐
    · 验收：整页截图人工/Agent 复核，废除“必须纯扩展冷启动截图”的僵化限制
```

---

## 三、 针对 4 大硬墙的 CDP 实操方法论与代码模板

所有 CDP 操作通过本机 Chrome 调试端口（默认 `127.0.0.1:9222`）执行。Python 通道可复用 `work/rfa/cdp.py` 或 `native_driver.py`。

### 1. 攻破硬墙 1：`isTrusted` 真实物理事件注入

CDP 的 `Input.dispatchMouseEvent` 与 `Input.dispatchKeyEvent` 由浏览器内核直接调度，**`event.isTrusted` 必定为 `true`**。

#### A. 物理鼠标点击（解决下拉点击无响应、单选不选中）
```python
def cdp_click(cdp_client, selector, context_id=None):
    """通过 CDP 物理派发真实的 mousePressed + mouseReleased 事件。"""
    # 1. 滚动目标到视口并获取绝对坐标
    js_get_rect = f"""(() => {{
      const el = document.querySelector({json.dumps(selector)});
      if (!el) return null;
      el.scrollIntoView({{ block: 'center', inline: 'center' }});
      const r = el.getBoundingClientRect();
      return {{ x: r.left + r.width / 2, y: r.top + r.height / 2 }};
    }})()"""
    pt = cdp_client.js(js_get_rect, context_id=context_id)
    if not pt:
        raise RuntimeError(f"Element not found or not visible: {selector}")

    x, y = pt['x'], pt['y']
    # 2. 派发物理按下与抬起
    cdp_client.send("Input.dispatchMouseEvent", {
        "type": "mousePressed", "x": x, "y": y,
        "button": "left", "clickCount": 1
    })
    time.sleep(0.05)
    cdp_client.send("Input.dispatchMouseEvent", {
        "type": "mouseReleased", "x": x, "y": y,
        "button": "left", "clickCount": 1
    })
```

---

### 2. 攻破硬墙 2：文件上传安全沙箱穿透（`DOM.setFileInputFiles`）

利用 CDP 特权命令直接向任意 `<input type="file">` 注入本地绝对路径，无需操作系统弹窗，完全静默可靠。

```python
def cdp_upload_file(cdp_client, file_input_selector, absolute_file_path):
    """穿透安全沙箱，直接挂载本地文件到 input[type=file]。"""
    if not os.path.isabs(absolute_file_path):
        raise ValueError(f"Path must be absolute: {absolute_file_path}")
    if not os.path.exists(absolute_file_path):
        raise FileNotFoundError(f"File not found: {absolute_file_path}")

    # 1. 取得主文档 DOM 根节点
    doc = cdp_client.send("DOM.getDocument", {"depth": -1})
    root_id = doc["root"]["nodeId"]

    # 2. 检索目标 input[type=file] 的 nodeId
    node = cdp_client.send("DOM.querySelector", {
        "nodeId": root_id,
        "selector": file_input_selector
    })
    node_id = node.get("nodeId")
    if not node_id:
        raise RuntimeError(f"File input node not found: {file_input_selector}")

    # 3. 物理注入文件路径
    cdp_client.send("DOM.setFileInputFiles", {
        "nodeId": node_id,
        "files": [absolute_file_path]
    })

    # 4. 主世界派发 change 事件以激活前端上传触发器
    js_trigger = f"""(() => {{
      const el = document.querySelector({json.dumps(file_input_selector)});
      if (el) {{
        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
      }}
    }})()"""
    cdp_client.js(js_trigger)
```

---

### 3. 攻破硬墙 3：React / Vue 虚拟 DOM 与模型状态穿透

解决修改 DOM 后提交被 React/Vue 内部状态重置为空的问题。提供 **物理打字流** 与 **原型链 Setter 穿透** 两种武器。

#### 方案 A：物理按键打字流（最强兼容，100% 触发 React/Vue 事件流）
通过 CDP 直接聚焦并清空输入框，随后使用 `Input.insertText` 逐字输入，内核会自动派发 `beforeinput`、`input` 等物理事件，React SyntheticEvent 与 Vue `v-model` 会无缝接收。

```python
def cdp_type_text(cdp_client, selector, text, context_id=None):
    """物理打字：聚焦 -> 全选删除 -> Input.insertText 真实按键注入 -> blur。"""
    # 1. 聚焦并全选
    focus_js = f"""(() => {{
      const el = document.querySelector({json.dumps(selector)});
      if (!el) return false;
      el.focus();
      if (el.select) el.select();
      return true;
    }})()"""
    if not cdp_client.js(focus_js, context_id=context_id):
        raise RuntimeError(f"Target not focusable: {selector}")

    # 2. 模拟全选并删除现有内容
    cdp_client.send("Input.dispatchKeyEvent", {
        "type": "keyDown", "modifiers": 2, "windowsVirtualKeyCode": 65, "code": "KeyA", "key": "a"
    })
    cdp_client.send("Input.dispatchKeyEvent", {
        "type": "keyUp", "modifiers": 2, "windowsVirtualKeyCode": 65, "code": "KeyA", "key": "a"
    })
    cdp_client.send("Input.dispatchKeyEvent", {
        "type": "keyDown", "windowsVirtualKeyCode": 8, "code": "Backspace", "key": "Backspace"
    })
    cdp_client.send("Input.dispatchKeyEvent", {
        "type": "keyUp", "windowsVirtualKeyCode": 8, "code": "Backspace", "key": "Backspace"
    })

    # 3. 物理输入目标文本
    cdp_client.send("Input.insertText", {"text": text})

    # 4. 派发失焦事件完成数据校验
    blur_js = f"""(() => {{
      const el = document.querySelector({json.dumps(selector)});
      if (el) {{
        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
        el.dispatchEvent(new Event('blur', {{ bubbles: false }}));
      }}
    }})()"""
    cdp_client.js(blur_js, context_id=context_id)
```

#### 方案 B：原型链原生 Setter 穿透（毫秒级批量更新）
绕过前端框架重写的属性描述符，调用原生 `HTMLInputElement.prototype` 的 setter：
```javascript
(() => {
  const el = document.querySelector('input[name="expectedSalary"]');
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const nativeSetter = Object.getOwnPropertyDescriptor(proto, 'value').set;
  nativeSetter.call(el, '20000');
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
})()
```

---

### 4. 攻破硬墙 4：Portal / Overlay 漂浮层与虚拟滚动穿透

用于解决 Ant Design、Element UI、北森 Phoenix 中，下拉面板/级联选择器挂载在 `document.body`、或者长列表虚拟化导致选项不在 DOM 的问题。

```python
def cdp_select_portal_option(cdp_client, trigger_selector, option_text, overlay_container_selector="body"):
    """
    穿透 Portal 浮层：
    1. 点击触发器展开下拉
    2. 等待全局 Overlay 渲染
    3. 滚动虚拟列表检索目标文本
    4. 物理点击目标选项
    """
    # 1. 物理点击触发控件
    cdp_click(cdp_client, trigger_selector)
    time.sleep(0.3)  # 等待浮层动画与 Portal 挂载

    # 2. 在 body 或全局浮层中查找选项
    find_option_js = f"""(() => {{
      const overlay = document.querySelector({json.dumps(overlay_container_selector)}) || document.body;
      const want = {json.dumps(option_text.strip().lower())};
      
      // 遍历所有可能的浮层选项节点
      const candidates = overlay.querySelectorAll(
        '.ant-select-item-option, .el-select-dropdown__item, .phoenix-select-option, [role="option"], li, div'
      );
      for (const el of candidates) {{
        const text = (el.innerText || el.textContent || '').trim().toLowerCase();
        if (text === want || text.includes(want)) {{
          el.scrollIntoView({{ block: 'nearest' }});
          const r = el.getBoundingClientRect();
          if (r.width > 0 && r.height > 0) {{
            return {{ x: r.left + r.width / 2, y: r.top + r.height / 2 }};
          }}
        }}
      }}
      return null;
    }})()"""

    pt = cdp_client.js(find_option_js)
    if not pt:
        # 若未找到，尝试在浮层容器派发虚拟滚轮 (mouseWheel) 继续查找
        raise RuntimeError(f"Portal option '{option_text}' not found in overlay.")

    # 3. 物理点击选项
    cdp_client.send("Input.dispatchMouseEvent", {
        "type": "mousePressed", "x": pt["x"], "y": pt["y"], "button": "left", "clickCount": 1
    })
    time.sleep(0.05)
    cdp_client.send("Input.dispatchMouseEvent", {
        "type": "mouseReleased", "x": pt["x"], "y": pt["y"], "button": "left", "clickCount": 1
    })
```

---

## 四、 网申实战常见疑难组件 CDP 标准解法速查

| 组件类型 | 典型代表 | 失败原因 | CDP 标准解决方案 |
|---|---|---|---|
| **附件上传** | 简历/成绩单/证书上传 | 扩展沙箱禁止读写文件路径 | 使用 `DOM.setFileInputFiles` 直接绑定本地绝对路径，无需弹窗 |
| **北森 Phoenix 日期面板** | 年/月/日三级联动面板 | 合成事件无法触发内部状态更新 | 点击输入框展开 → 物理点击年份面板翻页 → 物理点击 `.phoenix-calendar-month-select` 展开月份并选中 → 物理点击日 |
| **级联地区选择** | 省/市/区县三级联动 | Portal 挂载在 `body` 根节点，选项不在表单容器 | 展开后全局定位 `.area-item-container`，物理点击 `.icon-container` 单选图标，确认底部计数为 1/1 后点确定 |
| **自定义单选/复选** | Phoenix radio / Antd checkbox | 原生 `input.checked` 属性不更新 | 物理点击外层容器 `.phoenix-radio`，核对容器 class 是否包含 `phoenix-radio--checked` |
| **受控数字/期望薪资** | 限制只填数字的输入框 | 直接写字符串触发红色校验红字 | 使用 `cdp_type_text` 物理按键输入合法纯数字，或清空留空 |

---

## 五、 交付门（Gate 2）验收闭环重构

1. **冷启动复验与 CDP 协同的边界（与 `loop.py gate` 对齐）**：
   - 已废除的是“截图必须由扩展从头到尾填完”：附件、级联与受控组件允许 CDP 协同介入。
   - 但**冷启动复验本身不能省**：`loop.py gate` 要求 `state.coldStart` 存在，且 `pageWasEmpty=true`、`ok=true`、冷启动截图哈希与 `finalShot` 一致；缺一项判 `NO_COLD_START` / `COLD_START_NOT_EMPTY` / `COLD_START_NOT_OK`。
   - 刷新后页面被站点自动回填（“继续上次填写”、服务端暂存）时，交付门必然拒收；这是站点行为，需要人工清空后重跑冷启动，不能靠文档宣布它不存在。
2. **终态物理交付门验收标准**：
   - **必填项覆盖（Required Coverage）**：页面所有带星号、`aria-required` 或站点红字的必填项必须全部有值。
   - **零报错红字（Zero Red Text）**：页面无任何未解除的前端校验红字（如“格式错误”、“请选择”）。
   - **经历行数对齐（Row Gap = 0）**：教育、实习、项目经历区块的渲染行数必须与真实简历条数严格 1:1 吻合。
   - **附件挂载完成（Attachment Bound）**：简历 PDF 等必需附件已显示在上传列表或回显出文件名。
   - **整页视觉复核（Final Shot Review）**：抓取最终状态整页截图并完成四项清单复核。
