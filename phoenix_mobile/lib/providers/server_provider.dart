import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';

import '../config/app_config.dart';
import '../services/p2p_server.dart';
import '../services/qr_service.dart';
import '../models/device_info.dart';

class ReceivedFile {
  final String uploadId;
  final String name;
  final DateTime receivedAt;

  ReceivedFile({
    required this.uploadId,
    required this.name,
    required this.receivedAt,
  });
}

class ServerProvider extends ChangeNotifier {
  P2PServer? _server;
  bool _running = false;
  String _qrContent = '';
  List<String> _lanIPs = [];
  String _token = '';
  int _port = AppConfig.defaultPort;

  // Transfer state
  String? _currentFileName;
  double _progress = 0;
  String _speedText = '';
  final List<ReceivedFile> _receivedFiles = [];
  final List<String> _connectedDevices = [];

  // Shared files for download by connected devices
  final List<String> _sharedFiles = [];

  bool get running => _running;
  String get qrContent => _qrContent;
  List<String> get lanIPs => _lanIPs;
  String get token => _token;
  int get port => _port;
  String? get currentFileName => _currentFileName;
  double get progress => _progress;
  String get speedText => _speedText;
  List<ReceivedFile> get receivedFiles => List.unmodifiable(_receivedFiles);
  List<String> get connectedDevices => List.unmodifiable(_connectedDevices);
  List<String> get sharedFiles => List.unmodifiable(_sharedFiles);

  Future<void> startServer(int port, String deviceName) async {
    if (_running) return;

    _port = port;

    // Get receive directory
    String receiveDir;
    if (Platform.isAndroid || Platform.isIOS) {
      final dir = await getExternalStorageDirectory();
      receiveDir = '${(dir?.path ?? (await getApplicationDocumentsDirectory()).path)}${Platform.pathSeparator}received';
    } else {
      receiveDir = '${Directory.current.path}${Platform.pathSeparator}received';
    }

    _server = P2PServer(
      deviceName: deviceName,
      port: port,
      receiveDir: receiveDir,
    );

    // Wire up callbacks
    _server!.onDeviceConnected = (ip, name) {
      if (!_connectedDevices.contains(name.isNotEmpty ? name : ip)) {
        _connectedDevices.add(name.isNotEmpty ? name : ip);
        notifyListeners();
      }
    };

    _server!.onUploadProgress = (fileName, received, total, filesDone, filesTotal) {
      _currentFileName = fileName;
      if (total > 0) {
        _progress = received / total;
      }
      notifyListeners();
    };

    _server!.onFileReceived = (uploadId, fileName) {
      _receivedFiles.add(ReceivedFile(
        uploadId: uploadId,
        name: fileName,
        receivedAt: DateTime.now(),
      ));
      _currentFileName = null;
      _progress = 0;
      notifyListeners();
    };

    await _server!.start();
    _lanIPs = await _server!.getLanIPs();
    _token = _server!.fullToken;

    // Build QR content
    final qrDevice = DeviceInfo(
      version: 1,
      type: AppConfig.deviceTypePhone,
      name: deviceName,
      hosts: _lanIPs,
      port: port,
      tokenPrefix: _server!.qrToken,
    );
    _qrContent = QRService.buildQRContent(qrDevice);

    _running = true;
    notifyListeners();
  }

  void stopServer() {
    _server?.stop();
    _server = null;
    _running = false;
    _qrContent = '';
    _lanIPs = [];
    _token = '';
    _currentFileName = null;
    _progress = 0;
    _speedText = '';
    _connectedDevices.clear();
    notifyListeners();
  }

  void addSharedFiles(List<String> paths) {
    for (final p in paths) {
      if (!_sharedFiles.contains(p)) {
        _sharedFiles.add(p);
        _server?.sharedFiles.add(p);
      }
    }
    notifyListeners();
  }

  void removeSharedFile(String path) {
    _sharedFiles.remove(path);
    _server?.sharedFiles.remove(path);
    notifyListeners();
  }

  void clearSharedFiles() {
    _sharedFiles.clear();
    _server?.sharedFiles.clear();
    notifyListeners();
  }

  void clearReceivedFiles() {
    _receivedFiles.clear();
    notifyListeners();
  }

  @override
  void dispose() {
    _server?.stop();
    super.dispose();
  }
}
