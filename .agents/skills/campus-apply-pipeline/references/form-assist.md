# 可核对的批量填表

本环境的 `auto-resume-submit/scripts/form_assist.py` 提供本地表单盘点和显式计划执行；它使用既有 DrissionPage 与 HTTP 服务租约，不依赖牛客私有服务，不发送简历给新增服务。牛客助手/官网解析可继续使用，但须等解析和页面加载稳定后再取得快照。

## 先绑定页面，再映射

1. 从当前技能配置取 Python 和脚本目录，用 `attach.py tabs` 获取确切 `tab_id`；精细操作使用 `on id:<tab_id>`。URL 片段若匹配多个标签，工具停止而非取最后一个。所有该工具的浏览器操作需先取得共享 `/v1/lease`，服务不可达或忙时不绕锁执行。
2. 核实本次公司、岗位、用户资料和权限后，执行 `form_assist.py inspect --tab-id ID --context <当前公司/岗位标题的唯一CSS> --out <私有快照路径>`。`--context` 指向顶层页面真实目标岗位/公司标识，不能用固定Logo或无关文字代替。缺少唯一上下文时可先盘点，但不能执行批量填写；仍可沿用正常浏览器核验与操作。iframe 须显式加 `--frame <唯一CSS选择器>`，不能假定顶层脚本已覆盖 iframe。
3. 依据资料档案把模块、标签、重复条目和真实选项对应起来；本人、联系人、学历、学位和学习形式分别判断。按项目/单位/学校及日期识别来源，不按一个全局字段名盲填。快照默认不包含字段值，而保存值的哈希、是否已填及控件元数据；可将已确认来源值按同一 `digest()` 计算后比较。密码、验证码、隐藏值不读取。

计划是本地 JSON，放入忽略版本控制的私有 `work/`。从**当前**快照复制 `tab_id/page_key/document_key/frame/target_selector/target_key/snapshot_key`；每条 `operations` 从所选字段复制 `selector/signature`，`value` 必须来自已确认事实。用 `overwrite:true` 表达已授权的明确纠正，默认保护已有值。不能把快照标识、控件标签或示例文字当候选事实。

```python
plan = {key: snapshot[key] for key in
        ('tab_id', 'page_key', 'document_key', 'frame',
         'target_selector', 'target_key', 'snapshot_key')}
plan['operations'] = [{
    'selector': selected_field['selector'],
    'signature': selected_field['signature'],
    'value': confirmed_value
}]
```

## 执行与边界

先执行 `form_assist.py fill --tab-id ID --context <同一目标CSS> --plan <私有计划路径>` 检查计划；实际执行加 `--apply`。这个参数由 Agent 在既有任务授权内使用，不额外要求用户重复确认。iframe 的 inspect 和 fill 使用相同 `--frame` 和顶层 `--context`。每批最多 32 个字段，下一批重新盘点。

- 已实现普通文本、邮箱、电话、数字、textarea、单选原生 select 和单文件输入。文本用真实键入，select 用原生控件接口；失焦使用键盘事件，不把特殊按键字符作为文本插入。
- 非文件字段先正常滚动并检查中心命中点；被遮挡时停止，按正常流程处理弹层。日期、自定义下拉、多选、单选/复选组件、敏感字段及只读字段交原有浏览器流程，不套普通输入；没有强行修改框架私有 handler/store 的路径。
- 页面、岗位 URL/可见目标标题、frame 文档、可见表单文本、字段签名、已有值或经历顺序与快照不一致，计划失效。全部操作先校验；填写后等待约一秒回读，失焦清空、其他字段联动变化或异步改写时停止。重新检查后生成新计划，不盲重试整批。有限回读窗口不能证明未来不会异步改写，仍须按官网暂存/预览结果复核。
- 附件只使用当前真实 file input，校验本地文件及 accept 后选择文件。已有文件不凭“同名同大小”判断相同内容；确需替换时显式设置 `overwrite:true` 并执行重新选择。已确认正式附件正常关联时不重复上传。`file_selected` 仅证明原生输入接受了文件，之后仍须核实官网上传反馈/正式附件；不等于服务器接收或投递成功。
- 工具没有点击保存、预览、添加经历或最终投递的操作。`fields_checked` 只表示本批当前值通过回读；不证明网站已保存、完整简历合格或可以提交；结果显式保留 `site_saved_verified:false` 和 `submission_verified:false`。

缺失的经历沿用正常浏览器新增：先比较真实来源数与现有条目及身份，只补缺失项；每新增一条确认数量确实增加一条。单条编辑器在正常保存后核验对应记录恰好多一条或原记录已更新，结果未知先回查；不因扩展的 filled 标记或成功计数就认为保存成功。

最终必填/声明检查、提交断点、官网申请核验和看板登记仍按 [application-playbook.md](application-playbook.md) 执行。本地计划包含个人资料，不能提交仓库、上传无关服务或贴入公共日志。
