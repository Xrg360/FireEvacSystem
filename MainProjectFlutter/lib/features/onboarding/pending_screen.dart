import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../state/session.dart';

class PendingScreen extends ConsumerWidget {
  const PendingScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(sessionProvider);
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Icon(Icons.hourglass_top, size: 64, color: Colors.amberAccent),
              const SizedBox(height: 16),
              Text('Waiting for approval', textAlign: TextAlign.center, style: Theme.of(context).textTheme.headlineSmall),
              const SizedBox(height: 8),
              Text(
                'Hi ${s.user?.name ?? ''}. A ${s.societyName ?? 'society'} admin needs to approve your account before you receive alarms.',
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 24),
              FilledButton(onPressed: () => ref.read(sessionProvider.notifier).refreshMe(), child: const Text('Check again')),
              TextButton(onPressed: () => ref.read(sessionProvider.notifier).logout(), child: const Text('Sign out')),
            ],
          ),
        ),
      ),
    );
  }
}
