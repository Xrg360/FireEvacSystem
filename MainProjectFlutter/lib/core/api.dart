import 'package:dio/dio.dart';

import 'storage.dart';

class ApiException implements Exception {
  ApiException(this.status, this.message, [this.detail]);
  final int? status;
  final String message;
  final Object? detail;

  bool get isOffline => status == null;

  @override
  String toString() => message;
}

/// REST client for the Flask API. Attaches the JWT and refreshes it once on 401.
class Api {
  Api(this.storage, {this.onSessionExpired}) {
    dio = Dio(BaseOptions(connectTimeout: const Duration(seconds: 6), receiveTimeout: const Duration(seconds: 10)));
    dio.interceptors.add(
      QueuedInterceptorsWrapper(
        onRequest: (options, handler) async {
          options.baseUrl = '${storage.serverUrl}/api';
          final token = await storage.accessToken;
          if (token != null && options.extra['noAuth'] != true) options.headers['Authorization'] = 'Bearer $token';
          handler.next(options);
        },
        onError: (err, handler) async {
          final retried = err.requestOptions.extra['retried'] == true;
          if (err.response?.statusCode == 401 && !retried && err.requestOptions.extra['noAuth'] != true) {
            if (await _refresh()) {
              final opts = err.requestOptions..extra['retried'] = true;
              opts.headers['Authorization'] = 'Bearer ${await storage.accessToken}';
              try {
                return handler.resolve(await dio.fetch(opts));
              } on DioException catch (e) {
                return handler.next(e);
              }
            }
            onSessionExpired?.call();
          }
          handler.next(err);
        },
      ),
    );
  }

  final AppStorage storage;
  final void Function()? onSessionExpired;
  late final Dio dio;

  Future<bool> _refresh() async {
    final refresh = await storage.refreshToken;
    if (refresh == null) return false;
    try {
      final r = await Dio(BaseOptions(baseUrl: '${storage.serverUrl}/api'))
          .post<Map<String, dynamic>>('/auth/refresh', data: {'refresh_token': refresh});
      await storage.saveTokens(r.data!['access_token'] as String, r.data!['refresh_token'] as String);
      return true;
    } catch (_) {
      return false;
    }
  }

  /// Fresh access token for the socket handshake (refreshing if the stored one is rejected).
  Future<String?> freshToken() async {
    try {
      await get('/auth/me');
    } catch (_) {}
    return storage.accessToken;
  }

  Future<Map<String, dynamic>> get(String path, {Map<String, dynamic>? query}) =>
      _wrap(() => dio.get<dynamic>(path, queryParameters: query));

  Future<Map<String, dynamic>> post(String path, [Object? body, bool noAuth = false]) =>
      _wrap(() => dio.post<dynamic>(path, data: body ?? {}, options: Options(extra: {'noAuth': noAuth})));

  Future<Map<String, dynamic>> _wrap(Future<Response<dynamic>> Function() call) async {
    try {
      final r = await call();
      final data = r.data;
      if (data is Map<String, dynamic>) return data;
      return {'data': data};
    } on DioException catch (e) {
      final res = e.response;
      if (res == null) {
        throw ApiException(null, 'Cannot reach the evacuation server');
      }
      final body = res.data;
      final message = body is Map && body['message'] != null ? body['message'].toString() : 'Request failed (${res.statusCode})';
      throw ApiException(res.statusCode, message, body is Map ? body['detail'] : null);
    }
  }

  /// Checks that a URL points at the evacuation server.
  static Future<bool> ping(String baseUrl) async {
    try {
      final r = await Dio(BaseOptions(connectTimeout: const Duration(seconds: 4)))
          .get<Map<String, dynamic>>('${baseUrl.replaceAll(RegExp(r'/+$'), '')}/api/health');
      return r.data?['status'] == 'ok';
    } catch (_) {
      return false;
    }
  }
}
