import 'dart:async';
import 'dart:io';

import 'package:dtorrent_parser/dtorrent_parser.dart' hide TorrentFile;
import 'package:flutter/foundation.dart';
import 'package:open_filex/open_filex.dart';
import 'package:path_provider/path_provider.dart';
import 'package:flutter/services.dart';

import '../models/torrent_file.dart';
import '../services/bt_download_service.dart';
import '../utils/file_logger.dart';

class TorrentProvider extends ChangeNotifier {
  static const _channel = MethodChannel('com.phoenixhelper/file_ops');

  List<TorrentFile> _torrents = [];
  bool _loading = false;
  String? _torrentDir;
  final BtDownloadService _btService = BtDownloadService();
  final Set<String> _selectedTorrents = {};
  bool _btSelectMode = false;
  bool _syncInProgress = false;
  Timer? _refreshTimer;

  List<TorrentFile> get torrents => _torrents;
  bool get loading => _loading;
  BtDownloadService get btService => _btService;
  bool get btSelectMode => _btSelectMode;
  Set<String> get selectedTorrents => _selectedTorrents;

  TorrentProvider() {
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
  }

  void _scheduleSync(Duration delay) {
    Future.delayed(delay, () {
      if (!_syncInProgress) {
        syncTorrents();
      }
    });
  }

  Future<String> get torrentDir async {
    if (_torrentDir != null) return _torrentDir!;
    final appDir = await getApplicationDocumentsDirectory();
    final dir = Directory('${appDir.path}${Platform.pathSeparator}torrents');
    if (!dir.existsSync()) await dir.create(recursive: true);
    _torrentDir = dir.path;
    return _torrentDir!;
  }

  Future<String> _btSavePath() async {
    final appDir = await getApplicationDocumentsDirectory();
    return '${appDir.path}${Platform.pathSeparator}bt_downloads';
  }

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

  void toggleBtSelectMode() {
    _btSelectMode = !_btSelectMode;
    if (!_btSelectMode) _selectedTorrents.clear();
    notifyListeners();
  }

  void toggleBtSelection(String path) {
    if (_selectedTorrents.contains(path)) {
      _selectedTorrents.remove(path);
    } else {
      _selectedTorrents.add(path);
    }
    notifyListeners();
  }

  void setAllTorrentsSelected(bool selected) {
    if (selected) {
      for (final t in _torrents) {
        _selectedTorrents.add(t.path);
      }
    } else {
      _selectedTorrents.clear();
    }
    notifyListeners();
  }

  Future<void> deleteSelectedTorrents() async {
    for (final path in _selectedTorrents) {
      try { await File(path).delete(); } catch (_) {}
    }
    _selectedTorrents.clear();
    _btSelectMode = false;
    notifyListeners();
    await _btService.cleanUpAfterDelete();
    await syncTorrents();
  }

  Future<void> importTorrent(String sourcePath) async {
    final destDir = await torrentDir;
    final name = sourcePath.split(Platform.pathSeparator).last;
    final destPath = '$destDir${Platform.pathSeparator}$name';
    await File(sourcePath).copy(destPath);
    await syncTorrents();
  }

  Future<void> deleteTorrent(TorrentFile file) async {
    await _btService.cleanUpAfterDelete();
    // Wipe .bt.state and downloaded data for this torrent
    try {
      final meta = await Torrent.parseFromFile(file.path);
      final hex = meta.infoHashBuffer
          .map((b) => b.toRadixString(16).padLeft(2, '0'))
          .join();
      final savePath = await _btSavePath();
      final stateFile = File('$savePath${Platform.pathSeparator}$hex.bt.state');
      if (await stateFile.exists()) await stateFile.delete();
      final dataDir = Directory('$savePath${Platform.pathSeparator}${meta.name}');
      if (await dataDir.exists()) await dataDir.delete(recursive: true);
    } catch (_) {}
    await File(file.path).delete();
    await syncTorrents();
  }

  void openTorrent(TorrentFile file) {
    _channel.invokeMethod('openFileWithMime', {
      'path': file.path,
      'mime': 'application/x-bittorrent',
    }).catchError((_) {
      OpenFilex.open(file.path, type: 'application/x-bittorrent');
    });
  }

  Future<void> startDownload(TorrentFile file) async {
    final savePath = await _btSavePath();
    await Directory(savePath).create(recursive: true);
    await _btService.startDownload(file.path, savePath);
  }

  Future<void> stopDownload() async {
    await _btService.stopDownload();
  }

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
    _btService.dispose();
    super.dispose();
  }
}
