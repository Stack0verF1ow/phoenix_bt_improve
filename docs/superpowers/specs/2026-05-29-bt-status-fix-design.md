# BT "已完成"绿色状态修复设计

## 问题描述

移动端 BT 种子列表只能显示"未下载"（蓝色）和"已暂停"（橙色）两种状态，永远不会显示"已完成"（绿色）。暂停状态也只能在下拉刷新后才更新。

## 根因分析

经代码审查，发现以下问题：

### Bug 1（主因）：`isStateFileComplete()` 静默吞异常

**位置**: `phoenix_mobile/lib/models/torrent_file.dart:25-43`

`isStateFileComplete()` 的 `catch (_)` 会吞掉所有异常（包括 `FileSystemException`、权限错误、文件锁定），返回 `false`。在 Android 上，`readAsBytesSync()` 可能在以下情况抛出异常：

- `StateFile` 的 `RandomAccessFile` 仍然持有文件句柄（`_task.stop()` 尚未完成）
- Android scoped storage 权限问题
- 文件内容尚未完全刷盘

结果：已完成的种子被误判为 `partial`（橙色），而不是 `completed`（绿色）。

### Bug 2：`stopDownload()` 销毁完成状态

**位置**: `phoenix_mobile/lib/services/bt_download_service.dart:152-163`

`stopDownload()` 将 `_completed` 重置为 `false`，`_progress` 重置为 `0`。下载完成后的 1 秒延迟 `syncTorrents()` 如果在 `stopDownload()` 之后才执行，会触发又一次 `syncTorrents()`。同时，`_task.stop().then()` 和 `stopDownload()` 可能造成对同一个 `TorrentTask` 的双重 `stop()`，导致 state 文件损坏。

### Bug 3：无定期状态刷新

**位置**: `phoenix_mobile/lib/providers/torrent_provider.dart`

`syncTorrents()` 只在以下时机被调用：
- 页面初始化（`initState`）
- 手动下拉刷新（`RefreshIndicator`）
- 下载完成/暂停回调

没有定时器定期重读磁盘状态。用户需要手动下拉才能看到状态变化。

### Bug 4：完成横幅依赖易失内存状态

**位置**: `phoenix_mobile/lib/screens/torrent_screen.dart:202-211`

"下载完成!" 绿色横幅基于 `bt.completed`（易失内存状态），而非 `file.status`（持久磁盘状态）。App 重启或 `stopDownload()` 后横幅消失。

## 修复方案

### Fix 1：`isStateFileComplete()` 增加重试 + 日志

文件：`phoenix_mobile/lib/models/torrent_file.dart`

- 将 `catch (_)` 改为多次重试读取（最多 3 次，每次间隔 500ms）
- 添加 `FileLogger` 日志，当 catch 到异常时记录具体错误
- 只有在所有重试都失败后才返回 `false`

```dart
static bool isStateFileComplete(String statePath, int piecesNum) {
  for (var attempt = 0; attempt < 3; attempt++) {
    try {
      final f = File(statePath);
      if (!f.existsSync()) return false;
      final bytes = f.readAsBytesSync();
      final bitfieldLen = (piecesNum + 7) ~/ 8;
      if (bytes.length < bitfieldLen) return false;
      for (var i = 0; i < bitfieldLen; i++) {
        final byte = bytes[i];
        final expected = (i == bitfieldLen - 1)
            ? (0xFF << ((bitfieldLen * 8) - piecesNum)) & 0xFF
            : 0xFF;
        if (byte != expected) return false;
      }
      return true;
    } catch (e) {
      FileLogger.log('[TorrentFile] isStateFileComplete attempt ${attempt + 1} failed: $e');
      if (attempt < 2) {
        Thread.sleep(Duration(milliseconds: 500));  // 伪代码，实际用 Future.delayed
      }
    }
  }
  return false;
}
```

