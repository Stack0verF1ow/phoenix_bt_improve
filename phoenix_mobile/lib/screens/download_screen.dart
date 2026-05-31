import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/server_status.dart';
import '../providers/connection_provider.dart';
import '../providers/transfer_provider.dart';
import '../services/settings_service.dart';
import '../utils/file_logger.dart';
import '../utils/format_utils.dart';

class DownloadScreen extends StatefulWidget {
  const DownloadScreen({super.key});

  @override
  State<DownloadScreen> createState() => _DownloadScreenState();
}

class _DownloadScreenState extends State<DownloadScreen> {
  Timer? _errorTimer;
  String? _downloadingFilePath;
  bool _userCancelled = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _loadFiles();
      context.read<ConnectionProvider>().onFilesChanged = _onFilesChanged;
    });
  }

  void _onFilesChanged() {
    if (!mounted) return;
    _loadFiles();
  }

  @override
  void dispose() {
    _errorTimer?.cancel();
    // Clean up callback to avoid stale references
    try {
      context.read<ConnectionProvider>().onFilesChanged = null;
    } catch (_) {}
    super.dispose();
  }

  /// Check if a partial file exists for the given remote path.
  String? _getPartialFilePath(String remotePath, int remoteSize) {
    final dir = context.read<SettingsService>().downloadDir;
    final name = remotePath.contains('\\')
        ? remotePath.split('\\').last
        : remotePath.split('/').last;
    final path = '$dir/$name';
    final f = File(path);
    if (f.existsSync() && f.lengthSync() > 0) {
      if (remoteSize > 0 && f.lengthSync() >= remoteSize) {
        return null;
      }
      FileLogger.log('[_getPartialFilePath] found partial: $path (${f.lengthSync()} bytes)');
      return path;
    }
    return null;
  }

  String _formatPartialSize(String path) {
    final size = File(path).lengthSync();
    return formatSize(size);
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

    final settings = context.read<SettingsService>();
    final name = file.path.contains('\\')
        ? file.path.split('\\').last
        : file.path.split('/').last;
    final localPath = '${settings.downloadDir}/$name';
    final localFile = File(localPath);
    if (localFile.existsSync() && localFile.lengthSync() >= file.size && file.size > 0) {
      final transfer = context.read<TransferProvider>();
      transfer.markDownloaded(file.path);
      transfer.setDownloadState(TransferState.done);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('文件已存在: $localPath'),
          backgroundColor: Colors.green,
          duration: const Duration(seconds: 3),
        ),
      );
      return;
    }

    final transfer = context.read<TransferProvider>();
    _userCancelled = false;
    setState(() => _downloadingFilePath = file.path);
    conn.setTransferring(true);
    transfer.setDownloadState(TransferState.uploading);

    try {
      final savePath = await client.downloadFile(
        file.path,
        settings.downloadDir,
        expectedSize: file.size,
        onProgress: (received, total) {
          if (total > 0) {
            transfer.setDownloadProgress((received / total).clamp(0.0, 1.0));
          }
          transfer.updateDownloadSpeed(received, total > 0 ? total : received);
        },
      );

      transfer.setDownloadState(TransferState.done);
      transfer.markDownloaded(file.path);

      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('下载完成: $savePath'),
          backgroundColor: Colors.green,
          duration: const Duration(seconds: 4),
        ),
      );
    } catch (e) {
      FileLogger.log('[_downloadFile] caught error: _userCancelled=$_userCancelled, error=$e');
      if (_userCancelled) {
        // User cancelled — don't show error, just reset state
        FileLogger.log('[_downloadFile] user cancelled, setting idle');
        transfer.setDownloadState(TransferState.idle);
      } else {
        transfer.setDownloadError(e.toString());
        _errorTimer?.cancel();
        _errorTimer = Timer(const Duration(seconds: 5), () {
          if (mounted) transfer.clearDownloadError();
        });
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('下载失败: $e'), backgroundColor: Colors.red),
        );
      }
    } finally {
      conn.setTransferring(false);
      if (mounted) setState(() => _downloadingFilePath = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    final transfer = context.watch<TransferProvider>();
    final busy = transfer.downloadState == TransferState.uploading;
    final device = context.watch<ConnectionProvider>().device;
    final isPC = device?.isPC ?? true;

    return Scaffold(
      appBar: AppBar(
        title: Text(isPC ? '从电脑下载' : '从手机下载'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: busy ? null : _loadFiles,
          ),
        ],
      ),
      body: Column(
        children: [
          if (busy || transfer.downloadState == TransferState.paused) ...[
            LinearProgressIndicator(value: transfer.downloadProgress),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                        transfer.isDownloadPaused ? '已暂停' : '正在下载...',
                        style: TextStyle(color: Colors.grey[600])),
                  ),
                  if (transfer.downloadSpeedText.isNotEmpty && !transfer.isDownloadPaused)
                    Text(transfer.downloadSpeedText,
                        style: TextStyle(color: Colors.grey[600], fontSize: 13)),
                  const SizedBox(width: 8),
                  SizedBox(
                    height: 28,
                    child: TextButton(
                      onPressed: () {
                        final client = context.read<ConnectionProvider>().client;
                        if (client == null) return;
                        transfer.toggleDownloadPause();
                        if (transfer.isDownloadPaused) {
                          client.pauseDownload();
                        } else {
                          client.resumeDownload();
                        }
                      },
                      style: TextButton.styleFrom(
                        padding: const EdgeInsets.symmetric(horizontal: 8),
                        foregroundColor: transfer.isDownloadPaused ? Colors.green : Colors.orange,
                        textStyle: const TextStyle(fontSize: 12),
                      ),
                      child: Text(transfer.isDownloadPaused ? '继续' : '暂停'),
                    ),
                  ),
                  SizedBox(
                    height: 28,
                    child: TextButton(
                      onPressed: () {
                        FileLogger.log('[Cancel] setting _userCancelled=true, cancelling token');
                        _userCancelled = true;
                        context.read<ConnectionProvider>().client?.cancelDownload();
                      },
                      style: TextButton.styleFrom(
                        padding: const EdgeInsets.symmetric(horizontal: 8),
                        foregroundColor: Colors.red,
                        textStyle: const TextStyle(fontSize: 12),
                      ),
                      child: const Text('取消'),
                    ),
                  ),
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
                    ? Center(
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            const Icon(Icons.folder_open, size: 64, color: Colors.grey),
                            const SizedBox(height: 16),
                            Text(isPC ? '电脑端尚未选择文件' : '对方尚未选择文件',
                                style: const TextStyle(color: Colors.grey)),
                            const SizedBox(height: 8),
                            Text(isPC ? '请在电脑端点击"选择文件"后刷新' : '请对方选择共享文件后刷新',
                                style: TextStyle(color: Colors.grey[500], fontSize: 12)),
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
                            final partialPath = _getPartialFilePath(file.path, file.size);
                            final hasPartial = partialPath != null;
                            final isDone = transfer.downloadedFiles.contains(file.path);
                            return ListTile(
                              leading: Icon(
                                isDone ? Icons.check_circle : Icons.insert_drive_file,
                                color: isDone ? Colors.green : Colors.blue,
                              ),
                              title: Text(file.name),
                              subtitle: Text(
                                hasPartial && !isDone
                                    ? '可续传 · 已下载 ${_formatPartialSize(partialPath)} / ${formatSize(file.size)}'
                                    : formatSize(file.size),
                                style: TextStyle(
                                  fontSize: 12,
                                  color: hasPartial && !isDone
                                      ? Colors.orange
                                      : null,
                                ),
                              ),
                              trailing: isDone
                                  ? const Icon(Icons.check_circle,
                                      color: Colors.green)
                                  : IconButton(
                                      icon: isDownloading
                                          ? const SizedBox(
                                              width: 18,
                                              height: 18,
                                              child:
                                                  CircularProgressIndicator(
                                                      strokeWidth: 2),
                                            )
                                          : Icon(
                                              hasPartial
                                                  ? Icons.downloading
                                                  : Icons.download,
                                              color: hasPartial
                                                  ? Colors.orange
                                                  : null,
                                            ),
                                      onPressed: (busy ||
                                              _downloadingFilePath != null)
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

}
