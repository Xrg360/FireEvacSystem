import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../services/notifications.dart';
import '../../state/evacuation.dart';
import '../../state/session.dart';

class SettingsScreen extends ConsumerWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final storage = ref.watch(storageProvider);
    final s = ref.watch(sessionProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: ListView(children: [
        ListTile(leading: const Icon(Icons.person_outline), title: Text(s.user?.name ?? ''), subtitle: Text('${s.user?.email ?? ''}\n${s.user?.role.replaceAll('_', ' ') ?? ''}'), isThreeLine: true),
        ListTile(leading: const Icon(Icons.dns_outlined), title: const Text('Server'), subtitle: Text(storage.serverUrl), onTap: () => context.push('/server')),
        ListTile(leading: const Icon(Icons.verified_user_outlined), title: const Text('Permissions & alarm setup'), onTap: () => context.push('/permissions')),
        ListTile(
          leading: const Icon(Icons.notifications_outlined),
          title: const Text('Push notifications'),
          subtitle: Text(firebaseReady ? 'Enabled (alarms reach you when the app is closed)' : 'Not configured on this build - alarms only arrive while the app is open'),
        ),
        ListTile(
          leading: const Icon(Icons.notification_important_outlined),
          title: const Text('Test the alarm'),
          subtitle: const Text('Shows the full-screen alarm notification without contacting the server'),
          onTap: () => showIncidentNotification({'title': 'TEST - this is only a test', 'body': 'Your alarm works.', 'status': 'evacuating'}),
        ),
        ListTile(
          leading: const Icon(Icons.map_outlined),
          title: const Text('Offline building map'),
          subtitle: Text(ref.watch(evacuationProvider).graph == null ? 'Not downloaded' : 'Saved · v${ref.watch(evacuationProvider).graph!.graphVersion}'),
        ),
        const ListTile(
          leading: Icon(Icons.privacy_tip_outlined),
          title: Text('Privacy'),
          subtitle: Text('Your position is only sent during a fire, a drill or a simulation, and the server deletes position history after a few days.'),
          isThreeLine: true,
        ),
        ListTile(leading: const Icon(Icons.logout), title: const Text('Sign out'), onTap: () => ref.read(sessionProvider.notifier).logout()),
        const Padding(
          padding: EdgeInsets.all(16),
          child: Text('AI-Driven Smart Fire Evacuation System · IEEE ICSCC 2025. Not a certified life-safety system.', style: TextStyle(fontSize: 11, color: Colors.white54)),
        ),
      ]),
    );
  }
}
