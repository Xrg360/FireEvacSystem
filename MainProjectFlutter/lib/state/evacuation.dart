import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geolocator/geolocator.dart';

import '../core/api.dart';
import '../core/socket_service.dart';
import '../services/notifications.dart';
import '../services/scan_service.dart';
import '../shared/graph.dart';
import '../shared/models.dart';
import '../shared/offline_routing.dart';
import 'session.dart';

/// Seconds without the server before the phone switches to on-device routing.
const offlineAfter = Duration(seconds: 10);

/// Seconds without usable Wi-Fi results before GPS starts and the picker is offered.
const wifiStaleAfter = Duration(seconds: 45);

class EvacState {
  const EvacState({
    this.graph,
    this.incident,
    this.myStatus = 'unknown',
    this.fix,
    this.route,
    this.noRoute = false,
    this.hazards = const {},
    this.connected = false,
    this.offline = false,
    this.scanning = false,
    this.scanProblem,
    this.scansSent = 0,
    this.lastReadings = const {},
    this.lastScanAt,
    this.buildingMode = 'live',
    this.acknowledged = false,
    this.pendingActions = 0,
    this.gps,
    this.manualNodeId,
  });

  final BuildingGraph? graph;
  final Incident? incident;
  final String myStatus;
  final PositionFix? fix;
  final RouteInfo? route;
  final bool noRoute;
  final Map<int, String> hazards;
  final bool connected;
  final bool offline;
  final bool scanning;
  final String? scanProblem;
  final int scansSent;
  final Map<String, double> lastReadings;
  final DateTime? lastScanAt;
  final String buildingMode;
  final bool acknowledged;
  final int pendingActions;
  final Position? gps;
  final int? manualNodeId;

  bool get incidentActive => incident?.active ?? false;
  bool get simulation => buildingMode == 'simulation';
  bool get wifiStale => lastScanAt == null || DateTime.now().difference(lastScanAt!) > wifiStaleAfter;

  /// Show the "Where are you?" sheet: the server asks for it, or we are offline without a position.
  bool get needsPicker => (fix?.needsPicker ?? true) || (offline && manualNodeId == null && (fix?.nodeId == null));

  EvacState copyWith({
    BuildingGraph? graph,
    Incident? incident,
    bool clearIncident = false,
    String? myStatus,
    PositionFix? fix,
    RouteInfo? route,
    bool clearRoute = false,
    bool? noRoute,
    Map<int, String>? hazards,
    bool? connected,
    bool? offline,
    bool? scanning,
    String? scanProblem,
    bool clearScanProblem = false,
    int? scansSent,
    Map<String, double>? lastReadings,
    DateTime? lastScanAt,
    String? buildingMode,
    bool? acknowledged,
    int? pendingActions,
    Position? gps,
    int? manualNodeId,
  }) =>
      EvacState(
        graph: graph ?? this.graph,
        incident: clearIncident ? null : incident ?? this.incident,
        myStatus: myStatus ?? this.myStatus,
        fix: fix ?? this.fix,
        route: clearRoute ? null : route ?? this.route,
        noRoute: noRoute ?? this.noRoute,
        hazards: hazards ?? this.hazards,
        connected: connected ?? this.connected,
        offline: offline ?? this.offline,
        scanning: scanning ?? this.scanning,
        scanProblem: clearScanProblem ? null : scanProblem ?? this.scanProblem,
        scansSent: scansSent ?? this.scansSent,
        lastReadings: lastReadings ?? this.lastReadings,
        lastScanAt: lastScanAt ?? this.lastScanAt,
        buildingMode: buildingMode ?? this.buildingMode,
        acknowledged: acknowledged ?? this.acknowledged,
        pendingActions: pendingActions ?? this.pendingActions,
        gps: gps ?? this.gps,
        manualNodeId: manualNodeId ?? this.manualNodeId,
      );
}

final evacuationProvider = NotifierProvider<EvacuationController, EvacState>(EvacuationController.new);

/// Fires when the alarm screen should open (new incident).
final alarmSignal = StreamController<Incident>.broadcast();

class EvacuationController extends Notifier<EvacState> {
  SocketService? _socket;
  ScanService? _scanner;
  StreamSubscription<Position>? _gpsSub;
  DateTime? _gpsRetryAfter;
  final List<StreamSubscription<dynamic>> _subs = [];
  Timer? _watchdog;
  DateTime? _disconnectedAt;
  int _offlineVersion = 0;

  Api get _api => ref.read(apiProvider);

