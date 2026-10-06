import 'dart:async';

import 'package:socket_io_client/socket_io_client.dart' as io;

/// Socket.IO connection to the evacuation server (paper §VI: WebSocket publish/subscribe).
///
/// Server -> phone events: incident.updated, route.assigned, route.cleared, route.none,
/// position.fix, hazards. Phone -> server: scan, gps, manual_location, floor_confirm.
class SocketService {
  SocketService({required this.serverUrl, required this.tokenProvider});

  final String serverUrl;
  final Future<String?> Function() tokenProvider;
  io.Socket? _socket;

  final _events = StreamController<(String, Map<String, dynamic>)>.broadcast();
  final _connected = StreamController<bool>.broadcast();
  bool isConnected = false;

  Stream<(String, Map<String, dynamic>)> get events => _events.stream;
  Stream<bool> get connection => _connected.stream;

  static const _listen = [
    'incident.updated',
    'route.assigned',
    'route.cleared',
    'route.none',
    'position.fix',
    'hazards',
  ];

  Future<void> connect() async {
    if (_socket != null) return;
    final token = await tokenProvider();
    final s = io.io(
      serverUrl,
      io.OptionBuilder()
          .setTransports(['websocket'])
          .setAuth({'token': token})
          .enableReconnection()
          .setReconnectionDelay(1000)
          .setReconnectionDelayMax(5000)
          .disableAutoConnect()
          .build(),
    );
    s.onConnect((_) => _setConnected(true));
    s.onDisconnect((_) => _setConnected(false));
    s.onConnectError((_) => _setConnected(false));
    // refresh the token before every reconnection attempt
    s.io.on('reconnect_attempt', (_) async {
      final t = await tokenProvider();
      s.auth = {'token': t};
    });
    for (final name in _listen) {
      s.on(name, (data) {
        if (data is Map) _events.add((name, Map<String, dynamic>.from(data)));
      });
    }
    _socket = s..connect();
  }

  void _setConnected(bool v) {
    isConnected = v;
    _connected.add(v);
  }

  /// Emit with acknowledgement; returns null if not connected or no answer in time.
  Future<Map<String, dynamic>?> call(String event, Map<String, dynamic> data, {Duration timeout = const Duration(seconds: 4)}) {
    final s = _socket;
    if (s == null || !isConnected) return Future.value(null);
    final completer = Completer<Map<String, dynamic>?>();
    s.emitWithAck(event, data, ack: (resp) {
      if (!completer.isCompleted) completer.complete(resp is Map ? Map<String, dynamic>.from(resp) : null);
    });
    return completer.future.timeout(timeout, onTimeout: () => null);
  }

  Future<void> dispose() async {
    _socket?.dispose();
    _socket = null;
    _setConnected(false);
  }
}
