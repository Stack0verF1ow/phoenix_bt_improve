import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:provider/provider.dart';

import '../providers/connection_provider.dart';
import '../services/qr_service.dart';
import '../services/settings_service.dart';

class ScanScreen extends StatefulWidget {
  const ScanScreen({super.key});

  @override
  State<ScanScreen> createState() => _ScanScreenState();
}

class _ScanScreenState extends State<ScanScreen> {
  final MobileScannerController _controller = MobileScannerController();
  bool _processing = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _onDetect(BarcodeCapture capture) async {
    if (_processing) return;
    final barcode = capture.barcodes.firstOrNull;
    if (barcode == null) return;

    final raw = barcode.rawValue;
    if (raw == null || raw.isEmpty) return;

    final device = QRService.parseQRContent(raw);
    if (device == null) {
      _showError('无效的二维码：不是 PHX:// 协议');
      return;
    }

    _processing = true;
    final provider = context.read<ConnectionProvider>();
    final localName = context.read<SettingsService>().deviceName;
    final ok = await provider.connect(device, localName: localName);

    if (!mounted) return;

    if (ok) {
      context.pushReplacement('/device');
    } else {
      _showError(provider.error ?? '连接失败');
      _processing = false;
    }
  }

  void _showError(String msg) {
    if (!mounted) return;
    // Provide helpful hint for connection timeout
    final display = msg.contains('timeout') || msg.contains('Timeout')
        ? '$msg\n\n提示：如果是手机热点模式，请关闭移动数据后重试'
        : msg;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(display),
        backgroundColor: Colors.red,
        duration: const Duration(seconds: 6),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('扫描二维码')),
      body: Stack(
        children: [
          MobileScanner(
            controller: _controller,
            onDetect: _onDetect,
          ),
          Center(
            child: Container(
              width: 250,
              height: 250,
              decoration: BoxDecoration(
                border: Border.all(color: Colors.white, width: 2),
                borderRadius: BorderRadius.circular(16),
              ),
            ),
          ),
          if (_processing)
            const Center(child: CircularProgressIndicator()),
          Positioned(
            bottom: 80,
            left: 0,
            right: 0,
            child: Text(
              '扫描电脑上的 PHX:// 二维码',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: Colors.white.withValues(alpha: 0.9),
                fontSize: 16,
                shadows: [
                  Shadow(
                    color: Colors.black.withValues(alpha: 0.5),
                    blurRadius: 8,
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
