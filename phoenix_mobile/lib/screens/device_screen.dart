import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../providers/connection_provider.dart';
import '../providers/transfer_provider.dart';
import 'upload_screen.dart';
import 'download_screen.dart';

class DeviceScreen extends StatefulWidget {
  const DeviceScreen({super.key});

  @override
  State<DeviceScreen> createState() => _DeviceScreenState();
}

class _DeviceScreenState extends State<DeviceScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<ConnectionProvider>().refreshStatus();
    });
  }

  @override
  Widget build(BuildContext context) {
    final conn = context.watch<ConnectionProvider>();
    final device = conn.device;
    final status = conn.status;

    if (!conn.connected || device == null) {
      return Scaffold(
        appBar: AppBar(title: const Text('设备')),
        body: const Center(child: Text('未连接')),
      );
    }

    return Scaffold(
      appBar: AppBar(
        title: Text(device.name),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () => conn.refreshStatus(),
          ),
          IconButton(
            icon: const Icon(Icons.link_off),
            onPressed: () {
              conn.disconnect();
              context.read<TransferProvider>().reset();
              context.pushReplacement('/');
            },
          ),
        ],
      ),
      body: Column(
        children: [
          _StatusCard(device: device, status: status),
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: _ActionButton(
                  icon: Icons.upload_file,
                  label: '上传到电脑',
                  onTap: () => _navigateToUpload(context),
                ),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: _ActionButton(
                  icon: Icons.download,
                  label: '从电脑下载',
                  onTap: () => _navigateToDownload(context),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  void _navigateToUpload(BuildContext context) {
    Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => const UploadScreen()),
    );
  }

  void _navigateToDownload(BuildContext context) {
    Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => const DownloadScreen()),
    );
  }
}

class _StatusCard extends StatelessWidget {
  final dynamic device;
  final dynamic status;

  const _StatusCard({required this.device, required this.status});

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.all(16),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('设备信息',
                style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            _InfoRow(label: '名称', value: device.name),
            _InfoRow(label: 'IP', value: device.primaryHost),
            _InfoRow(label: '端口', value: '${device.port}'),
            if (status != null) ...[
              const Divider(),
              Text('服务器状态',
                  style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 8),
              _InfoRow(
                  label: 'uTorrent',
                  value: status.utorrentAvailable ? '可用' : '不可用'),
              _InfoRow(
                  label: '金凤登录',
                  value: status.phoenixLoggedIn ? '已登录' : '未登录'),
            ],
          ],
        ),
      ),
    );
  }
}

class _InfoRow extends StatelessWidget {
  final String label;
  final String value;

  const _InfoRow({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        children: [
          SizedBox(
            width: 80,
            child: Text(label,
                style: TextStyle(color: Colors.grey[600], fontSize: 14)),
          ),
          Expanded(child: Text(value, style: const TextStyle(fontSize: 14))),
        ],
      ),
    );
  }
}

class _ActionButton extends StatelessWidget {
  final IconData icon;
  final String label;
  final VoidCallback onTap;

  const _ActionButton({
    required this.icon,
    required this.label,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 16),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 24, horizontal: 16),
          child: Column(
            children: [
              Icon(icon, size: 40, color: Theme.of(context).colorScheme.primary),
              const SizedBox(height: 8),
              Text(label, style: const TextStyle(fontSize: 16)),
            ],
          ),
        ),
      ),
    );
  }
}
