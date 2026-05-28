import 'dart:io';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:qr_flutter/qr_flutter.dart';

import '../config/app_config.dart';
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
  HttpServer? _server;
  bool _running = false;
  String _qrContent = '';
  List<String> _lanIPs = [];

  @override
  void dispose() {
    _stopServer();
    super.dispose();
  }

  void _buildQRContent() {
    final name = Uri.encodeComponent(_deviceName);
    final token = 'dev${DateTime.now().millisecondsSinceEpoch.toString().substring(8)}';
    setState(() {
      _qrContent =
          'PHX://v=1&t=${AppConfig.deviceTypePhone}&n=$name&h=${_lanIPs.join(",")}&p=$_listenPort&k=${token.substring(0, 6)}';
    });
  }

  Future<List<String>> _getLANIPs() async {
    try {
      final interfaces = await NetworkInterface.list();
      final ips = <String>[];
      for (final iface in interfaces) {
        for (final addr in iface.addresses) {
          if (addr.type == InternetAddressType.IPv4 &&
              !addr.isLoopback &&
              !addr.address.startsWith('169.254.')) {
            ips.add(addr.address);
          }
        }
      }
      return ips;
    } catch (_) {
      return ['127.0.0.1'];
    }
  }

  Future<void> _startServer() async {
    try {
      _server = await HttpServer.bind(
        InternetAddress.anyIPv4,
        _listenPort,
      );

      _lanIPs = await _getLANIPs();
      _buildQRContent();

      setState(() => _running = true);

      _server!.listen((request) {
        request.response
          ..statusCode = 200
          ..headers.set('Content-Type', 'application/json')
          ..write('{"status":"ok","device":"$_deviceName"}')
          ..close();
      });
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('启动服务器失败: $e'), backgroundColor: Colors.red),
      );
    }
  }

  void _stopServer() {
    _server?.close();
    _server = null;
    setState(() => _running = false);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('接收文件')),
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              if (!_running) ...[
                const Icon(Icons.wifi_tethering, size: 64, color: Colors.green),
                const SizedBox(height: 16),
                const Text('开启后展示二维码，让其他设备扫码连接',
                    textAlign: TextAlign.center),
                const SizedBox(height: 24),
                ElevatedButton.icon(
                  onPressed: _startServer,
                  icon: const Icon(Icons.play_arrow),
                  label: const Text('开启接收'),
                  style: ElevatedButton.styleFrom(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 32, vertical: 16),
                  ),
                ),
              ] else ...[
                QrImageView(
                  data: _qrContent,
                  version: QrVersions.auto,
                  size: 260,
                ),
                const SizedBox(height: 24),
                Text('设备: $_deviceName',
                    style: const TextStyle(fontSize: 16)),
                const SizedBox(height: 8),
                Text('端口: $_listenPort',
                    style: TextStyle(color: Colors.grey[600])),
                const SizedBox(height: 16),
                Text('等待其他设备扫码连接...',
                    style: TextStyle(color: Colors.grey[500])),
                const SizedBox(height: 24),
                OutlinedButton.icon(
                  onPressed: _stopServer,
                  icon: const Icon(Icons.stop),
                  label: const Text('停止接收'),
                  style: OutlinedButton.styleFrom(foregroundColor: Colors.red),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
