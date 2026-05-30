import 'dart:async';
import 'dart:io' as io;
import 'dart:math' show min;
import 'dart:typed_data';

import 'package:dio/dio.dart';

import '../models/device_info.dart';
import '../models/server_status.dart';
import '../models/upload_session.dart';
import '../utils/file_logger.dart';

class ApiException implements Exception {
  final int statusCode;
  final String message;
  ApiException(this.statusCode, this.message);

  @override
  String toString() => 'ApiException($statusCode): $message';
}

class HttpClient {
  CancelToken? _downloadCancelToken;
  io.HttpClient? _nativeDownloadClient;
  bool _downloadPaused = false;

  bool get isDownloadPaused => _downloadPaused;

  void pauseDownload() {
    _downloadPaused = true;
  }

  void resumeDownload() {
    _downloadPaused = false;
  }
  CancelToken? _uploadCancelToken;
  final DeviceInfo _device;
  final Dio _dio;
  bool _registered = false;

  HttpClient(this._device)
      : _dio = Dio(BaseOptions(
          baseUrl: _device.baseUrl,
          connectTimeout: const Duration(seconds: 5),
          receiveTimeout: const Duration(seconds: 10),
          sendTimeout: const Duration(seconds: 30),
        ));

  DeviceInfo get device => _device;
  bool get isRegistered => _registered;

  void _setToken(String token) {
    _dio.options.headers['X-Device-Token'] = token;
  }

  Future<void> register({String localName = ''}) async {
    final resp = await _dio.post(
      '/api/register',
      data: {'token': _device.tokenPrefix, 'device_name': localName},
      options: Options(contentType: Headers.jsonContentType),
    );
    if (resp.statusCode! != 200) {
      throw ApiException(resp.statusCode!, 'Register failed');
    }
    final data = resp.data as Map<String, dynamic>;
    final token = data['session'] as String?;
    if (token == null || token.isEmpty) {
      throw ApiException(0, 'No session token returned');
    }
    _setToken(token);
    _registered = true;
  }

  Future<ServerStatus> getStatus() async {
    final resp = await _dio.get('/api/status');
    if (resp.statusCode! != 200) {
      throw ApiException(resp.statusCode!, 'Status request failed');
    }
    return ServerStatus.fromJson(resp.data as Map<String, dynamic>);
  }

  Future<UploadSession> prepareUpload(
    Map<String, Map<String, dynamic>> files, {
    int chunkSize = 4 * 1024 * 1024,
  }) async {
    final filesWithChunkSize = files.map((key, value) {
      final updated = Map<String, dynamic>.from(value);
      updated['chunkSize'] = chunkSize;
      return MapEntry(key, updated);
    });

    final resp = await _dio.post(
      '/api/prepare-upload',
      data: {'files': filesWithChunkSize},
      options: Options(
        contentType: Headers.jsonContentType,
        validateStatus: (s) => s != null && s < 500,
      ),
    );
    if (resp.statusCode != null && resp.statusCode! >= 400) {
      final msg = _extractErrorMessage(resp.data);
      throw ApiException(resp.statusCode!, msg);
    }
    return UploadSession.fromJson(resp.data as Map<String, dynamic>);
  }

  Future<void> uploadFile({
    required String sessionId,
    required String fileId,
    required String token,
    required List<int> bytes,
    void Function(int sent, int total)? onProgress,
  }) async {
    _uploadCancelToken = CancelToken();
    final resp = await _dio.post(
      '/api/upload',
      queryParameters: {
        'sessionId': sessionId,
        'fileId': fileId,
        'token': token,
      },
      data: Uint8List.fromList(bytes),
      options: Options(
        contentType: 'application/octet-stream',
        receiveTimeout: const Duration(minutes: 5),
        sendTimeout: const Duration(minutes: 5),
        validateStatus: (s) => s != null && s < 500,
      ),
      onSendProgress: onProgress,
      cancelToken: _uploadCancelToken,
    );
    if (resp.statusCode != null && resp.statusCode! >= 400) {
      final msg = _extractErrorMessage(resp.data);
      throw ApiException(resp.statusCode!, msg);
    }
  }

  Future<UploadStatus> getUploadStatus({
    required String sessionId,
    String? fileId,
    String? token,
  }) async {
    final queryParams = <String, String>{};
    if (fileId != null) queryParams['fileId'] = fileId;
    if (token != null) queryParams['token'] = token;

    final resp = await _dio.get(
      '/api/upload/$sessionId',
      queryParameters: queryParams.isEmpty ? null : queryParams,
      options: Options(validateStatus: (s) => s != null && s < 500),
    );
    if (resp.statusCode != null && resp.statusCode! >= 400) {
      final msg = _extractErrorMessage(resp.data);
      throw ApiException(resp.statusCode!, msg);
    }
    return UploadStatus.fromJson(resp.data as Map<String, dynamic>);
  }

