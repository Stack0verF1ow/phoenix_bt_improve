# 金凤 BT 本地做种助手 (Phoenix Helper)

PySide6 桌面应用 + Flutter 移动端，实现一键制种/上传金凤站点/uTorrent 做种全流程，以及局域网文件传输。

---

## 仓库结构

```
d:\phoenix-helper/
├── src/phoenix_helper/       # Python 桌面端源码
│   ├── app.py                # 入口
│   ├── config.py             # AppConfig 配置
│   ├── lan/                  # LAN 传输模块（HTTP 服务器 + QR 码）
│   ├── ui/                   # PySide6 UI
│   ├── clients/              # uTorrent 等外部客户端交互
│   ├── torrent/              # 制种、种子解析
│   ├── phoenix/              # 金凤站点 API 客户端
├── phoenix_mobile/           # Flutter 移动端项目
└── pyproject.toml
```

**当前活跃分支**: `feature/lan-transfer`（LAN 传输功能开发中）

---

## 桌面端运行

```bash
cd d:\phoenix-helper
.build-venv\Scripts\activate
python -m phoenix_helper.app
```

### 虚拟环境说明

- `.build-venv/` 在 `.gitignore` 中，不追踪
- 已知问题：uv 管理的 Python (3.12.13) 的 OpenSSL DLL 在 Windows 上有 `OPENSSL_Applink` 兼容性问题，表现是调用 `urllib.request.urlopen` 时直接崩溃
- **已修复**：内网轮询改用 `http.client.HTTPConnection`（纯 socket，不触发 OpenSSL）
- 如需重建环境：`uv venv --python 3.12.13 .build-venv && .build-venv\Scripts\activate && pip install -e .`

### 关键依赖

```
PySide6>=6.7,<6.8            # Qt GUI（QtWebEngine 内置在 PySide6-Addons 中）
requests>=2.31                # HTTP 客户端
beautifulsoup4>=4.12          # HTML 解析
qrcode[pil]>=7.4              # 二维码生成
```

---

## LAN 传输模块 (`src/phoenix_helper/lan/`)

HTTP 直传方案（无 WebEngine），三步上传协议：

1. **POST /api/prepare-upload** — 客户端宣告文件，服务端返回 session + file token
2. **POST /api/upload** — 传输原始文件字节（stream），校验 token
3. **POST /api/confirm-seed** — 确认完成，可选触发自动做种

其他端点：
- `GET /api/status` — 服务端能力声明
- `POST /api/register` — QR token 交换完整 session
- `GET /api/devices` — 已注册设备列表（轮询更新）
- `GET /api/files` / `GET /api/files/download` — 文件列表与下载

**二维码协议**: `PHX://v=1&t=pc&n=设备名&h=IP1,IP2&p=端口&k=token前6位`

### 自动做种流程（SeedWorker）

```
收到文件 → ResourceDraft.from_path → create_torrent → PhoenixClient.upload_torrent
→ 下载站点种子 → uTorrent 打开做种
```

---

## Flutter 移动端 (`phoenix_mobile/`)

- 扫码发现 PC/手机，HTTP 直传文件
- 构建需复制到 ASCII 路径：`bash build_apk.sh`（自动 robocopy 到 `d:\phx-build`）
- 热重载：`flutter run -d <device_id>`
- `mobile_scanner 6.0.11` + `dio` + `go_router`
- NDK version: `27.0.12077973`

---

## 已知技术债

1. **两个 git 副本并存**: `d:\金凤拯救计划` 是旧目录（仅备份），`d:\phoenix-helper` 是当前工作目录。两者指向同一 remote origin，不要 push 旧目录的改动
2. **`pyproject.toml` 去掉 `PySide6-WebEngine`**: 该独立包已不存在于 PyPI，QtWebEngine 已内置在 PySide6-Addons 中
3. **OpenSSL 兼容性**: 如果在新机器上遇到同样崩溃，可考虑用 `http.client` 替代所有 `urlopen` 调用，或更换 Python 发行版
4. **CJK 路径**: 用户名 `吴名` 导致 Flutter impellerc / Gradle worker daemon 在 CJK 路径下失败，已在 `build_apk.sh` 中用 robocopy 到 ASCII 路径绕过

---

## 开发计划

参见 `本地助手开发计划.md`，当前阶段：
- Phase 1 ✅ PC 端 LAN 服务器 + QR 码 + 文件接收
- Phase 2 ✅ Flutter 移动端 MVP（扫码连接 + 上传/下载）
- Phase 3 🔄 自动做种集成（手机→PC→种子→uTorrent）
- Phase 4 ⬜ 手机↔手机互传
- Phase 5 ⬜ 移动端 BT 下载
- Phase 6 ⬜ 打磨
