import 'dart:math' as math;

/// Building graph in the shared fixture format (fire-backend/contracts/fixtures).
class Floor {
  Floor({required this.id, required this.level, required this.name, required this.widthM, required this.heightM, this.planImage});
  final int id;
  final int level;
  final String name;
  final double widthM;
  final double heightM;
  final String? planImage;

  factory Floor.fromJson(Map<String, dynamic> j) => Floor(
        id: j['id'] as int,
        level: j['level'] as int,
        name: (j['name'] ?? 'Floor ${j['level']}') as String,
        widthM: (j['width_m'] as num? ?? 30).toDouble(),
        heightM: (j['height_m'] as num? ?? 20).toDouble(),
        planImage: j['plan_image'] as String?,
      );
}

class GNode {
  GNode({
    required this.id,
    required this.key,
    required this.name,
    required this.type,
    required this.floorId,
    required this.level,
    required this.x,
    required this.y,
    this.capacity = 10,
    this.exitFlowPerMin,
    this.lat,
    this.lng,
  });
  final int id;
  final String key;
  final String name;
  final String type;
  final int floorId;
  final int level;
  final double x;
  final double y;
  final int capacity;
  final double? exitFlowPerMin;
  final double? lat;
  final double? lng;

  bool get isExit => type == 'exit';
}

class GEdge {
  GEdge({required this.a, required this.b, required this.kind, required this.length, this.accessible = true});
  final int a;
  final int b;
  final String kind;
  final double length;
  final bool accessible;
  int other(int n) => n == a ? b : a;
}

class AccessPointInfo {
  AccessPointInfo({required this.bssid, required this.level, required this.x, required this.y, required this.pRef, required this.eta});
  final String bssid;
  final int level;
  final double x;
  final double y;
  final double pRef;
  final double eta;
}

class BuildingGraph {
  BuildingGraph({
    required this.buildingId,
    required this.name,
    required this.floorHeight,
    required this.graphVersion,
    required this.floors,
    required this.nodes,
    required this.edges,
    required this.accessPoints,
    this.footprint,
  }) {
    for (final n in nodes.values) {
      adjacency[n.id] = [];
    }
    for (final e in edges) {
      adjacency[e.a]!.add(e);
      adjacency[e.b]!.add(e);
    }
    final perLevel = [
      for (final e in edges)
        if (nodes[e.a]!.level != nodes[e.b]!.level) e.length / (nodes[e.a]!.level - nodes[e.b]!.level).abs(),
    ];
    minVerticalLen = perLevel.isEmpty ? floorHeight : perLevel.reduce(math.min);
  }

  final int buildingId;
  final String name;
  final double floorHeight;
  final int graphVersion;
  final List<Floor> floors;
  final Map<int, GNode> nodes;
  final List<GEdge> edges;
  final List<AccessPointInfo> accessPoints;
  final List<List<double>>? footprint;
  final Map<int, List<GEdge>> adjacency = {};
  late final double minVerticalLen;

  List<int> get exits => [for (final n in nodes.values) if (n.type == 'exit') n.id];
  List<int> get refuges => [for (final n in nodes.values) if (n.type == 'refuge') n.id];

  Floor? floorByLevel(int level) => floors.where((f) => f.level == level).firstOrNull;

  GNode byKey(String key) => nodes.values.firstWhere((n) => n.key == key);

  GEdge? edgeBetween(int a, int b) => adjacency[a]?.where((e) => e.other(a) == b).firstOrNull;

  double walkLength(int a, int b) => edgeBetween(a, b)?.length ?? distance(a, b);

  double distance(int a, int b) {
    final na = nodes[a]!, nb = nodes[b]!;
    final dz = (na.level - nb.level) * floorHeight;
    return math.sqrt(math.pow(na.x - nb.x, 2) + math.pow(na.y - nb.y, 2) + dz * dz);
  }

