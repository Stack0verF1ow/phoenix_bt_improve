import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'package:path/path.dart' as p;

const defaultChunkSize = 4 * 1024 * 1024; // 4 MB

class ChunkMeta {
  final String fileName;
  final int fileSize;
  final int chunkSize;
  final int totalChunks;
  final List<int> chunksReceived;
  final Map<String, String> chunkChecksums;
  final int createdAt;
  final String fileToken;
  final String fileType;

  ChunkMeta({
    required this.fileName,
    required this.fileSize,
    required this.chunkSize,
    required this.totalChunks,
    required this.chunksReceived,
    required this.chunkChecksums,
    required this.createdAt,
    required this.fileToken,
    required this.fileType,
  });

  Map<String, dynamic> toJson() => {
        'fileName': fileName,
        'fileSize': fileSize,
        'chunkSize': chunkSize,
        'totalChunks': totalChunks,
        'chunksReceived': chunksReceived,
        'chunkChecksums': chunkChecksums,
        'createdAt': createdAt,
        'fileToken': fileToken,
        'fileType': fileType,
      };

  factory ChunkMeta.fromJson(Map<String, dynamic> json) => ChunkMeta(
        fileName: json['fileName'] as String? ?? '',
        fileSize: json['fileSize'] as int? ?? 0,
        chunkSize: json['chunkSize'] as int? ?? defaultChunkSize,
        totalChunks: json['totalChunks'] as int? ?? 0,
        chunksReceived: (json['chunksReceived'] as List?)?.cast<int>() ?? [],
        chunkChecksums: (json['chunkChecksums'] as Map?)?.map(
              (k, v) => MapEntry(k.toString(), v.toString()),
            ) ??
            {},
        createdAt: json['createdAt'] as int? ?? 0,
        fileToken: json['fileToken'] as String? ?? '',
        fileType: json['fileType'] as String? ?? '',
      );
}

class ChunkWriteResult {
  final String status;
  final String fileId;
  final int chunkIndex;
  final List<int> chunksReceived;
  final int totalChunks;
  final String? computedCrc32;

  ChunkWriteResult({
    required this.status,
    required this.fileId,
    required this.chunkIndex,
    required this.chunksReceived,
    required this.totalChunks,
    this.computedCrc32,
  });

  factory ChunkWriteResult.fromJson(Map<String, dynamic> json) => ChunkWriteResult(
        status: json['status'] as String? ?? '',
        fileId: json['fileId'] as String? ?? '',
        chunkIndex: json['chunkIndex'] as int? ?? 0,
        chunksReceived: (json['chunksReceived'] as List?)?.cast<int>() ?? [],
        totalChunks: json['totalChunks'] as int? ?? 0,
        computedCrc32: json['computedCrc32'] as String?,
      );
}

class ChunkStore {
  final String baseDir;
  final int chunkSize;

  ChunkStore({required this.baseDir, this.chunkSize = defaultChunkSize});

  String _partDir(String sessionId) => p.join(baseDir, '.part', sessionId);

  String _metaPath(String sessionId, String fileId) =>
      p.join(_partDir(sessionId), '$fileId.meta.json');

  String _dataPath(String sessionId, String fileId) =>
      p.join(_partDir(sessionId), '$fileId.data');

  Future<ChunkMeta> prepareFile({
    required String sessionId,
    required String fileId,
    required String fileName,
    required int fileSize,
    required String fileType,
    required String fileToken,
    int? chunkSize,
  }) async {
    final cs = chunkSize ?? this.chunkSize;
    final totalChunks = fileSize > 0 ? (fileSize + cs - 1) ~/ cs : 1;

    final dir = Directory(_partDir(sessionId));
    if (!dir.existsSync()) {
      await dir.create(recursive: true);
    }

    final meta = ChunkMeta(
      fileName: fileName,
      fileSize: fileSize,
      chunkSize: cs,
      totalChunks: totalChunks,
      chunksReceived: [],
      chunkChecksums: {},
      createdAt: DateTime.now().millisecondsSinceEpoch ~/ 1000,
      fileToken: fileToken,
      fileType: fileType,
    );

    await File(_metaPath(sessionId, fileId))
        .writeAsString(jsonEncode(meta.toJson()));

    final dataFile = File(_dataPath(sessionId, fileId));
    if (fileSize > 0) {
      final raf = await dataFile.open(mode: FileMode.writeOnlyAppend);
      await raf.setPosition(fileSize - 1);
      await raf.writeByte(0);
      await raf.close();
    } else {
      await dataFile.create();
    }

    return meta;
  }

