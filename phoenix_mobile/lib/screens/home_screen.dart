import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../theme/app_colors.dart';
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
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Column(
          children: [
            const SizedBox(height: 8),
            Text(
              '选择操作',
              style: theme.textTheme.headlineSmall?.copyWith(
                fontWeight: FontWeight.bold,
              ),
            ),
            const SizedBox(height: 20),
            _ActionCard(
              icon: Icons.qr_code_scanner,
              title: '扫码连接',
              subtitle: '扫码连接电脑或其他手机，传输文件',
              color: AppColors.cardScan,
              onTap: () => context.push('/scan'),
            ),
            _ActionCard(
              icon: Icons.wifi_tethering,
              title: '发送给手机',
              subtitle: '开启接收模式，让其他设备扫码传输文件',
              color: AppColors.cardReceive,
              onTap: () => context.push('/receive'),
            ),
            _ActionCard(
              icon: Icons.settings,
              title: '设置',
              subtitle: '设备名称、端口等配置',
              color: AppColors.cardSettings,
              onTap: () => context.push('/settings'),
            ),
            _ActionCard(
              icon: Icons.folder_open,
              title: '已下载列表',
              subtitle: '查看、打开、管理已下载的文件',
              color: AppColors.cardFiles,
              onTap: () => Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => const DownloadedFilesScreen()),
              ),
            ),
            _ActionCard(
              icon: Icons.cloud_download,
              title: 'BT 下载',
              subtitle: '导入 .torrent 文件，使用内置引擎下载',
              color: AppColors.cardTorrent,
              onTap: () => Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => const TorrentScreen()),
              ),
            ),
            const SizedBox(height: 16),
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
    final theme = Theme.of(context);
    return Card(
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
          child: Row(
            children: [
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: color.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Icon(icon, color: color, size: 28),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: theme.textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      subtitle,
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
              Icon(Icons.chevron_right, color: theme.colorScheme.outline),
            ],
          ),
        ),
      ),
    );
  }
}
