import 'dart:async';

import 'package:flutter/material.dart';
import 'package:open_filex/open_filex.dart';
import 'package:provider/provider.dart';

import '../models/server_status.dart';
import '../providers/connection_provider.dart';
import '../providers/transfer_provider.dart';
import '../services/settings_service.dart';

class DownloadScreen extends StatefulWidget {
  const DownloadScreen({super.key});

  @override
  State<DownloadScreen> createState() => _DownloadScreenState();
}

class _DownloadScreenState extends State<DownloadScreen> {
  Timer? _errorTimer;
  String? _downloadingFilePath;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _loadFiles());
  }

  @override
  void dispose() {
    _errorTimer?.cancel();
    super.dispose();
  }

  Future<void> _loadFiles() async {
    final conn = context.read<ConnectionProvider>();
    final client = conn.client;
    if (client == null) return;

    final transfer = context.read<TransferProvider>();
    transfer.setLoadingFiles(true);

    try {
      final files = await client.listFiles();
      transfer.setFiles(files);
    } catch (e) {
      transfer.setLoadingFiles(false);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('加载文件列表失败: $e')),
      );
    }
  }

  Future<void> _downloadFile(FileEntry file) async {
    final conn = context.read<ConnectionProvider>();
    final client = conn.client;
    if (client == null) return;

    final transfer = context.read<TransferProvider>();
    setState(() => _downloadingFilePath = file.path);
    conn.setTransferring(true);
    transfer.setDownloadState(TransferState.uploading);

    try {
      final settings = context.read<SettingsService>();
      final savePath = await client.downloadFile(
        file.path,
        settings.downloadDir,
        onProgress: (received, total) {
          if (total > 0) {
            transfer.setDownloadProgress((received / total).clamp(0.0, 1.0));
          }
          transfer.updateDownloadSpeed(received, total > 0 ? total : received);
        },
      );

      transfer.setDownloadState(TransferState.done);

      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('下载完成: $savePath'),
          backgroundColor: Colors.green,
          duration: const Duration(seconds: 4),
        ),
      );
    } catch (e) {
      transfer.setDownloadError(e.toString());
      _errorTimer?.cancel();
      _errorTimer = Timer(const Duration(seconds: 5), () {
        if (mounted) transfer.clearDownloadError();
      });
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('下载失败: $e'), backgroundColor: Colors.red),
      );
    } finally {
      conn.setTransferring(false);
      if (mounted) setState(() => _downloadingFilePath = null);
    }
  }

  void _openFileManager() {
    final dir = context.read<SettingsService>().downloadDir;
    OpenFilex.open(dir);
  }

  @override
  Widget build(BuildContext context) {
    final transfer = context.watch<TransferProvider>();
    final busy = transfer.downloadState == TransferState.uploading;

    return Scaffold(
      appBar: AppBar(
        title: const Text('从电脑下载'),
        actions: [
          IconButton(
            icon: const Icon(Icons.folder_open),
            tooltip: '打开下载目录',
            onPressed: _openFileManager,
          ),
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: busy ? null : _loadFiles,
          ),
        ],
      ),
      body: Column(
        children: [
          if (busy) ...[
            LinearProgressIndicator(value: transfer.downloadProgress),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              child: Row(
                children: [
                  Expanded(
                    child: Text('正在下载...',
                        style: TextStyle(color: Colors.grey[600])),
                  ),
                  if (transfer.downloadSpeedText.isNotEmpty)
                    Text(transfer.downloadSpeedText,
                        style: TextStyle(color: Colors.grey[600], fontSize: 13)),
                ],
              ),
            ),
          ],
          if (transfer.downloadState == TransferState.done)
            const Padding(
              padding: EdgeInsets.all(8),
              child: Text('下载完成!',
                  style: TextStyle(color: Colors.green)),
            ),
          if (transfer.downloadError != null)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              child: Row(
                children: [
                  Expanded(
                    child: Text(transfer.downloadError!,
                        style: const TextStyle(color: Colors.red)),
                  ),
                  IconButton(
                    icon: const Icon(Icons.close, size: 18),
                    onPressed: () => transfer.clearDownloadError(),
                  ),
                ],
              ),
            ),
          Expanded(
            child: transfer.loadingFiles
                ? const Center(child: CircularProgressIndicator())
                : transfer.files.isEmpty
                    ? const Center(
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Icon(Icons.folder_open, size: 64, color: Colors.grey),
                            SizedBox(height: 16),
                            Text('电脑端尚未选择文件',
                                style: TextStyle(color: Colors.grey)),
                            SizedBox(height: 8),
                            Text('请在电脑端点击"选择文件"后刷新',
                                style: TextStyle(color: Colors.grey, fontSize: 12)),
                          ],
                        ),
                      )
                    : RefreshIndicator(
                        onRefresh: _loadFiles,
                        child: ListView.builder(
                          itemCount: transfer.files.length,
                          itemBuilder: (_, i) {
                            final file = transfer.files[i];
                            final isDownloading = _downloadingFilePath == file.path;
                            return ListTile(
                              leading: const Icon(Icons.insert_drive_file,
                                  color: Colors.blue),
                              title: Text(file.name),
                              subtitle: Text(_formatSize(file.size)),
                              trailing: IconButton(
                                icon: isDownloading
                                    ? const SizedBox(
                                        width: 18,
                                        height: 18,
                                        child: CircularProgressIndicator(
                                            strokeWidth: 2),
                                      )
                                    : const Icon(Icons.download),
                                onPressed: (busy || _downloadingFilePath != null)
                                    ? null
                                    : () => _downloadFile(file),
                              ),
                            );
                          },
                        ),
                      ),
          ),
        ],
      ),
    );
  }

  String _formatSize(int bytes) {
    if (bytes < 1024) return '$bytes B';
    if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
    return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
  }
}