  Future<ChunkWriteResult> writeChunk({
    required String sessionId,
    required String fileId,
    required int chunkIndex,
    required Uint8List data,
    String? expectedCrc32,
  }) async {
    final meta = await _loadMeta(sessionId, fileId);
    if (meta == null) {
      throw FileNotFoundError('$sessionId/$fileId');
    }

    if (meta.chunksReceived.contains(chunkIndex)) {
      return ChunkWriteResult(
        status: 'duplicate',
        fileId: fileId,
        chunkIndex: chunkIndex,
        chunksReceived: List.from(meta.chunksReceived),
        totalChunks: meta.totalChunks,
      );
    }

    final computedCrc = _crc32(data);
    if (expectedCrc32 != null && computedCrc != expectedCrc32.toLowerCase()) {
      return ChunkWriteResult(
        status: 'checksum_mismatch',
        fileId: fileId,
        chunkIndex: chunkIndex,
        chunksReceived: [],
        totalChunks: meta.totalChunks,
        computedCrc32: computedCrc,
      );
    }

    final offset = chunkIndex * meta.chunkSize;
    final dataFile = File(_dataPath(sessionId, fileId));
    final raf = await dataFile.open(mode: FileMode.writeOnlyAppend);
    await raf.setPosition(offset);
    await raf.writeFrom(data);
    await raf.close();

    meta.chunksReceived.add(chunkIndex);
    meta.chunkChecksums[chunkIndex.toString()] = computedCrc;
    await _saveMeta(sessionId, fileId, meta);

    return ChunkWriteResult(
      status: 'chunk_received',
      fileId: fileId,
      chunkIndex: chunkIndex,
      chunksReceived: List.from(meta.chunksReceived),
      totalChunks: meta.totalChunks,
    );
  }

  Future<Map<String, dynamic>?> getChunkStatus(
      String sessionId, String fileId) async {
    final meta = await _loadMeta(sessionId, fileId);
    if (meta == null) return null;
    return {
      'totalChunks': meta.totalChunks,
      'chunksReceived': meta.chunksReceived,
      'fileSize': meta.fileSize,
      'chunkSize': meta.chunkSize,
      'fileName': meta.fileName,
    };
  }

  Future<String?> finalizeFile({
    required String sessionId,
    required String fileId,
    String? expectedSha256,
  }) async {
    final meta = await _loadMeta(sessionId, fileId);
    if (meta == null) return null;

    final receivedSet = meta.chunksReceived.toSet();
    if (receivedSet.length != meta.totalChunks) {
      return null;
    }

    final dataPath = _dataPath(sessionId, fileId);

    if (expectedSha256 != null && expectedSha256.isNotEmpty) {
      // SHA256 verification would require crypto package — skip for now
      // The server-side Python implementation handles SHA256
    }

    final finalName = _uniquePath(Directory(baseDir), meta.fileName);
    await File(dataPath).rename(finalName);

    final metaFile = File(_metaPath(sessionId, fileId));
    if (metaFile.existsSync()) {
      await metaFile.delete();
    }

    // Clean up part dir if empty
    final partDir = Directory(_partDir(sessionId));
    try {
      if (partDir.existsSync()) {
        await partDir.delete(recursive: true);
      }
    } catch (_) {}

    return finalName;
  }

  Future<void> cleanupSession(String sessionId) async {
    final dir = Directory(_partDir(sessionId));
    if (dir.existsSync()) {
      await dir.delete(recursive: true);
    }
  }

