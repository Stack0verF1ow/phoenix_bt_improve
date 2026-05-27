import 'package:flutter/foundation.dart';

import '../models/device_info.dart';
import '../models/server_status.dart';
import '../services/http_client.dart';

class ConnectionProvider extends ChangeNotifier {
  HttpClient? _client;
  ServerStatus? _status;
  String? _error;
  bool _connecting = false;

  HttpClient? get client => _client;
  DeviceInfo? get device => _client?.device;
  ServerStatus? get status => _status;
  String? get error => _error;
  bool get connecting => _connecting;
  bool get connected => _client != null && _client!.isRegistered;

  Future<bool> connect(DeviceInfo info) async {
    _connecting = true;
    _error = null;
    notifyListeners();

    try {
      final client = HttpClient(info);
      await client.register();
      _client = client;
      _status = await client.getStatus();
      _connecting = false;
      notifyListeners();
      return true;
    } catch (e) {
      _error = e.toString();
      _connecting = false;
      notifyListeners();
      return false;
    }
  }

  Future<void> refreshStatus() async {
    if (_client == null) return;
    try {
      _status = await _client!.getStatus();
      notifyListeners();
    } catch (e) {
      _error = e.toString();
      notifyListeners();
    }
  }

  void disconnect() {
    _client?.dispose();
    _client = null;
    _status = null;
    _error = null;
    notifyListeners();
  }

  void clearError() {
    _error = null;
    notifyListeners();
  }
}
