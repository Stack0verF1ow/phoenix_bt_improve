import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:open_filex/open_filex.dart';
import 'package:provider/provider.dart';
import 'package:saf/src/storage_access_framework/api.dart' as saf;
import 'package:share_plus/share_plus.dart';

import '../services/settings_service.dart';

enum _SortMode { name, date, size }

/// Source filter flags (bitfield-style, combined via | ).
/// We store them as a simple bool per flag — checkboxes not radio.
class _SourceFilter {
  bool bt = true;
  bool pc = true;
  bool received = true;
  bool get all => bt && pc && received;
  void setAll() { bt = pc = received = true; }
}

class DownloadedFilesScreen extends StatefulWidget {
  const DownloadedFilesScreen({super.key});

  @override
  State<DownloadedFilesScreen> createState() => _DownloadedFilesScreenState();
}

class _DownloadedFilesScreenState extends State<DownloadedFilesScreen> {
  List<FileSystemEntity> _allFiles = [];
  List<FileSystemEntity> _filteredFiles = [];
  bool _loading = true;
  final _searchCtrl = TextEditingController();
  String _searchQuery = '';
  _SortMode _sortMode = _SortMode.date;
  bool _sortAsc = false;
  final _sourceFilter = _SourceFilter();

  @override
  void initState() {
    super.initState();
    _scanFiles();
  }

  @override
  void dispose() {
    _searchCtrl.dispose();
    super.dispose();
  }

  Future<void> _scanFiles() async {
    setState(() => _loading = true);
    final dir = Directory(context.read<SettingsService>().downloadDir);
    if (!await dir.exists()) {
      setState(() {
        _allFiles = [];
        _filteredFiles = [];
        _loading = false;
      });
      return;
    }

    const hiddenNames = {
      'isolate_snapshot_data', 'isolate snapshot data',
      'kernel_blob.bin', 'kernel blob.bin',
      'vm_snapshot_data', 'vm snapshot data',
    };

    final allEntries = await dir.list(recursive: true).toList();
    final entries = allEntries.where((e) {
      if (e is! File) return false;
      final name = e.uri.pathSegments.last;
      if (name.startsWith('.') || name.startsWith('res_')) return false;
      if (name.endsWith('.tmp') || name.endsWith('.temp')) return false;
      if (name.endsWith('.bt.state')) return false;
      if (hiddenNames.contains(name)) return false;
      if (name.length == 32 && name.contains(RegExp(r'^[0-9a-f]+$'))) return false;
      if (name.endsWith('.torrent')) return false;
      return true;
    }).toList();

    _allFiles = entries;
    _applyFilterAndSort();
    setState(() => _loading = false);
  }

  void _applyFilterAndSort() {
    var files = _allFiles.where((e) {
      // Search filter
      if (_searchQuery.isNotEmpty) {
        final name = e.uri.pathSegments.last.toLowerCase();
        if (!name.contains(_searchQuery.toLowerCase())) return false;
      }
      // Source filter
      if (!_sourceFilter.all) {
        final path = e.path.replaceAll('\\', '/');
        final isBt = path.contains('/bt_downloads/');
        final isReceived = path.contains('/received/');
        final isPc = !isBt && !isReceived;
        if ((isBt && !_sourceFilter.bt) ||
            (isPc && !_sourceFilter.pc) ||
            (isReceived && !_sourceFilter.received)) {
          return false;
        }
      }
      return true;
    }).toList();

    files.sort((a, b) {
      final aStat = a.statSync();
      final bStat = b.statSync();
      int cmp;
      switch (_sortMode) {
        case _SortMode.name:
          cmp = a.uri.pathSegments.last
              .toLowerCase()
              .compareTo(b.uri.pathSegments.last.toLowerCase());
        case _SortMode.date:
          cmp = aStat.modified.compareTo(bStat.modified);
        case _SortMode.size:
          cmp = aStat.size.compareTo(bStat.size);
      }
      return _sortAsc ? cmp : -cmp;
    });

    _filteredFiles = files;
  }

