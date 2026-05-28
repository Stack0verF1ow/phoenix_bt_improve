import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:open_filex/open_filex.dart';
import 'package:provider/provider.dart';
import 'package:saf/src/storage_access_framework/api.dart' as saf;
import 'package:share_plus/share_plus.dart';

import '../services/settings_service.dart';

class DownloadedFilesScreen extends StatefulWidget {
  const DownloadedFilesScreen({super.key});

  @override
  State<DownloadedFilesScreen> createState() => _DownloadedFilesScreenState();
}

class _DownloadedFilesScreenState extends State<DownloadedFilesScreen> {
  List<FileSystemEntity> _files = [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _scanFiles();
  }

  Future<void> _scanFiles() async {
    setState(() => _loading = true);
    final dir = Directory(context.read<SettingsService>().downloadDir);
    if (!await dir.exists()) {
      setState(() {
        _files = [];
        _loading = false;
      });
      return;
    }
    final allEntries = await dir.list().toList();
    // Filter out internal/temp files
    final entries = allEntries.where((e) {
      final name = e.uri.pathSegments.last;
      if (name.startsWith('.') || name.startsWith('res_')) return false;
      if (name.endsWith('.tmp') || name.endsWith('.temp')) return false;
      return true;
    }).toList();
    entries.sort((a, b) {
      final aStat = a.statSync();
      final bStat = b.statSync();
      return bStat.modified.compareTo(aStat.modified);
    });
    setState(() {
      _files = entries;
      _loading = false;
    });
  }

  static const _channel = MethodChannel('com.phoenixhelper/file_ops');

  static const _archiveMimes = {
    'zip': 'application/x-zip-compressed',
    'rar': 'application/x-rar-compressed',
    '7z': 'application/x-7z-compressed',
    'tar': 'application/x-tar',
    'gz': 'application/gzip',
  };

  void _openFile(File file) {
    final name = file.uri.pathSegments.last;
    final ext = name.contains('.') ? name.split('.').last.toLowerCase() : '';

    if (Platform.isAndroid && _archiveMimes.containsKey(ext)) {
      _channel.invokeMethod('openFileWithMime', {
        'path': file.path,
        'mime': _archiveMimes[ext],
      }).catchError((_) => OpenFilex.open(file.path));
    } else {
      OpenFilex.open(file.path);
    }
  }

  void _shareFile(File file) {
    Share.shareXFiles([XFile(file.path)]);
  }

  void _openFileManager() {
    final dir = context.read<SettingsService>().downloadDir;
    if (Platform.isAndroid) {
      _channel.invokeMethod('openFolder', {'path': dir}).catchError((_) {
        OpenFilex.open(dir);
      });
    } else {
      OpenFilex.open(dir);
    }
  }

