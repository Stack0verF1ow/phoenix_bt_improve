import 'dart:io';

import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../config/app_config.dart';

class SettingsService {
  static const _keyDeviceName = 'device_name';
  static const _keyPort = 'listen_port';

  late SharedPreferences _prefs;
  String _downloadDir = '';

  Future<void> load() async {
    _prefs = await SharedPreferences.getInstance();
    if (Platform.isAndroid) {
      // Use external storage so files are accessible to file managers
      final dir = await getExternalStorageDirectory();
      _downloadDir = dir?.path ?? (await getApplicationDocumentsDirectory()).path;
    } else {
      final dir = await getApplicationDocumentsDirectory();
      _downloadDir = dir.path;
    }
  }

  String get deviceName =>
      _prefs.getString(_keyDeviceName) ?? Platform.localHostname;

  int get port => _prefs.getInt(_keyPort) ?? AppConfig.defaultPort;

  String get downloadDir => _downloadDir;

  Future<void> saveDeviceName(String name) async {
    await _prefs.setString(_keyDeviceName, name);
  }

  Future<void> savePort(int port) async {
    await _prefs.setInt(_keyPort, port);
  }
}
