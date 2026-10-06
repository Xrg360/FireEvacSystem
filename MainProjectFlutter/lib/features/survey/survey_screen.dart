import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../services/scan_service.dart';
import '../../shared/graph.dart';
import '../../state/evacuation.dart';
import '../../state/session.dart';
import '../../widgets/floor_map.dart';

/// Survey mode (surveyor / admin): stand in a room, record labelled Wi-Fi scans. These train the
/// fingerprint model and calibrate P_ref / eta per router (paper eq. 1) - "Calibrate" in the dashboard.
class SurveyScreen extends ConsumerStatefulWidget {
  const SurveyScreen({super.key});

  @override
  ConsumerState<SurveyScreen> createState() => _SurveyScreenState();
}

class _SurveyScreenState extends ConsumerState<SurveyScreen> {
  ScanService? _scanner;
  Map<String, double> _latest = {};
  int? _level;
  GNode? _node;
  bool _recording = false;
  int _target = 20;
  int _recorded = 0;
  Map<int, int> _coverage = {};
  String? _error;
  final List<String> _log = [];

  @override
  void initState() {
    super.initState();
    _scanner = ScanService((r) {
      setState(() => _latest = r);
      if (_recording) _record(r);
    });
    _scanner!.start(every: const Duration(seconds: 3)).then((p) => mounted ? setState(() => _error = p) : null);
    _loadCoverage();
  }

  @override
  void dispose() {
    _scanner?.stop();
    super.dispose();
  }

  int? get _buildingId => ref.read(sessionProvider).user?.buildingId;

  Future<void> _loadCoverage() async {
    final bid = _buildingId;
    if (bid == null) return;
    try {
      final r = await ref.read(apiProvider).get('/buildings/$bid/survey/coverage');
      setState(() => _coverage = {for (final n in r['nodes'] as List) (n as Map)['node_id'] as int: n['samples'] as int});
    } catch (_) {}
  }

  Future<void> _record(Map<String, double> readings) async {
    final bid = _buildingId;
    if (bid == null || _node == null) return;
    try {
      final r = await ref.read(apiProvider).post('/buildings/$bid/survey', {
        'node_id': _node!.id,
        'readings': [for (final e in readings.entries) {'bssid': e.key, 'rssi': e.value}],
      });
      setState(() {
        _recorded++;
        _coverage[_node!.id] = r['samples_at_node'] as int;
        _log.insert(0, '${_node!.name}: ${readings.length} routers');
        if (_recorded >= _target) _recording = false;
      });
    } on ApiException catch (e) {
      setState(() {
        _recording = false;
        _error = e.message;
      });
    }
  }

  Future<void> _registerRouter() async {
    final bid = _buildingId;
    if (bid == null || _node == null || _latest.isEmpty) return;
    final strongest = _latest.entries.reduce((a, b) => a.value >= b.value ? a : b);
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Register router here?'),
        content: Text('The strongest router is ${strongest.key} (${strongest.value.round()} dBm). Register it at ${_node!.name}? Stand right next to it.'),
        actions: [TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')), FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Register'))],
      ),
    );
    if (ok != true) return;
    try {
      await ref.read(apiProvider).post('/buildings/$bid/access-points/register', {'bssid': strongest.key, 'node_id': _node!.id});
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Router ${strongest.key} registered at ${_node!.name}')));
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final g = ref.watch(evacuationProvider).graph;
    if (g == null) return Scaffold(appBar: AppBar(title: const Text('Wi-Fi survey')), body: const Center(child: Text('Building map not loaded yet.')));
    final level = _level ?? g.floors.first.level;
    final floors = [...g.floors]..sort((a, b) => b.level.compareTo(a.level));
    final throttled = (_scanner?.refusedScans ?? 0) > (_scanner?.acceptedScans ?? 0);
    return Scaffold(
      appBar: AppBar(title: const Text('Wi-Fi survey')),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (_error != null) Container(color: Colors.orange, padding: const EdgeInsets.all(8), child: Text(_error!, style: const TextStyle(color: Colors.black))),
          if (throttled)
            Container(
              color: Colors.amber,
              padding: const EdgeInsets.all(8),
              child: const Text('Android is throttling Wi-Fi scans. Turn off Developer options → Wi-Fi scan throttling for a scan every ~3 s.', style: TextStyle(color: Colors.black)),
            ),
          SizedBox(
            height: 48,
            child: ListView(scrollDirection: Axis.horizontal, padding: const EdgeInsets.all(6), children: [
              for (final f in floors)
                Padding(padding: const EdgeInsets.only(right: 6), child: ChoiceChip(label: Text(f.name), selected: f.level == level, onSelected: (_) => setState(() => _level = f.level))),
            ]),
          ),
          Expanded(
            child: FloorMap(graph: g, level: level, highlightNode: _node?.id, onTapNode: (n) => setState(() {
                  _node = n;
                  _recording = false;
                })),
          ),
          Card(
            margin: const EdgeInsets.all(12),
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                Text(_node == null ? 'Tap the place you are standing in' : '${_node!.name} - ${_coverage[_node!.id] ?? 0} scans saved (aim for 20)',
                    style: const TextStyle(fontWeight: FontWeight.w700)),
                Text('${_latest.length} routers heard now'),
                const SizedBox(height: 8),
                Row(children: [
                  Expanded(
                    child: FilledButton(
                      onPressed: _node == null
                          ? null
                          : () => setState(() {
                                _recording = !_recording;
                                _recorded = 0;
                              }),
                      child: Text(_recording ? 'Stop ($_recorded/$_target)' : 'Record $_target scans'),
                    ),
                  ),
                  const SizedBox(width: 8),
                  DropdownButton<int>(
                    value: _target,
                    items: const [10, 20, 30].map((v) => DropdownMenuItem(value: v, child: Text('$v'))).toList(),
                    onChanged: (v) => setState(() => _target = v ?? 20),
                  ),
                ]),
                TextButton.icon(onPressed: _node == null ? null : _registerRouter, icon: const Icon(Icons.router_outlined), label: const Text('A router is mounted here - register it')),
                if (_log.isNotEmpty) Text(_log.first, style: const TextStyle(fontSize: 12, color: Colors.white60)),
              ]),
            ),
          ),
        ],
      ),
    );
  }
}
