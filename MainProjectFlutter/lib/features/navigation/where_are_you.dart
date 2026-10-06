import 'package:flutter/material.dart';

import '../../shared/graph.dart';

/// "Where are you?" picker: floor -> room. The answer is a strong observation on the server
/// (re-seeds the particle filter) and the start node for offline routing.
Future<int?> showWhereAreYou(BuildContext context, BuildingGraph graph, {int? suggestedNode, int? suggestedLevel}) {
  return showModalBottomSheet<int>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    builder: (_) => _WhereAreYou(graph: graph, suggestedNode: suggestedNode, suggestedLevel: suggestedLevel),
  );
}

class _WhereAreYou extends StatefulWidget {
  const _WhereAreYou({required this.graph, this.suggestedNode, this.suggestedLevel});
  final BuildingGraph graph;
  final int? suggestedNode;
  final int? suggestedLevel;

  @override
  State<_WhereAreYou> createState() => _WhereAreYouState();
}

class _WhereAreYouState extends State<_WhereAreYou> {
  late int _level = widget.suggestedLevel ?? widget.graph.nodes[widget.suggestedNode]?.level ?? widget.graph.floors.first.level;

  @override
  Widget build(BuildContext context) {
    final floors = [...widget.graph.floors]..sort((a, b) => b.level.compareTo(a.level));
    final places = widget.graph.nodes.values.where((n) => n.level == _level && n.type != 'assembly').toList()
      ..sort((a, b) => _rank(a).compareTo(_rank(b)) != 0 ? _rank(a).compareTo(_rank(b)) : a.name.compareTo(b.name));
    return DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.75,
      builder: (context, controller) => Column(
        children: [
          const SizedBox(height: 12),
          const Text('Where are you?', style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800)),
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: 24, vertical: 6),
            child: Text('Your Wi-Fi position is uncertain. Pick the place you are in or next to so we can guide you.', textAlign: TextAlign.center),
          ),
          SizedBox(
            height: 48,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 12),
              children: [
                for (final f in floors)
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 4),
                    child: ChoiceChip(label: Text(f.name), selected: f.level == _level, onSelected: (_) => setState(() => _level = f.level)),
                  ),
              ],
            ),
          ),
          Expanded(
            child: ListView(
              controller: controller,
              children: [
                for (final n in places)
                  ListTile(
                    leading: Icon(_icon(n.type)),
                    title: Text(n.name),
                    subtitle: n.id == widget.suggestedNode ? const Text('Last known position') : null,
                    selected: n.id == widget.suggestedNode,
                    onTap: () => Navigator.pop(context, n.id),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  static int _rank(GNode n) => switch (n.type) { 'room' => 0, 'corridor' => 1, 'stair' || 'lift' => 2, _ => 3 };

  static IconData _icon(String type) => switch (type) {
        'room' => Icons.door_front_door_outlined,
        'corridor' => Icons.swap_horiz,
        'stair' => Icons.stairs_outlined,
        'lift' => Icons.elevator_outlined,
        'exit' => Icons.exit_to_app,
        'refuge' => Icons.shield_outlined,
        _ => Icons.place_outlined,
      };
}