  Future<void> uploadFileChunked({
    required String sessionId,
    required String fileId,
    required String token,
    required String filePath,
    required int fileSize,
    required int chunkSize,
    int maxRetries = 3,
    void Function(int sent, int total)? onProgress,
    void Function(int chunkIndex, int totalChunks)? onChunkComplete,
    bool Function()? shouldPause,
  }) async {
    final file = io.File(filePath);
    if (!await file.exists()) {
      throw ApiException(0, 'File not found: $filePath');
    }

    final totalChunks = (fileSize + chunkSize - 1) ~/ chunkSize;

    Set<int> completedChunks = {};
    try {
      final status = await getUploadStatus(
        sessionId: sessionId,
        fileId: fileId,
        token: token,
      );
      if (status.fileChunks != null && status.fileChunks!.containsKey(fileId)) {
        completedChunks = status.fileChunks![fileId]!.chunksReceived.toSet();
      }
    } catch (_) {}

    if (onProgress != null) {
      onProgress(completedChunks.length * chunkSize, fileSize);
    }

    for (var chunkIndex = 0; chunkIndex < totalChunks; chunkIndex++) {
      if (completedChunks.contains(chunkIndex)) continue;

      while (shouldPause != null && shouldPause()) {
        await Future.delayed(const Duration(milliseconds: 200));
      }

      final offset = chunkIndex * chunkSize;
      final length = min(chunkSize, fileSize - offset);

      final raf = await file.open();
      await raf.setPosition(offset);
      final bytes = await raf.read(length);
      await raf.close();

      for (var attempt = 0; attempt < maxRetries; attempt++) {
        // Check pause between retry attempts
        while (shouldPause != null && shouldPause()) {
          await Future.delayed(const Duration(milliseconds: 200));
        }

        try {
          _uploadCancelToken = CancelToken();
          final resp = await _dio.post(
            '/api/upload',
            queryParameters: {
              'sessionId': sessionId,
              'fileId': fileId,
              'token': token,
              'chunkIndex': chunkIndex.toString(),
            },
            data: Uint8List.fromList(bytes),
            options: Options(
              contentType: 'application/octet-stream',
              receiveTimeout: const Duration(minutes: 2),
              sendTimeout: const Duration(minutes: 2),
              validateStatus: (s) => s != null && s < 500,
            ),
            cancelToken: _uploadCancelToken,
          );

          final statusCode = resp.statusCode ?? 0;
          if (statusCode == 200 || statusCode == 409) {
            completedChunks.add(chunkIndex);
            if (onProgress != null) {
              final sent = completedChunks.length * chunkSize;
              onProgress(sent > fileSize ? fileSize : sent, fileSize);
            }
            if (onChunkComplete != null) {
              onChunkComplete(chunkIndex, totalChunks);
            }
            break;
          } else if (statusCode == 400) {
            final msg = _extractErrorMessage(resp.data);
            if (msg.contains('CRC') || msg.contains('checksum')) {
              if (attempt < maxRetries - 1) continue;
              throw ApiException(statusCode, 'CRC mismatch after $maxRetries retries');
            }
            throw ApiException(statusCode, msg);
          } else {
            throw ApiException(statusCode, 'Upload chunk $chunkIndex failed (status $statusCode)');
          }
        } on DioException catch (e) {
          if (e.type == DioExceptionType.cancel) rethrow;
          final respMsg = _extractErrorMessageFromDioException(e);
          if (attempt < maxRetries - 1) continue;
          throw ApiException(e.response?.statusCode ?? 0, respMsg);
        }
      }
    }
  }

  Future<UploadConfirmResult> confirmSeed({
    required String sessionId,
    required bool autoSeed,
    String title = '',
    String category = '',
    String description = '',
    List<String> tags = const [],
    Map<String, String>? fileHashes,
  }) async {
    final data = <String, dynamic>{
      'sessionId': sessionId,
      'auto_seed': autoSeed,
      'title': title,
      'category': category,
      'description': description,
      'tags': tags,
    };
    if (fileHashes != null) {
      data['fileHashes'] = fileHashes;
    }

    final resp = await _dio.post(
      '/api/confirm-seed',
      data: data,
      options: Options(
        contentType: Headers.jsonContentType,
        validateStatus: (s) => s != null && s < 500,
      ),
    );
    if (resp.statusCode != null && resp.statusCode! >= 400) {
      final msg = _extractErrorMessage(resp.data);
      throw ApiException(resp.statusCode!, msg);
    }
    return UploadConfirmResult.fromJson(resp.data as Map<String, dynamic>);
  }

