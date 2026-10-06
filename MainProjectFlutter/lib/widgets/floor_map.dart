import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../core/theme.dart';
import '../shared/graph.dart';

/// Floor plan with the evacuation route, the user's position (with uncertainty) and hazards.
class FloorMap extends StatelessWidget {
  const FloorMap({
    super.key,
    required this.graph,
    required this.level,
    this.route = const [],
    this.hazards = const {},
    this.me,
    this.meSpreadM,
    this.highlightNode,
    this.onTapNode,
  });

  final BuildingGraph graph;
  final int level;
  final List<int> route;
  final Map<int, String> hazards;
  final Offset? me;
  final double? meSpreadM;
  final int? highlightNode;
  final void Function(GNode node)? onTapNode;

  @override
  Widget build(BuildContext context) {
    final floor = graph.floorByLevel(level);
    final nodes = graph.nodes.values.where((n) => n.level == level && n.type != 'assembly').toList();
    if (floor == null || nodes.isEmpty) return const Center(child: Text('No map for this floor'));
    final minX = math.min(0.0, nodes.map((n) => n.x).reduce(math.min)) - 2;
    final minY = math.min(0.0, nodes.map((n) => n.y).reduce(math.min)) - 2;
    final maxX = math.max(floor.widthM, nodes.map((n) => n.x).reduce(math.max)) + 2;
    final maxY = math.max(floor.heightM, nodes.map((n) => n.y).reduce(math.max)) + 2;
    final world = Rect.fromLTRB(minX, minY, maxX, maxY);

    return LayoutBuilder(builder: (context, c) {
      final scale = math.min(c.maxWidth / world.width, c.maxHeight / world.height);
      final size = Size(world.width * scale, world.height * scale);
      Offset toScreen(double x, double y) => Offset((x - world.left) * scale, (y - world.top) * scale);
      return InteractiveViewer(
        maxScale: 5,
        boundaryMargin: const EdgeInsets.all(80),
        child: Center(
          child: GestureDetector(
            onTapUp: onTapNode == null
                ? null
                : (d) {
                    GNode? best;
                    var bestD = double.infinity;
                    for (final n in nodes) {
                      final dist = (toScreen(n.x, n.y) - d.localPosition).distance;
                      if (dist < bestD) {
                        bestD = dist;
                        best = n;
                      }
                    }
                    if (best != null && bestD < 40) onTapNode!(best);
                  },
            child: CustomPaint(
              size: size,
              painter: _MapPainter(graph: graph, level: level, nodes: nodes, route: route, hazards: hazards, me: me, meSpreadM: meSpreadM, highlight: highlightNode, toScreen: toScreen, scale: scale),
            ),
          ),
        ),
      );
    });
  }
}

class _MapPainter extends CustomPainter {
  _MapPainter({
    required this.graph,
    required this.level,
    required this.nodes,
    required this.route,
    required this.hazards,
    required this.me,
    required this.meSpreadM,
    required this.highlight,
    required this.toScreen,
    required this.scale,
  });

  final BuildingGraph graph;
  final int level;
  final List<GNode> nodes;
  final List<int> route;
  final Map<int, String> hazards;
  final Offset? me;
  final double? meSpreadM;
  final int? highlight;
  final Offset Function(double, double) toScreen;
  final double scale;

  @override
  void paint(Canvas canvas, Size size) {
    final wall = Paint()
      ..color = Colors.white24
      ..strokeWidth = 2;
    for (final e in graph.edges) {
      final a = graph.nodes[e.a]!, b = graph.nodes[e.b]!;
      if (a.level != level || b.level != level) continue;
      canvas.drawLine(toScreen(a.x, a.y), toScreen(b.x, b.y), wall);
    }

    // hazards
    for (final n in nodes) {
      final hz = hazards[n.id];
      if (hz == null) continue;
      final color = hz == 'fire' ? AppColors.fire : hz == 'smoke' ? AppColors.smoke : AppColors.risk;
      canvas.drawCircle(toScreen(n.x, n.y), (hz == 'fire' ? 2.6 : 2.1) * scale, Paint()..color = color.withValues(alpha: hz == 'fire' ? 0.55 : 0.3));
    }

    // route on this floor
    final pts = [for (final id in route) if (graph.nodes[id]?.level == level) toScreen(graph.nodes[id]!.x, graph.nodes[id]!.y)];
    if (pts.length > 1) {
      final path = Path()..moveTo(pts.first.dx, pts.first.dy);
      for (final p in pts.skip(1)) {
        path.lineTo(p.dx, p.dy);
      }
      canvas.drawPath(
        path,
        Paint()
          ..color = AppColors.route
          ..style = PaintingStyle.stroke
          ..strokeWidth = 6
          ..strokeCap = StrokeCap.round
          ..strokeJoin = StrokeJoin.round,
      );
      // arrow head at the end of this floor's segment
      final a = pts[pts.length - 2], b = pts.last;
      final ang = math.atan2(b.dy - a.dy, b.dx - a.dx);
      final head = Path()
        ..moveTo(b.dx, b.dy)
        ..lineTo(b.dx - 14 * math.cos(ang - 0.5), b.dy - 14 * math.sin(ang - 0.5))
        ..lineTo(b.dx - 14 * math.cos(ang + 0.5), b.dy - 14 * math.sin(ang + 0.5))
        ..close();
      canvas.drawPath(head, Paint()..color = AppColors.route);
    }

    // nodes
    for (final n in nodes) {
      final p = toScreen(n.x, n.y);
      final r = (n.type == 'exit' ? 1.0 : n.type == 'corridor' ? 0.5 : 0.8) * scale;
      final fill = hazards[n.id] == 'fire'
          ? AppColors.fire
          : n.type == 'exit'
              ? AppColors.safe
              : n.type == 'refuge'
                  ? AppColors.route
                  : const Color(0xFF2A2A2E);
      canvas.drawCircle(p, math.max(r, 5), Paint()..color = fill);
      if (n.id == highlight) {
        canvas.drawCircle(p, math.max(r, 5) + 4, Paint()
          ..color = Colors.white
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2);
      }
      if (n.type != 'corridor') {
        final label = n.type == 'exit' ? 'EXIT · ${n.name}' : n.name;
        final tp = TextPainter(
          text: TextSpan(text: label, style: TextStyle(color: n.type == 'exit' ? AppColors.safe : Colors.white70, fontSize: 10, fontWeight: n.type == 'exit' ? FontWeight.w700 : FontWeight.w400)),
          textDirection: TextDirection.ltr,
          maxLines: 1,
          ellipsis: '…',
        )..layout(maxWidth: 110);
        // stairs and refuges usually sit next to a flat: label them above to avoid overlaps
        final above = n.type == 'stair' || n.type == 'refuge';
        tp.paint(canvas, p + Offset(-tp.width / 2, above ? -(math.max(r, 5) + 2 + tp.height) : math.max(r, 5) + 2));
      }
    }

    // me
    if (me != null) {
      final p = toScreen(me!.dx, me!.dy);
      if (meSpreadM != null && meSpreadM! > 0) {
        canvas.drawCircle(p, math.min(meSpreadM!, 8) * scale, Paint()..color = AppColors.route.withValues(alpha: 0.18));
      }
      canvas.drawCircle(p, 9, Paint()..color = Colors.white);
      canvas.drawCircle(p, 6.5, Paint()..color = AppColors.route);
    }
  }

  @override
  bool shouldRepaint(covariant _MapPainter old) =>
      old.route != route || old.hazards != hazards || old.me != me || old.level != level || old.meSpreadM != meSpreadM || old.highlight != highlight;
}