  @override
  EvacState build() {
    ref.onDispose(_teardown);
    final session = ref.watch(sessionProvider);
    if (session.status == SessionStatus.ready && session.user?.buildingId != null) {
      Future.microtask(() => _start(session.user!.buildingId!));
    }
    return EvacState(buildingMode: session.buildingMode ?? 'live');
  }

  // ------------------------------------------------------------------ lifecycle

  Future<void> _start(int buildingId) async {
    final storage = ref.read(storageProvider);
    // offline cache first so the map works without the server
    final cached = storage.readJson('graph:$buildingId');
    if (cached != null) state = state.copyWith(graph: BuildingGraph.fromJson(cached));
    final cachedHz = storage.readJson('hazards:$buildingId');
    if (cachedHz != null) state = state.copyWith(hazards: _parseHazards(cachedHz));
    state = state.copyWith(pendingActions: storage.pendingActions.length);

    _socket = SocketService(serverUrl: storage.serverUrl, tokenProvider: _api.freshToken);
    _subs.add(_socket!.connection.listen(_onConnection));
    _subs.add(_socket!.events.listen(_onEvent));
    await _socket!.connect();
    await refreshIncident();
    _watchdog = Timer.periodic(const Duration(seconds: 2), (_) => _tick());
  }

  void _teardown() {
    for (final s in _subs) {
      s.cancel();
    }
    _subs.clear();
    _watchdog?.cancel();
    _scanner?.stop();
    _gpsSub?.cancel();
    _socket?.dispose();
  }

  Future<void> _loadGraph(int buildingId, int version) async {
    if (state.graph?.graphVersion == version && state.graph?.buildingId == buildingId) return;
    try {
      final g = await _api.get('/buildings/$buildingId/graph');
      await ref.read(storageProvider).writeJson('graph:$buildingId', g);
      state = state.copyWith(graph: BuildingGraph.fromJson(g));
    } catch (_) {}
  }

  /// Pull the current incident (on start, reconnect, and from the home screen).
  Future<void> refreshIncident() async {
    try {
      final r = await _api.get('/me/incident');
      final b = r['building'] as Map<String, dynamic>?;
      if (b != null) {
        state = state.copyWith(buildingMode: b['mode'] as String?);
        await _loadGraph(b['id'] as int, b['graph_version'] as int);
      }
      if (r['hazards'] is Map) _setHazards(Map<String, dynamic>.from(r['hazards'] as Map));
      final inc = r['incident'] == null ? null : Incident.fromJson(r['incident'] as Map<String, dynamic>);
      _applyIncident(inc, myStatus: r['my_status'] as String?);
      if (state.incidentActive) {
        final me = await _api.get('/positioning/me');
        if (me['fix'] is Map) state = state.copyWith(fix: PositionFix.fromJson(Map<String, dynamic>.from(me['fix'] as Map)));
        if (me['route'] is Map) state = state.copyWith(route: RouteInfo.fromJson(Map<String, dynamic>.from(me['route'] as Map)));
      }
    } on ApiException catch (_) {}
  }

  void _applyIncident(Incident? inc, {String? myStatus}) {
    final wasActive = state.incidentActive;
    if (inc == null || !inc.active) {
      state = state.copyWith(clearIncident: true, clearRoute: true, myStatus: 'unknown', acknowledged: false, noRoute: false);
      _stopTracking();
      cancelAlarmNotification();
      return;
    }
    final status = myStatus ?? (state.incident?.id == inc.id ? state.myStatus : 'unknown');
    state = state.copyWith(incident: inc, myStatus: status, acknowledged: status != 'unknown' ? true : (state.incident?.id == inc.id && state.acknowledged));
    if (status != 'safe') _startTracking();
    if (!wasActive && status == 'unknown') alarmSignal.add(inc);
  }

  // ------------------------------------------------------------------ socket

  void _onConnection(bool connected) {
    state = state.copyWith(connected: connected);
    if (connected) {
      _disconnectedAt = null;
      if (state.offline) state = state.copyWith(offline: false);
      refreshIncident();
      _flushPending();
    } else {
      _disconnectedAt ??= DateTime.now();
    }
  }

  void _onEvent((String, Map<String, dynamic>) e) {
    final (name, data) = e;
    switch (name) {
      case 'incident.updated':
        final inc = Incident.fromJson(Map<String, dynamic>.from(data['incident'] as Map));
        _applyIncident(inc);
      case 'hazards':
        _setHazards(Map<String, dynamic>.from(data['hazards'] as Map));
      case 'route.assigned':
        state = state.copyWith(route: RouteInfo.fromJson(data), noRoute: false);
      case 'route.cleared':
        state = state.copyWith(clearRoute: true);
      case 'route.none':
        state = state.copyWith(clearRoute: true, noRoute: true);
      case 'position.fix':
        state = state.copyWith(fix: PositionFix.fromJson(data));
        _maybeGps();
    }
  }

