import 'dart:io';

import '../utils/file_logger.dart';

enum TorrentStatus { notDownloaded, partial, completed }

class TorrentFile {
  final String name;
  final String path;
  final int size;
  final DateTime addedAt;
  final TorrentStatus status;

  TorrentFile({
    required this.name,
    required this.path,
    required this.size,
    required this.addedAt,
    this.status = TorrentStatus.notDownloaded,
  });

  /// Check a .bt.state file to see if all pieces are complete.
  /// [piecesNum] is the total piece count from the torrent metainfo.
  ///
  /// dtorrent_task_v2 writes the state file as:
  ///   [bitfield bytes (ceil(piecesNum/8))][8 bytes uploaded counter]
  ///
  /// Retries up to 3 times with 500ms delay if reading the file fails
  /// (may happen if StateFile is still being flushed on Android).
  static Future<bool> isStateFileComplete(String statePath, int piecesNum) async {
    final bitfieldLen = (piecesNum + 7) ~/ 8;
    for (var attempt = 0; attempt < 3; attempt++) {
      try {
        final f = File(statePath);
        if (!f.existsSync()) return false;
        final bytes = f.readAsBytesSync();
        if (bytes.length < bitfieldLen) return false;
        for (var i = 0; i < bitfieldLen; i++) {
          final byte = bytes[i];
          final expected = (i == bitfieldLen - 1)
              ? (0xFF << ((bitfieldLen * 8) - piecesNum)) & 0xFF
              : 0xFF;
          if (byte != expected) return false;
        }
        return true;
      } catch (e) {
        FileLogger.log('[TorrentFile] isStateFileComplete attempt ${attempt + 1}/3 failed for $statePath: $e');
        if (attempt < 2) {
          await Future.delayed(const Duration(milliseconds: 500));
        }
      }
    }
    FileLogger.log('[TorrentFile] isStateFileComplete all 3 attempts failed, returning false for $statePath');
    return false;
  }
}