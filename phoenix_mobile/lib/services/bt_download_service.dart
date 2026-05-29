import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:dtorrent_parser/dtorrent_parser.dart';
import 'package:dtorrent_task_v2/dtorrent_task_v2.dart';
import 'package:flutter/foundation.dart';

import '../utils/file_logger.dart';

class BtDownloadService extends ChangeNotifier {
  static const _peerIdPrefix = '-UT3560-';

  TorrentTask? _task;
  bool _running = false;
  double _progress = 0;
  double _speed = 0;
  String? _error;
  String _currentName = '';
  Timer? _pollTimer;
  bool _completed = false;
  bool _stopping = false;

  bool get stopping => _stopping;
  List<Uri>? _trackerUrls;
  String? _infoHashHex;
  String _peerId = '';
  int _startBytes = 0;
  DateTime _startTime = DateTime.now();
  String _savePath = '';
  String? _torrentPath;

  bool get running => _running;
  double get progress => _progress;
  double get speed => _speed;
  String? get error => _error;
  String get currentName => _currentName;
  bool get completed => _completed;

  static String _makePeerId() {
    final rng = Random.secure();
    final bytes = List<int>.generate(9, (_) => rng.nextInt(256));
    return '$_peerIdPrefix${base64Encode(bytes)}';
  }

  Future<void> _sendTrackerEvent(String event) async {
    if (_trackerUrls == null || _infoHashHex == null) return;
    final client = HttpClient();
    try {
      for (final url in _trackerUrls!) {
        final uri = Uri.parse(
          '$url?info_hash=${Uri.encodeQueryComponent(_infoHashHex!)}'
          '&peer_id=$_peerId'
          '&port=0&uploaded=0&downloaded=0&left=0'
          '&compact=1&event=$event',
        );
        try {
          final req = await client.getUrl(uri);
          await req.close();
        } catch (_) {}
      }
    } finally {
      client.close(force: true);
    }
  }

  Future<void> _wipeState() async {
    if (_infoHashHex == null || _savePath.isEmpty) return;
    final stateFile = File(
        '$_savePath${Platform.pathSeparator}$_infoHashHex.bt.state');
    if (await stateFile.exists()) await stateFile.delete();
    final dataDir = Directory(
        '$_savePath${Platform.pathSeparator}$_currentName');
    if (await dataDir.exists()) await dataDir.delete(recursive: true);
  }

  Future<void> startDownload(String torrentPath, String savePath) async {
    if (_running) return;

    _torrentPath = torrentPath;
    _savePath = savePath;

    final metaInfo = await Torrent.parseFromFile(torrentPath);
    _currentName = metaInfo.name;
    _trackerUrls = metaInfo.announces.toList();
    _infoHashHex = metaInfo.infoHashBuffer
        .map((b) => b.toRadixString(16).padLeft(2, '0'))
        .join();
    _peerId = _makePeerId();

    _running = true;
    _progress = 0;
    _speed = 0;
    _error = null;
    _completed = false;
    _startBytes = 0;
    _startTime = DateTime.now();
    FileLogger.log('[BtDownload] startDownload: $_currentName, hash=$_infoHashHex');
    notifyListeners();

    try {
      _task = TorrentTask.newTask(
        metaInfo, savePath,
        false, null, null, null, _peerId,
      );

      await _task!.start();

      // If already complete (stale state), wipe and restart fresh
      if (_task!.progress >= 1.0) {
        await _task?.stop();
        await _wipeState();
        _task = TorrentTask.newTask(
          metaInfo, savePath,
          false, null, null, null, _peerId,
        );
        await _task!.start();
      }

      _pollTimer = Timer.periodic(const Duration(seconds: 1), (_) {
        if (_task == null) return;
        _progress = _task!.progress;
        final downloaded = _task!.downloaded ?? 0;
        final elapsed = DateTime.now().difference(_startTime).inMilliseconds;
        if (_progress < 0.01 && downloaded <= _startBytes) {
          _speed = 0;
        } else if (elapsed > 0) {
          _speed = (downloaded - _startBytes) / (elapsed / 1000);
        }

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
        notifyListeners();
      });
    } catch (e) {
      _running = false;
      _error = e.toString();
      notifyListeners();
    }
  }

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

  /// Called when the user explicitly deletes a torrent — wipe state + data too.
  Future<void> cleanUpAfterDelete() async {
    await _task?.stop();
    _task = null;
    _running = false;
    _completed = false;
    _progress = 0;
    _error = null;
    await _wipeState();
    notifyListeners();
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    _task?.dispose();
    super.dispose();
  }
}
