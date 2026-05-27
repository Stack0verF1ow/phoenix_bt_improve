import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';
import 'package:provider/provider.dart';

import '../models/server_status.dart';
import '../providers/connection_provider.dart';
import '../providers/transfer_provider.dart';

class DownloadScreen extends StatefulWidget {
  const DownloadScreen({super.key});

  @override
  State<DownloadScreen> createState() => _DownloadScreenState();
}

class _DownloadScreenState extends State<DownloadScreen> {
  @override
  void initState() {
    super.initState();
    _loadFiles();
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
    if (file.isDir) return;

    final conn = context.read<ConnectionProvider>();
    final client = conn.client;
    if (client == null) return;

    final transfer = context.read<TransferProvider>();
    transfer.setDownloadState(TransferState.uploading);

    try {
      final dir = await getApplicationDocumentsDirectory();
      final savePath = await client.downloadFile(
        file.path,
        dir.path,
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
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('下载失败: $e'), backgroundColor: Colors.red),
      );
    }
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
              child: Text('正在下载...',
                  style: TextStyle(color: Colors.grey[600])),
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
              padding: const EdgeInsets.all(8),
              child: Text(transfer.downloadError!,
                  style: const TextStyle(color: Colors.red)),
            ),
          Expanded(
            child: transfer.loadingFiles
                ? const Center(child: CircularProgressIndicator())
                : transfer.files.isEmpty
                    ? const Center(child: Text('没有可下载的文件'))
                    : RefreshIndicator(
                        onRefresh: _loadFiles,
                        child: ListView.builder(
                          itemCount: transfer.files.length,
                          itemBuilder: (_, i) {
                            final file = transfer.files[i];
                            return ListTile(
                              leading: Icon(
                                file.isDir
                                    ? Icons.folder
                                    : Icons.insert_drive_file,
                                color:
                                    file.isDir ? Colors.amber : Colors.blue,
                              ),
                              title: Text(file.name),
                              subtitle: file.isDir
                                  ? null
                                  : Text(_formatSize(file.size)),
                              trailing: file.isDir
                                  ? null
                                  : IconButton(
                                      icon: busy
                                          ? const SizedBox(
                                              width: 18,
                                              height: 18,
                                              child:
                                                  CircularProgressIndicator(
                                                      strokeWidth: 2),
                                            )
                                          : const Icon(Icons.download),
                                      onPressed: busy
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