  Map<int, String> _parseHazards(Map<String, dynamic> raw) => {for (final e in raw.entries) int.parse(e.key): e.value.toString()};

  void _setHazards(Map<String, dynamic> raw) {
    final hz = _parseHazards(raw);
    state = state.copyWith(hazards: hz);
    final bid = state.graph?.buildingId;
    if (bid != null) ref.read(storageProvider).writeJson('hazards:$bid', raw);
    if (state.offline) _routeOffline();
  }

  // ------------------------------------------------------------------ tracking (privacy: only during an incident / simulation)

  Future<void> _startTracking() async {
    if (_scanner?.running ?? false) return;
    _scanner = ScanService(_onReadings);
    final problem = await _scanner!.start();
    state = state.copyWith(scanning: problem == null, scanProblem: problem, clearScanProblem: problem == null);
  }

  /// Simulation-mode dev panel can start tracking without an incident.
  Future<void> startDevTracking() => _startTracking();

  void _stopTracking() {
    _scanner?.stop();
    _scanner = null;
    _gpsSub?.cancel();
    _gpsSub = null;
    state = state.copyWith(scanning: false);
  }

  Future<void> _onReadings(Map<String, double> readings) async {
    state = state.copyWith(lastReadings: readings, lastScanAt: DateTime.now());
    final payload = {
      'readings': [for (final e in readings.entries) {'bssid': e.key, 'rssi': e.value}],
    };
    final ack = await _socket?.call('scan', payload);
    if (ack == null && !state.offline) {
      // socket down: REST fallback
      try {
        await _api.post('/positioning/scan', payload);
      } catch (_) {}
    }
    state = state.copyWith(scansSent: state.scansSent + 1);
    if (state.offline) _routeOffline();
  }

  /// GPS / fused location only when Wi-Fi is missing or weak (block-level / outside decisions).
  void _maybeGps() {
    final weak = state.wifiStale || (state.fix?.needsPicker ?? false) || (state.fix?.source == 'last_known');
    if (!state.incidentActive || !weak) {
      _gpsSub?.cancel();
      _gpsSub = null;
      return;
    }
    if (_gpsSub != null) return;
    if (_gpsRetryAfter != null && DateTime.now().isBefore(_gpsRetryAfter!)) return;
    _gpsSub = Geolocator.getPositionStream(
      // Plain LocationManager: never pops Google's "Location Accuracy" dialog over the
      // evacuation screen, and works without Play Services.
      locationSettings: AndroidSettings(
        accuracy: LocationAccuracy.high,
        distanceFilter: 3,
        intervalDuration: const Duration(seconds: 5),
        forceLocationManager: true,
      ),
    ).listen(
      (p) {
        state = state.copyWith(gps: p);
        _socket?.call('gps', {'lat': p.latitude, 'lng': p.longitude, 'accuracy_m': p.accuracy});
      },
      onError: (_) {
        // GPS unavailable (off / denied): back off instead of retrying every tick
        _gpsSub?.cancel();
        _gpsSub = null;
        _gpsRetryAfter = DateTime.now().add(const Duration(seconds: 60));
      },
      cancelOnError: true,
    );
  }

  void _tick() {
    if (!state.incidentActive) return;
    _maybeGps();
    final down = _disconnectedAt != null && DateTime.now().difference(_disconnectedAt!) > offlineAfter;
    if (down && !state.offline) {
      state = state.copyWith(offline: true);
      _routeOffline();
    }
  }

  // ------------------------------------------------------------------ offline fallback (paper §VI edge processing)

  void _routeOffline() {
    final g = state.graph;
    if (g == null) return;
    int? node = state.manualNodeId;
    if (node == null && state.lastReadings.isNotEmpty && !state.wifiStale) {
      final f = triangulate(g, state.lastReadings);
      if (f != null) {
        node = f.nodeId;
        state = state.copyWith(fix: PositionFix(source: 'offline', x: f.x, y: f.y, level: f.level, nodeId: f.nodeId, confidence: 0.4));
      }
    }
    node ??= state.fix?.nodeId;
    if (node == null) return;
    final stairsOk = ref.read(sessionProvider).user?.stairsOk ?? true;
    final r = planOffline(g, node, state.hazards, stairsOk: stairsOk);
    if (r == null) {
      state = state.copyWith(clearRoute: true, noRoute: true);
      return;
    }
    state = state.copyWith(
      noRoute: false,
      route: RouteInfo(
        version: --_offlineVersion,
        reason: 'offline',
        path: r.path,
        steps: offlineSteps(g, r.path),
        goalId: r.goal,
        goalName: g.nodes[r.goal]!.name,
        goalType: r.goalType,
        remainingM: r.length,
        offline: true,
      ),
    );
  }

