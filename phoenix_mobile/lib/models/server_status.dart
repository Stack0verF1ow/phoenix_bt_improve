class ServerStatus {
  final String name;
  final String version;
  final int protocolVersion;
  final bool utorrentAvailable;
  final bool phoenixLoggedIn;
  final int filesAvailable;
  final int maxUploadSize;
  final String deviceType; // 'pc' or 'phone'
  final bool canAutoSeed;
  final int fileListVersion;

  ServerStatus({
    required this.name,
    required this.version,
    required this.protocolVersion,
    required this.utorrentAvailable,
    required this.phoenixLoggedIn,
    required this.filesAvailable,
    required this.maxUploadSize,
    this.deviceType = 'pc',
    this.canAutoSeed = false,
    this.fileListVersion = 0,
  });

  factory ServerStatus.fromJson(Map<String, dynamic> json) {
    return ServerStatus(
      name: json['name'] as String? ?? '',
      version: json['version'] as String? ?? '',
      protocolVersion: json['protocol_version'] as int? ?? 0,
      utorrentAvailable: json['utorrent_available'] as bool? ?? false,
      phoenixLoggedIn: json['phoenix_logged_in'] as bool? ?? false,
      filesAvailable: json['files_available'] as int? ?? 0,
      maxUploadSize: json['max_upload_size'] as int? ?? 0,
      deviceType: json['device_type'] as String? ?? 'pc',
      canAutoSeed: json['can_auto_seed'] as bool? ?? false,
      fileListVersion: json['fileListVersion'] as int? ?? 0,
    );
  }

  bool get isPC => deviceType == 'pc';
  bool get isPhone => deviceType == 'phone';
}

class FileEntry {
  final String path;
  final String name;
  final String type;
  final int size;
  final double mtime;

  FileEntry({
    required this.path,
    required this.name,
    required this.type,
    required this.size,
    required this.mtime,
  });

  factory FileEntry.fromJson(Map<String, dynamic> json) {
    return FileEntry(
      path: json['path'] as String? ?? '',
      name: json['name'] as String? ?? '',
      type: json['type'] as String? ?? 'file',
      size: json['size'] as int? ?? 0,
      mtime: (json['mtime'] as num?)?.toDouble() ?? 0,
    );
  }

  bool get isDir => type == 'dir';
}