  void _onSearch(String value) {
    setState(() { _searchQuery = value; _applyFilterAndSort(); });
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
      final treeUriString = await saf.openDocumentTree();
      if (treeUriString == null) return;
      final treeUri = Uri.parse(treeUriString);
      final bytes = await file.readAsBytes();
      final ext = name.contains('.') ? name.split('.').last.toLowerCase() : '';
      final mime = _mimeTypeForExt(ext);
      final result = await saf.createFileAsBytes(
        treeUri, mimeType: mime, displayName: name, content: bytes,
      );
      if (result == null) throw Exception('无法在目标目录创建文件');
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
              onTap: () { Navigator.pop(ctx); _openFile(file); },
            ),
            ListTile(
              leading: const Icon(Icons.share),
              title: const Text('分享'),
              onTap: () { Navigator.pop(ctx); _shareFile(file); },
            ),
            ListTile(
              leading: const Icon(Icons.drive_file_move),
              title: const Text('移动到...'),
              onTap: () { Navigator.pop(ctx); _moveFile(file); },
            ),
            ListTile(
              leading: const Icon(Icons.delete, color: Colors.red),
              title: const Text('删除', style: TextStyle(color: Colors.red)),
              onTap: () { Navigator.pop(ctx); _deleteFile(file); },
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
      body: Column(
        children: [
          // Search bar
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
            child: TextField(
              controller: _searchCtrl,
              decoration: InputDecoration(
                hintText: '搜索文件名...',
                prefixIcon: const Icon(Icons.search),
                suffixIcon: _searchQuery.isNotEmpty
                    ? IconButton(
                        icon: const Icon(Icons.clear),
                        onPressed: () { _searchCtrl.clear(); _onSearch(''); },
                      )
                    : null,
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
                contentPadding: const EdgeInsets.symmetric(vertical: 0, horizontal: 12),
                isDense: true,
              ),
              onChanged: _onSearch,
            ),
          ),
          // Source filter chips
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12),
            child: Wrap(
              spacing: 6,
              children: [
                FilterChip(
                  label: const Text('全部', style: TextStyle(fontSize: 12)),
                  selected: _sourceFilter.all,
                  onSelected: (_) {
                    setState(() { _sourceFilter.setAll(); _applyFilterAndSort(); });
                  },
                  visualDensity: VisualDensity.compact,
                ),
                FilterChip(
                  label: const Text('种子下载', style: TextStyle(fontSize: 12)),
                  selected: _sourceFilter.bt,
                  onSelected: (v) {
                    setState(() { _sourceFilter.bt = v; _applyFilterAndSort(); });
                  },
                  visualDensity: VisualDensity.compact,
                ),
                FilterChip(
                  label: const Text('电脑下载', style: TextStyle(fontSize: 12)),
                  selected: _sourceFilter.pc,
                  onSelected: (v) {
                    setState(() { _sourceFilter.pc = v; _applyFilterAndSort(); });
                  },
                  visualDensity: VisualDensity.compact,
                ),
                FilterChip(
                  label: const Text('接收文件', style: TextStyle(fontSize: 12)),
                  selected: _sourceFilter.received,
                  onSelected: (v) {
                    setState(() { _sourceFilter.received = v; _applyFilterAndSort(); });
                  },
                  visualDensity: VisualDensity.compact,
                ),
              ],
            ),
          ),
          // Sort bar
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
            child: Row(
              children: [
                _buildSortChip(_SortMode.name, '文件名'),
                const SizedBox(width: 8),
                _buildSortChip(_SortMode.date, '时间'),
                const SizedBox(width: 8),
                _buildSortChip(_SortMode.size, '大小'),
                const Spacer(),
                IconButton(
                  icon: Icon(_sortAsc ? Icons.arrow_upward : Icons.arrow_downward, size: 18),
                  tooltip: '切换排序方向',
                  onPressed: () { setState(() { _sortAsc = !_sortAsc; _applyFilterAndSort(); }); },
                ),
              ],
            ),
          ),
          // File list
          Expanded(child: _loading
              ? const Center(child: CircularProgressIndicator())
              : _filteredFiles.isEmpty
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
                        itemCount: _filteredFiles.length,
                        itemBuilder: (_, i) {
                          final entity = _filteredFiles[i];
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
          ),
        ],
      ),
    );
  }

  Widget _buildSortChip(_SortMode mode, String label) {
    final active = _sortMode == mode;
    return ChoiceChip(
      label: Text(label, style: const TextStyle(fontSize: 12)),
      selected: active,
      onSelected: (_) {
        setState(() {
          if (active) { _sortAsc = !_sortAsc; }
          else { _sortMode = mode; _sortAsc = false; }
          _applyFilterAndSort();
        });
      },
      visualDensity: VisualDensity.compact,
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
    return Icons.insert_drive_file;
  }

  static Color _colorForExt(String ext) {
    const video = {'mp4', 'mkv', 'avi', 'mov', 'wmv', 'flv'};
    const audio = {'mp3', 'flac', 'wav', 'aac', 'ogg', 'm4a'};
    const image = {'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp'};
    if (video.contains(ext)) return Colors.purple;
    if (audio.contains(ext)) return Colors.orange;
    if (image.contains(ext)) return Colors.green;
    return Colors.grey;
  }

  static String _mimeTypeForExt(String ext) {
    const map = {
      'mp4': 'video/mp4', 'mkv': 'video/x-matroska', 'avi': 'video/x-msvideo',
      'mp3': 'audio/mpeg', 'flac': 'audio/flac', 'wav': 'audio/wav',
      'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png', 'gif': 'image/gif',
      'pdf': 'application/pdf', 'txt': 'text/plain', 'zip': 'application/zip',
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