  // ------------------------------------------------------------------ resident actions

  Future<void> acknowledge() async {
    state = state.copyWith(acknowledged: true, myStatus: state.myStatus == 'unknown' ? 'evacuating' : state.myStatus);
    await cancelAlarmNotification();
    await _send('/me/acknowledge', {});
  }

  Future<void> setStatus(String status) async {
    state = state.copyWith(myStatus: status, acknowledged: true);
    if (status == 'safe') _stopTracking();
    await _send('/me/status', {'status': status});
  }

  Future<void> sos(String kind, String? note) async {
    state = state.copyWith(myStatus: 'needs_help', acknowledged: true);
    await _send('/sos', {'kind': kind, 'note': note});
  }

  Future<void> manualPick(int nodeId) async {
    final node = state.graph?.nodes[nodeId];
    state = state.copyWith(
      manualNodeId: nodeId,
      fix: PositionFix(source: 'manual', x: node?.x, y: node?.y, level: node?.level, nodeId: nodeId, confidence: 0.9, floorConfidence: 1),
    );
    final ack = await _socket?.call('manual_location', {'node_id': nodeId});
    if (ack == null) {
      try {
        await _api.post('/positioning/manual', {'node_id': nodeId});
      } catch (_) {
        _routeOffline();
      }
    }
  }

  Future<void> confirmFloor(int level) async {
    await _socket?.call('floor_confirm', {'level': level});
  }

  /// Status changes and SOS are queued while offline and replayed on reconnect.
  Future<void> _send(String path, Map<String, dynamic> body) async {
    try {
      await _api.post(path, body);
    } on ApiException catch (e) {
      if (e.isOffline) {
        final storage = ref.read(storageProvider);
        final pending = storage.pendingActions..add({'path': path, 'body': body});
        await storage.setPendingActions(pending);
        state = state.copyWith(pendingActions: pending.length);
      }
    }
  }

  Future<void> _flushPending() async {
    final storage = ref.read(storageProvider);
    final pending = storage.pendingActions;
    if (pending.isEmpty) return;
    final left = <Map<String, dynamic>>[];
    for (final a in pending) {
      try {
        await _api.post(a['path'] as String, Map<String, dynamic>.from(a['body'] as Map));
      } on ApiException catch (e) {
        if (e.isOffline) left.add(a);
      }
    }
    await storage.setPendingActions(left);
    state = state.copyWith(pendingActions: left.length);
  }
}

/// Landmark-style steps for an offline route (same wording as the server).
List<RouteStep> offlineSteps(BuildingGraph g, List<int> path) {
  if (path.length < 2) return [RouteStep(path.first, 'arrive', 'You are at the exit. Move away from the building.', 0)];
  final steps = <RouteStep>[RouteStep(path.first, 'start', 'Leave ${g.nodes[path.first]!.name}.', 0)];
  var i = 1;
  while (i < path.length) {
    final prev = g.nodes[path[i - 1]]!, node = g.nodes[path[i]]!;
    var dist = g.walkLength(prev.id, node.id);
    if (node.level != prev.level) {
      var j = i;
      while (j + 1 < path.length && g.nodes[path[j + 1]]!.level != g.nodes[path[j]]!.level) {
        dist += g.walkLength(path[j], path[j + 1]);
        j++;
      }
      final target = g.nodes[path[j]]!;
      final dir = target.level < prev.level ? 'down' : 'up';
      final via = prev.type == 'stair' || prev.type == 'lift' ? prev.name : node.name;
      steps.add(RouteStep(target.id, 'stairs', 'Take $via $dir to ${g.floorByLevel(target.level)?.name ?? 'level ${target.level}'}.', dist));
      i = j + 1;
      continue;
    }
    final kind = node.type == 'exit' ? 'exit' : node.type == 'refuge' ? 'refuge' : 'go';
    final text = switch (kind) {
      'exit' => 'Exit the building through ${node.name}.',
      'refuge' => 'Go to the refuge area: ${node.name}.',
      _ => node.type == 'stair' || node.type == 'lift' ? 'Go to ${node.name}.' : 'Go through ${node.name}.',
    };
    steps.add(RouteStep(node.id, kind, text, dist));
    i++;
  }
  return steps;
}
