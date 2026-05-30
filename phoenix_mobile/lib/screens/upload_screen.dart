import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/connection_provider.dart';
import '../providers/transfer_provider.dart';
import '../services/file_service.dart';

class UploadScreen extends StatefulWidget {
  const UploadScreen({super.key});

  @override
  State<UploadScreen> createState() => _UploadScreenState();
}

class _UploadScreenState extends State<UploadScreen> {
  List<_SelectedFile> _selectedFiles = [];
  bool _autoSeed = false;
  final _titleController = TextEditingController();
  Timer? _errorTimer;

  @override
  void dispose() {
    _errorTimer?.cancel();
    _titleController.dispose();
    super.dispose();
  }

  Future<void> _pickFiles() async {
    final files = await FileService.pickFiles();
    if (files.isNotEmpty) {
      setState(() {
        _selectedFiles = files
            .map((f) => _SelectedFile(
                  name: f.name,
                  size: f.size,
                  bytes: f.bytes,
                  path: f.path,
                ))
            .toList();
      });
    }
  }

  Future<void> _startUpload() async {
    if (_selectedFiles.isEmpty) return;

    final conn = context.read<ConnectionProvider>();
    final client = conn.client;
    if (client == null) return;

    final transfer = context.read<TransferProvider>();
    conn.setTransferring(true);
    transfer.setState(TransferState.preparing);

    try {
      final filesMap = <String, Map<String, dynamic>>{};
      for (int i = 0; i < _selectedFiles.length; i++) {
        final f = _selectedFiles[i];
        filesMap['file$i'] = {
          'name': f.name,
          'size': f.size,
          'type': 'application/octet-stream',
        };
      }

      transfer.setStatus('正在准备上传...');
      final session = await client.prepareUpload(filesMap);

      transfer.setState(TransferState.uploading);
      int totalBytes = _selectedFiles.fold(0, (sum, f) => sum + f.size);
      int sentBytes = 0;

      for (int i = 0; i < _selectedFiles.length; i++) {
        final f = _selectedFiles[i];
        final fid = 'file$i';
        final token = session.fileTokens[fid];
        if (token == null) continue;

        transfer.setStatus('正在上传: ${f.name}');

        if (f.path != null && f.size > 0) {
          final chunkSize = session.chunkSize;
          final totalChunks = (f.size + chunkSize - 1) ~/ chunkSize;
          transfer.setChunkedState(ChunkedUploadState(
            sessionId: session.sessionId,
            fileId: fid,
            token: token,
            filePath: f.path!,
            fileSize: f.size,
            chunkSize: chunkSize,
            totalChunks: totalChunks,
          ));

          await client.uploadFileChunked(
            sessionId: session.sessionId,
            fileId: fid,
            token: token,
            filePath: f.path!,
            fileSize: f.size,
            chunkSize: chunkSize,
            shouldPause: () => transfer.isPaused,
            onProgress: (sent, total) {
              final current = sentBytes + sent;
              transfer.setProgress((current / totalBytes).clamp(0.0, 1.0));
              transfer.updateUploadSpeed(current, totalBytes);
            },
            onChunkComplete: (idx, total) {
              transfer.setStatus('正在上传: ${f.name} (${idx + 1}/$total)');
            },
          );
          transfer.setChunkedState(null);
          sentBytes += f.size;
        } else {
          final bytes = await _readBytes(f);
          final fileSentBefore = sentBytes;
          await client.uploadFile(
            sessionId: session.sessionId,
            fileId: fid,
            token: token,
            bytes: bytes,
            onProgress: (sent, total) {
              final current = fileSentBefore + sent;
              transfer.setProgress((current / totalBytes).clamp(0.0, 1.0));
              transfer.updateUploadSpeed(current, totalBytes);
            },
          );
          sentBytes += bytes.length;
        }
        transfer.setProgress((sentBytes / totalBytes).clamp(0.0, 1.0));
      }

      transfer.setStatus('正在确认...');
      transfer.setState(TransferState.confirming);
      await client.confirmSeed(
        sessionId: session.sessionId,
        autoSeed: _autoSeed,
        title: _titleController.text.isNotEmpty ? _titleController.text : '',
      );

      transfer.setState(TransferState.done);
      transfer.setStatus('上传完成');

      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('上传成功！'), backgroundColor: Colors.green),
      );
      Navigator.of(context).pop();
    } catch (e) {
      final t = context.read<TransferProvider>();
      if (t.chunkedState?.isPaused == true) {
        return;
      }
      t.setError(e.toString());
      _errorTimer?.cancel();
      _errorTimer = Timer(const Duration(seconds: 5), () {
        if (mounted) t.clearUploadError();
      });
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('上传失败: $e'), backgroundColor: Colors.red),
      );
    } finally {
      conn.setTransferring(false);
    }
  }

  Future<List<int>> _readBytes(_SelectedFile file) async {
    if (file.bytes != null) return file.bytes!;
    if (file.path != null) {
      return await File(file.path!).readAsBytes();
    }
    return [];
  }

  @override
  Widget build(BuildContext context) {
    final transfer = context.watch<TransferProvider>();
    final busy = transfer.state == TransferState.preparing ||
        transfer.state == TransferState.uploading ||
        transfer.state == TransferState.confirming ||
        transfer.state == TransferState.paused;

    final device = context.watch<ConnectionProvider>().device;
    final isPC = device?.isPC ?? true;

    return Scaffold(
      appBar: AppBar(title: Text(isPC ? '上传到电脑' : '上传到手机')),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            OutlinedButton.icon(
              onPressed: busy ? null : _pickFiles,
              icon: const Icon(Icons.attach_file),
              label: const Text('选择文件'),
            ),
            const SizedBox(height: 12),
            if (_selectedFiles.isNotEmpty) ...[
              Text('已选择 ${_selectedFiles.length} 个文件',
                  style: const TextStyle(fontWeight: FontWeight.w500)),
              const SizedBox(height: 4),
              Expanded(
                child: ListView.builder(
                  itemCount: _selectedFiles.length,
                  itemBuilder: (_, i) => ListTile(
                    dense: true,
                    leading: const Icon(Icons.insert_drive_file),
                    title: Text(_selectedFiles[i].name),
                    trailing: Text(
                      _formatSize(_selectedFiles[i].size),
                      style: TextStyle(color: Colors.grey[600], fontSize: 12),
                    ),
                  ),
                ),
              ),
            ],
            CheckboxListTile(
              title: const Text('自动做种'),
              subtitle: Text(
                '勾选后将自动制种并上传到金凤，鼓励分享资源',
                style: TextStyle(color: Colors.grey[500], fontSize: 12),
              ),
              value: _autoSeed,
              onChanged: busy ? null : (v) => setState(() => _autoSeed = v ?? false),
            ),
            if (_autoSeed)
              TextField(
                controller: _titleController,
                decoration: const InputDecoration(
                  labelText: '资源标题（可选）',
                  border: OutlineInputBorder(),
                ),
              ),
            const SizedBox(height: 16),
            if (transfer.state == TransferState.uploading ||
        transfer.state == TransferState.paused) ...[
              LinearProgressIndicator(value: transfer.progress),
              const SizedBox(height: 8),
              Row(
                children: [
                  Expanded(
                    child: Text(transfer.statusText,
                        style: TextStyle(color: Colors.grey[600])),
                  ),
                  if (transfer.speedText.isNotEmpty)
                    Text(transfer.speedText,
                        style: TextStyle(color: Colors.grey[600], fontSize: 13)),
                  const SizedBox(width: 8),
                  if (transfer.state == TransferState.uploading ||
                      transfer.state == TransferState.paused) ...[
                    SizedBox(
                      height: 28,
                      child: TextButton(
                        onPressed: () => transfer.togglePause(),
                        style: TextButton.styleFrom(
                          padding: const EdgeInsets.symmetric(horizontal: 8),
                          foregroundColor: transfer.isPaused ? Colors.green : Colors.orange,
                          textStyle: const TextStyle(fontSize: 12),
                        ),
                        child: Text(transfer.isPaused ? '继续' : '暂停'),
                      ),
                    ),
                  ],
                  SizedBox(
                    height: 28,
                    child: TextButton(
                      onPressed: () {
                        context.read<ConnectionProvider>().client?.cancelUpload();
                        context.read<TransferProvider>().setState(TransferState.idle);
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
            ] else if (transfer.state == TransferState.confirming) ...[
              const LinearProgressIndicator(),
              const SizedBox(height: 8),
              Text(transfer.statusText,
                  style: TextStyle(color: Colors.grey[600])),
            ] else if (transfer.state == TransferState.done) ...[
              const SizedBox(height: 8),
              Row(
                children: [
                  const Icon(Icons.check_circle, color: Colors.green, size: 20),
                  const SizedBox(width: 8),
                  Text(transfer.statusText,
                      style: const TextStyle(color: Colors.green)),
                ],
              ),
            ],
            if (transfer.state == TransferState.error)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Row(
                  children: [
                    Expanded(
                      child: Text(transfer.error ?? '未知错误',
                          style: const TextStyle(color: Colors.red)),
                    ),
                    IconButton(
                      icon: const Icon(Icons.close, size: 18),
                      onPressed: () => transfer.clearUploadError(),
                    ),
                  ],
                ),
              ),
            const Spacer(),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton.icon(
                onPressed: busy ? null : _startUpload,
                icon: busy
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.cloud_upload),
                label: Text(busy ? '上传中...' : '开始上传'),
                style: ElevatedButton.styleFrom(
                  padding: const EdgeInsets.symmetric(vertical: 16),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  String _formatSize(int bytes) {
    if (bytes < 1024) return '$bytes B';
    if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
    return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
  }
}

class _SelectedFile {
  final String name;
  final int size;
  final List<int>? bytes;
  final String? path;

  _SelectedFile({
    required this.name,
    required this.size,
    this.bytes,
    this.path,
  });
}