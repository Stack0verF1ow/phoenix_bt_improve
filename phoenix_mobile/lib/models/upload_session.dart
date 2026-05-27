class UploadSession {
  final String sessionId;
  final Map<String, String> fileTokens;
  final int expiresIn;

  UploadSession({
    required this.sessionId,
    required this.fileTokens,
    required this.expiresIn,
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
