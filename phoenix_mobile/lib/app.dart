import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import 'theme/app_theme.dart';

import 'providers/connection_provider.dart';
import 'providers/server_provider.dart';
import 'providers/torrent_provider.dart';
import 'providers/transfer_provider.dart';
import 'screens/device_screen.dart';
import 'screens/home_screen.dart';
import 'screens/receive_screen.dart';
import 'screens/scan_screen.dart';
import 'screens/settings_screen.dart';
import 'services/settings_service.dart';

final _router = GoRouter(
  initialLocation: '/',
  onException: (context, state, router) {
    // Ignore content:// and file:// URIs from Android intents
    router.go('/');
  },
  routes: [
    GoRoute(path: '/', builder: (_, __) => const HomeScreen()),
    GoRoute(path: '/scan', builder: (_, __) => const ScanScreen()),
    GoRoute(path: '/device', builder: (_, __) => const DeviceScreen()),
    GoRoute(path: '/receive', builder: (_, __) => const ReceiveScreen()),
    GoRoute(path: '/settings', builder: (_, __) => const SettingsScreen()),
  ],
);

class PhoenixHelperApp extends StatelessWidget {
  final SettingsService settings;
  const PhoenixHelperApp({super.key, required this.settings});

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        Provider.value(value: settings),
        ChangeNotifierProvider(create: (_) => ConnectionProvider()),
        ChangeNotifierProvider(create: (_) => TransferProvider()),
        ChangeNotifierProvider(create: (_) => ServerProvider()),
        ChangeNotifierProvider(create: (_) => TorrentProvider()),
      ],
      child: MaterialApp.router(
        title: 'Phoenix Helper',
        theme: AppTheme.lightTheme(),
        darkTheme: AppTheme.darkTheme(),
        routerConfig: _router,
        debugShowCheckedModeBanner: false,
      ),
    );
  }
}
