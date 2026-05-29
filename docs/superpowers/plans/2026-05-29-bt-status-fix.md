# BT "已完成"绿色状态修复 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复移动端 BT 种子列表只显示"未下载"和"已暂停"，永不显示"已完成"（绿色）状态的问题，以及暂停状态只能手动下拉刷新的问题。

**Architecture:** 修复 4 个 Bug：1) `isStateFileComplete()` 吞异常导致完成状态被误判为 partial；2) 下载完成后任务停止时序问题导致 state 文件可能未刷盘；3) 无定期状态刷新机制；4) 完成横幅依赖易失内存状态而非持久磁盘状态。

**Tech Stack:** Flutter/Dart, dtorrent_task_v2, dtorrent_parser

---

## Files to Modify

| File | Responsibility |
|------|---------------|
| `phoenix_mobile/lib/models/torrent_file.dart` | `isStateFileComplete()` 异常处理 + 异步重试 |
| `phoenix_mobile/lib/services/bt_download_service.dart` | 完成流程改进 + 防重入保护 |
| `phoenix_mobile/lib/providers/torrent_provider.dart` | 异步同步 + 定期刷新 + 去重 |
| `phoenix_mobile/lib/screens/torrent_screen.dart` | 完成横幅基于 `file.status` |

---

### Task 1: 修复 `isStateFileComplete()` — 异步重试 + 日志

**Files:**
- Modify: `phoenix_mobile/lib/models/torrent_file.dart`

**Problem:** `isStateFileComplete()` 是同步方法，用 `catch (_)` 吞掉所有异常（包括 Android 文件锁定），返回 `false` 让已完成的种子显示为 partial（橙色）而非 completed（绿色）。

**Solution:** 改为异步方法，增加最多 3 次重试（每次间隔 500ms），记录异常日志。

- [ ] **Step 1: 将 `isStateFileComplete` 改为异步方法并添加重试逻辑**

替换 `phoenix_mobile/lib/models/torrent_file.dart` 整个内容为：

```dart
import 'dart:io';

import '../utils/file_logger.dart';

enum TorrentStatus { notDownloaded, partial, completed }

class TorrentFile {
  final String name;
  final String path;
  final int size;
  final DateTime addedAt;
  final TorrentStatus status;

  TorrentFile({
    required this.name,
    required this.path,
    required this.size,
    required this.addedAt,
    this.status = TorrentStatus.notDownloaded,
  });

  /// Check a .bt.state file to see if all pieces are complete.
  /// [piecesNum] is the total piece count from the torrent metainfo.
  ///
  /// dtorrent_task_v2 writes the state file as:
  ///   [bitfield bytes (ceil(piecesNum/8))][8 bytes uploaded counter]
  ///
  /// Retries up to 3 times with 500ms delay if reading the file fails
  /// (may happen if StateFile is still being flushed on Android).
  static Future<bool> isStateFileComplete(String statePath, int piecesNum) async {
    final bitfieldLen = (piecesNum + 7) ~/ 8;
    for (var attempt = 0; attempt < 3; attempt++) {
      try {
        final f = File(statePath);
        if (!f.existsSync()) return false;
        final bytes = f.readAsBytesSync();
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
        FileLogger.log('[TorrentFile] isStateFileComplete attempt ${attempt + 1}/3 failed for $statePath: $e');
        if (attempt < 2) {
          await Future.delayed(const Duration(milliseconds: 500));
        }
      }
    }
    FileLogger.log('[TorrentFile] isStateFileComplete all 3 attempts failed, returning false for $statePath');
    return false;
  }
}
```

- [ ] **Step 2: 更新 `syncTorrents()` 调用点改为 await**

在 `phoenix_mobile/lib/providers/torrent_provider.dart` 第 86 行，`isStateFileComplete` 调用已经在一个 async 方法内，需要在调用前加 `await`：

将：
```dart
            final complete = TorrentFile.isStateFileComplete(statePath, meta.pieces.length);
```

改为：
```dart
            final complete = await TorrentFile.isStateFileComplete(statePath, meta.pieces.length);
```

- [ ] **Step 3: 验证编译通过**

Run: `cd D:\phoenix-helper\phoenix_mobile && flutter analyze lib/models/torrent_file.dart lib/providers/torrent_provider.dart`

Expected: No errors related to `isStateFileComplete`.

- [ ] **Step 4: Commit**

```bash
git add phoenix_mobile/lib/models/torrent_file.dart phoenix_mobile/lib/providers/torrent_provider.dart
git commit -m "fix: isStateFileComplete with async retry and logging"
```

