import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app.dart';
import 'core/storage.dart';
import 'services/notifications.dart';
import 'state/session.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final storage = await AppStorage.open();
  await initNotifications();
  runApp(ProviderScope(overrides: [storageProvider.overrideWithValue(storage)], child: const FireEvacApp()));
}
