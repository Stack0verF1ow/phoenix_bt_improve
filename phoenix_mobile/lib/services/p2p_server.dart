import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

/// Callback signatures.
typedef FileReceivedCallback = void Function(String uploadId, String fileName);
typedef UploadProgressCallback = void Function(
    String fileName, int received, int total, int filesDone, int filesTotal);
typedef DeviceConnectedCallback = void Function(String ip, String deviceName);

// ── Helpers ──────────────────────────────────────────────────

String _uuid() {
  final rng = Random.secure();
  final bytes = List<int>.generate(16, (_) => rng.nextInt(256));
  bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // variant 1
  String hex(int b) => b.toRadixString(16).padLeft(2, '0');
  final s = bytes.map(hex).join();
  return '${s.substring(0, 8)}-${s.substring(8, 12)}-'
      '${s.substring(12, 16)}-${s.substring(16, 20)}-${s.substring(20)}';
}

String _generateToken(int byteLength) {
  final rng = Random.secure();
  return List<int>.generate(byteLength, (_) => rng.nextInt(256))
      .map((b) => b.toRadixString(16).padLeft(2, '0'))
      .join();
}

// ── Rate Limiter ──────────────────────────────────────────────

class _RateLimiter {
  static const _window = Duration(seconds: 60);
  static const _maxRequests = 60;

  final _buckets = <String, List<DateTime>>{};

  bool allow(String ip) {
    final now = DateTime.now();
    final cutoff = now.subtract(_window);
    final hits = _buckets.putIfAbsent(ip, () => []);
    hits.removeWhere((t) => t.isBefore(cutoff));
    if (hits.length >= _maxRequests) return false;
    hits.add(now);
    return true;
  }
}

// ── Session ───────────────────────────────────────────────────

class _Session {
  final String id;
  final String peerIp;
  final Map<String, Map<String, dynamic>> files = {};
  final List<String> fileIds = [];
  final Map<String, String> fileTokens = {};
  final Map<String, List<int>> received = {};
  String seedStatus = 'idle';
  final DateTime createdAt;

  _Session(this.id, this.peerIp) : createdAt = DateTime.now();

  bool get isExpired =>
      DateTime.now().difference(createdAt).inSeconds > 600;
}

// ── Session Manager ───────────────────────────────────────────

class _SessionManager {
  final _sessions = <String, _Session>{};
  Timer? _cleanup;

  _SessionManager() {
    _cleanup = Timer.periodic(const Duration(seconds: 60), (_) {
      _sessions.removeWhere((_, s) => s.isExpired);
    });
  }

  _Session create(String peerIp) {
    final id = _uuid();
    final session = _Session(id, peerIp);
    _sessions[id] = session;
    return session;
  }

  _Session? get(String id) {
    final s = _sessions[id];
    if (s != null && s.isExpired) {
      _sessions.remove(id);
      return null;
    }
    return s;
  }

  void remove(String id) => _sessions.remove(id);

  void dispose() {
    _cleanup?.cancel();
    _sessions.clear();
  }
}

// ── Device Registry ───────────────────────────────────────────

class _ConnectedDevice {
  final String ip;
  String name;
  final DateTime connectedAt;
  DateTime lastSeen;

  _ConnectedDevice(this.ip, this.name)
      : connectedAt = DateTime.now(),
        lastSeen = DateTime.now();
}

class _DeviceRegistry {
  final _devices = <String, _ConnectedDevice>{};

  void register(String ip, String name) {
    final existing = _devices[ip];
    if (existing != null) {
      existing.lastSeen = DateTime.now();
      if (name.isNotEmpty) existing.name = name;
    } else {
      _devices[ip] = _ConnectedDevice(ip, name);
    }
  }

  void unregister(String ip) => _devices.remove(ip);

  List<Map<String, dynamic>> listDevices() {
    final cutoff = DateTime.now().subtract(const Duration(seconds: 60));
    _devices.removeWhere((_, d) => d.lastSeen.isBefore(cutoff));
    return _devices.values
        .map((d) => {
              'ip': d.ip,
              'name': d.name.isNotEmpty ? d.name : d.ip,
              'connected_at': d.connectedAt.millisecondsSinceEpoch ~/ 1000,
            })
        .toList();
  }
}

