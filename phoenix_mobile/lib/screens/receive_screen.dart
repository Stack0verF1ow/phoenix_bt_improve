import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:qr_flutter/qr_flutter.dart';

import '../providers/server_provider.dart';
import '../services/settings_service.dart';

class ReceiveScreen extends StatefulWidget {
  const ReceiveScreen({super.key});

  @override
  State<ReceiveScreen> createState() => _ReceiveScreenState();
}

class _ReceiveScreenState extends State<ReceiveScreen> {
  late final String _deviceName;
  late final int _listenPort;

  @override
  void initState() {
    super.initState();
    final settings = context.read<SettingsService>();
    _deviceName = settings.deviceName;
    _listenPort = settings.port;
  }

  @override
  void dispose() {
    // Stop server when leaving the screen
    final server = context.read<ServerProvider>();
    if (server.running) server.stopServer();
    super.dispose();
  }

  Future<void> _pickSharedFiles() async {
    final result = await FilePicker.platform.pickFiles(allowMultiple: true);
    if (result != null) {
      final paths = result.paths.whereType<String>().toList();
      context.read<ServerProvider>().addSharedFiles(paths);
    }
  }

  @override
  Widget build(BuildContext context) {
    final server = context.watch<ServerProvider>();
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(title: const Text('接收文件')),
      body: server.running
          ? _buildRunningUI(server, theme)
          : _buildStoppedUI(theme),
    );
  }

  Widget _buildStoppedUI(ThemeData theme) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.wifi_tethering, size: 64, color: Colors.green),
            const SizedBox(height: 16),
            const Text(
              '开启接收模式，让其他设备扫码传输文件',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 16),
            ),
            const SizedBox(height: 24),
            ElevatedButton.icon(
              onPressed: () {
                context.read<ServerProvider>().startServer(
                      _listenPort,
                      _deviceName,
                    );
              },
              icon: const Icon(Icons.play_arrow),
              label: const Text('开启接收'),
              style: ElevatedButton.styleFrom(
                padding:
                    const EdgeInsets.symmetric(horizontal: 32, vertical: 16),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildRunningUI(ServerProvider server, ThemeData theme) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // QR Code + info
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                children: [
                  QrImageView(
                    data: server.qrContent,
                    version: QrVersions.auto,
                    size: 220,
                  ),
                  const SizedBox(height: 16),
                  Text('设备: $_deviceName',
                      style: const TextStyle(fontSize: 16)),
                  const SizedBox(height: 4),
                  Text('端口: $_listenPort',
                      style: TextStyle(color: Colors.grey[600])),
                  const SizedBox(height: 4),
                  Text(
                    'IP: ${server.lanIPs.join(", ")}',
                    style: TextStyle(color: Colors.grey[600], fontSize: 12),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 12),

          // Transfer progress
          if (server.currentFileName != null) ...[
            Card(
              color: theme.colorScheme.primaryContainer,
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('正在接收: ${server.currentFileName}',
                        style: const TextStyle(fontWeight: FontWeight.w600)),
                    const SizedBox(height: 8),
                    LinearProgressIndicator(value: server.progress),
                    if (server.speedText.isNotEmpty) ...[
                      const SizedBox(height: 4),
                      Text(server.speedText,
                          style: TextStyle(
                              fontSize: 12, color: Colors.grey[700])),
                    ],
                  ],
                ),
              ),
            ),
            const SizedBox(height: 12),
          ],

          // Connected devices
          if (server.connectedDevices.isNotEmpty) ...[
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('已连接设备',
                        style: theme.textTheme.titleSmall),
                    const SizedBox(height: 8),
                    for (final dev in server.connectedDevices)
                      Padding(
                        padding: const EdgeInsets.symmetric(vertical: 2),
                        child: Row(
                          children: [
                            const Icon(Icons.phone_android, size: 16),
                            const SizedBox(width: 8),
                            Text(dev),
                          ],
                        ),
                      ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 12),
          ],

          // Received files
          if (server.receivedFiles.isNotEmpty) ...[
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Text('已接收文件',
                            style: theme.textTheme.titleSmall),
                        const Spacer(),
                        TextButton(
                          onPressed: server.clearReceivedFiles,
                          child: const Text('清空'),
                        ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    for (final file in server.receivedFiles.reversed)
                      Padding(
                        padding: const EdgeInsets.symmetric(vertical: 2),
                        child: Row(
                          children: [
                            const Icon(Icons.insert_drive_file, size: 16),
                            const SizedBox(width: 8),
                            Expanded(child: Text(file.name)),
                          ],
                        ),
                      ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 12),
          ],

          // Shared files
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Text('共享文件', style: theme.textTheme.titleSmall),
                      const Spacer(),
                      TextButton.icon(
                        onPressed: _pickSharedFiles,
                        icon: const Icon(Icons.add, size: 16),
                        label: const Text('选择'),
                      ),
                      if (server.sharedFiles.isNotEmpty)
                        TextButton(
                          onPressed: server.clearSharedFiles,
                          child: const Text('清空'),
                        ),
                    ],
                  ),
                  if (server.sharedFiles.isEmpty)
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 8),
                      child: Text('无共享文件',
                          style: TextStyle(color: Colors.grey[500])),
                    )
                  else
                    for (final path in server.sharedFiles)
                      Padding(
                        padding: const EdgeInsets.symmetric(vertical: 2),
                        child: Row(
                          children: [
                            const Icon(Icons.insert_drive_file, size: 16),
                            const SizedBox(width: 8),
                            Expanded(
                              child: Text(
                                path.split(Platform.pathSeparator).last,
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                            IconButton(
                              icon: const Icon(Icons.close, size: 16),
                              onPressed: () =>
                                  server.removeSharedFile(path),
                            ),
                          ],
                        ),
                      ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 16),

          // Stop button
          OutlinedButton.icon(
            onPressed: server.stopServer,
            icon: const Icon(Icons.stop),
            label: const Text('停止接收'),
            style: OutlinedButton.styleFrom(foregroundColor: Colors.red),
          ),
        ],
      ),
    );
  }
}
