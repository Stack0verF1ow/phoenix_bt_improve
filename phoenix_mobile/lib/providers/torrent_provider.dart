import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:open_filex/open_filex.dart';
import 'package:path_provider/path_provider.dart';
import 'package:flutter/services.dart';

import '../models/torrent_file.dart';
import '../services/bt_download_service.dart';

class TorrentProvider extends ChangeNotifier {
  static const _channel = MethodChannel('com.phoenixhelper/file_ops');

  List<TorrentFile> _torrents = [];
  bool _loading = false;
  String? _torrentDir;
  final BtDownloadService _btService = BtDownloadService();

  List<TorrentFile> get torrents => _torrents;
  bool get loading => _loading;
  BtDownloadService get btService => _btService;

  TorrentProvider() {
    _btService.addListener(notifyListeners);
  }

  Future<String> get torrentDir async {
    if (_torrentDir != null) return _torrentDir!;
    final appDir = await getApplicationDocumentsDirectory();
    final dir = Directory('${appDir.path}${Platform.pathSeparator}torrents');
    if (!dir.existsSync()) await dir.create(recursive: true);
    _torrentDir = dir.path;
    return _torrentDir!;
  }

  Future<void> syncTorrents() async {
    _loading = true;
    notifyListeners();

    final dir = Directory(await torrentDir);
    final entries = <TorrentFile>[];
    if (dir.existsSync()) {
      for (final entity in dir.listSync()) {
        if (entity is! File || !entity.path.endsWith('.torrent')) continue;
        final stat = entity.statSync();
        entries.add(TorrentFile(
          name: entity.uri.pathSegments.last,
          path: entity.path,
          size: stat.size,
          addedAt: stat.modified,
        ));
      }
      entries.sort((a, b) => b.addedAt.compareTo(a.addedAt));
    }

    _torrents = entries;
    _loading = false;
    notifyListeners();
  }

  Future<void> importTorrent(String sourcePath) async {
    final destDir = await torrentDir;
    final name = sourcePath.split(Platform.pathSeparator).last;
    final destPath = '$destDir${Platform.pathSeparator}$name';
    await File(sourcePath).copy(destPath);
    await syncTorrents();
  }

  Future<void> deleteTorrent(TorrentFile file) async {
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
    final saveDir = await getApplicationDocumentsDirectory();
    final savePath = '${saveDir.path}${Platform.pathSeparator}bt_downloads';
    await Directory(savePath).create(recursive: true);
    await _btService.startDownload(file.path, savePath);
  }

  Future<void> stopDownload() async {
    await _btService.stopDownload();
  }
}
