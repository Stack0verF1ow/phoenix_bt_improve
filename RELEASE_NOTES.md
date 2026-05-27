## v0.2.0 — 全面重构，移除浏览器依赖

### 重大变更

- **移除 Selenium** — 不再需要 Edge/Chrome/Firefox 浏览器驱动
- **移除 Qt WebEngine** — 不再嵌入 Chromium 浏览器，安装包从 316MB 降至 **114MB**
- **HTTP 直连上传** — 修复 Cookie 处理逻辑后，ASP.NET 表单提交完全通过 `requests` 完成，不再需要真实浏览器环境
- **账号密码登录** — 直接输入金凤站点用户名密码即可，不再需要打开浏览器提取 Cookie

### 新增功能

- **uTorrent 路径跨盘自动检测** — 搜索所有盘符的 `Program Files` 和根目录下的 uTorrent/BitTorrent 安装
- **一键配置** — 首次运行向导自动检测 uTorrent 路径
- **设置自动保存** — 编辑字段后自动保存，不再需要手动点"保存"
- **设置页 UI 简化** — 分组清晰（站点登录 / Tracker / uTorrent 路径），移除不必要的内容

### 体验优化

- 做种按钮更大、蓝色主色调，操作路径更清晰
- 选择文件/文件夹按钮高亮，更容易发现
- 进度条更细更美观
- 日志框等宽字体，阅读更舒适
- "查看结果"按钮现在正确跳转到种子详情页

### 技术栈

`Python 3.12 + PySide6 + requests + BeautifulSoup4`
