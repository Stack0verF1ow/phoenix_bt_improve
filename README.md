# 金凤本地做种助手

本仓库用于开发金凤 BT 的桌面端本地助手。助手的目标是让上传者选择文件或文件夹、填写少量信息后，一键完成制种、上传、下载最终种子并调用 µTorrent 3.1 做种。

## 当前状态

已搭建 Python + PySide6 MVP 骨架：

- torrent bencode 编解码、生成和解析。
- 从已有种子读取 Tracker。
- ASP.NET WebForms 上传页字段解析。
- 显式粘贴 Cookie 或导入 Netscape `cookies.txt`。
- 金凤上传客户端封装。
- µTorrent 3.1 打开种子 / WebUI 添加种子封装。
- 自动在常见安装目录查找 `uTorrent.exe`。
- PySide6 主界面。
- 基础单元测试。

## 安装开发环境

```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -e .[dev]
```

## 运行

```bash
python -m phoenix_helper.app
```

或安装后运行：

```bash
phoenix-helper
```

## 设置项来源

- Tracker：在“设置”页点击“从测试种子读取”，或选择任意金凤下载过的 `.torrent` 读取 announce。
- 登录状态：推荐在设置页点击“网页登录”，像浏览器一样完成学校账号登录，再点击“保存登录状态”。助手只保存登录后的站点 Cookie，不保存学校账号密码。
- Cookie 备用导入：也可以从浏览器开发者工具复制 `phoenix.stu.edu.cn` 请求里的 `Cookie` 请求头，再点“粘贴/规范化”；支持 curl、`Set-Cookie` 多行、浏览器 Cookie 表格，或 Netscape `cookies.txt`。
- µTorrent 路径：在“设置”页点击“自动查找”，找不到时手动选择 `uTorrent.exe`。

助手不会静默读取浏览器加密 Cookie；Cookie 必须由用户显式粘贴或导入，避免误取其它网站凭据。

设置页可以点击“一键配置”自动读取测试种子的 Tracker、查找 µTorrent，并保存到本机。配置保存到当前用户目录：

```text
%APPDATA%\PhoenixHelper\config.json
```

Cookie 和 µTorrent WebUI 密码会使用 Windows 当前用户的本机加密能力保存；仓库里不要提交这个配置文件。学校统一认证通常会有跳转、验证码或风控，第一版不保存学校账号密码，推荐保存站点登录后的 Cookie。

µTorrent 3.1 没有稳定公开的命令行接口用于启用 WebUI。助手可以自动查找 µTorrent、保存 WebUI 地址/账号/密码并检测连通性；启用 WebUI 本身仍建议在 µTorrent 设置界面里完成，避免直接修改内部配置文件造成损坏。

## 测试

```bash
pytest
```

## 打包 Windows exe

推荐使用干净的 CPython 虚拟环境打包，避免 Anaconda 自带 OpenSSL/Qt DLL 混入 exe：

```bash
python scripts/build_windows_clean.py
```

如果你已经在非 Anaconda 的项目虚拟环境中，也可以直接运行：

```bash
python scripts/build_windows.py
```

打包完成后双击运行：

```text
dist/phoenix-helper.exe
```

窗口标题仍为“金凤本地做种助手”。当前默认使用英文 exe 文件名和控制台启动器，以避开 PyInstaller onefile 在中文文件名下可能出现的静默崩溃。

## 注意

不要提交账号、密码、Cookie、µTorrent WebUI 密码、本地下载内容或临时生成的 torrent。`.gitignore` 已覆盖常见本地文件，但提交前仍应检查 `git status`。
