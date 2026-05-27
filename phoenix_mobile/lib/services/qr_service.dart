import '../models/device_info.dart';

class QRService {
  static DeviceInfo? parseQRContent(String content) {
    return DeviceInfo.parseQR(content);
  }
}
