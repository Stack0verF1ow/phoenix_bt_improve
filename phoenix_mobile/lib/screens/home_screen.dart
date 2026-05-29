import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import 'downloaded_files_screen.dart';
import 'torrent_screen.dart';

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Phoenix Helper'),
        centerTitle: true,
      ),
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          children: [
            const SizedBox(height: 24),
            Text(
              '选择操作',
              style: theme.textTheme.headlineSmall?.copyWith(
                fontWeight: FontWeight.bold,
              ),
            ),
            const SizedBox(height: 32),
            _ActionCard(
              icon: Icons.qr_code_scanner,
              title: '连接电脑',
              subtitle: '扫码连接电脑，传输文件',
              color: Colors.blue,
              onTap: () => context.push('/scan'),
            ),
            const SizedBox(height: 16),
            _ActionCard(
              icon: Icons.wifi_tethering,
              title: '发送给手机',
              subtitle: '开启接收模式，让其他设备扫码传输文件',
              color: Colors.green,
              onTap: () => context.push('/receive'),
            ),
            const SizedBox(height: 16),
            _ActionCard(
              icon: Icons.settings,
              title: '设置',
              subtitle: '设备名称、端口等配置',
              color: Colors.grey[600]!,
              onTap: () => context.push('/settings'),
            ),
            const SizedBox(height: 16),
            _ActionCard(
              icon: Icons.folder_open,
              title: '已下载列表',
              subtitle: '查看、打开、管理已下载的文件',
              color: Colors.orange,
              onTap: () => Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => const DownloadedFilesScreen()),
              ),
            ),
            const SizedBox(height: 16),
            _ActionCard(
              icon: Icons.cloud_download,
              title: 'BT 下载',
              subtitle: '导入 .torrent 文件，使用 uTorrent 下载',
              color: Colors.teal,
              onTap: () => Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => const TorrentScreen()),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ActionCard extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final Color color;
  final VoidCallback onTap;

  const _ActionCard({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.color,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      elevation: 2,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Row(
            children: [
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: color.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Icon(icon, color: color, size: 32),
              ),
              const SizedBox(width: 20),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: const TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      subtitle,
                      style: TextStyle(
                        fontSize: 14,
                        color: Colors.grey[600],
                      ),
                    ),
                  ],
                ),
              ),
              Icon(Icons.chevron_right, color: Colors.grey[400]),
            ],
          ),
        ),
      ),
    );
  }
}
