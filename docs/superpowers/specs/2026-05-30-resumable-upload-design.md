# 断点续传设计

## 问题描述

移动端和桌面端之间的 LAN 文件传输（手机→PC、手机→手机上传方向）目前只能整体传输，中断后从头重传。对于经常 1GB+ 的文件，WiFi 不稳定、App 切后台、主动暂停等场景下体验很差。

下载方向已支持 HTTP Range 续传，本文档只涉及上传方向的断点续传改造。

## 方案选择

采用 **方案 C：分块上传 + 断点状态查询**。

原因：
- 1GB+ 文件 + 全中断场景（WiFi 不稳定/主动暂停/App 切后台），稳健性最重要
- 当前上传协议将整个文件缓存到内存，1GB 文件直接吃 1GB 内存，分块方式写入磁盘更友好
- 方案 B（Range 上传）在 App 切后台后恢复 offset 比较麻烦，不如分块 + 状态查询稳健

参考：LocalSend（82k star）协议 v2.1 **不支持断点续传**，分块续传是我们的差异化需求。

## 协议变更

### 现有协议保持兼容

现有三步模型（prepare-upload → upload → confirm-seed）保持不变。新增/变更的端点向后兼容：不传 `chunkIndex` 参数时走原始整体上传模式。

### `POST /api/prepare-upload`（修改）

请求体新增 `chunkSize`：

```json
{
  "files": {
    "file0": {
      "name": "video.mp4",
      "size": 1073741824,
      "type": "video/mp4",
      "chunkSize": 4194304
    }
  }
}
```

响应体新增 `chunkSize`：

```json
{
  "sessionId": "uuid",
  "fileTokens": {"file0": "tok0"},
  "chunkSize": 4194304,
  "expires_in": 600
}
```

### `POST /api/upload`（修改）

新增查询参数：

| 参数 | 必需 | 说明 |
|------|------|------|
| `sessionId` | 是 | 不变 |
| `fileId` | 是 | 不变 |
| `token` | 是 | 不变 |
| `chunkIndex` | 否 | chunk 序号（0-based），不传则为兼容模式 |
| `chunkHash` | 否 | 该 chunk 的 CRC32 校验值 |

可选请求头（调试用）：

```
Content-Range: bytes 8388608-12582911/1073741824
```

响应：

```json
// chunk 模式
{"status": "chunk_received", "fileId": "file0", "chunkIndex": 2, "chunksReceived": [0,1,2], "totalChunks": 256}

// 兼容模式（不传 chunkIndex）
{"status": "received", "fileId": "file0", "name": "video.mp4", "size": 1073741824}
```

新增错误码：

| HTTP | 说明 |
|------|------|
| 400 | CRC32 校验失败 |
| 409 | chunk 已收到（幂等，客户端可忽略） |

### `GET /api/upload/{sessionId}`（增强）

新增 `fileId` 查询参数，返回 chunk 接收状态：

```
GET /api/upload/{sessionId}?fileId=file0&token=tok0
```

响应：

```json
{
  "sessionId": "uuid",
  "status": "active",
  "file_chunks": {
    "file0": {
      "totalChunks": 256,
      "chunksReceived": [0, 1, 3, 5],
      "fileSize": 1073741824,
      "chunkSize": 4194304
    }
  },
  "files_received": 0,
  "files_total": 1,
  "seed_status": "idle"
}
```

不带 `fileId` 参数时返回与现在相同格式（向后兼容）。

### `POST /api/confirm-seed`（修改）

请求体新增 `fileHashes`（可选）：

```json
{
  "sessionId": "uuid",
  "auto_seed": true,
  "fileHashes": {
    "file0": "sha256hash..."
  }
}
```

服务端确认流程：

1. 遍历每个 fileId，检查 `totalChunks == chunksReceived.length`
2. 缺失 chunk → 返回 400 + 缺失列表
3. 有 `fileHashes` → 校验 SHA256
4. 全部通过 → rename `.part/{sessionId}/{fileId}.data` → `{receive_dir}/{fileName}`
5. 删除 `.meta.json` 和临时目录

## 数据模型与存储

### 服务端临时文件结构

```
{receive_dir}/
  .part/
    {sessionId}/
      {fileId}.meta.json    # 文件元数据 + chunk 状态
      {fileId}.data         # 累积写入的文件（seek 方式填 chunk）
```

### `.meta.json` 内容

