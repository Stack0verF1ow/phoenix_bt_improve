import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/torrent_file.dart';
import '../providers/torrent_provider.dart';
import '../services/bt_download_service.dart';

class TorrentScreen extends StatefulWidget {
  const TorrentScreen({super.key});

  @override
  State<TorrentScreen> createState() => _TorrentScreenState();
}

class _TorrentScreenState extends State<TorrentScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<TorrentProvider>().syncTorrents();
    });
  }

  Future<void> _importTorrent() async {
    String? pickedPath;
    try {
      final result = await FilePicker.platform.pickFiles(
        type: FileType.any,
      );
      if (result == null || result.paths.isEmpty) return;
      pickedPath = result.paths.first;
      if (pickedPath == null) return;
      if (!pickedPath.endsWith('.torrent')) {
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('请选择 .torrent 文件'),
              backgroundColor: Colors.orange),
        );
        return;
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('文件选择失败: $e'),
            backgroundColor: Colors.red),
      );
      return;
    }

    if (!mounted) return;
    final provider = context.read<TorrentProvider>();

    try {
      await provider.importTorrent(pickedPath!);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('已导入 .torrent 文件'),
          backgroundColor: Colors.green,
        ),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('导入失败: $e'), backgroundColor: Colors.red),
      );
    }
  }

  void _showActions(TorrentFile file) {
    final provider = context.read<TorrentProvider>();
    final bt = provider.btService;
    final isDownloading = bt.running && bt.currentName == file.name;

    showModalBottomSheet(
      context: context,
      builder: (_) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (!isDownloading)
              ListTile(
                leading: const Icon(Icons.download),
                title: const Text('下载到本机'),
                onTap: () {
                  Navigator.of(context).pop();
                  provider.startDownload(file);
                },
              ),
            ListTile(
              leading: const Icon(Icons.open_in_new),
              title: const Text('用外部 App 打开'),
              onTap: () {
                Navigator.of(context).pop();
                provider.openTorrent(file);
              },
            ),
            ListTile(
              leading: const Icon(Icons.delete, color: Colors.red),
              title: const Text('删除', style: TextStyle(color: Colors.red)),
              onTap: () async {
                Navigator.of(context).pop();
                await provider.deleteTorrent(file);
              },
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<TorrentProvider>();
    final bt = provider.btService;

    return Scaffold(
      appBar: AppBar(
        title: const Text('BT 下载'),
        actions: [
          if (bt.running)
            TextButton(
              onPressed: provider.stopDownload,
              child: const Text('停止', style: TextStyle(color: Colors.red)),
            ),
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: provider.loading ? null : () => provider.syncTorrents(),
          ),
        ],
      ),
      floatingActionButton: bt.running
          ? null
          : FloatingActionButton.extended(
              onPressed: _importTorrent,
              icon: const Icon(Icons.add),
              label: const Text('导入 .torrent 文件'),
            ),
      body: _buildBody(provider, bt),
    );
  }

  Widget _buildBody(TorrentProvider provider, BtDownloadService bt) {
    // Show active download progress at top
    if (bt.running) {
      return Column(
        children: [
          Card(
            margin: const EdgeInsets.all(12),
            color: Theme.of(context).colorScheme.primaryContainer,
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('正在下载: ${bt.currentName}',
                      style: const TextStyle(fontWeight: FontWeight.w600)),
                  const SizedBox(height: 8),
                  LinearProgressIndicator(value: bt.progress),
                  const SizedBox(height: 4),
                  Text(
                    '${(bt.progress * 100).toStringAsFixed(1)}%  '
                    '${_formatSpeed(bt.speed)}',
                    style: TextStyle(fontSize: 13, color: Colors.grey[700]),
                  ),
                ],
              ),
            ),
          ),
          if (bt.completed)
            const Padding(
              padding: EdgeInsets.all(8),
              child: Text('下载完成!', style: TextStyle(color: Colors.green)),
            ),
          if (bt.error != null)
            Padding(
              padding: const EdgeInsets.all(8),
              child: Text('错误: ${bt.error}',
                  style: const TextStyle(color: Colors.red)),
            ),
          Expanded(child: _buildTorrentList(provider)),
        ],
      );
    }

    if (bt.completed) {
      return Column(
        children: [
          const Padding(
            padding: EdgeInsets.all(8),
            child: Text('下载完成!', style: TextStyle(color: Colors.green)),
          ),
          Expanded(child: _buildTorrentList(provider)),
        ],
      );
    }

    return _buildTorrentList(provider);
  }

  Widget _buildTorrentList(TorrentProvider provider) {
    if (provider.loading && provider.torrents.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }

    if (provider.torrents.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.cloud_download, size: 64, color: Colors.grey),
              const SizedBox(height: 16),
              const Text('暂无 BT 下载任务',
                  style: TextStyle(fontSize: 16, color: Colors.grey)),
              const SizedBox(height: 8),
              Text(
                '点击下方按钮导入 .torrent 文件\n开始 BT 下载',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 13, color: Colors.grey[500]),
              ),
            ],
          ),
        ),
      );
    }

    return RefreshIndicator(
      onRefresh: () => provider.syncTorrents(),
      child: ListView.builder(
        padding: const EdgeInsets.only(bottom: 80),
        itemCount: provider.torrents.length,
        itemBuilder: (_, i) {
          final file = provider.torrents[i];
          return ListTile(
            leading: const Icon(Icons.cloud_download, color: Colors.blue),
            title: Text(file.name),
            subtitle:
                Text('${_formatSize(file.size)}  ·  ${_formatTime(file.addedAt)}'),
            onTap: () => provider.openTorrent(file),
            onLongPress: () => _showActions(file),
          );
        },
      ),
    );
  }

  String _formatSize(int bytes) {
    if (bytes < 1024) return '$bytes B';
    if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
    return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
  }

  String _formatTime(DateTime dt) {
    return '${dt.month}/${dt.day} ${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
  }

  String _formatSpeed(double bytesPerSec) {
    if (bytesPerSec < 1024) return '${bytesPerSec.toStringAsFixed(0)} B/s';
    if (bytesPerSec < 1024 * 1024) {
      return '${(bytesPerSec / 1024).toStringAsFixed(1)} KB/s';
    }
    return '${(bytesPerSec / (1024 * 1024)).toStringAsFixed(1)} MB/s';
  }
}
