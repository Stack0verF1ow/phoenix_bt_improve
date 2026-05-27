# 金凤本地做种助手

一键完成制种、上传到金凤 PT 站、下载官方种子、调用 uTorrent 做种。

## 功能

- 选择文件或文件夹，自动生成 .torrent 种子
- HTTP 直连上传到金凤网站（无需浏览器、无需 Selenium、无需 WebEngine）
- 账号密码登录（无需打开浏览器提取 Cookie）
- 自动下载站点返回的官方种子
- 调用 uTorrent 命令行启动做种
- 自动检测 uTorrent 安装路径（支持跨盘搜索）
- 显示每日剩余上传次数

## 快速开始

### 1. 下载

从 `dist/` 目录获取打包好的程序：

- `phoenix-helper-http/` — 文件夹版本（114MB，推荐）
- `phoenix-helper/` — 旧版（含 WebEngine 浏览器引擎，316MB）

### 2. 首次运行

1. 启动程序，首次运行会自动检测 uTorrent 路径
2. 如未自动检测到，进入 **设置** 页面，点击 **自动查找** 或手动浏览选择 `uTorrent.exe`
3. 在 **设置** → **站点登录** 中点击 **登录**，输入金凤站点用户名和密码
4. 点击 **保存设置**

### 3. 使用方法

1. 在 **一键做种** 页面选择文件或文件夹（支持拖放）
2. 确认标题、简介等信息（自动填充，可手动修改）
3. 点击 **一键做种**
4. 等待完成：制种 → HTTP 上传 → 下载站点种子 → uTorrent 自动开始做种

## 项目结构

```
src/phoenix_helper/
├── app.py                   # 入口
├── config.py                # 配置管理（DPAPI 加密）
├── models.py                # 数据模型
├── phoenix/
│   ├── client.py            # 站点 API（登录、上传、下载种子）
│   ├── forms.py             # ASP.NET 表单解析
│   ├── parser.py            # HTML 响应解析
│   └── cookies.py           # Cookie 格式化
├── torrent/
│   ├── bencode.py           # Bencode 编解码
│   ├── creator.py           # .torrent 文件生成
│   └── inspector.py         # .torrent 文件解析
├── clients/
│   ├── discovery.py         # uTorrent 路径自动发现
│   ├── utorrent.py          # uTorrent 命令行启动
│   └── browser_cookies.py   # 浏览器 Cookie 读取（备用）
└── ui/
    ├── main_window.py       # 主窗口
    ├── setup_dialog.py      # 首次配置向导
    ├── http_login_dialog.py # 登录对话框
    └── widgets.py           # 日志组件
```

## 配置文件位置

```text
%APPDATA%\PhoenixHelper\config.json
```

密码和 Cookie 使用 Windows DPAPI 加密存储。

## 从源码运行

```bash
# 创建虚拟环境
python -m venv .build-venv
.build-venv\Scripts\activate

# 安装依赖
pip install -e .[dev]

# 运行
python -m phoenix_helper.app
```

## 打包

```bash
# 自动使用 .build-venv 打包为 onedir 模式
python scripts/build_onedir.py
```

输出在 `dist/phoenix-helper-http/`。

## 技术演进

1. **Selenium 方案**（已废弃）：使用 Edge/Chrome/Firefox 驱动自动化操作浏览器
2. **Qt WebEngine 方案**（已废弃）：嵌入 Chromium 浏览器处理 ASP.NET 表单
3. **HTTP 直连方案**（当前）：纯 `requests` 模拟表单提交，修复 Cookie 处理方式后成功绕过服务端验证

## 常见问题

### uTorrent 未自动检测到

点击 **设置** → **自动查找**。程序会搜索所有盘符的 `Program Files` 目录和根目录。如仍未找到，手动浏览选择 `uTorrent.exe`。

### 上传失败

- 检查 **设置** → **站点登录** 中的登录状态
- 检查每日上传次数是否已用完
- 查看日志输出框中的详细错误信息

### 启动时提示"另一程序正在使用此文件"

Windows Defender 实时扫描导致。解决方案：

1. 打开 **Windows 安全中心** → **病毒和威胁防护** → **管理设置**
2. 在 **排除项** 中添加程序所在文件夹

## 注意事项

- 不要提交 `config.json`、Cookie、密码等敏感信息
- `.gitignore` 已覆盖常见本地文件，提交前请检查 `git status`
