import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../services/settings_service.dart';
import '../utils/file_logger.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late TextEditingController _nameController;
  late TextEditingController _portController;

  @override
  void initState() {
    super.initState();
    final settings = context.read<SettingsService>();
    _nameController = TextEditingController(text: settings.deviceName);
    _portController = TextEditingController(text: settings.port.toString());
  }

  @override
  void dispose() {
    _nameController.dispose();
    _portController.dispose();
    super.dispose();
  }

  Future<void> _saveSettings() async {
    final settings = context.read<SettingsService>();
    final name = _nameController.text.trim();
    final port = int.tryParse(_portController.text);

    if (name.isNotEmpty) {
      await settings.saveDeviceName(name);
    }
    if (port != null && port >= 1024 && port <= 65535) {
      await settings.savePort(port);
    }

    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('设置已保存')),
    );
    Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    final settings = context.read<SettingsService>();

    return Scaffold(
      appBar: AppBar(title: const Text('设置')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          TextField(
            controller: _nameController,
            decoration: const InputDecoration(
              labelText: '设备名称',
              border: OutlineInputBorder(),
              helperText: '其他设备扫码时将显示此名称',
            ),
          ),
          const SizedBox(height: 24),
          TextField(
            controller: _portController,
            decoration: const InputDecoration(
              labelText: '接收端口',
              border: OutlineInputBorder(),
              helperText: '用于接收文件的端口号 (1024-65535)',
            ),
            keyboardType: TextInputType.number,
          ),
          const SizedBox(height: 24),
          Row(
            children: [
              Expanded(
                child: InputDecorator(
                  decoration: const InputDecoration(
                    labelText: '下载保存位置',
                    border: OutlineInputBorder(),
                    helperText: '文件下载后保存在此目录',
                  ),
                  child: Text(
                    settings.downloadDir,
                    style: TextStyle(color: Colors.grey[600], fontSize: 13),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              IconButton(
                icon: const Icon(Icons.copy),
                tooltip: '复制路径',
                onPressed: () {
                  Clipboard.setData(ClipboardData(text: settings.downloadDir));
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('路径已复制')),
                  );
                },
              ),
            ],
          ),
          const SizedBox(height: 32),
          SizedBox(
            width: double.infinity,
            child: ElevatedButton(
              onPressed: _saveSettings,
              style: ElevatedButton.styleFrom(
                padding: const EdgeInsets.symmetric(vertical: 16),
              ),
              child: const Text('保存'),
            ),
          ),
          const SizedBox(height: 24),
          const Divider(),
          ListTile(
            leading: const Icon(Icons.bug_report),
            title: const Text('查看调试日志'),
            subtitle: Text(FileLogger.filePath ?? '未初始化',
                style: const TextStyle(fontSize: 11)),
            onTap: () async {
              final content = await FileLogger.readAll();
              if (!context.mounted) return;
              Navigator.of(context).push(MaterialPageRoute(
                builder: (_) => _LogViewerScreen(content: content),
              ));
            },
          ),
        ],
      ),
    );
  }
}

class _LogViewerScreen extends StatelessWidget {
  final String content;
  const _LogViewerScreen({required this.content});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('调试日志'),
        actions: [
          IconButton(
            icon: const Icon(Icons.copy),
            tooltip: '复制全部',
            onPressed: () {
              Clipboard.setData(ClipboardData(text: content));
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(content: Text('日志已复制到剪贴板')),
              );
            },
          ),
          IconButton(
            icon: const Icon(Icons.delete_outline),
            tooltip: '清空日志',
            onPressed: () async {
              await FileLogger.clear();
              if (context.mounted) Navigator.of(context).pop();
            },
          ),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(12),
        child: SelectableText(
          content.isEmpty ? '(日志为空)' : content,
          style: const TextStyle(fontFamily: 'monospace', fontSize: 11),
        ),
      ),
    );
  }
}
