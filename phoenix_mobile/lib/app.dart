import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import 'providers/connection_provider.dart';
import 'providers/transfer_provider.dart';
import 'screens/device_screen.dart';
import 'screens/home_screen.dart';
import 'screens/receive_screen.dart';
import 'screens/scan_screen.dart';
import 'screens/settings_screen.dart';

final _router = GoRouter(
  initialLocation: '/',
  routes: [
    GoRoute(path: '/', builder: (_, __) => const HomeScreen()),
    GoRoute(path: '/scan', builder: (_, __) => const ScanScreen()),
    GoRoute(path: '/device', builder: (_, __) => const DeviceScreen()),
    GoRoute(path: '/receive', builder: (_, __) => const ReceiveScreen()),
    GoRoute(path: '/settings', builder: (_, __) => const SettingsScreen()),
  ],
);

class PhoenixHelperApp extends StatelessWidget {
  const PhoenixHelperApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider(create: (_) => ConnectionProvider()),
        ChangeNotifierProvider(create: (_) => TransferProvider()),
      ],
      child: MaterialApp.router(
        title: 'Phoenix Helper',
        theme: ThemeData(
          colorSchemeSeed: Colors.blue,
          useMaterial3: true,
          brightness: Brightness.light,
        ),
        darkTheme: ThemeData(
          colorSchemeSeed: Colors.blue,
          useMaterial3: true,
          brightness: Brightness.dark,
        ),
        routerConfig: _router,
        debugShowCheckedModeBanner: false,
      ),
    );
  }
}
