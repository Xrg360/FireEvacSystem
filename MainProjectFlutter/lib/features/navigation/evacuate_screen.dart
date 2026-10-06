import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/native.dart';
import '../../core/theme.dart';
import '../../shared/models.dart';
import '../../state/evacuation.dart';
import '../../state/session.dart';
import '../../widgets/floor_map.dart';
import 'where_are_you.dart';

class EvacuateScreen extends ConsumerStatefulWidget {
  const EvacuateScreen({super.key});

  @override
  ConsumerState<EvacuateScreen> createState() => _EvacuateScreenState();
}

class _EvacuateScreenState extends ConsumerState<EvacuateScreen> {
  int? _viewLevel;
  bool _large = false;
  bool _pickerOpen = false;
  DateTime? _pickerDismissedAt;
  bool _floorAsked = false;
  int _lastRouteVersion = 0;

  @override
  void initState() {
    super.initState();
    NativeBridge.keepScreenOn(true);
    _large = ref.read(storageProvider).flag('large_text');
  }

  @override
  void dispose() {
    NativeBridge.keepScreenOn(false);
    super.dispose();
  }

  void _reactTo(EvacState s) {
    // "Where are you?" when the position is unknown/uncertain (not more than once a minute)
    final dismissedRecently = _pickerDismissedAt != null && DateTime.now().difference(_pickerDismissedAt!) < const Duration(seconds: 60);
    if (s.incidentActive && s.myStatus != 'safe' && s.graph != null && s.needsPicker && !_pickerOpen && !dismissedRecently && s.scansSent > 1) {
      _pickerOpen = true;
      WidgetsBinding.instance.addPostFrameCallback((_) => _openPicker(s));
    }
    // floor confirmation requested by the server
    if (s.fix?.confirmFloor == true && !_floorAsked && s.fix?.level != null) {
      _floorAsked = true;
      WidgetsBinding.instance.addPostFrameCallback((_) => _confirmFloor(s));
    }
    // announce reroutes
    final r = s.route;
    if (r != null && r.version != _lastRouteVersion) {
      final reroute = _lastRouteVersion != 0 && r.version > 0;
      _lastRouteVersion = r.version;
      if (reroute && mounted) {
        final why = switch (r.reason) {
          'hazard' => 'Fire or smoke on your previous route.',
          'congestion' => 'Your previous route is crowded.',
          'deviation' => 'You left the previous route.',
          _ => 'Conditions changed.',
        };
        WidgetsBinding.instance.addPostFrameCallback((_) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(backgroundColor: AppColors.smoke, content: Text('New route: $why Follow the blue line.')));
        });
      }
    }
  }

  Future<void> _openPicker(EvacState s) async {
    final node = await showWhereAreYou(context, s.graph!, suggestedNode: s.fix?.nodeId ?? s.manualNodeId, suggestedLevel: s.fix?.level);
    _pickerOpen = false;
    if (node != null) {
      await ref.read(evacuationProvider.notifier).manualPick(node);
    } else {
      _pickerDismissedAt = DateTime.now();
    }
  }

  Future<void> _confirmFloor(EvacState s) async {
    final g = s.graph!;
    final floor = g.floorByLevel(s.fix!.level!);
    final yes = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Which floor are you on?'),
        content: Text('Are you on ${floor?.name ?? 'level ${s.fix!.level}'}?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('No, pick another')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Yes')),
        ],
      ),
    );
    if (yes == true) {
      await ref.read(evacuationProvider.notifier).confirmFloor(s.fix!.level!);
    } else if (yes == false && mounted) {
      await _openPicker(s);
    }
    Future.delayed(const Duration(minutes: 2), () => _floorAsked = false);
  }

  Future<void> _needHelp() async {
    final note = TextEditingController();
    var kind = 'help';
    final send = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setS) => Padding(
          padding: EdgeInsets.fromLTRB(20, 20, 20, MediaQuery.of(ctx).viewInsets.bottom + 20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text('Request help', style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800)),
              const SizedBox(height: 8),
              const Text('Rescuers see your last known position and phone number.'),
              const SizedBox(height: 12),
              SegmentedButton<String>(
                segments: const [
                  ButtonSegment(value: 'help', label: Text('Need help')),
                  ButtonSegment(value: 'trapped', label: Text('Trapped')),
                  ButtonSegment(value: 'medical', label: Text('Medical')),
                ],
                selected: {kind},
                onSelectionChanged: (v) => setS(() => kind = v.first),
              ),
              const SizedBox(height: 12),
              TextField(controller: note, decoration: const InputDecoration(labelText: 'Details (optional), e.g. "2 people, smoke at door"')),
              const SizedBox(height: 16),
              FilledButton(style: FilledButton.styleFrom(backgroundColor: AppColors.fire), onPressed: () => Navigator.pop(ctx, true), child: const Text('SEND SOS')),
              const SizedBox(height: 8),
              const Text('If smoke is around you: stay low, close the door, block gaps with cloth.', style: TextStyle(color: Colors.white70)),
            ],
          ),
        ),
      ),
    );
    if (send == true) {
      await ref.read(evacuationProvider.notifier).sos(kind, note.text.trim().isEmpty ? null : note.text.trim());
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('SOS sent. Rescuers have been notified.')));
    }
    note.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(evacuationProvider);
    _reactTo(s);
    final g = s.graph;
    final route = s.route;
    final myLevel = s.fix?.level ?? (route != null && g != null ? g.nodes[route.path.first]?.level : null);
    final level = _viewLevel ?? myLevel ?? g?.floors.first.level ?? 0;
    final textScale = _large ? 1.35 : 1.0;

    if (!s.incidentActive) {
      return Scaffold(
        appBar: AppBar(title: const Text('Evacuation')),
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              const Icon(Icons.verified_user, size: 72, color: AppColors.safe),
              const SizedBox(height: 12),
              const Text('The incident is over.', style: TextStyle(fontSize: 22, fontWeight: FontWeight.w700)),
              const SizedBox(height: 8),
              const Text('Follow instructions from responders before re-entering.', textAlign: TextAlign.center),
              const SizedBox(height: 20),
              FilledButton(onPressed: () => context.go('/home'), child: const Text('Back to home')),
            ]),
          ),
        ),
      );
    }

    final currentIdx = _currentStepIndex(route, s.fix?.nodeId);
    final current = route == null || route.steps.isEmpty ? null : route.steps[currentIdx.clamp(0, route.steps.length - 1)];

    return MediaQuery(
      data: MediaQuery.of(context).copyWith(textScaler: TextScaler.linear(textScale)),
      child: Scaffold(
        appBar: AppBar(
          title: Text(s.incident!.isDrill ? 'Drill - evacuate' : 'Evacuate'),
          actions: [
            IconButton(
              tooltip: 'Large text',
              icon: Icon(_large ? Icons.text_decrease : Icons.text_increase),
              onPressed: () {
                setState(() => _large = !_large);
                ref.read(storageProvider).setFlag('large_text', _large);
              },
            ),
            IconButton(tooltip: 'Set my location', icon: const Icon(Icons.edit_location_alt_outlined), onPressed: g == null ? null : () => _openPicker(s)),
          ],
        ),
        body: SafeArea(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              ..._banners(s),
              if (s.myStatus == 'safe')
                _statusCard(Icons.verified, AppColors.safe, 'You are marked SAFE', 'Stay at the assembly point and away from the building.')
              else if (s.myStatus == 'needs_help')
                _statusCard(Icons.support, AppColors.fire, 'Help requested', 'Rescuers can see your last known position. Stay low and keep doors closed.'),
              if (current != null && s.myStatus != 'safe')
                Container(
                  margin: const EdgeInsets.fromLTRB(12, 8, 12, 4),
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(color: AppColors.route.withValues(alpha: 0.18), borderRadius: BorderRadius.circular(16), border: Border.all(color: AppColors.route)),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(current.text, style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w800)),
                    const SizedBox(height: 6),
                    Text(
                      '${route!.toRefuge ? 'Refuge area' : 'Exit'}: ${route.goalName} · ${route.remainingM.round()} m${route.offline ? ' · computed on this phone' : ''}',
                      style: const TextStyle(color: Colors.white70),
                    ),
                  ]),
                ),
              if (route == null && !s.noRoute && s.myStatus != 'safe')
                _statusCard(Icons.wifi_find, Colors.white70, 'Finding your position…', s.scanning ? 'Scanning Wi-Fi (${s.lastReadings.length} routers heard).' : 'Waiting for location.'),
              Expanded(
                flex: 5,
                child: g == null
                    ? const Center(child: CircularProgressIndicator())
                    : Column(children: [
                        // floor switcher in its own row so it never covers the map
                        SizedBox(
                          height: 44,
                          child: ListView(
                            scrollDirection: Axis.horizontal,
                            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                            children: [
                              for (final f in [...g.floors]..sort((a, b) => b.level.compareTo(a.level)))
                                Padding(
                                  padding: const EdgeInsets.only(right: 6),
                                  child: ChoiceChip(
                                    label: Text(f.level == myLevel ? '${f.name} •' : f.name, style: const TextStyle(fontSize: 12)),
                                    selected: f.level == level,
                                    onSelected: (_) => setState(() => _viewLevel = f.level == myLevel ? null : f.level),
                                  ),
                                ),
                            ],
                          ),
                        ),
                        Expanded(
                          child: FloorMap(
                            graph: g,
                            level: level,
                            route: route?.path ?? const [],
                            hazards: s.hazards,
                            me: s.fix?.x != null && s.fix?.level == level ? Offset(s.fix!.x!, s.fix!.y!) : null,
                            meSpreadM: s.fix?.spreadM,
                          ),
                        ),
                      ]),
              ),
              if (route != null && s.myStatus != 'safe')
                Expanded(
                  flex: 3,
                  child: ListView.builder(
                    padding: const EdgeInsets.symmetric(horizontal: 12),
                    itemCount: route.steps.length,
                    itemBuilder: (_, i) {
                      final st = route.steps[i];
                      final done = i < currentIdx;
                      return ListTile(
                        dense: true,
                        leading: Icon(_stepIcon(st.kind), color: done ? Colors.white30 : (i == currentIdx ? AppColors.route : Colors.white)),
                        title: Text(st.text, style: TextStyle(color: done ? Colors.white38 : null, decoration: done ? TextDecoration.lineThrough : null)),
                        trailing: st.distanceM > 0 ? Text('${st.distanceM.round()} m') : null,
                      );
                    },
                  ),
                ),
              Padding(
                padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
                child: Row(children: [
                  Expanded(
                    child: FilledButton.icon(
                      style: FilledButton.styleFrom(backgroundColor: AppColors.safe),
                      onPressed: s.myStatus == 'safe' ? null : () => ref.read(evacuationProvider.notifier).setStatus('safe'),
                      icon: const Icon(Icons.verified),
                      label: const Text("I'M SAFE"),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: GestureDetector(
                      onLongPress: () => launchUrl(Uri.parse('tel:112')),
                      child: FilledButton.icon(
                        style: FilledButton.styleFrom(backgroundColor: AppColors.fire),
                        onPressed: _needHelp,
                        icon: const Icon(Icons.sos),
                        label: const Text('NEED HELP'),
                      ),
                    ),
                  ),
                ]),
              ),
              const Padding(
                padding: EdgeInsets.only(bottom: 6),
                child: Text('Long-press NEED HELP to call 112', textAlign: TextAlign.center, style: TextStyle(fontSize: 11, color: Colors.white54)),
              ),
            ],
          ),
        ),
      ),
    );
  }

  List<Widget> _banners(EvacState s) {
    final out = <Widget>[];
    void add(Color c, IconData i, String text) => out.add(Container(
          color: c.withValues(alpha: 0.9),
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
          child: Row(children: [Icon(i, size: 18, color: Colors.black), const SizedBox(width: 8), Expanded(child: Text(text, style: const TextStyle(color: Colors.black, fontWeight: FontWeight.w600)))]),
        ));
    if (s.offline) add(AppColors.risk, Icons.cloud_off, 'OFFLINE - route computed on this phone from the last known fire data.');
    if (s.noRoute) add(AppColors.fire, Icons.block, 'No safe route found from here. Stay low, close the door, and press NEED HELP.');
    if (s.fix?.outside == true && s.myStatus != 'safe') add(AppColors.safe, Icons.park, 'GPS shows you are outside the building. Tap I\'M SAFE if you are at the assembly point.');
    if (s.scanProblem != null) add(AppColors.smoke, Icons.wifi_off, s.scanProblem!);
    if (s.route?.toRefuge == true) add(AppColors.route, Icons.accessible, 'Step-free route to a refuge area. Rescuers know where you are going.');
    if (s.pendingActions > 0) add(Colors.white70, Icons.schedule_send, '${s.pendingActions} update(s) will be sent when the connection returns.');
    return out;
  }

  Widget _statusCard(IconData icon, Color color, String title, String body) => Container(
        margin: const EdgeInsets.fromLTRB(12, 8, 12, 4),
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(color: color.withValues(alpha: 0.15), borderRadius: BorderRadius.circular(14), border: Border.all(color: color.withValues(alpha: 0.6))),
        child: Row(children: [
          Icon(icon, color: color, size: 30),
          const SizedBox(width: 12),
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(title, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16)), Text(body)])),
        ]),
      );

  /// The next instruction is the first step whose node is still ahead of us on the path.
  int _currentStepIndex(RouteInfo? r, int? myNode) {
    if (r == null || myNode == null) return 1;
    final pos = r.path.indexOf(myNode);
    if (pos < 0) return 1;
    for (var i = 0; i < r.steps.length; i++) {
      final idx = r.path.indexOf(r.steps[i].nodeId);
      if (idx > pos) return i;
    }
    return r.steps.length - 1;
  }

  static IconData _stepIcon(String kind) => switch (kind) {
        'start' => Icons.trip_origin,
        'stairs' => Icons.stairs_outlined,
        'exit' => Icons.exit_to_app,
        'refuge' => Icons.shield_outlined,
        'arrive' => Icons.flag,
        _ => Icons.arrow_upward,
      };
}
