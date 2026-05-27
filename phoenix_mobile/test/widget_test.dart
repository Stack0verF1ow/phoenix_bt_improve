import 'package:flutter_test/flutter_test.dart';

import 'package:phoenix_mobile/app.dart';

void main() {
  testWidgets('App renders home screen', (WidgetTester tester) async {
    await tester.pumpWidget(const PhoenixHelperApp());
    expect(find.text('Phoenix Helper'), findsOneWidget);
    expect(find.text('连接电脑'), findsOneWidget);
    expect(find.text('发送给手机'), findsOneWidget);
    expect(find.text('设置'), findsOneWidget);
  });
}
