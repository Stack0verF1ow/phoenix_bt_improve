import '../models/device_info.dart';

class QRService {
  static DeviceInfo? parseQRContent(String content) {
    return DeviceInfo.parseQR(content);
  }

  /// Build a PHX:// QR content string from DeviceInfo.
  static String buildQRContent(DeviceInfo device) {
    final name = Uri.encodeComponent(device.name);
    final hosts = device.hosts.join(',');
    return 'PHX://v=${device.version}&t=${device.type}'
        '&n=$name&h=$hosts&p=${device.port}&k=${device.tokenPrefix}';
  }
}