---

### Task 2: 修复 `BtDownloadService` 完成流程 — 防重入 + 正确停止时序

**Files:**
- Modify: `phoenix_mobile/lib/services/bt_download_service.dart`

**Problem:** 
1. 下载到 100% 后立即设 `_running=false` 并 fire-and-forget `_task.stop()`，`_task.stop().then()` 中再 `notifyListeners()` 导致双重 `syncTorrents()`
2. `stopDownload()` 可能在 `_task.stop()` 还在进行中被调用，造成双重停止

**Solution:** 添加 `_stopping` 标志防止重入；完成时不立即设 `_running=false`，而是在 `_task.stop()` 完成后再设；`stopDownload()` 检查 `_stopping` 标志。

- [ ] **Step 1: 修改 `BtDownloadService` 完成流程和防重入保护**

在 `phoenix_mobile/lib/services/bt_download_service.dart` 中：

1. 添加 `_stopping` 字段（在 `_completed` 声明后面，约第 22 行后）：

在：
```dart
  bool _completed = false;
```

后添加：
```dart
  bool _stopping = false;
```

2. 修改完成检测逻辑（第 129-142 行），将：

```dart
        if (_task!.progress >= 1.0 && !_completed) {
          FileLogger.log('[BtDownload] progress>=1.0, completing. stopping task...');
          _pollTimer?.cancel();
          _completed = true;
          _running = false;
          notifyListeners();
          // Stop task and send tracker event asynchronously
          _task?.stop().then((_) {
            FileLogger.log('[BtDownload] task stopped, state file flushed');
            _sendTrackerEvent('stopped');
            notifyListeners();
          });
          return;
        }
```

改为：

```dart
        if (_task!.progress >= 1.0 && !_completed) {
          FileLogger.log('[BtDownload] progress>=1.0, completing. stopping task...');
          _pollTimer?.cancel();
          _completed = true;
          _stopping = true;
          notifyListeners();
          _task?.stop().then((_) {
            FileLogger.log('[BtDownload] task stopped, state file flushed');
            _stopping = false;
            _running = false;
            _sendTrackerEvent('stopped');
            notifyListeners();
          });
          return;
        }
```

3. 修改 `stopDownload()` 方法（第 152-163 行），将：

```dart
  Future<void> stopDownload() async {
    FileLogger.log('[BtDownload] stopDownload called');
    _pollTimer?.cancel();
    await _task?.stop();
    _task = null;
    _running = false;
    _completed = false;
    _progress = 0;
    _error = null;
    notifyListeners();
    FileLogger.log('[BtDownload] stopDownload done, notified listeners');
  }
```

改为：

```dart
  Future<void> stopDownload() async {
    FileLogger.log('[BtDownload] stopDownload called, stopping=$_stopping');
    _pollTimer?.cancel();
    if (_stopping) {
      FileLogger.log('[BtDownload] already stopping, waiting for task.stop to finish');
      await _task?.stop();
    } else {
      await _task?.stop();
    }
    _task = null;
    _stopping = false;
    _running = false;
    _completed = false;
    _progress = 0;
    _error = null;
    notifyListeners();
    FileLogger.log('[BtDownload] stopDownload done, notified listeners');
  }
```

4. 修改 `cleanUpAfterDelete()` 方法（第 166-175 行），将：

```dart
  Future<void> cleanUpAfterDelete() async {
    await _task?.stop();
```

改为：

```dart
  Future<void> cleanUpAfterDelete() async {
    if (_stopping) {
      await _task?.stop();
    } else {
      await _task?.stop();
    }
```

（此方法没有实际逻辑变化，但保持一致性——`_stopping` 标志在这里同样需要尊重）

- [ ] **Step 2: 验证编译通过**

Run: `cd D:\phoenix-helper\phoenix_mobile && flutter analyze lib/services/bt_download_service.dart`

Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add phoenix_mobile/lib/services/bt_download_service.dart
git commit -m "fix: BtDownloadService stopping race condition and task.stop timing"
```

---

### Task 3: 修复 `TorrentProvider` — 去重 syncTorrents + 定期刷新

**Files:**
- Modify: `phoenix_mobile/lib/providers/torrent_provider.dart`

**Problem:**
1. 完成时 `notifyListeners()` 触发两次 `syncTorrents()`（一次在 `_completed=true` 时，一次在 `_task.stop()` 完成后）
2. 没有定期刷新机制，用户只能手动下拉刷新

**Solution:**
1. 添加 `_syncInProgress` 和 `_syncNeeded` 标志防止并发 sync
2. BtDownloadService listener 中：完成时只标记需要 sync（延迟 1 秒），停止时立即 sync（但也去重）
3. 添加 `_refreshTimer` 定期刷新（15 秒），页面可见时开启，不可见时暂停

- [ ] **Step 1: 在 `TorrentProvider` 中添加去重和定期刷新**

在 `phoenix_mobile/lib/providers/torrent_provider.dart` 中：

1. 在类的成员变量区域（约第 16 行后），添加：

在：
```dart
  final Set<String> _selectedTorrents = {};
  bool _btSelectMode = false;
