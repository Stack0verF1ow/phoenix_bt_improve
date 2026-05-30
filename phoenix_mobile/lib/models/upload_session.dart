class UploadSession {
  final String sessionId;
  final Map<String, String> fileTokens;
  final int expiresIn;
  final int chunkSize;

  UploadSession({
    required this.sessionId,
    required this.fileTokens,
    required this.expiresIn,
    this.chunkSize = 4 * 1024 * 1024,
  });

  factory UploadSession.fromJson(Map<String, dynamic> json) {
    final tokens = <String, String>{};
    if (json['fileTokens'] is Map) {
      (json['fileTokens'] as Map).forEach((k, v) {
        tokens[k.toString()] = v.toString();
      });
    }
    return UploadSession(
      sessionId: json['sessionId'] as String? ?? '',
      fileTokens: tokens,
      expiresIn: json['expires_in'] as int? ?? 600,
      chunkSize: json['chunkSize'] as int? ?? 4 * 1024 * 1024,
    );
  }
}

class UploadConfirmResult {
  final String status;
  final List<UploadInfo> uploads;

  UploadConfirmResult({required this.status, required this.uploads});

  factory UploadConfirmResult.fromJson(Map<String, dynamic> json) {
    final list = <UploadInfo>[];
    if (json['uploads'] is List) {
      for (final item in json['uploads'] as List) {
        list.add(UploadInfo(
          uploadId: item['uploadId'] as String? ?? '',
          name: item['name'] as String? ?? '',
          size: item['size'] as int? ?? 0,
        ));
      }
    }
    return UploadConfirmResult(
      status: json['status'] as String? ?? 'idle',
      uploads: list,
    );
  }
}

class UploadInfo {
  final String uploadId;
  final String name;
  final int size;

  UploadInfo({
    required this.uploadId,
    required this.name,
    required this.size,
  });
}

class ChunkFileInfo {
  final int totalChunks;
  final List<int> chunksReceived;
  final int fileSize;
  final int chunkSize;
  final String fileName;

  ChunkFileInfo({
    required this.totalChunks,
    required this.chunksReceived,
    required this.fileSize,
    required this.chunkSize,
    required this.fileName,
  });

  factory ChunkFileInfo.fromJson(Map<String, dynamic> json) => ChunkFileInfo(
        totalChunks: json['totalChunks'] as int? ?? 0,
        chunksReceived: (json['chunksReceived'] as List?)?.cast<int>() ?? [],
        fileSize: json['fileSize'] as int? ?? 0,
        chunkSize: json['chunkSize'] as int? ?? 4 * 1024 * 1024,
        fileName: json['fileName'] as String? ?? '',
      );
}

class UploadStatus {
  final String sessionId;
  final String status;
  final int filesReceived;
  final int filesTotal;
  final String seedStatus;
  final Map<String, ChunkFileInfo>? fileChunks;

  UploadStatus({
    required this.sessionId,
    required this.status,
    required this.filesReceived,
    required this.filesTotal,
    required this.seedStatus,
    this.fileChunks,
  });

  factory UploadStatus.fromJson(Map<String, dynamic> json) {
    Map<String, ChunkFileInfo>? chunks;
    if (json['file_chunks'] != null) {
      chunks = {};
      final fc = json['file_chunks'] as Map<String, dynamic>;
      for (final entry in fc.entries) {
        chunks[entry.key] =
            ChunkFileInfo.fromJson(entry.value as Map<String, dynamic>);
      }
    }
    return UploadStatus(
      sessionId: json['sessionId'] as String? ?? '',
      status: json['status'] as String? ?? 'unknown',
      filesReceived: json['files_received'] as int? ?? 0,
      filesTotal: json['files_total'] as int? ?? 0,
      seedStatus: json['seed_status'] as String? ?? 'idle',
      fileChunks: chunks,
    );
  }
}