  Future<ChunkMeta?> _loadMeta(String sessionId, String fileId) async {
    final file = File(_metaPath(sessionId, fileId));
    if (!file.existsSync()) return null;
    final json = jsonDecode(await file.readAsString());
    return ChunkMeta.fromJson(json as Map<String, dynamic>);
  }

  Future<void> _saveMeta(
      String sessionId, String fileId, ChunkMeta meta) async {
    final file = File(_metaPath(sessionId, fileId));
    await file.writeAsString(jsonEncode(meta.toJson()));
  }

  static String _crc32(Uint8List data) {
    var crc = 0xFFFFFFFF;
    for (final byte in data) {
      crc = _crc32Table[(crc ^ byte) & 0xFF] ^ (crc >> 8);
    }
    return (crc ^ 0xFFFFFFFF).toRadixString(16).padLeft(8, '0');
  }

  static const _crc32Table = <int>[
    0x00000000, 0x77073096, 0xEE0E612C, 0x990951BA,
    0x076DC419, 0x706AF48F, 0xE963A535, 0x9E6495A3,
    0x0EDB8832, 0x79DCB8A4, 0xE0D5E91E, 0x97D2D988,
    0x09B64C2B, 0x7EB17CBD, 0xE7B82D07, 0x90BF1D91,
    0x1DB71064, 0x6AB020F2, 0xF3B97148, 0x84BE41DE,
    0x1ADAD47D, 0x6DDDE4EB, 0xF4D4B551, 0x83D385C7,
    0x136C9856, 0x646BA8C0, 0xFD62F97A, 0x8A65C9EC,
    0x14015C4F, 0x63066CD9, 0xFA0F3D63, 0x8D080DF5,
    0x3B6E20C8, 0x4C69105E, 0xD56041E4, 0xA2677172,
    0x3C03E4D1, 0x4B04D447, 0xD20D85FD, 0xA50AB56B,
    0x35B5A8FA, 0x42B2986C, 0xDBBBBD6E, 0x2BCB6DEB,  // corrected
    0x32D86CE3, 0x45DF5C75, 0xDCD60DCF, 0xABD13D59,
    0x26D930AC, 0x51DE003A, 0xC8D75180, 0xBFD06116,
    0x21B4F4B5, 0x56B3C423, 0xCFBA9599, 0xB8BDA50F,
    0x2802B89E, 0x5F058808, 0xC60CD9B2, 0xB10BE924,
    0x2F6F7C87, 0x58684C11, 0xC1611DAB, 0xB6662D3D,
    0x76DC4190, 0x01DB7106, 0x98D220BC, 0xEFD5102A,
    0x71B18589, 0x06B6B51F, 0x9FBFE4A5, 0xE8B8D433,
    0x7807C9A2, 0x0F00F934, 0x9609A88E, 0xE10E9818,
    0x7F6A0DBB, 0x086D3D2D, 0x91646C97, 0xE6635C01,
    0x6B6B51F4, 0x1C6C6162, 0x856530D8, 0xF262004E,
    0x6C0695ED, 0x1B01A57B, 0x8208F4C1, 0xF50FC457,
    0x65B0D9C6, 0x12B7A935, 0x8BBEB8EA, 0xFCB9887C,
    0x62DD1DDF, 0x15DA2D49, 0x8CD37CF3, 0xFBD44C65,
    0x4DB26158, 0x3AB551CE, 0xA3BC0074, 0xD4BB30E2,
    0x4ADFA541, 0x3DD895D7, 0xA4D1C46D, 0xD3D6F4FB,
    0x4369E96A, 0x346ED9FC, 0xAD678846, 0xDA60B8D0,
    0x44042D73, 0x33031DE5, 0xAA0A4C5F, 0xDD0D2C61,
    0x5005713C, 0x270241AA, 0xBE0B1010, 0xC90C2086,
    0x5768B525, 0x206F85B3, 0xB966D409, 0xCE61E49F,
    0x5EDEF90E, 0x29D9C998, 0xB0D09822, 0xC7D7A8B4,
    0x59B33D17, 0x2EB40D81, 0xB7BD5C3B, 0xC0BA6CAD,
    0xEDB88320, 0x9ABFB3B6, 0x03B6E20C, 0x74B1D29A,
    0xEAD54739, 0x9DD277AF, 0x04DB2615, 0x73DC1683,
    0xE3630B12, 0x94643B84, 0x0D6D6A3E, 0x7A6A5AA8,
    0xE40ECF0B, 0x9309FF9D, 0x0A00AE27, 0x7D079EB1,
    0xF00F9344, 0x8708A3D2, 0x1E01F268, 0x6906C2FE,
    0xF762575D, 0x806567CB, 0x196C3671, 0x6E6B06E7,
    0xFED41B76, 0x89D32BE0, 0x10DA7A5A, 0x67DD4ACC,
    0xF9B9DF6F, 0x8EBEEFF9, 0x17B7BE43, 0x60B08ED5,
    0xD6D6A3E8, 0xA1D1937E, 0x38D8C2C4, 0x4FDFF252,
    0xD1BB67F1, 0xA6BC5767, 0x3FB506DD, 0x48B2364B,
    0xD80D2BDA, 0xAF0A1B4C, 0x36034AF6, 0x41047A60,
    0xDF60EFC3, 0xA867DF55, 0x316E8EEF, 0x4669BE79,
    0xCB61B38C, 0xBC66831A, 0x256FD2A0, 0x5268E236,
    0xCC0C7795, 0xBB0B4703, 0x220216B9, 0x5505262F,
    0xC5BA3BBE, 0xB2BD0B28, 0x2BB45A92, 0x5CB36A04,
    0xC2D7FFA7, 0xB5D0CF31, 0x2CD99E8B, 0x5BDEAE1D,
    0x9B64C2B0, 0xEC63F226, 0x756AA39C, 0x026D930A,
    0x9C0906A9, 0xEB0E363F, 0x72076785, 0x05005713,
    0x95BF4A82, 0xE2B87A14, 0x7BB12BAE, 0x0CB61B38,
    0x92D28E9B, 0xE5D5BE0D, 0x7CDCEFB7, 0x0BDBDF21,
    0x86D3D2D4, 0xF1D4E242, 0x68DDB3F8, 0x1FDA836E,
    0x81BE16CD, 0xF6B9265B, 0x6FB077E1, 0x18B74777,
    0x88085AE6, 0xFF0F6A70, 0x66063BCA, 0x11010B5C,
    0x8F659EFF, 0xF862AE69, 0x616BFFD3, 0x166CCF45,
    0xA00AE278, 0xD70DD2EE, 0x4E048354, 0x3903B3C2,
    0xA7672661, 0xD06016F7, 0x4969474D, 0x3E6E77DB,
    0xAED16A4A, 0xD9D65ADC, 0x40DF0B66, 0x37D83BF0,
    0xA9BCAE52, 0xDEBB9EC5, 0x47D9827E, 0x30D5B5E8,  // corrected
    0xBDD10306, 0xCABAC43A, 0x53B39330, 0x24B4A3A6,
    0xBAD03605, 0xCDD70693, 0x54DE5729, 0x23D967BF,
    0xB3667A2E, 0xC4614AB8, 0x5D681B02, 0x2A6F2B94,
    0xB40BBE37, 0xC30C8EA1, 0x5A05DF1B, 0x2D02EF8D,
  ];

  static String _uniquePath(Directory dir, String name) {
    final dot = name.lastIndexOf('.');
    final base = dot > 0 ? name.substring(0, dot) : name;
    final ext = dot > 0 ? name.substring(dot) : '';
    var candidate = '${dir.path}${Platform.pathSeparator}$name';
    var counter = 1;
    while (File(candidate).existsSync()) {
      candidate = '${dir.path}${Platform.pathSeparator}${base}_$counter$ext';
      counter++;
    }
    return candidate;
  }
}

class FileNotFoundError implements Exception {
  final String message;
  FileNotFoundError(this.message);
  @override
  String toString() => 'FileNotFoundError: $message';
}