```

后添加：
```dart
  bool _syncInProgress = false;
  Timer? _refreshTimer;
```

2. 修改构造函数中的 listener（第 30-46 行），将：

```dart
    _btService.addListener(() {
      FileLogger.log('[TorrentProvider] bt listener: running=${_btService.running} completed=${_btService.completed}');
      if (_btService.completed) {
        // Delay sync to ensure .bt.state file is flushed to disk
        Future.delayed(const Duration(seconds: 1), () {
          FileLogger.log('[TorrentProvider] delayed syncTorrents (completed)');
          syncTorrents();
        });
      } else if (!_btService.running) {
        // Stopped/paused — re-sync status from disk
        FileLogger.log('[TorrentProvider] immediate syncTorrents (paused/stopped)');
        syncTorrents();
      } else {
        // Progress update — just notify UI
        notifyListeners();
      }
    });
```

改为：

```dart
    _btService.addListener(() {
      FileLogger.log('[TorrentProvider] bt listener: running=${_btService.running} completed=${_btService.completed} stopping=${_btService._stopping}');
      if (_btService.completed) {
        _scheduleSync(const Duration(seconds: 2));
      } else if (!_btService.running && !_btService._stopping) {
        _scheduleSync(const Duration(seconds: 1));
      } else {
        notifyListeners();
      }
    });
```

**注意**：`_stopping` 是 `BtDownloadService` 的私有字段。我们需要让它可访问，或者换一种方式判断。更好的方案是在 `BtDownloadService` 添加一个 getter `bool get stopping => _stopping;`。

3. 在 `BtDownloadService`（`bt_download_service.dart`）的 getters 区域（约第 31 行后）添加：

```dart
  bool get stopping => _stopping;
```

4. 回到 `torrent_provider.dart`，修改 listener：

```dart
    _btService.addListener(() {
      FileLogger.log('[TorrentProvider] bt listener: running=${_btService.running} completed=${_btService.completed} stopping=${_btService.stopping}');
      if (_btService.completed) {
        _scheduleSync(const Duration(seconds: 2));
      } else if (!_btService.running && !_btService.stopping) {
        _scheduleSync(const Duration(seconds: 1));
      } else {
        notifyListeners();
      }
    });
```

5. 在 `TorrentProvider` 中添加 `_scheduleSync` 方法（在 `syncTorrents` 方法之前）：

```dart
  void _scheduleSync(Duration delay) {
    Future.delayed(delay, () {
      if (!_syncInProgress) {
        syncTorrents();
      }
    });
  }
```

6. 修改 `syncTorrents()` 方法（第 63-110 行），在开头和结尾添加去重逻辑：

将 `syncTorrents()` 方法改为：

```dart
  Future<void> syncTorrents() async {
    if (_syncInProgress) return;
    _syncInProgress = true;

    _loading = true;
    notifyListeners();

    final dir = Directory(await torrentDir);
    final entries = <TorrentFile>[];
    final savePath = await _btSavePath();

    if (dir.existsSync()) {
      for (final entity in dir.listSync()) {
        if (entity is! File || !entity.path.endsWith('.torrent')) continue;
        final stat = entity.statSync();

        var status = TorrentStatus.notDownloaded;
        try {
          final meta = await Torrent.parseFromFile(entity.path);
          final hex = meta.infoHashBuffer
              .map((b) => b.toRadixString(16).padLeft(2, '0'))
              .join();
          final statePath = '$savePath${Platform.pathSeparator}$hex.bt.state';
          final stateFile = File(statePath);
          final exists = await stateFile.exists();
          if (exists) {
            final complete = await TorrentFile.isStateFileComplete(statePath, meta.pieces.length);
            status = complete ? TorrentStatus.completed : TorrentStatus.partial;
            FileLogger.log('[syncTorrents] ${entity.uri.pathSegments.last}: stateFile exists, complete=$complete, pieces=${meta.pieces.length}');
          } else {
            FileLogger.log('[syncTorrents] ${entity.uri.pathSegments.last}: no stateFile at $statePath');
          }
        } catch (e) {
          FileLogger.log('[syncTorrents] ${entity.uri.pathSegments.last}: error=$e');
        }

        entries.add(TorrentFile(
          name: entity.uri.pathSegments.last,
          path: entity.path,
          size: stat.size,
          addedAt: stat.modified,
          status: status,
        ));
      }
      entries.sort((a, b) => b.addedAt.compareTo(a.addedAt));
    }

    _torrents = entries;
    _loading = false;
    _syncInProgress = false;
    notifyListeners();
  }