```json
{
  "fileName": "video.mp4",
  "fileSize": 1073741824,
  "chunkSize": 4194304,
  "totalChunks": 256,
  "chunksReceived": [0, 1, 3, 5],
  "chunkChecksums": {
    "0": "a1b2c3d4",
    "1": "e5f6a7b8"
  },
  "createdAt": 1748000000,
  "fileToken": "tok0"
}
```

### 设计决策

1. **直接 seek 写入 `.data` 文件** — 不用散 chunk 文件再合片。每个 chunk 到达后 `seek(chunkIndex * chunkSize)` 写入正确位置，confirm 时 rename 即可
2. **`.meta.json` 每收到 chunk 实时更新** — 断电后也能恢复
3. **CRC32 校验每个 chunk** — LAN 场景不需要 SHA256 级校验，CRC32 足够检测传输错误
4. **最后一个 chunk 可能小于 chunkSize** — `fileSize - (totalChunks - 1) * chunkSize`
5. **10 分钟超时清理** — 沿用现有 `_SESSION_TTL = 600s`，超时后清理 `.part/{sessionId}/`

## 客户端上传续传逻辑

### `http_client.dart` 改动

新增 `uploadFileChunked` 方法：

```
1. prepare-upload → 获取 sessionId + chunkSize
2. 计算本地文件的总 chunk 数
3. GET /upload-status → 获取服务端已收 chunks
4. 计算缺失 chunks = all_chunks - chunksReceived
5. 并发上传缺失 chunks（最多 3 个并发）：
   a. 读取文件偏移量 bytes = file[offset : offset + chunkSize]
   b. 计算 CRC32
   c. POST /upload?...&chunkIndex=N&chunkHash=crc32
   d. 收到 400 → CRC 失败，重传该 chunk（最多 3 次）
   e. 收到 409 → chunk 已收到，忽略
6. 全部完成 → confirm-seed
```

### 暂停/继续

**主动暂停：**

1. 取消正在进行 chunk 上传（CancelToken）
2. 保存进度到内存（已完成哪些 chunk）
3. 不调用 confirm-seed，不取消 session

**继续传输：**

1. `GET /upload-status` 查询服务端已收 chunks
2. 合并本地 + 服务端记录，计算缺失 chunks
3. 从缺失处续传

### App 切后台/网络中断

1. Dio 连接断开 → 捕获异常，标记传输为"暂停中"
2. App 恢复前台 → 自动查 upload-status → 续传
3. sessionId 过期（410/404）→ 提示用户重新开始

### session 过期重启

如果 session 过期（>10min），临时文件已被清理：

1. 客户端检测到 410/404
2. 重新 `POST /prepare-upload`
3. 从头上传所有 chunks
4. 可选：提示用户"上传超时，需要重新开始"

## 下载续传（已完成，无需改动）

`http_client.dart` 的 `downloadFile` 已实现：
- 检查本地文件大小 → 发 `Range: bytes=N-`
- 服务端返回 206 → append 模式写入
- 服务端返回 200 → 从头覆盖写入

两个服务端（`server.py` 和 `p2p_server.dart`）都已支持 Range 头。

## 修改文件清单

| 文件 | 责任 | 改动 |
|------|------|------|
| `src/phoenix_helper/lan/server.py` | PC 服务端 | `_handlePrepareUpload` 加 chunkSize，`_handleUpload` 支持 chunk 模式，`_handleUploadStatus` 增强，`_handleConfirmSeed` 完整性校验 + rename，临时文件管理 |
| `phoenix_mobile/lib/services/p2p_server.dart` | 手机服务端 | 对称实现 server.py 的 chunk 逻辑 |
| `phoenix_mobile/lib/services/http_client.dart` | 手机客户端 | 新增 `uploadFileChunked` 方法，断点续传，暂停/继续 |
| `phoenix_mobile/lib/models/upload_session.dart` | 数据模型 | 新增 `chunkSize` 字段 |
| `phoenix_mobile/lib/providers/*` | 状态管理 | 上传进度显示 chunk 维度，暂停/继续 UI |
| `phoenix_mobile/lib/screens/upload_screen.dart` | UI | 暂停/继续按钮，chunk 进度显示 |

## 不在范围内

- PC 端上传到手机（目前无此场景，手机是接收方时走 P2P 服务端）
- 下载方向的改动（已有 Range 支持）
- 加密/HTTPS（沿袭现有 HTTP 模式）
- 多文件并行上传的 chunk 交错（每个文件 chunk 串行上传，多文件间可并行）