  Future<List<FileEntry>> listFiles({String? path}) async {
    final resp = await _dio.get(
      '/api/files',
      queryParameters: path != null ? {'path': path} : null,
    );
    if (resp.statusCode! != 200) {
      throw ApiException(resp.statusCode!, 'List files failed');
    }
    final data = resp.data as Map<String, dynamic>;
    final entries = data['entries'] as List? ?? [];
    return entries
        .map((e) => FileEntry.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<String> downloadFile(
    String path,
    String saveDir, {
    int? expectedSize,
    void Function(int received, int total)? onProgress,
  }) async {
    final name = path.contains('\\')
        ? path.split('\\').last
        : path.split('/').last;
    final savePath = '$saveDir/$name';

    final existingFile = io.File(savePath);
    final existingSize = existingFile.existsSync() ? existingFile.lengthSync() : 0;
    FileLogger.log('[HttpClient.download] $name existingSize=$existingSize expectedSize=$expectedSize');

    if (expectedSize != null && existingSize >= expectedSize && existingSize > 0) {
      FileLogger.log('[HttpClient.download] $name already complete ($existingSize >= $expectedSize), skipping');
      return savePath;
    }

    final uri = _device.baseUrl.endsWith('/')
        ? '${_device.baseUrl}api/files/download?path=${Uri.encodeComponent(path)}'
        : '${_device.baseUrl}/api/files/download?path=${Uri.encodeComponent(path)}';

    final client = io.HttpClient();
    _nativeDownloadClient = client;
    _downloadCancelToken = CancelToken();
    _downloadPaused = false;
    io.IOSink? sink;
    try {
      final req = await client.getUrl(Uri.parse(uri));
      req.headers.set('X-Device-Token', _dio.options.headers['X-Device-Token'] ?? '');
      if (existingSize > 0) {
        req.headers.set('Range', 'bytes=$existingSize-');
        FileLogger.log('[HttpClient.download] sent Range: bytes=$existingSize-');
      }

      final resp = await req.close();
      final statusCode = resp.statusCode;
      FileLogger.log('[HttpClient.download] response status=$statusCode');

      if (statusCode == 416) {
        FileLogger.log('[HttpClient.download] 416 Range Not Satisfiable, file likely complete');
        await resp.drain<void>();
        client.close(force: true);
        return savePath;
      }

      final isResume = statusCode == 206 && existingSize > 0;
      sink = existingFile.openWrite(
          mode: isResume ? io.FileMode.append : io.FileMode.write);

      int received = isResume ? existingSize : 0;
      int total = received;
      if (isResume) {
        final cr = resp.headers.value('content-range') ?? '';
        if (cr.contains('/')) {
          try { total = int.parse(cr.split('/').last); } catch (_) {}
        }
      } else {
        total = int.tryParse(resp.headers.value('content-length') ?? '') ?? 0;
      }

      await for (final chunk in resp) {
        while (_downloadPaused) {
          await Future.delayed(const Duration(milliseconds: 100));
        }
        sink.add(chunk);
        received += chunk.length;
        if (onProgress != null) onProgress(received, total);
      }
      await sink.flush();
      await sink.close();
      sink = null;
      FileLogger.log('[HttpClient.download] completed: $savePath ($received bytes)');
    } catch (e) {
      FileLogger.log('[HttpClient.download] error: $e');
      rethrow;
    } finally {
      try {
        await sink?.flush();
        await sink?.close();
      } catch (_) {}
      _nativeDownloadClient = null;
      client.close(force: true);
    }

    return savePath;
  }

  Future<void> disconnect() async {
    try {
      await _dio.post('/api/disconnect');
    } catch (_) {}
  }

  void cancelUpload() {
    _uploadCancelToken?.cancel();
    _uploadCancelToken = null;
  }

  void cancelDownload() {
    _downloadPaused = false;  // Clear pause so the stream doesn't hang
    _downloadCancelToken?.cancel();
    _downloadCancelToken = null;
    try {
      _nativeDownloadClient?.close(force: true);
    } catch (_) {}
    _nativeDownloadClient = null;
  }

  void dispose() {
    _dio.close();
  }

  String _extractErrorMessage(dynamic data) {
    if (data is Map<String, dynamic>) {
      return data['message']?.toString() ?? data['error']?.toString() ?? data.toString();
    }
    return data?.toString() ?? 'Unknown error';
  }

  String _extractErrorMessageFromDioException(DioException e) {
    final data = e.response?.data;
    if (data is Map<String, dynamic>) {
      final msg = data['message'] ?? data['error'];
      if (msg != null) return 'HTTP ${e.response?.statusCode}: $msg';
    }
    return 'HTTP ${e.response?.statusCode ?? '?'}: ${e.message ?? e.type.toString()}';
  }
}