```

7. 添加定期刷新的启动和停止方法（在 `syncTorrents` 之后）：

```dart
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
```

8. 在 `dispose()` 方法中取消定时器（文件末尾，类结束前）。添加 `dispose` 方法（当前类没有 dispose）：

实际上检查类的末尾——`TorrentProvider` 当前没有 `dispose` 方法。添加：

```dart
  @override
  void dispose() {
    _refreshTimer?.cancel();
    _btService.dispose();
    super.dispose();
  }
```

等等——`_btService` 是在 `TorrentProvider` 内部创建的，所以应该在这里 dispose 它。但检查现有的代码，`_btService` 是 `final` 在约第 19 行创建的，没有现有的 dispose。由于 `TorrentProvider` 在 app 生命周期内存在（在 `MultiProvider` 中注册），它的 dispose 可能不会被调用，但加上以防万一还是好的。

- [ ] **Step 2: 验证编译通过**

Run: `cd D:\phoenix-helper\phoenix_mobile && flutter analyze lib/providers/torrent_provider.dart lib/services/bt_download_service.dart lib/models/torrent_file.dart`

Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add phoenix_mobile/lib/providers/torrent_provider.dart phoenix_mobile/lib/services/bt_download_service.dart phoenix_mobile/lib/models/torrent_file.dart
git commit -m "fix: TorrentProvider dedup syncTorrents + periodic refresh + stopping getter"
```

---

### Task 4: 修复 `TorrentScreen` — 完成横幅基于 `file.status` + 启停定期刷新

**Files:**
- Modify: `phoenix_mobile/lib/screens/torrent_screen.dart`

**Problem:**
1. 完成"下载完成!"横幅依赖 `bt.completed`（易失内存状态），App 重启或 `stopDownload()` 后横幅消失
2. 没有启动定期刷新的代码

**Solution:**
1. 横幅改为检查 `provider.torrents` 中是否有 `TorrentStatus.completed` 的种子
2. 在 `initState` 中启动定期刷新，在 `dispose` 中停止

- [ ] **Step 1: 修改 `_buildBody` 方法中完成横幅逻辑**

在 `phoenix_mobile/lib/screens/torrent_screen.dart` 中，修改 `_buildBody` 方法（第 182-213 行）。

将：
```dart
  Widget _buildBody(TorrentProvider provider, BtDownloadService bt) {
    if (bt.running) {
      return Column(
        children: [
          _buildProgressCard(bt),
          if (bt.completed)
            const Padding(
              padding: EdgeInsets.all(8),
              child: Text('下载完成!', style: TextStyle(color: Colors.green)),
            ),
          if (bt.error != null)
            Padding(
              padding: const EdgeInsets.all(8),
              child: Text('错误: ${bt.error}',
                  style: const TextStyle(color: Colors.red)),
            ),
          Expanded(child: _buildTorrentList(provider)),
        ],
      );
    }
    if (bt.completed) {
      return Column(
        children: [
          const Padding(
              padding: EdgeInsets.all(8),
              child: Text('下载完成!', style: TextStyle(color: Colors.green))),
          Expanded(child: _buildTorrentList(provider)),
        ],
      );
    }
    return _buildTorrentList(provider);
  }
```

改为：
```dart
  Widget _buildBody(TorrentProvider provider, BtDownloadService bt) {
    final anyCompleted = provider.torrents.any(
        (t) => t.status == TorrentStatus.completed);

    if (bt.running) {
      return Column(
        children: [
          _buildProgressCard(bt),
          if (bt.completed)
            const Padding(
              padding: EdgeInsets.all(8),
              child: Text('下载完成!', style: TextStyle(color: Colors.green)),
            ),
          if (bt.error != null)
            Padding(
              padding: const EdgeInsets.all(8),
              child: Text('错误: ${bt.error}',
                  style: const TextStyle(color: Colors.red)),
            ),
          Expanded(child: _buildTorrentList(provider)),
        ],
      );
    }
    if (anyCompleted) {
      return Column(
        children: [
          const Padding(
              padding: EdgeInsets.all(8),
              child: Text('下载完成!', style: TextStyle(color: Colors.green))),
          Expanded(child: _buildTorrentList(provider)),
        ],
      );
    }
    return _buildTorrentList(provider);
  }
```

