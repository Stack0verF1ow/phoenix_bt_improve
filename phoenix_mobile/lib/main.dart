import 'package:flutter/material.dart';

import 'app.dart';
import 'services/settings_service.dart';
import 'utils/file_logger.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await FileLogger.init();
  final settings = SettingsService();
  await settings.load();
  runApp(PhoenixHelperApp(settings: settings));
}
