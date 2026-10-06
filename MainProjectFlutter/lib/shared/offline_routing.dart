import 'dart:collection';
import 'dart:math' as math;

import 'graph.dart';

/// On-device fallback routing - a port of the server's A* (paper Alg. 2) and cost model,
/// used when the evacuation server is unreachable (paper §VI fault tolerance / edge processing).
/// Congestion is unknown offline, so only hazards, lifts and mobility are considered.

const _hazardWeight = {'none': 0.0, 'risk': 0.25, 'smoke': 1.0};

class OfflineRoute {
  OfflineRoute(this.path, this.cost, this.length, this.goalType);
  final List<int> path;
  final double cost;
  final double length;
  final String goalType;
  int get goal => path.last;
}

OfflineRoute? astar(
  BuildingGraph g,
  int start,
  Iterable<int> goals,
  double? Function(GEdge edge, int from, int to) cost, {
  Set<int> blocked = const {},
}) {
  final goalSet = goals.toSet()..removeAll(blocked);
  if (goalSet.isEmpty || !g.nodes.containsKey(start)) return null;
  if (goalSet.contains(start)) return OfflineRoute([start], 0, 0, '');
  double h(int n) => goalSet.map((gl) => g.lowerBound(n, gl)).reduce(math.min);

  final gScore = <int, double>{start: 0};
  final lengthSoFar = <int, double>{start: 0};
  final cameFrom = <int, int>{};
  final closed = <int>{};
  var seq = 0;
  // (f, insertion order, node) - order breaks ties deterministically like the Python heap
  final open = SplayTreeSet<(double, int, int)>((x, y) => x.$1 != y.$1 ? x.$1.compareTo(y.$1) : x.$2.compareTo(y.$2));
  open.add((h(start), seq++, start));

  while (open.isNotEmpty) {
    final current = open.first.$3;
    open.remove(open.first);
    if (closed.contains(current)) continue;
    if (goalSet.contains(current)) {
      final path = [current];
      while (cameFrom.containsKey(path.last)) {
        path.add(cameFrom[path.last]!);
      }
      return OfflineRoute(path.reversed.toList(), gScore[current]!, lengthSoFar[current]!, '');
    }
    closed.add(current);
    for (final edge in g.adjacency[current]!) {
      final nb = edge.other(current);
      if (closed.contains(nb) || blocked.contains(nb)) continue;
      final step = cost(edge, current, nb);
      if (step == null) continue;
      final tentative = gScore[current]! + step;
      if (tentative < (gScore[nb] ?? double.infinity)) {
        cameFrom[nb] = current;
        gScore[nb] = tentative;
        lengthSoFar[nb] = lengthSoFar[current]! + edge.length;
        open.add((tentative + h(nb), seq++, nb));
      }
    }
  }
  return null;
}

/// Same rules as the server planner without congestion: fire pruned, lifts pruned during an
/// incident, stairs pruned for residents who cannot use them (they go to a refuge area).
OfflineRoute? planOffline(BuildingGraph g, int start, Map<int, String> hazards, {bool stairsOk = true, double alpha = 4.0}) {
  final blocked = {for (final e in hazards.entries) if (e.value == 'fire' && e.key != start) e.key};
  double? cost(GEdge edge, int from, int to) {
    final hz = hazards[to] ?? 'none';
    if (hz == 'fire') return null;
    if (edge.kind == 'lift') return null;
    if (!stairsOk && (edge.kind == 'stair' || !edge.accessible)) return null;
    return edge.length * (1 + alpha * (_hazardWeight[hz] ?? 0));
  }

  final toExit = astar(g, start, g.exits, cost, blocked: blocked);
  if (toExit != null) return OfflineRoute(toExit.path, toExit.cost, toExit.length, 'exit');
  if (g.refuges.isNotEmpty) {
    final toRefuge = astar(g, start, g.refuges, cost, blocked: blocked);
    if (toRefuge != null) return OfflineRoute(toRefuge.path, toRefuge.cost, toRefuge.length, 'refuge');
  }
  return null;
}

/// Smoke around fire and risk one step further - mirrors fire-backend hazards_from_fire.
Map<int, String> expandHazards(BuildingGraph g, Map<int, String> explicit) {
  final out = <int, String>{};
  const severity = {'none': 0, 'risk': 1, 'smoke': 2, 'fire': 3};
  void put(int n, String lvl) {
    if ((severity[lvl] ?? 0) > (severity[out[n] ?? 'none'] ?? 0)) out[n] = lvl;
  }

  explicit.forEach(put);
  final fire = [for (final e in explicit.entries) if (e.value == 'fire') e.key];
  final smoke = <int>{};
  for (final f in fire) {
    for (final e in g.adjacency[f] ?? const <GEdge>[]) {
      if (e.kind != 'outdoor' && out[e.other(f)] == null) smoke.add(e.other(f));
    }
  }
  for (final s in smoke) {
    put(s, 'smoke');
  }
  for (final s in smoke) {
    for (final e in g.adjacency[s] ?? const <GEdge>[]) {
      if (e.kind != 'outdoor' && out[e.other(s)] == null) out[e.other(s)] = 'risk';
    }
  }
  return out;
}

// ---------------------------------------------------------------- positioning (paper eq. 1, Alg. 3)

/// eq. 1: d = d_ref * 10^(-(P_received - P_ref) / (10 * eta))
double estimateDistance(double pReceived, double pRef, double eta) => math.pow(10, -(pReceived - pRef) / (10 * eta)).toDouble();

class OfflineFix {
  OfflineFix(this.x, this.y, this.level, this.nodeId);
  final double x;
  final double y;
  final int level;
  final int? nodeId;
}

/// Alg. 3 weighted triangulation on the phone; floor by weighted vote.
OfflineFix? triangulate(BuildingGraph g, Map<String, double> readings, {int maxAps = 6}) {
  final index = {for (final ap in g.accessPoints) ap.bssid: ap};
  final obs = [
    for (final e in readings.entries)
      if (index[e.key.toLowerCase()] != null && e.value > -100 && e.value < 0) (index[e.key.toLowerCase()]!, e.value),
  ]..sort((a, b) => b.$2.compareTo(a.$2));
  if (obs.isEmpty) return null;
  final strongest = obs.take(maxAps).toList();
  final floorWeight = <int, double>{};
  for (final (ap, rssi) in strongest) {
    final d = estimateDistance(rssi, ap.pRef, ap.eta);
    floorWeight[ap.level] = (floorWeight[ap.level] ?? 0) + 1 / math.pow(math.max(d, 0.5), 2);
  }
  final level = floorWeight.entries.reduce((a, b) => a.value >= b.value ? a : b).key;
  var sx = 0.0, sy = 0.0, total = 0.0;
  for (final (ap, rssi) in strongest) {
    if (ap.level != level) continue;
    final w = 1 / math.pow(math.max(estimateDistance(rssi, ap.pRef, ap.eta), 0.5), 2);
    sx += w * ap.x;
    sy += w * ap.y;
    total += w;
  }
  if (total == 0) return null;
  final x = sx / total, y = sy / total;
  return OfflineFix(x, y, level, g.nearestNode(x, y, level));
}
