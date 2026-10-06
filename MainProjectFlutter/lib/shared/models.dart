// Payload models matching fire-backend/contracts/events.schema.json and the REST API.

double? _d(Object? v) => (v as num?)?.toDouble();

class AppUser {
  AppUser({
    required this.id,
    required this.name,
    required this.email,
    required this.role,
    required this.status,
    this.buildingId,
    this.flat,
    this.stairsOk = true,
    this.phone,
  });
  final int id;
  final String name;
  final String email;
  final String role;
  final String status;
  final int? buildingId;
  final String? flat;
  final bool stairsOk;
  final String? phone;

  bool get approved => status == 'approved';
  bool get canSurvey => role == 'surveyor' || role == 'society_admin';

  factory AppUser.fromJson(Map<String, dynamic> j) => AppUser(
        id: j['id'] as int,
        name: j['name'] as String,
        email: j['email'] as String,
        role: j['role'] as String,
        status: j['status'] as String,
        buildingId: j['building_id'] as int?,
        flat: j['flat'] as String?,
        stairsOk: (j['stairs_ok'] ?? true) as bool,
        phone: j['phone'] as String?,
      );
}

class Incident {
  Incident({required this.id, required this.kind, required this.status, required this.isSimulation, this.startedAt});
  final int id;
  final String kind;
  final String status;
  final bool isSimulation;
  final DateTime? startedAt;

  bool get active => status == 'evacuating' || status == 'detected';
  bool get isDrill => kind == 'drill';

  factory Incident.fromJson(Map<String, dynamic> j) => Incident(
        id: j['id'] as int,
        kind: j['kind'] as String,
        status: j['status'] as String,
        isSimulation: (j['is_simulation'] ?? false) as bool,
        startedAt: j['started_at'] == null ? null : DateTime.tryParse(j['started_at'] as String),
      );
}

class PositionFix {
  PositionFix({
    required this.source,
    this.x,
    this.y,
    this.level,
    this.nodeId,
    this.confidence = 0,
    this.floorConfidence = 0,
    this.spreadM,
    this.outside = false,
    this.nearAssemblyNode,
    this.needsPicker = false,
    this.confirmFloor = false,
  });
  final String source; // wifi_pf | manual | gps | last_known | unknown | offline
  final double? x;
  final double? y;
  final int? level;
  final int? nodeId;
  final double confidence;
  final double floorConfidence;
  final double? spreadM;
  final bool outside;
  final int? nearAssemblyNode;
  final bool needsPicker;
  final bool confirmFloor;

  factory PositionFix.fromJson(Map<String, dynamic> j) => PositionFix(
        source: (j['source'] ?? 'unknown') as String,
        x: _d(j['x']),
        y: _d(j['y']),
        level: j['level'] as int?,
        nodeId: j['node_id'] as int?,
        confidence: _d(j['confidence']) ?? 0,
        floorConfidence: _d(j['floor_confidence']) ?? 0,
        spreadM: _d(j['spread_m']),
        outside: (j['outside'] ?? false) as bool,
        nearAssemblyNode: j['near_assembly_node'] as int?,
        needsPicker: (j['needs_picker'] ?? false) as bool,
        confirmFloor: (j['confirm_floor'] ?? false) as bool,
      );
}

class RouteStep {
  RouteStep(this.nodeId, this.kind, this.text, this.distanceM);
  final int nodeId;
  final String kind;
  final String text;
  final double distanceM;

  factory RouteStep.fromJson(Map<String, dynamic> j) =>
      RouteStep(j['node_id'] as int, j['kind'] as String, j['text'] as String, _d(j['distance_m']) ?? 0);
}

class RouteInfo {
  RouteInfo({
    required this.version,
    required this.reason,
    required this.path,
    required this.steps,
    required this.goalId,
    required this.goalName,
    required this.goalType,
    required this.remainingM,
    this.offline = false,
  });
  final int version;
  final String reason;
  final List<int> path;
  final List<RouteStep> steps;
  final int goalId;
  final String goalName;
  final String goalType;
  final double remainingM;
  final bool offline;

  bool get toRefuge => goalType == 'refuge';

  factory RouteInfo.fromJson(Map<String, dynamic> j) {
    final goal = j['goal'] as Map<String, dynamic>;
    return RouteInfo(
      version: (j['version'] ?? 0) as int,
      reason: (j['reason'] ?? 'initial') as String,
      path: [for (final n in j['path'] as List) n as int],
      steps: [for (final s in j['steps'] as List) RouteStep.fromJson(s as Map<String, dynamic>)],
      goalId: goal['id'] as int,
      goalName: goal['name'] as String,
      goalType: (j['goal_type'] ?? goal['type']) as String,
      remainingM: _d(j['remaining_m']) ?? 0,
    );
  }
}
