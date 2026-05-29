import 'dart:io';

/// Try connecting to each host:port, return the first reachable one.
Future<String?> probeReachableHost(
  List<String> hosts,
  int port, {
  Duration timeout = const Duration(seconds: 3),
}) async {
  for (final host in hosts) {
    try {
      final socket = await Socket.connect(host, port, timeout: timeout);
      socket.destroy();
      return host;
    } catch (_) {
      continue;
    }
  }
  return null;
}
