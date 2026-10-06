import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Tokens live in the Android keystore (secure storage); everything else in shared prefs.
class AppStorage {
  AppStorage(this._prefs);

  static const _secure = FlutterSecureStorage();
  final SharedPreferences _prefs;

  static Future<AppStorage> open() async => AppStorage(await SharedPreferences.getInstance());

  // ---- server -------------------------------------------------------------
  static const defaultServer = String.fromEnvironment('API_URL', defaultValue: '');

  String get serverUrl => _prefs.getString('server_url') ?? defaultServer;
  Future<void> setServerUrl(String url) => _prefs.setString('server_url', url.trim().replaceAll(RegExp(r'/+$'), ''));

  // ---- session ------------------------------------------------------------
  Future<String?> get accessToken => _secure.read(key: 'access_token');
  Future<String?> get refreshToken => _secure.read(key: 'refresh_token');

  Future<void> saveTokens(String access, String refresh) async {
    await _secure.write(key: 'access_token', value: access);
    await _secure.write(key: 'refresh_token', value: refresh);
  }

  Future<void> clearTokens() async {
    await _secure.delete(key: 'access_token');
    await _secure.delete(key: 'refresh_token');
  }

  /// Device id issued by the server on first login; reused so the install keeps one identity.
  String? get deviceId => _prefs.getString('device_id');
  Future<void> setDeviceId(String id) => _prefs.setString('device_id', id);

  // ---- offline cache (graph + last known hazards/route) --------------------
  Map<String, dynamic>? readJson(String key) {
    final raw = _prefs.getString('cache:$key');
    if (raw == null) return null;
    try {
      return jsonDecode(raw) as Map<String, dynamic>;
    } catch (_) {
      return null;
    }
  }

  Future<void> writeJson(String key, Map<String, dynamic> value) => _prefs.setString('cache:$key', jsonEncode(value));

  // ---- queued actions while offline ---------------------------------------
  List<Map<String, dynamic>> get pendingActions {
    final raw = _prefs.getStringList('pending_actions') ?? const [];
    return raw.map((e) => jsonDecode(e) as Map<String, dynamic>).toList();
  }

  Future<void> setPendingActions(List<Map<String, dynamic>> actions) =>
      _prefs.setStringList('pending_actions', actions.map(jsonEncode).toList());

  bool flag(String key) => _prefs.getBool('flag:$key') ?? false;
  Future<void> setFlag(String key, bool value) => _prefs.setBool('flag:$key', value);
}
