import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../providers/connection_provider.dart';
import '../providers/transfer_provider.dart';
import '../services/settings_service.dart';
import 'upload_screen.dart';
import 'download_screen.dart';

class DeviceScreen extends StatefulWidget {
  const DeviceScreen({super.key});

  @override
  State<DeviceScreen> createState() => _DeviceScreenState();
}

class _DeviceScreenState extends State<DeviceScreen> {
  bool _showingLostDialog = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<ConnectionProvider>().refreshStatus();
    });
  }

  void _checkServerLost(ConnectionProvider conn) {
    if (conn.serverLost && !_showingLostDialog) {
      _showingLostDialog = true;
      showDialog(
        context: context,
        barrierDismissible: false,
        builder: (_) => AlertDialog(
          title: const Text('连接断开'),
          content: const Text('电脑端已停止服务或网络断开'),
          actions: [
            TextButton(
              onPressed: () async {
                Navigator.of(context).pop();
                conn.clearServerLost();
                await conn.disconnect();
                if (!mounted) return;
                context.read<TransferProvider>().reset();
                context.go('/');
              },
              child: const Text('返回首页'),
            ),
          ],
        ),
      ).then((_) {
        _showingLostDialog = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final conn = context.watch<ConnectionProvider>();
    final device = conn.device;
    final status = conn.status;

    // Check for server loss
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _checkServerLost(conn);
    });

    if (!conn.connected || device == null) {
      return Scaffold(
        appBar: AppBar(title: const Text('设备')),
        body: const Center(child: Text('未连接')),
      );
    }

    final localName = context.read<SettingsService>().deviceName;

    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) async {
        if (didPop) return;
        await conn.disconnect();
        if (!mounted) return;
        context.read<TransferProvider>().reset();
        context.go('/');
      },
      child: Scaffold(
      appBar: AppBar(
        title: Text(localName),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () => conn.refreshStatus(),
          ),
          IconButton(
            icon: const Icon(Icons.link_off),
            onPressed: () async {
              await conn.disconnect();
              if (!mounted) return;
              context.read<TransferProvider>().reset();
              context.go('/');
            },
          ),
        ],
      ),
      body: Column(
        children: [
          _StatusCard(device: device, status: status, localName: localName),
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
      ),
    );
  }

  void _navigateToUpload(BuildContext context) async {
    await Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => const UploadScreen()),
    );
    // Refresh status immediately after returning from upload
    if (mounted) {
      context.read<ConnectionProvider>().refreshStatus();
    }
  }

  void _navigateToDownload(BuildContext context) async {
    await Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => const DownloadScreen()),
    );
    // Refresh status immediately after returning from download
    if (mounted) {
      context.read<ConnectionProvider>().refreshStatus();
    }
  }
}

class _StatusCard extends StatelessWidget {
  final dynamic device;
  final dynamic status;
  final String localName;

  const _StatusCard({
    required this.device,
    required this.status,
    required this.localName,
  });

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
            _InfoRow(label: '本机', value: localName),
            _InfoRow(label: '连接到', value: device.name),
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
