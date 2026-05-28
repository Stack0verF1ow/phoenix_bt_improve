import 'dart:async';

import 'package:flutter/foundation.dart';

import '../models/device_info.dart';
import '../models/server_status.dart';
import '../services/http_client.dart';

class ConnectionProvider extends ChangeNotifier {
  HttpClient? _client;
  ServerStatus? _status;
  String? _error;
  bool _connecting = false;
  bool _serverLost = false;
  bool _transferring = false;
  int _consecutiveFailures = 0;
  static const _maxFailures = 3;
  Timer? _heartbeat;

  HttpClient? get client => _client;
  DeviceInfo? get device => _client?.device;
  ServerStatus? get status => _status;
  String? get error => _error;
  bool get connecting => _connecting;
  bool get connected => _client != null && _client!.isRegistered;
  bool get serverLost => _serverLost;

  /// Call before starting upload/download to suppress heartbeat disconnect.
  void setTransferring(bool value) {
    _transferring = value;
    if (value) {
      _consecutiveFailures = 0;
    }
  }

  Future<bool> connect(DeviceInfo info, {String localName = ''}) async {
    _connecting = true;
    _error = null;
    _serverLost = false;
    _consecutiveFailures = 0;
    notifyListeners();

    try {
      final client = HttpClient(info);
      await client.register(localName: localName);
      _client = client;
      _status = await client.getStatus();
      _connecting = false;
      _startHeartbeat();
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
      _serverLost = false;
      _consecutiveFailures = 0;
      notifyListeners();
    } catch (e) {
      _error = e.toString();
      notifyListeners();
    }
  }

  void _startHeartbeat() {
    _heartbeat?.cancel();
    _heartbeat = Timer.periodic(const Duration(seconds: 2), (_) async {
      if (_client == null || _transferring) return;
      try {
        await _client!.getStatus();
        _consecutiveFailures = 0;
        if (_serverLost) {
          _serverLost = false;
          notifyListeners();
        }
      } catch (_) {
        _consecutiveFailures++;
        if (_consecutiveFailures >= _maxFailures && !_serverLost) {
          _serverLost = true;
          notifyListeners();
        }
      }
    });
  }

  Future<void> disconnect() async {
    _heartbeat?.cancel();
    _heartbeat = null;
    // Notify server before disposing client
    if (_client != null && _client!.isRegistered) {
      await _client!.disconnect();
    }
    _client?.dispose();
    _client = null;
    _status = null;
    _error = null;
    _serverLost = false;
    _consecutiveFailures = 0;
    _transferring = false;
    notifyListeners();
  }

  /// Called by UI when PC stops or user leaves page — immediate disconnect.
  void notifyServerGone() {
    _serverLost = true;
    notifyListeners();
  }

  void clearError() {
    _error = null;
    notifyListeners();
  }

  void clearServerLost() {
    _serverLost = false;
    _consecutiveFailures = 0;
    notifyListeners();
  }

  @override
  void dispose() {
    _heartbeat?.cancel();
    super.dispose();
  }
}
