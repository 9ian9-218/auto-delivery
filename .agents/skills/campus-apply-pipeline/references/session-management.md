# 登录状态复用

优先保持同一浏览器、专用非默认用户数据根目录、具体 profile 及正常标签；认证数据由浏览器及操作系统保管。固定目录保留本地数据，不保证招聘网站继续接受会话；同一 ATS 品牌、手机号或牛客账号不证明不同企业已登录。

## 本机工具

本环境的 `auto-resume-submit/scripts/session_status.py` 只管理非秘密观察台账：

- `doctor`：读取端口主进程和目录配置，报告 match/mismatch/unknown 等。不会启动浏览器或访问 cookie；match 不是“已登录”。命令行未明确 profile 子目录时不假定 Default。
- `list`：在共享任务锁内接管已运行浏览器，通过新建的后台 `chrome://version` 页面只读取 Profile Path，随后只关闭该自建标签，列出该实际 profile 的历史登录观察。
- `mark --site <业务URL> [--tenant <站点租户标识>] --state logged_in --basis account_page`：仅在 Agent 已核实目标企业当前账号/申请列表页面后记录。“需登录”使用 `expired/login_page`，“无法检查”使用 `unknown/check_unavailable`。

list/mark 不启动新浏览器，需要现有 HTTP 服务和 CDP 在线；不能仅依据端口在线、成功跳转到认证域、旧台账、cookie 文件存在或用户说扫码完成就记成已核实。浏览器身份取品牌、实际数据根目录与具体 profile，网站键为业务 origin 和可选租户；同一 origin 下租户不同应明确填写站点租户标识，不能填账号、手机号或 token。

台账位于项目私有 `work/browser_sessions.json`，只存 origin、租户、profile 标识哈希、状态、核验时间和证据类别；没有密码、cookie、token、验证码和完整认证跳转 URL。历史观察永远返回 `recheck_required:true`，是恢复线索，不是账号当前有效的证明。登录失效后更新观察，按当前网站正常入口恢复。

## 处理重复登录

1. 交互前先核实实际端口、浏览器、根目录及具体 profile。已经运行的浏览器不会因为改启动配置而换目录；出现失配时保留现有窗口及草稿，在下一次正常启动时使用确定的稳定目录，不为修复失配强关或搬运资料。
2. 已登录就复用同一标签/资料目录，避免反复新建临时自动化上下文。服务退出采用 detach；关闭时清理数据、站点例外、系统时间或浏览器策略是实际失效后的排查项，不默认更改全局安全设置。
3. 需认证时使用网站正常登录、浏览器密码管理器、扫码或短信等方式；账号口令由用户及原生密码管理器管理。图形验证、MFA、频控和重新授权按工具要求交接，保持页面并保存断点。
4. 正常密码自动填充/站点 SSO 可以减少重复输入，但站点服务端仍可撤销或过期会话。Chrome 的应用/机器绑定加密、默认目录远程调试限制也使跨浏览器复制不可靠。当前方案不导出/重放 cookie 或 storageState，不延长 cookie 寿命，也不承诺永久免认证。

技术依据见 [DrissionPage 启动设置](https://www.drissionpage.cn/browser_control/browser_options/)、[Chrome 远程调试目录要求](https://developer.chrome.com/blog/remote-debugging-port)、[Chrome Cookie 应用绑定加密](https://security.googleblog.com/2024/07/improving-security-of-chrome-cookies-on.html)、[Edge 会话持久化排查](https://learn.microsoft.com/en-us/troubleshoot/microsoft-edge/security/cookies-sessions-not-persisting)。对某企业是否仍登录，最终以该企业当前受保护页面为准。
