import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:dtorrent_parser/dtorrent_parser.dart';
import 'package:dtorrent_task_v2/dtorrent_task_v2.dart';
import 'package:flutter/foundation.dart';

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
  List<Uri>? _trackerUrls;
  String? _infoHashHex;
  String _peerId = '';
  int _startBytes = 0;
  DateTime _startTime = DateTime.now();

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

  Future<void> startDownload(String torrentPath, String savePath) async {
    if (_running) return;

    final metaInfo = await Torrent.parseFromFile(torrentPath);
    _currentName = metaInfo.name;
    _trackerUrls = metaInfo.announces.toList();
    _infoHashHex = metaInfo.infoHashBuffer
        .map((b) => b.toRadixString(16).padLeft(2, '0'))
        .join();
    _peerId = _makePeerId();

    final stateFile = File(
        '$savePath${Platform.pathSeparator}$_infoHashHex.bt.state');
    if (await stateFile.exists()) await stateFile.delete();
    final dataDir = Directory(
        '$savePath${Platform.pathSeparator}${metaInfo.name}');
    if (await dataDir.exists()) await dataDir.delete(recursive: true);

    _running = true;
    _progress = 0;
    _speed = 0;
    _error = null;
    _completed = false;
    _startBytes = 0;
    _startTime = DateTime.now();
    notifyListeners();

    try {
      _task = TorrentTask.newTask(
        metaInfo, savePath,
        false, null, null, null, _peerId,
      );

      await _task!.start();

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
          _completed = true;
          _running = false;
          _pollTimer?.cancel();
          _task?.stop();
          _sendTrackerEvent('stopped');
          Timer(const Duration(seconds: 4), () {
            _completed = false;
            notifyListeners();
          });
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
    _pollTimer?.cancel();
    await _task?.stop();
    _task = null;
    _running = false;
    _completed = false;
    _progress = 0;
    _error = null;
    notifyListeners();
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    _task?.dispose();
    super.dispose();
  }
}
