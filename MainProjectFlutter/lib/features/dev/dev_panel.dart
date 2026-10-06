import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../state/evacuation.dart';
import '../../widgets/floor_map.dart';

/// Simulation-mode developer panel: set your ground-truth position by tapping the map (sent as a
/// manual pick), see what the phone is scanning and how the server located you.
class DevPanel extends ConsumerStatefulWidget {
  const DevPanel({super.key});

  @override
  ConsumerState<DevPanel> createState() => _DevPanelState();
}

class _DevPanelState extends ConsumerState<DevPanel> {
  int? _level;

  @override
  void initState() {
    super.initState();
    ref.read(evacuationProvider.notifier).startDevTracking();
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(evacuationProvider);
    final g = s.graph;
    if (!s.simulation) {
      return Scaffold(appBar: AppBar(title: const Text('Developer panel')), body: const Center(child: Text('Only available while the building is in Simulation mode.')));
    }
    if (g == null) return const Scaffold(body: Center(child: CircularProgressIndicator()));
    final level = _level ?? s.fix?.level ?? g.floors.first.level;
    final readings = s.lastReadings.entries.toList()..sort((a, b) => b.value.compareTo(a.value));
    final fix = s.fix;
    return Scaffold(
      appBar: AppBar(title: const Text('Developer panel (simulation)')),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.all(8),
            child: Wrap(spacing: 6, children: [
              for (final f in [...g.floors]..sort((a, b) => b.level.compareTo(a.level)))
                ChoiceChip(label: Text(f.name), selected: f.level == level, onSelected: (_) => setState(() => _level = f.level)),
            ]),
          ),
          const Padding(padding: EdgeInsets.symmetric(horizontal: 12), child: Text('Tap a room to place yourself there (manual position).')),
          Expanded(
            flex: 3,
            child: FloorMap(
              graph: g,
              level: level,
              route: s.route?.path ?? const [],
              hazards: s.hazards,
              me: fix?.x != null && fix?.level == level ? Offset(fix!.x!, fix.y!) : null,
              meSpreadM: fix?.spreadM,
              onTapNode: (n) => ref.read(evacuationProvider.notifier).manualPick(n.id),
            ),
          ),
          Expanded(
            flex: 2,
            child: ListView(padding: const EdgeInsets.all(12), children: [
              Text('Socket: ${s.connected ? 'connected' : 'disconnected'} · scans sent: ${s.scansSent} · incident: ${s.incident?.kind ?? 'none'}'),
              Text('Fix: ${fix?.source ?? '-'} · node ${fix?.nodeId != null ? g.nodes[fix!.nodeId]?.name : '-'} · level ${fix?.level ?? '-'} · '
                  'confidence ${fix != null ? (fix.confidence * 100).round() : 0}% · floor ${fix != null ? (fix.floorConfidence * 100).round() : 0}% · ±${fix?.spreadM?.toStringAsFixed(1) ?? '-'} m'),
              if (s.route != null) Text('Route v${s.route!.version} (${s.route!.reason}) → ${s.route!.goalName}, ${s.route!.remainingM.round()} m'),
              const Divider(),
              Text('Wi-Fi now (${readings.length} routers):', style: const TextStyle(fontWeight: FontWeight.w700)),
              for (final r in readings.take(12))
                Text('${r.key}  ${r.value.round()} dBm${g.accessPoints.any((a) => a.bssid == r.key) ? '  (mapped)' : ''}', style: const TextStyle(fontFamily: 'monospace', fontSize: 12)),
            ]),
          ),
        ],
      ),
    );
  }
}
