import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme.dart';
import '../../state/evacuation.dart';
import '../../state/session.dart';

class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final session = ref.watch(sessionProvider);
    final evac = ref.watch(evacuationProvider);
    final user = session.user;
    final inc = evac.incident;
    final active = evac.incidentActive;

    return Scaffold(
      appBar: AppBar(
        title: Text(session.buildingName ?? 'Fire Evacuation'),
        actions: [IconButton(onPressed: () => context.push('/settings'), icon: const Icon(Icons.settings_outlined), tooltip: 'Settings')],
      ),
      body: RefreshIndicator(
        onRefresh: () => ref.read(evacuationProvider.notifier).refreshIncident(),
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Container(
              padding: const EdgeInsets.all(24),
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(20),
                gradient: active ? emergencyGradient : const LinearGradient(colors: [Color(0xFF0F3D1F), Color(0xFF0A1F12)]),
              ),
              child: Column(
                children: [
                  Icon(active ? Icons.local_fire_department : Icons.verified_user, size: 64, color: active ? Colors.white : AppColors.safe),
                  const SizedBox(height: 12),
                  Text(
                    active ? (inc!.isDrill ? 'DRILL IN PROGRESS' : 'FIRE - EVACUATE') : 'No emergency',
                    style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w900, letterSpacing: 1),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    active ? 'Follow your personal route out of the building.' : 'You will be alerted here if there is a fire in ${session.buildingName ?? 'your building'}.',
                    textAlign: TextAlign.center,
                    style: const TextStyle(color: Colors.white70),
                  ),
                  if (active) ...[
                    const SizedBox(height: 16),
                    FilledButton.icon(
                      style: FilledButton.styleFrom(backgroundColor: Colors.white, foregroundColor: AppColors.fireDark),
                      onPressed: () => context.go('/evacuate'),
                      icon: const Icon(Icons.directions_run),
                      label: Text(evac.myStatus == 'safe' ? 'I\'m safe - view status' : 'Open my evacuation route'),
                    ),
                  ],
                ],
              ),
            ),
            const SizedBox(height: 16),
            Card(
              child: Column(
                children: [
                  ListTile(leading: const Icon(Icons.home_outlined), title: Text(user?.name ?? ''), subtitle: Text([session.buildingName, user?.flat].whereType<String>().join(' · '))),
                  ListTile(
                    leading: Icon(evac.connected ? Icons.cloud_done_outlined : Icons.cloud_off_outlined, color: evac.connected ? AppColors.safe : Colors.amber),
                    title: Text(evac.connected ? 'Connected to the evacuation server' : 'Not connected'),
                    subtitle: Text(evac.graph != null ? 'Building map saved for offline use (v${evac.graph!.graphVersion})' : 'Map not downloaded yet'),
                  ),
                  if (user?.stairsOk == false)
                    const ListTile(
                      leading: Icon(Icons.accessible),
                      title: Text('Step-free routes'),
                      subtitle: Text('You will be guided to the nearest exit or refuge area without stairs.'),
                    ),
                ],
              ),
            ),
            const SizedBox(height: 8),
            if (user?.canSurvey ?? false)
              Card(
                child: ListTile(
                  leading: const Icon(Icons.wifi_tethering),
                  title: const Text('Wi-Fi survey mode'),
                  subtitle: const Text('Record signal fingerprints room by room to improve positioning.'),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => context.push('/survey'),
                ),
              ),
            if (evac.simulation)
              Card(
                child: ListTile(
                  leading: const Icon(Icons.science_outlined),
                  title: const Text('Simulation mode - developer panel'),
                  subtitle: const Text('The building is in simulation mode. Set your position by tapping the map.'),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => context.push('/dev'),
                ),
              ),
            const SizedBox(height: 16),
            const Text(
              'Not a certified life-safety system. Always follow the fire alarm, exit signs and responders.',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 11, color: Colors.white54),
            ),
          ],
        ),
      ),
    );
  }
}
