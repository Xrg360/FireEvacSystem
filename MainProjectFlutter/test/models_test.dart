import 'dart:convert';
import 'dart:io';

import 'package:fire_evac/shared/graph.dart';
import 'package:fire_evac/shared/models.dart';
import 'package:fire_evac/shared/offline_routing.dart';
import 'package:fire_evac/state/evacuation.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('route.assigned payload parses (contract: fire-backend/app/realtime/schemas.py)', () {
    final r = RouteInfo.fromJson({
      'ts': 1,
      'device_id': 'd',
      'incident_id': 3,
      'version': 2,
      'reason': 'hazard',
      'path': [52, 51, 55],
      'nodes': [],
      'steps': [
        {'node_id': 52, 'kind': 'start', 'text': 'Leave Flat 302.', 'distance_m': 0},
        {'node_id': 55, 'kind': 'exit', 'text': 'Exit the building through West Fire Exit.', 'distance_m': 2.5},
      ],
      'goal': {'id': 55, 'name': 'West Fire Exit', 'type': 'exit'},
      'goal_type': 'exit',
      'remaining_m': 44.0,
      'latency_ms': 120.5,
    });
    expect(r.reason, 'hazard');
    expect(r.steps.last.kind, 'exit');
    expect(r.toRefuge, isFalse);
  });

  test('position.fix payload parses, including GPS-outside and picker flags', () {
    final f = PositionFix.fromJson({
      'source': 'gps',
      'x': null,
      'y': null,
      'level': null,
      'node_id': null,
      'confidence': 0.1,
      'floor_confidence': 0,
      'spread_m': null,
      'outside': true,
      'near_assembly_node': 13,
      'needs_picker': false,
      'confirm_floor': false,
      'gps': {'lat': 9.96, 'lng': 76.41, 'accuracy_m': 8},
    });
    expect(f.outside, isTrue);
    expect(f.nearAssemblyNode, 13);
  });

  test('offline steps collapse a stair run into one instruction', () {
    final file = File('../fire-backend/contracts/fixtures/block_b_tower.json');
    if (!file.existsSync()) return;
    final g = BuildingGraph.fromJson(jsonDecode(file.readAsStringSync()) as Map<String, dynamic>);
    final r = planOffline(g, g.byKey('B3-F02').id, const {})!;
    final steps = offlineSteps(g, r.path);
    expect(steps.where((s) => s.kind == 'stairs').length, 1);
    expect(steps.last.kind, 'exit');
    expect(steps.firstWhere((s) => s.kind == 'stairs').text, contains('down to Ground Floor'));
  });

  test('a person who cannot use stairs is never routed down a staircase offline', () {
    final file = File('../fire-backend/contracts/fixtures/block_b_tower.json');
    if (!file.existsSync()) return;
    final g = BuildingGraph.fromJson(jsonDecode(file.readAsStringSync()) as Map<String, dynamic>);
    final r = planOffline(g, g.byKey('B2-F01').id, const {}, stairsOk: false)!;
    expect(r.goalType, 'refuge');
    for (var i = 0; i + 1 < r.path.length; i++) {
      expect(g.edgeBetween(r.path[i], r.path[i + 1])!.kind, isNot('stair'));
    }
  });
}
