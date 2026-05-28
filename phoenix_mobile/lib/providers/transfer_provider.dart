import 'package:flutter/foundation.dart';

import '../models/server_status.dart';

enum TransferState { idle, preparing, uploading, confirming, done, error }

class TransferProvider extends ChangeNotifier {
  // Upload
  TransferState _state = TransferState.idle;
  double _progress = 0;
  String? _error;
  String _statusText = '';
  String _speedText = '';
  DateTime? _transferStart;
  int _lastBytes = 0;
  DateTime? _lastSpeedUpdate;

  // Download
  TransferState _downloadState = TransferState.idle;
  double _downloadProgress = 0;
  String? _downloadError;
  String _downloadSpeedText = '';
  DateTime? _downloadStart;
  int _downloadLastBytes = 0;
  DateTime? _downloadLastSpeedUpdate;

  // Files
  List<FileEntry> _files = [];
  bool _loadingFiles = false;

  // Upload
  TransferState get state => _state;
  double get progress => _progress;
  String? get error => _error;
  String get statusText => _statusText;
  String get speedText => _speedText;

  // Download
  TransferState get downloadState => _downloadState;
  double get downloadProgress => _downloadProgress;
  String? get downloadError => _downloadError;
  String get downloadSpeedText => _downloadSpeedText;

  // Files
  List<FileEntry> get files => _files;
  bool get loadingFiles => _loadingFiles;

  void setProgress(double value) {
    _progress = value;
    notifyListeners();
  }

  void setStatus(String text) {
    _statusText = text;
    notifyListeners();
  }

  void updateUploadSpeed(int sentBytes, int totalBytes) {
    final now = DateTime.now();
    if (_transferStart == null) {
      _transferStart = now;
      _lastBytes = sentBytes;
      _lastSpeedUpdate = now;
      return;
    }
    final elapsed = now.difference(_lastSpeedUpdate!).inMilliseconds;
    if (elapsed < 500) return; // update every 500ms max
    final bytesDelta = sentBytes - _lastBytes;
    final speed = bytesDelta / (elapsed / 1000); // bytes per second
    _speedText = _formatSpeed(speed);
    _lastBytes = sentBytes;
    _lastSpeedUpdate = now;
    notifyListeners();
  }

  void updateDownloadSpeed(int receivedBytes, int totalBytes) {
    final now = DateTime.now();
    if (_downloadStart == null) {
      _downloadStart = now;
      _downloadLastBytes = receivedBytes;
      _downloadLastSpeedUpdate = now;
      return;
    }
    final elapsed = now.difference(_downloadLastSpeedUpdate!).inMilliseconds;
    if (elapsed < 500) return;
    final bytesDelta = receivedBytes - _downloadLastBytes;
    final speed = bytesDelta / (elapsed / 1000);
    _downloadSpeedText = _formatSpeed(speed);
    _downloadLastBytes = receivedBytes;
    _downloadLastSpeedUpdate = now;
    notifyListeners();
  }

  static String _formatSpeed(double bytesPerSec) {
    if (bytesPerSec < 1024) return '${bytesPerSec.toStringAsFixed(0)} B/s';
    if (bytesPerSec < 1024 * 1024) return '${(bytesPerSec / 1024).toStringAsFixed(1)} KB/s';
    return '${(bytesPerSec / (1024 * 1024)).toStringAsFixed(1)} MB/s';
  }

  void setState(TransferState newState) {
    _state = newState;
    if (newState == TransferState.idle) {
      _progress = 0;
      _error = null;
      _speedText = '';
      _transferStart = null;
    }
    if (newState == TransferState.uploading) {
      _transferStart = null;
      _speedText = '';
    }
    notifyListeners();
  }

  void setError(String msg) {
    _error = msg;
    _state = TransferState.error;
    _speedText = '';
    notifyListeners();
  }

  void clearUploadError() {
    _error = null;
    if (_state == TransferState.error) {
      _state = TransferState.idle;
    }
    notifyListeners();
  }

  void setDownloadProgress(double value) {
    _downloadProgress = value;
    notifyListeners();
  }

  void setDownloadState(TransferState newState) {
    _downloadState = newState;
    if (newState == TransferState.done) {
      _downloadProgress = 1.0;
      _downloadSpeedText = '';
    }
    if (newState == TransferState.idle) {
      _downloadProgress = 0;
      _downloadError = null;
      _downloadSpeedText = '';
      _downloadStart = null;
    }
    if (newState == TransferState.uploading) {
      _downloadStart = null;
      _downloadSpeedText = '';
    }
    notifyListeners();
  }

  void setDownloadError(String msg) {
    _downloadError = msg;
    _downloadState = TransferState.error;
    _downloadSpeedText = '';
    notifyListeners();
  }

  void clearDownloadError() {
    _downloadError = null;
    if (_downloadState == TransferState.error) {
      _downloadState = TransferState.idle;
    }
    notifyListeners();
  }

  void setFiles(List<FileEntry> files) {
    _files = files;
    _loadingFiles = false;
    notifyListeners();
  }

  void setLoadingFiles(bool loading) {
    _loadingFiles = loading;
    notifyListeners();
  }

  void reset() {
    _state = TransferState.idle;
    _progress = 0;
    _error = null;
    _statusText = '';
    _speedText = '';
    _transferStart = null;
    _downloadState = TransferState.idle;
    _downloadProgress = 0;
    _downloadError = null;
    _downloadSpeedText = '';
    _downloadStart = null;
    _files = [];
    _loadingFiles = false;
    notifyListeners();
  }
}