**注意**：`isStateFileComplete` 当前是 `static` 同步方法。重试逻辑需要改为异步或使用 `Isolate`。考虑到调用链，最简方案是改为单次读取但记录异常原因，并在 `syncTorrents()` 调用时增加延迟。

### Fix 2：完成后的任务停止流程改进

文件：`phoenix_mobile/lib/services/bt_download_service.dart`

关键改动：

1. 下载到 100% 后，不再立即 `stop()` 任务。改为：
   - 设置 `_completed = true`，通知 UI
   - 等待 `_task.stop()` 真正完成（await 而非 fire-and-forget）
   - `stop()` 完成后再通知 UI，触发 `syncTorrents()`

2. `stopDownload()` 增加防重入保护：如果 `_task` 正在停止中，等待停止完成而不是重复调用 `stop()`

```dart
bool _stopping = false;

// 在 poll timer 的完成检测中：
if (_task!.progress >= 1.0 && !_completed) {
  _pollTimer?.cancel();
  _completed = true;
  notifyListeners();  // 先通知 UI 显示"已完成"
  _stopping = true;
  _task?.stop().then((_) {
    _stopping = false;
    _running = false;
    _sendTrackerEvent('stopped');
    notifyListeners();  // 再通知 UI 触发 syncTorrents
  });
  return;
}

// stopDownload() 中：
Future<void> stopDownload() async {
  if (_stopping) return;  // 防重入
  _pollTimer?.cancel();
  if (_task != null) {
    await _task!.stop();
  }
  _task = null;
  _running = false;
  _completed = false;
  _progress = 0;
  _error = null;
  notifyListeners();
}
```

### Fix 3：添加定期状态刷新

文件：`phoenix_mobile/lib/providers/torrent_provider.dart`

添加 `Timer.periodic(Duration(seconds: 15))` 定期调用 `syncTorrents()`，在页面不可见时暂停（通过 `WidgetsBindingObserver` 或页面生命周期）。

```dart
Timer? _refreshTimer;

void startPeriodicRefresh() {
  _refreshTimer?.cancel();
  _refreshTimer = Timer.periodic(const Duration(seconds: 15), (_) {
    syncTorrents();
  });
}

void stopPeriodicRefresh() {
  _refreshTimer?.cancel();
  _refreshTimer = null;
}

@override
void dispose() {
  _refreshTimer?.cancel();
  // ... 其他清理
  super.dispose();
}
```

在 `TorrentScreen` 的 `initState` 中调用 `startPeriodicRefresh()`，在 `dispose` 中调用 `stopPeriodicRefresh()`。

### Fix 4：完成横幅改为基于 `file.status`

文件：`phoenix_mobile/lib/screens/torrent_screen.dart`

将完成横幅的逻辑从依赖 `bt.completed`（易失）改为依赖 `TorrentFile.status`（持久）：

```dart
// 检查是否有任何种子是完成状态
final anyCompleted = provider.torrents.any((t) => t.status == TorrentStatus.completed);

if (bt.running) {
  // 正在下载时的显示逻辑...
} else if (anyCompleted) {
  // 显示"已完成"横幅，基于持久状态
  return Column(children: [
    const Padding(child: Text('下载完成!', style: TextStyle(color: Colors.green))),
    Expanded(child: _buildTorrentList(provider)),
  ]);
} else {
  return _buildTorrentList(provider);
}
```

## 修改文件清单

| 文件 | 改动 |
|------|------|
| `phoenix_mobile/lib/models/torrent_file.dart` | `isStateFileComplete()` 异常处理改进 |
| `phoenix_mobile/lib/services/bt_download_service.dart` | 完成流程改进 + 防重入保护 |
| `phoenix_mobile/lib/providers/torrent_provider.dart` | 定期刷新 + 双重 sync 修复 |
| `phoenix_mobile/lib/screens/torrent_screen.dart` | 完成横幅改为基于 `file.status` |

## 不在范围内

- PC 端做种状态查询（用户确认不需要）
- 断点续传功能（后续单独处理）
- 移动端做种功能