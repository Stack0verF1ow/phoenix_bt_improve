import '../config/app_config.dart';

class DeviceInfo {
  final int version;
  final String type;
  final String name;
  final List<String> hosts;
  final int port;
  final String tokenPrefix;

  DeviceInfo({
    required this.version,
    required this.type,
    required this.name,
    required this.hosts,
    required this.port,
    required this.tokenPrefix,
  });

  String get primaryHost => hosts.isNotEmpty ? hosts[0] : '127.0.0.1';
  String get baseUrl => 'http://$primaryHost:$port';

  bool get isPC => type == 'pc';

  @override
  String toString() =>
      'DeviceInfo(name: $name, type: $type, hosts: $hosts, port: $port)';

  static DeviceInfo? parseQR(String content) {
    if (!content.startsWith('PHX://')) return null;
    try {
      final query = content.substring(6);
      final params = <String, String>{};
      for (final part in query.split('&')) {
        final eq = part.indexOf('=');
        if (eq == -1) continue;
        params[part.substring(0, eq)] = Uri.decodeComponent(part.substring(eq + 1));
      }
      return DeviceInfo(
        version: int.tryParse(params['v'] ?? '') ?? 1,
        type: params['t'] ?? 'pc',
        name: params['n'] ?? 'Unknown',
        hosts: (params['h'] ?? '').split(',').where((s) => s.isNotEmpty).toList(),
        port: int.tryParse(params['p'] ?? '') ?? AppConfig.defaultPort,
        tokenPrefix: params['k'] ?? '',
      );
    } catch (_) {
      return null;
    }
  }
}
