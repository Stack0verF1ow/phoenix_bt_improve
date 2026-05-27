import 'package:flutter/foundation.dart';

import '../models/server_status.dart';

enum TransferState { idle, preparing, uploading, confirming, done, error }

class TransferProvider extends ChangeNotifier {
  // Upload
  TransferState _state = TransferState.idle;
  double _progress = 0;
  String? _error;
  String _statusText = '';

  // Download
  TransferState _downloadState = TransferState.idle;
  double _downloadProgress = 0;
  String? _downloadError;

  // Files
  List<FileEntry> _files = [];
  bool _loadingFiles = false;

  // Upload
  TransferState get state => _state;
  double get progress => _progress;
  String? get error => _error;
  String get statusText => _statusText;

  // Download
  TransferState get downloadState => _downloadState;
  double get downloadProgress => _downloadProgress;
  String? get downloadError => _downloadError;

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

  void setState(TransferState newState) {
    _state = newState;
    if (newState == TransferState.idle) {
      _progress = 0;
      _error = null;
    }
    notifyListeners();
  }

  void setError(String msg) {
    _error = msg;
    _state = TransferState.error;
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
    }
    if (newState == TransferState.idle) {
      _downloadProgress = 0;
      _downloadError = null;
    }
    notifyListeners();
  }

  void setDownloadError(String msg) {
    _downloadError = msg;
    _downloadState = TransferState.error;
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
    _downloadState = TransferState.idle;
    _downloadProgress = 0;
    _downloadError = null;
    _files = [];
    _loadingFiles = false;
    notifyListeners();
  }
}