// ── P2P Server ────────────────────────────────────────────────

class P2PServer {
  final String deviceName;
  final int port;
  final String receiveDir;

  FileReceivedCallback? onFileReceived;
  UploadProgressCallback? onUploadProgress;
  DeviceConnectedCallback? onDeviceConnected;

  HttpServer? _server;
  late final String _fullToken;
  late final String _qrToken;
  late final _RateLimiter _limiter;
  late final _SessionManager _sessions;
  late final _DeviceRegistry _devices;
  final List<String> sharedFiles = [];

  P2PServer({
    required this.deviceName,
    required this.port,
    required this.receiveDir,
  });

  bool get isRunning => _server != null;
  String get fullToken => _fullToken;
  String get qrToken => _qrToken;

  Future<void> start() async {
    // Generate 64-char hex token
    final rng = Random.secure();
    final bytes = List<int>.generate(32, (_) => rng.nextInt(256));
    _fullToken = bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join();
    _qrToken = _fullToken.substring(0, 6);

    _limiter = _RateLimiter();
    _sessions = _SessionManager();
    _devices = _DeviceRegistry();

    // Ensure receive directory exists
    final dir = Directory(receiveDir);
    if (!dir.existsSync()) await dir.create(recursive: true);

    _server = await HttpServer.bind(InternetAddress.anyIPv4, port);
    _server!.listen(_handleRequest);
  }

  void stop() {
    _server?.close();
    _server = null;
    _sessions.dispose();
  }

  Future<List<String>> getLanIPs() async {
    try {
      final interfaces = await NetworkInterface.list();
      final ips = <String>[];
      for (final iface in interfaces) {
        for (final addr in iface.addresses) {
          if (addr.type == InternetAddressType.IPv4 &&
              !addr.isLoopback &&
              !addr.address.startsWith('169.254.')) {
            ips.add(addr.address);
          }
        }
      }
      return ips;
    } catch (_) {
      return ['127.0.0.1'];
    }
  }

  // ── Request handling ──────────────────────────────────────

  Future<void> _handleRequest(HttpRequest request) async {
    // CORS headers
    request.response.headers.set('Access-Control-Allow-Origin', '*');
    request.response.headers.set(
        'Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    request.response.headers.set(
        'Access-Control-Allow-Headers', 'Content-Type, X-Device-Token');

    if (request.method == 'OPTIONS') {
      request.response.statusCode = 204;
      await request.response.close();
      return;
    }

    final path = request.uri.path;

    try {
      if (request.method == 'GET') {
        if (path == '/api/ping') return _handlePing(request);
        if (path == '/api/status') return _handleStatus(request);
        if (path == '/api/devices') return _handleListDevices(request);
        if (path == '/api/files') return _handleListFiles(request);
        if (path.startsWith('/api/files/download')) {
          return _handleDownload(request);
        }
      } else if (request.method == 'POST') {
        if (path == '/api/register') return _handleRegister(request);
        if (path == '/api/prepare-upload') {
          return _handlePrepareUpload(request);
        }
        if (path == '/api/upload') return _handleUpload(request);
        if (path == '/api/confirm-seed') return _handleConfirmSeed(request);
        if (path == '/api/disconnect') return _handleDisconnect(request);
      }
      _sendError(request, 404, 'Not found');
    } catch (e) {
      _sendError(request, 500, 'Internal error: $e');
    }
  }

  // ── Helpers ───────────────────────────────────────────────

  String get _clientIp => 'unknown'; // overridden per-request below

  void _sendJson(HttpRequest request, int status, Map<String, dynamic> data) {
    request.response
      ..statusCode = status
      ..headers.set('Content-Type', 'application/json')
      ..write(jsonEncode(data));
    request.response.close();
  }

  void _sendError(HttpRequest request, int status, String msg) {
    _sendJson(request, status, {'status': 'error', 'message': msg});
  }

