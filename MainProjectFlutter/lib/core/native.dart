import 'package:flutter/services.dart';

/// Small Android-only helpers implemented in MainActivity.kt.
class NativeBridge {
  static const _ch = MethodChannel('fire_evac/native');

  /// Keep the screen on while the evacuation screen is open.
  static Future<void> keepScreenOn(bool on) async {
    try {
      await _ch.invokeMethod('keepScreenOn', {'on': on});
    } catch (_) {}
  }

  /// Android 14+: full-screen alarms over the lock screen need a special permission.
  static Future<bool> canUseFullScreenIntent() async {
    try {
      return await _ch.invokeMethod<bool>('canUseFullScreenIntent') ?? true;
    } catch (_) {
      return true;
    }
  }

  static Future<void> openFullScreenIntentSettings() async {
    try {
      await _ch.invokeMethod('openFullScreenIntentSettings');
    } catch (_) {}
  }

  /// Manufacturer, used to show "allow autostart" instructions on aggressive OEMs.
  static Future<String> manufacturer() async {
    try {
      return (await _ch.invokeMethod<String>('manufacturer') ?? '').toLowerCase();
    } catch (_) {
      return '';
    }
  }
}