  /// Admissible lower bound (same as the server): max(horizontal distance, floors * shortest stair per floor).
  double lowerBound(int a, int b) {
    final na = nodes[a]!, nb = nodes[b]!;
    final horizontal = math.sqrt(math.pow(na.x - nb.x, 2) + math.pow(na.y - nb.y, 2));
    final vertical = (na.level - nb.level).abs() * minVerticalLen;
    return math.max(horizontal, vertical);
  }

  int? nearestNode(double x, double y, int level) {
    int? best;
    var bestD = double.infinity;
    for (final n in nodes.values) {
      if (n.level != level || n.type == 'assembly') continue;
      final d = math.sqrt(math.pow(n.x - x, 2) + math.pow(n.y - y, 2));
      if (d < bestD) {
        bestD = d;
        best = n.id;
      }
    }
    return best;
  }

  factory BuildingGraph.fromJson(Map<String, dynamic> j) {
    final b = j['building'] as Map<String, dynamic>;
    final floorHeight = (b['floor_height_m'] as num? ?? 3).toDouble();
    final floors = [for (final f in j['floors'] as List) Floor.fromJson(f as Map<String, dynamic>)];
    final levelOf = {for (final f in floors) f.id: f.level};
    final nodes = <int, GNode>{};
    for (final raw in j['nodes'] as List) {
      final n = raw as Map<String, dynamic>;
      nodes[n['id'] as int] = GNode(
        id: n['id'] as int,
        key: (n['key'] ?? '${n['id']}') as String,
        name: (n['name'] ?? n['key'] ?? '${n['id']}') as String,
        type: n['type'] as String,
        floorId: n['floor_id'] as int,
        level: levelOf[n['floor_id']]!,
        x: (n['x'] as num).toDouble(),
        y: (n['y'] as num).toDouble(),
        capacity: (n['capacity'] as num? ?? 10).toInt(),
        exitFlowPerMin: (n['exit_flow_per_min'] as num?)?.toDouble(),
        lat: (n['lat'] as num?)?.toDouble(),
        lng: (n['lng'] as num?)?.toDouble(),
      );
    }
    final edges = <GEdge>[];
    for (final raw in j['edges'] as List) {
      final e = raw as Map<String, dynamic>;
      final a = nodes[e['a']]!, bb = nodes[e['b']]!;
      final dz = (a.level - bb.level) * floorHeight;
      final straight = math.sqrt(math.pow(a.x - bb.x, 2) + math.pow(a.y - bb.y, 2) + dz * dz);
      final given = (e['length_m'] as num?)?.toDouble() ?? 0;
      edges.add(GEdge(a: a.id, b: bb.id, kind: (e['kind'] ?? 'corridor') as String, length: math.max(math.max(given, straight), 0.1), accessible: (e['accessible'] ?? true) as bool));
    }
    final aps = [
      for (final raw in (j['access_points'] as List? ?? const []))
        if ((raw as Map<String, dynamic>)['enabled'] != false && levelOf.containsKey(raw['floor_id']))
          AccessPointInfo(
            bssid: (raw['bssid'] as String).toLowerCase(),
            level: levelOf[raw['floor_id']]!,
            x: (raw['x'] as num).toDouble(),
            y: (raw['y'] as num).toDouble(),
            pRef: (raw['p_ref'] as num? ?? -40).toDouble(),
            eta: (raw['eta'] as num? ?? 2.7).toDouble(),
          ),
    ];
    final fp = b['footprint'] as List?;
    return BuildingGraph(
      buildingId: (b['id'] ?? 0) as int,
      name: (b['name'] ?? 'Building') as String,
      floorHeight: floorHeight,
      graphVersion: (b['graph_version'] ?? 1) as int,
      floors: floors,
      nodes: nodes,
      edges: edges,
      accessPoints: aps,
      footprint: fp == null ? null : [for (final p in fp) [(p[0] as num).toDouble(), (p[1] as num).toDouble()]],
    );
  }
}
