# Phoenix Helper — 金凤做种助手 & 局域网传输

PySide6 桌面应用 + Flutter 移动端，实现一键制种/上传金凤 PT 站/uTorrent 做种，以及局域网高速文件传输。

## 功能

### 桌面端（PySide6）

- **一键做种**：选择文件 → 自动制种 → 上传金凤站点 → 下载官方种子 → uTorrent 做种
- **局域网传输**：生成二维码，手机扫码连接，双向传输文件
- **共享文件**：选择文件共享给手机端下载
- **自动做种**：手机上传的文件可自动触发制种流程

### 移动端（Flutter）

- **扫码连接**：扫描二维码连接电脑或其他手机
- **文件传输**：上传文件到电脑 / 从电脑下载文件
- **断点续传**：分块上传，支持暂停/继续
- **接收模式**：开启后让其他设备扫码传文件
- **BT 下载**：导入 .torrent 文件，内置下载引擎
- **文件管理**：查看、打开、分享、移动已下载文件

### P2P 架构

任何设备（电脑或手机）都可以充当服务端或客户端，角色可互换。

## 快速开始

### 桌面端

```bash
# 从源码运行
cd d:\phoenix-helper
.build-venv\Scripts\activate
python -m phoenix_helper.app
```

或运行打包好的 `dist/phoenix-helper-http/phoenix-helper-http.exe`。

### 移动端

安装 `app-debug.apk`，打开后：

1. 点击 **扫码连接**，扫描电脑端显示的二维码
2. 连接成功后可上传/下载文件
3. 或点击 **发送给手机**，开启接收模式让其他设备扫码连接

## 局域网传输协议

三步上传：

1. `POST /api/prepare-upload` — 宣告文件，获取 session + token
2. `POST /api/upload` — 分块传输文件（支持断点续传）
3. `POST /api/confirm-seed` — 确认完成，可选触发自动做种

其他端点：

- `GET /api/ping` — 无认证存活探测（多网卡 IP 发现）
- `GET /api/status` — 设备能力声明（含 `fileListVersion` 用于文件列表自动刷新）
- `POST /api/register` — QR token 交换完整 session
- `GET /api/files` / `GET /api/files/download` — 文件列表与下载

**二维码格式**：`PHX://v=1&t={pc|phone}&n=设备名&h=IP1,IP2&p=端口&k=token前6位`

## 项目结构

```text
src/phoenix_helper/           # Python 桌面端
├── app.py                    # 入口
├── config.py                 # 配置管理
├── lan/                      # LAN 传输（P2P）
│   ├── server.py             # HTTP 服务端
│   ├── p2p_client.py         # P2P 客户端
│   ├── chunk_store.py        # 分块上传存储
│   ├── file_store.py         # 文件持久化
│   ├── qr_generator.py       # 二维码生成
│   └── ip_utils.py           # IP 探测
├── ui/                       # PySide6 界面
├── clients/                  # uTorrent 等外部客户端
├── torrent/                  # 制种、种子解析
└── phoenix/                  # 金凤站点 API

phoenix_mobile/               # Flutter 移动端
├── lib/
│   ├── screens/              # 页面（首页、扫码、上传、下载等）
│   ├── providers/            # 状态管理（连接、传输、服务端）
│   ├── services/             # 业务逻辑（HTTP、P2P、BT 下载）
│   ├── models/               # 数据模型
│   └── utils/                # 工具类（日志等）
└── android/                  # Android 原生代码
```

## 构建

### 桌面端（onedir exe）

```bash
.build-venv\Scripts\activate
python scripts/build_onedir.py
# 输出：dist/phoenix-helper-http/
```

### 移动端（APK）

```bash
# 需要先将源码同步到 ASCII 路径（CJK 用户名会导致 Flutter 崩溃）
bash phoenix_mobile/build_apk.sh
# 输出：D:\phx-build\build\app\outputs\flutter-apk\app-debug.apk
```

## 配置文件

- 桌面端：`%APPDATA%\PhoenixHelper\config.json`（密码 DPAPI 加密）
- 移动端下载目录：`/storage/emulated/0/Android/data/com.phoenixhelper.phoenix_mobile/files/`

## 已知问题

- **OpenSSL 兼容性**：uv 管理的 Python 3.12.13 在 Windows 上有 `OPENSSL_Applink` 问题，内网轮询已改用 `http.client` 绕过
- **CJK 路径**：用户名含中文会导致 Flutter 构建失败，需用 `build_apk.sh` 路径
- **两个 git 副本**：`d:\金凤拯救计划` 是旧备份，不要 push 旧目录的改动
