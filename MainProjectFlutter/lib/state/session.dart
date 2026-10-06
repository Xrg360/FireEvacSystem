import 'dart:async';

import 'package:device_info_plus/device_info_plus.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:package_info_plus/package_info_plus.dart';

import '../core/api.dart';
import '../core/storage.dart';
import '../services/notifications.dart';
import '../shared/models.dart';

/// Overridden in main() with the opened storage.
final storageProvider = Provider<AppStorage>((ref) => throw UnimplementedError('storage not opened'));

final apiProvider = Provider<Api>((ref) {
  final storage = ref.watch(storageProvider);
  return Api(storage, onSessionExpired: () => ref.read(sessionProvider.notifier).expired());
});

enum SessionStatus { loading, needsServer, loggedOut, pending, ready }

class SessionState {
  const SessionState({required this.status, this.user, this.buildingName, this.buildingMode, this.societyName, this.error});
  final SessionStatus status;
  final AppUser? user;
  final String? buildingName;
  final String? buildingMode;
  final String? societyName;
  final String? error;

  SessionState copyWith({SessionStatus? status, AppUser? user, String? buildingName, String? buildingMode, String? societyName, String? error}) =>
      SessionState(
        status: status ?? this.status,
        user: user ?? this.user,
        buildingName: buildingName ?? this.buildingName,
        buildingMode: buildingMode ?? this.buildingMode,
        societyName: societyName ?? this.societyName,
        error: error,
      );
}

final sessionProvider = NotifierProvider<SessionController, SessionState>(SessionController.new);

class SessionController extends Notifier<SessionState> {
  AppStorage get _storage => ref.read(storageProvider);
  Api get _api => ref.read(apiProvider);
  StreamSubscription<String>? _tokenSub;

  @override
  SessionState build() {
    ref.onDispose(() => _tokenSub?.cancel());
    Future.microtask(restore);
    return const SessionState(status: SessionStatus.loading);
  }

  Future<void> restore() async {
    if (_storage.serverUrl.isEmpty) {
      state = const SessionState(status: SessionStatus.needsServer);
      return;
    }
    if (await _storage.accessToken == null) {
      state = const SessionState(status: SessionStatus.loggedOut);
      return;
    }
    await refreshMe();
  }

  Future<void> refreshMe() async {
    try {
      final me = await _api.get('/auth/me');
      final user = AppUser.fromJson(me['user'] as Map<String, dynamic>);
      final building = me['building'] as Map<String, dynamic>?;
      state = SessionState(
        status: user.approved ? SessionStatus.ready : SessionStatus.pending,
        user: user,
        buildingName: building?['name'] as String?,
        buildingMode: building?['mode'] as String?,
        societyName: (me['society'] as Map<String, dynamic>?)?['name'] as String?,
      );
      if (user.approved) unawaited(_registerPush());
    } on ApiException catch (e) {
      if (e.isOffline) {
        // keep the user signed in while offline; cached graph + offline routing still work
        state = state.copyWith(status: state.user == null ? SessionStatus.ready : state.status, error: e.message);
      } else {
        await _storage.clearTokens();
        state = SessionState(status: SessionStatus.loggedOut, error: e.message);
      }
    }
  }

  Future<void> setServer(String url) async {
    await _storage.setServerUrl(url);
    await restore();
  }

  Future<String?> login(String email, String password) async {
    final device = await _deviceInfo();
    try {
      final r = await _api.post('/auth/login', {'email': email.trim(), 'password': password, 'device': device}, true);
      await _storage.saveTokens(r['access_token'] as String, r['refresh_token'] as String);
      final deviceId = r['device_id'] as String?;
      if (deviceId != null) await _storage.setDeviceId(deviceId);
      await refreshMe();
      return null;
    } on ApiException catch (e) {
      return e.message;
    }
  }

  Future<String?> register(Map<String, dynamic> body) async {
    try {
      await _api.post('/auth/register', body, true);
      return login(body['email'] as String, body['password'] as String);
    } on ApiException catch (e) {
      return e.message;
    }
  }

  Future<void> logout() async {
    final refresh = await _storage.refreshToken;
    if (refresh != null) {
      try {
        await _api.post('/auth/logout', {'refresh_token': refresh}, true);
      } catch (_) {}
    }
    await _storage.clearTokens();
    state = const SessionState(status: SessionStatus.loggedOut);
  }

  void expired() {
    _storage.clearTokens();
    state = const SessionState(status: SessionStatus.loggedOut, error: 'Your session expired. Please sign in again.');
  }

  Future<Map<String, dynamic>> _deviceInfo() async {
    String? model;
    String? version;
    try {
      final a = await DeviceInfoPlugin().androidInfo;
      model = '${a.manufacturer} ${a.model}';
    } catch (_) {}
    try {
      version = (await PackageInfo.fromPlatform()).version;
    } catch (_) {}
    return {'platform': 'android', 'model': model, 'app_version': version, 'device_id': _storage.deviceId};
  }

  Future<void> _registerPush() async {
    final token = await fcmToken();
    if (token == null) return;
    try {
      await _api.post('/devices/fcm', {'fcm_token': token});
    } catch (_) {}
    _tokenSub ??= fcmTokenRefresh.listen((t) => _api.post('/devices/fcm', {'fcm_token': t}).catchError((_) => <String, dynamic>{}));
  }
}