  Future<void> _moveFile(File file) async {
    final name = file.uri.pathSegments.last;
    try {
      // Use SAF to pick target directory (works with Android 11+ scoped storage)
      final treeUriString = await saf.openDocumentTree();
      if (treeUriString == null) return;
      final treeUri = Uri.parse(treeUriString);

      // Read source file bytes
      final bytes = await file.readAsBytes();

      // Determine MIME type
      final ext = name.contains('.') ? name.split('.').last.toLowerCase() : '';
      final mime = _mimeTypeForExt(ext);

      // Create file in target directory via SAF
      final result = await saf.createFileAsBytes(
        treeUri,
        mimeType: mime,
        displayName: name,
        content: bytes,
      );

      if (result == null) {
        throw Exception('无法在目标目录创建文件');
      }

      // Delete source file
      await file.delete();

      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('已移动: $name'), backgroundColor: Colors.green),
      );
      _scanFiles();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('移动失败: $e'), backgroundColor: Colors.red),
      );
    }
  }

  Future<void> _deleteFile(File file) async {
    final confirm = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('删除文件'),
        content: Text('确定删除 ${file.uri.pathSegments.last}？'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('取消')),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('删除', style: TextStyle(color: Colors.red)),
          ),
        ],
      ),
    );
    if (confirm != true) return;
    try {
      await file.delete();
      _scanFiles();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('删除失败: $e'), backgroundColor: Colors.red),
      );
    }
  }

  void _showActions(File file) {
    showModalBottomSheet(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.open_in_new),
              title: const Text('打开'),
              onTap: () {
                Navigator.pop(ctx);
                _openFile(file);
              },
            ),
            ListTile(
              leading: const Icon(Icons.share),
              title: const Text('分享'),
              onTap: () {
                Navigator.pop(ctx);
                _shareFile(file);
              },
            ),
            ListTile(
              leading: const Icon(Icons.drive_file_move),
              title: const Text('移动到...'),
              onTap: () {
                Navigator.pop(ctx);
                _moveFile(file);
              },
            ),
            ListTile(
              leading: const Icon(Icons.delete, color: Colors.red),
              title: const Text('删除', style: TextStyle(color: Colors.red)),
              onTap: () {
                Navigator.pop(ctx);
                _deleteFile(file);
              },
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('已下载列表'),
        actions: [
          IconButton(
            icon: const Icon(Icons.folder_open),
            tooltip: '在文件管理器中打开',
            onPressed: _openFileManager,
          ),
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _scanFiles,
          ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _files.isEmpty
              ? const Center(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.folder_open, size: 64, color: Colors.grey),
                      SizedBox(height: 16),
                      Text('暂无已下载文件', style: TextStyle(color: Colors.grey)),
                    ],
                  ),
                )
              : RefreshIndicator(
                  onRefresh: _scanFiles,
                  child: ListView.builder(
                    itemCount: _files.length,
                    itemBuilder: (_, i) {
                      final entity = _files[i];
                      if (entity is! File) return const SizedBox.shrink();
                      final stat = entity.statSync();
                      final name = entity.uri.pathSegments.last;
                      final ext = name.contains('.') ? name.split('.').last.toLowerCase() : '';
                      return ListTile(
                        leading: Icon(_iconForExt(ext), color: _colorForExt(ext)),
                        title: Text(name, maxLines: 2, overflow: TextOverflow.ellipsis),
                        subtitle: Text(
                          '${_formatSize(stat.size)}  ${_formatTime(stat.modified)}',
                          style: TextStyle(color: Colors.grey[500], fontSize: 12),
                        ),
                        onTap: () => _openFile(entity),
                        onLongPress: () => _showActions(entity),
                      );
                    },
                  ),
                ),
    );
  }

  static IconData _iconForExt(String ext) {
    const video = {'mp4', 'mkv', 'avi', 'mov', 'wmv', 'flv'};
    const audio = {'mp3', 'flac', 'wav', 'aac', 'ogg', 'm4a'};
    const image = {'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp'};
    const doc = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt'};
    const archive = {'zip', 'rar', '7z', 'tar', 'gz'};
    if (video.contains(ext)) return Icons.movie;
    if (audio.contains(ext)) return Icons.music_note;
    if (image.contains(ext)) return Icons.image;
    if (doc.contains(ext)) return Icons.description;
    if (archive.contains(ext)) return Icons.archive;
    if (ext == 'torrent') return Icons.cloud_download;
    return Icons.insert_drive_file;
  }

  static Color _colorForExt(String ext) {
    const video = {'mp4', 'mkv', 'avi', 'mov', 'wmv', 'flv'};
    const audio = {'mp3', 'flac', 'wav', 'aac', 'ogg', 'm4a'};
    const image = {'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp'};
    if (video.contains(ext)) return Colors.purple;
    if (audio.contains(ext)) return Colors.orange;
    if (image.contains(ext)) return Colors.green;
    if (ext == 'torrent') return Colors.blue;
    return Colors.grey;
  }

  static String _mimeTypeForExt(String ext) {
    const map = {
      'mp4': 'video/mp4', 'mkv': 'video/x-matroska', 'avi': 'video/x-msvideo',
      'mp3': 'audio/mpeg', 'flac': 'audio/flac', 'wav': 'audio/wav',
      'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png', 'gif': 'image/gif',
      'pdf': 'application/pdf', 'txt': 'text/plain', 'zip': 'application/zip',
      'torrent': 'application/x-bittorrent',
    };
    return map[ext] ?? 'application/octet-stream';
  }

  static String _formatSize(int bytes) {
    if (bytes < 1024) return '$bytes B';
    if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
    if (bytes < 1024 * 1024 * 1024) {
      return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
    }
    return '${(bytes / (1024 * 1024 * 1024)).toStringAsFixed(1)} GB';
  }

  static String _formatTime(DateTime dt) {
    return '${dt.year}-${dt.month.toString().padLeft(2, '0')}-${dt.day.toString().padLeft(2, '0')} '
        '${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
  }
}