  bool _checkRate(HttpRequest request) {
    final ip = request.connectionInfo?.remoteAddress.address ?? 'unknown';
    if (!_limiter.allow(ip)) {
      _sendError(request, 429, 'Too many requests');
      return false;
    }
    return true;
  }

  bool _checkAuth(HttpRequest request) {
    final token = request.headers.value('X-Device-Token') ?? '';
    if (token == _fullToken || token == _qrToken) return true;
    _sendError(request, 403, 'Invalid or missing X-Device-Token');
    return false;
  }

  bool _checkAuthAndRate(HttpRequest request) {
    return _checkRate(request) && _checkAuth(request);
  }

  Future<Map<String, dynamic>> _readBody(HttpRequest request) async {
    final body = await utf8.decoder.bind(request).join();
    return jsonDecode(body) as Map<String, dynamic>;
  }

  Future<List<int>> _readBodyBytes(HttpRequest request) async {
    final completer = Completer<List<int>>();
    final chunks = <int>[];
    request.listen(
      chunks.addAll,
      onDone: () => completer.complete(chunks),
      onError: (e) => completer.completeError(e),
    );
    return completer.future;
  }

  // ── Endpoints ─────────────────────────────────────────────

  void _handlePing(HttpRequest request) {
    _sendJson(request, 200, {'status': 'ok'});
  }

  void _handleRegister(HttpRequest request) async {
    if (!_checkRate(request)) return;
    final data = await _readBody(request);
    if (data['token'] != _qrToken) {
      _sendError(request, 403, 'Invalid token');
      return;
    }
    final ip = request.connectionInfo?.remoteAddress.address ?? 'unknown';
    final name = data['device_name'] as String? ?? '';
    _devices.register(ip, name);
    onDeviceConnected?.call(ip, name);
    _sendJson(request, 200, {
      'status': 'ok',
      'session': _fullToken,
      'device_name': deviceName,
    });
  }

  void _handleStatus(HttpRequest request) {
    if (!_checkAuthAndRate(request)) return;
    _sendJson(request, 200, {
      'name': deviceName,
      'version': '0.2.0',
      'protocol_version': 1,
      'utorrent_available': false,
      'phoenix_logged_in': false,
      'files_available': sharedFiles.length,
      'max_upload_size': 10 * 1024 * 1024 * 1024,
      'device_type': 'phone',
      'can_auto_seed': false,
    });
  }

  void _handlePrepareUpload(HttpRequest request) async {
    if (!_checkAuthAndRate(request)) return;
    final data = await _readBody(request);
    final files = data['files'] as Map<String, dynamic>? ?? {};
    final ip = request.connectionInfo?.remoteAddress.address ?? 'unknown';
    final session = _sessions.create(ip);

    for (final entry in files.entries) {
      final fid = entry.key;
      final info = entry.value as Map<String, dynamic>;
      session.files[fid] = info;
      session.fileIds.add(fid);
      session.fileTokens[fid] = _generateToken(6);
    }

    _sendJson(request, 200, {
      'sessionId': session.id,
      'fileTokens': session.fileTokens,
      'expires_in': 600,
    });
  }

  void _handleUpload(HttpRequest request) async {
    if (!_checkAuthAndRate(request)) return;
    final sid = request.uri.queryParameters['sessionId'] ?? '';
    final fid = request.uri.queryParameters['fileId'] ?? '';
    final token = request.uri.queryParameters['token'] ?? '';

    final session = _sessions.get(sid);
    if (session == null) {
      _sendError(request, 404, 'Session not found');
      return;
    }
    if (!session.fileTokens.containsKey(fid)) {
      _sendError(request, 404, 'File not found in session');
      return;
    }
    if (session.fileTokens[fid] != token) {
      _sendError(request, 403, 'Invalid file token');
      return;
    }

    final fileInfo = session.files[fid] ?? {};
    final totalSize = fileInfo['size'] as int? ?? 0;
    final fileName = fileInfo['name'] as String? ?? 'unknown';
    final filesDone = session.received.length;
    final filesTotal = session.files.length;

    // Read body in chunks with progress
    final chunks = <int>[];
    int received = 0;
    await for (final chunk in request) {
      chunks.addAll(chunk);
      received += chunk.length;
      onUploadProgress?.call(fileName, received, totalSize, filesDone, filesTotal);
    }

    session.received[fid] = chunks;

    _sendJson(request, 200, {
      'status': 'received',
      'fileId': fid,
      'name': fileName,
      'size': received,
    });
  }