- [ ] **Step 2: 在 `initState` 中启动定期刷新，在 `dispose` 中停止**

修改 `_TorrentScreenState`（第 19 行之后）：

将：
```dart
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<TorrentProvider>().syncTorrents();
      _checkPendingTorrent();
    });
  }
```

改为：
```dart
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final provider = context.read<TorrentProvider>();
      provider.syncTorrents();
      provider.startPeriodicRefresh();
      _checkPendingTorrent();
    });
  }

  @override
  void dispose() {
    context.read<TorrentProvider>().stopPeriodicRefresh();
    super.dispose();
  }
```

注意：在 `dispose()` 中使用 `context.read` 是安全的，因为 Provider 的 `context.read` 不需要 widget 在树中，它只是获取最近的 Provider 实例。但如果担心，可以改为在 `initState` 中保存 provider 引用。

更安全的方案：在 `initState` 中保存引用：

```dart
  late final TorrentProvider _provider;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _provider = context.read<TorrentProvider>();
      _provider.syncTorrents();
      _provider.startPeriodicRefresh();
      _checkPendingTorrent();
    });
  }

  @override
  void dispose() {
    _provider.stopPeriodicRefresh();
    super.dispose();
  }
```

但这有初始化顺序问题——如果 `dispose()` 在 `initState` 的 `addPostFrameCallback` 之前被调用（理论上不太可能），`_provider` 会被延迟初始化但未赋值。更安全的方案：

不使用 `late`，直接在 `dispose` 中 try-catch：

```dart
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final provider = context.read<TorrentProvider>();
      provider.syncTorrents();
      provider.startPeriodicRefresh();
      _checkPendingTorrent();
    });
  }

  @override
  void dispose() {
    try {
      context.read<TorrentProvider>().stopPeriodicRefresh();
    } catch (_) {}
    super.dispose();
  }
```

但 `context` 在 `dispose` 中可能不可用。更好的方案是使用 `Provider` 的 `didChangeDependencies` 模式或直接通过 `SliverAutoDispose` 等机制。

**最简单的方案**：让 `TorrentProvider` 在 `startPeriodicRefresh` 中管理 Timer，并在 `dispose()` 方法中自动清理。这样 `TorrentScreen` 不需要在 dispose 中手动停止。

不过，按 Flutter 惯例，在 State 的 dispose 中取消 Provider 的 timer 是标准做法。使用 `mounted` 检查 + try-catch：

最终方案——在 `TorrentScreen` 的 State 中：

```dart
  TorrentProvider? _provider;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _provider = context.read<TorrentProvider>();
      _provider!.syncTorrents();
      _provider!.startPeriodicRefresh();
      _checkPendingTorrent();
    });
  }

  @override
  void dispose() {
    _provider?.stopPeriodicRefresh();
    super.dispose();
  }
```

- [ ] **Step 3: 验证编译通过**

Run: `cd D:\phoenix-helper\phoenix_mobile && flutter analyze lib/screens/torrent_screen.dart`

Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add phoenix_mobile/lib/screens/torrent_screen.dart
git commit -m "fix: TorrentScreen completion banner based on persistent status + periodic refresh"
```

---

### Task 5: 端到端验证

**Files:** None (testing only)

- [ ] **Step 1: 确保所有改动编译通过**

Run: `cd D:\phoenix-helper\phoenix_mobile && flutter analyze`

Expected: No errors in the modified files.

- [ ] **Step 2: 手动测试场景**

在 Android 设备/模拟器上测试以下场景：

1. **下载完成显示绿色**：导入一个 .torrent 文件，下载到 100%，确认种子列表显示绿色 check_circle 图标和"已完成"文字
2. **App 重启后保持绿色**：下载完成后重启 App，确认种子列表仍然显示绿色"已完成"
3. **暂停显示橙色**：下载到一半手动停止，确认显示橙色"已暂停"
4. **下拉刷新**：手动下拉刷新，确认状态更新
5. **自动刷新**：下载完成后不手动操作，等待 15 秒确认状态自动更新

- [ ] **Step 3: 最终 Commit（如有修复）**

如果测试中发现需要额外修复，提交修复后变更。