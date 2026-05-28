import 'dart:typed_data';

import 'package:dio/dio.dart';

import '../models/device_info.dart';
import '../models/server_status.dart';
import '../models/upload_session.dart';

class ApiException implements Exception {
  final int statusCode;
  final String message;
  ApiException(this.statusCode, this.message);

  @override
  String toString() => 'ApiException($statusCode): $message';
}

class HttpClient {
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

  Future<UploadSession> prepareUpload(Map<String, Map<String, dynamic>> files) async {
    final resp = await _dio.post(
      '/api/prepare-upload',
      data: {'files': files},
      options: Options(contentType: Headers.jsonContentType),
    );
    if (resp.statusCode! != 200) {
      throw ApiException(resp.statusCode!, 'Prepare upload failed');
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
      ),
      onSendProgress: onProgress,
    );
    if (resp.statusCode! != 200) {
      throw ApiException(resp.statusCode!, 'Upload failed');
    }
  }

  Future<UploadConfirmResult> confirmSeed({
    required String sessionId,
    required bool autoSeed,
    String title = '',
    String category = '',
    String description = '',
    List<String> tags = const [],
  }) async {
    final resp = await _dio.post(
      '/api/confirm-seed',
      data: {
        'sessionId': sessionId,
        'auto_seed': autoSeed,
        'title': title,
        'category': category,
        'description': description,
        'tags': tags,
      },
      options: Options(contentType: Headers.jsonContentType),
    );
    if (resp.statusCode! != 200) {
      throw ApiException(resp.statusCode!, 'Confirm seed failed');
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
    void Function(int received, int total)? onProgress,
  }) async {
    final parts = path.split('/');
    final name = parts.isNotEmpty ? parts.last : 'download';
    final savePath = '$saveDir/$name';
    await _dio.download(
      '/api/files/download',
      savePath,
      queryParameters: {'path': path},
      options: Options(
        receiveTimeout: const Duration(minutes: 10),
      ),
      onReceiveProgress: onProgress,
    );
    return savePath;
  }

  Future<void> disconnect() async {
    try {
      await _dio.post('/api/disconnect');
    } catch (_) {
      // Ignore errors — server may already be gone
    }
  }

  void dispose() {
    _dio.close();
  }
}