  void _handleConfirmSeed(HttpRequest request) async {
    if (!_checkAuthAndRate(request)) return;
    final data = await _readBody(request);
    final sid = data['sessionId'] as String? ?? '';
    final session = _sessions.get(sid);
    if (session == null) {
      _sendError(request, 404, 'Session not found');
      return;
    }

    final uploads = <Map<String, dynamic>>[];
    final dir = Directory(receiveDir);

    for (final fid in session.fileIds) {
      final fileData = session.received[fid];
      if (fileData == null) continue;

      final fileInfo = session.files[fid] ?? {};
      final originalName = fileInfo['name'] as String? ?? 'file';

      // Save to disk with unique name
      final savePath = _uniquePath(dir, originalName);
      await File(savePath).writeAsBytes(fileData);

      final uploadId = _uuid();
      uploads.add({
        'uploadId': uploadId,
        'name': originalName,
        'size': fileData.length,
      });

      onFileReceived?.call(uploadId, originalName);
    }

    _sessions.remove(sid);

    _sendJson(request, 200, {
      'status': 'idle',
      'uploads': uploads,
    });
  }

  void _handleListDevices(HttpRequest request) {
    _sendJson(request, 200, {
      'devices': _devices.listDevices(),
      'count': _devices.listDevices().length,
    });
  }

  void _handleListFiles(HttpRequest request) {
    if (!_checkAuthAndRate(request)) return;
    final entries = <Map<String, dynamic>>[];
    for (final path in sharedFiles) {
      final file = File(path);
      if (file.existsSync()) {
        final stat = file.statSync();
        entries.add({
          'path': path,
          'name': path.split(Platform.pathSeparator).last,
          'type': 'file',
          'size': stat.size,
          'mtime': stat.modified.millisecondsSinceEpoch / 1000,
        });
      }
    }
    entries.sort((a, b) =>
        (a['name'] as String).toLowerCase().compareTo((b['name'] as String).toLowerCase()));
    _sendJson(request, 200, {'entries': entries});
  }

  void _handleDownload(HttpRequest request) async {
    if (!_checkAuthAndRate(request)) return;
    final path = request.uri.queryParameters['path'] ?? '';
    if (!sharedFiles.contains(path)) {
      _sendError(request, 403, 'File not in shared list');
      return;
    }
    final file = File(path);
    if (!file.existsSync()) {
      _sendError(request, 404, 'File not found');
      return;
    }

    final fileName = path.split(Platform.pathSeparator).last;
    final fileSize = file.lengthSync();
    request.response
      ..statusCode = 200
      ..headers.set('Content-Type', 'application/octet-stream')
      ..headers.set('Content-Length', fileSize.toString())
      ..headers.set('Content-Disposition', 'attachment; filename="$fileName"');

    int sent = 0;
    final stream = file.openRead();
    await for (final chunk in stream) {
      request.response.add(chunk);
      sent += chunk.length;
    }
    await request.response.close();
  }

  void _handleDisconnect(HttpRequest request) async {
    final ip = request.connectionInfo?.remoteAddress.address ?? 'unknown';
    _devices.unregister(ip);
    _sendJson(request, 200, {'status': 'disconnected'});
  }

  // ── Utilities ─────────────────────────────────────────────

  static String _uniquePath(Directory dir, String name) {
    final dot = name.lastIndexOf('.');
    final base = dot > 0 ? name.substring(0, dot) : name;
    final ext = dot > 0 ? name.substring(dot) : '';
    var candidate = '${dir.path}${Platform.pathSeparator}$name';
    var counter = 1;
    while (File(candidate).existsSync()) {
      candidate = '${dir.path}${Platform.pathSeparator}${base}_$counter$ext';
      counter++;
    }
    return candidate;
  }
}
