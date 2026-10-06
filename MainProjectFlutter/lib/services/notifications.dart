import 'dart:async';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';

/// Push alarms: the server sends a high-priority FCM *data* message; the app turns it into a
/// full-screen, alarm-category notification that shows over the lock screen and opens the
/// alarm screen. Push is optional - without a Firebase project the socket still delivers alarms
/// while the app is open.

const alarmChannelId = 'fire_alarm';
const _infoChannelId = 'fire_info';
final FlutterLocalNotificationsPlugin _local = FlutterLocalNotificationsPlugin();

/// Tap on a notification (or launch from one) -> app navigates to the alarm screen.
final StreamController<Map<String, String>> alarmTaps = StreamController.broadcast();

bool firebaseReady = false;

@pragma('vm:entry-point')
Future<void> firebaseBackgroundHandler(RemoteMessage message) async {
  await Firebase.initializeApp();
  await _initLocal();
  await showIncidentNotification(message.data);
}

Future<void> _initLocal() async {
  await _local.initialize(
    settings: const InitializationSettings(android: AndroidInitializationSettings('@mipmap/ic_launcher')),
    onDidReceiveNotificationResponse: (resp) => alarmTaps.add({'payload': resp.payload ?? ''}),
  );
  final android = _local.resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>();
  await android?.createNotificationChannel(
    const AndroidNotificationChannel(
      alarmChannelId,
      'Fire alarms',
      description: 'Full-screen evacuation alarms',
      importance: Importance.max,
      bypassDnd: true,
      audioAttributesUsage: AudioAttributesUsage.alarm,
    ),
  );
  await android?.createNotificationChannel(
    const AndroidNotificationChannel(_infoChannelId, 'Evacuation updates', importance: Importance.high),
  );
}

/// Initialise local notifications and (if configured) Firebase Messaging.
Future<void> initNotifications() async {
  await _initLocal();
  final launch = await _local.getNotificationAppLaunchDetails();
  if (launch?.didNotificationLaunchApp ?? false) {
    scheduleMicrotask(() => alarmTaps.add({'payload': launch!.notificationResponse?.payload ?? ''}));
  }
  try {
    await Firebase.initializeApp();
    FirebaseMessaging.onBackgroundMessage(firebaseBackgroundHandler);
    await FirebaseMessaging.instance.setForegroundNotificationPresentationOptions(alert: false, sound: false);
    FirebaseMessaging.onMessage.listen((m) => showIncidentNotification(m.data));
    FirebaseMessaging.onMessageOpenedApp.listen((m) => alarmTaps.add(m.data.map((k, v) => MapEntry(k, '$v'))));
    final initial = await FirebaseMessaging.instance.getInitialMessage();
    if (initial != null) scheduleMicrotask(() => alarmTaps.add(initial.data.map((k, v) => MapEntry(k, '$v'))));
    firebaseReady = true;
  } catch (e) {
    // No google-services.json: push disabled, socket alarms still work while the app is open.
    debugPrint('Firebase not configured, push disabled: $e');
    firebaseReady = false;
  }
}

Future<String?> fcmToken() async {
  if (!firebaseReady) return null;
  try {
    return await FirebaseMessaging.instance.getToken();
  } catch (_) {
    return null;
  }
}

Stream<String> get fcmTokenRefresh => firebaseReady ? FirebaseMessaging.instance.onTokenRefresh : const Stream.empty();

Future<void> showIncidentNotification(Map<String, dynamic> data) async {
  final active = data['status'] == null || data['status'] == 'evacuating' || data['status'] == 'detected';
  final title = (data['title'] ?? (active ? 'FIRE - evacuate now' : 'All clear')).toString();
  final body = (data['body'] ?? 'Open the app for your safest route out.').toString();
  if (!active) {
    await _local.show(
      id: 2,
      title: title,
      body: body,
      notificationDetails: const NotificationDetails(android: AndroidNotificationDetails(_infoChannelId, 'Evacuation updates')),
    );
    await _local.cancel(id: 1);
    return;
  }
  await _local.show(
    id: 1,
    title: title,
    body: body,
    payload: 'incident:${data['incident_id'] ?? ''}',
    notificationDetails: const NotificationDetails(
      android: AndroidNotificationDetails(
        alarmChannelId,
        'Fire alarms',
        importance: Importance.max,
        priority: Priority.max,
        category: AndroidNotificationCategory.alarm,
        fullScreenIntent: true,
        ongoing: true,
        autoCancel: false,
        audioAttributesUsage: AudioAttributesUsage.alarm,
        visibility: NotificationVisibility.public,
      ),
    ),
  );
}

Future<void> cancelAlarmNotification() => _local.cancel(id: 1);

Future<bool> requestNotificationPermissions() async {
  final android = _local.resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>();
  final granted = await android?.requestNotificationsPermission() ?? true;
  if (firebaseReady) {
    await FirebaseMessaging.instance.requestPermission();
  }
  return granted;
}

Future<void> requestFullScreenIntentPermission() async {
  final android = _local.resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>();
  await android?.requestFullScreenIntentPermission();
}
