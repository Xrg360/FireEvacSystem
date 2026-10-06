import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:vibration/vibration.dart';

import '../../core/native.dart';
import '../../core/theme.dart';
import '../../state/evacuation.dart';

/// Full-screen alarm (opened by the push notification or the socket).
class AlarmScreen extends ConsumerStatefulWidget {
  const AlarmScreen({super.key});

  @override
  ConsumerState<AlarmScreen> createState() => _AlarmScreenState();
}

class _AlarmScreenState extends ConsumerState<AlarmScreen> with SingleTickerProviderStateMixin {
  late final AnimationController _pulse = AnimationController(vsync: this, duration: const Duration(milliseconds: 900))..repeat(reverse: true);
  Timer? _buzz;

  @override
  void initState() {
    super.initState();
    NativeBridge.keepScreenOn(true);
    _vibrate();
    _buzz = Timer.periodic(const Duration(seconds: 3), (_) => _vibrate());
  }

  Future<void> _vibrate() async {
    if (await Vibration.hasVibrator()) Vibration.vibrate(pattern: [0, 600, 250, 600]);
  }

  @override
  void dispose() {
    _buzz?.cancel();
    Vibration.cancel();
    _pulse.dispose();
    super.dispose();
  }

  Future<void> _evacuate() async {
    _buzz?.cancel();
    Vibration.cancel();
    await ref.read(evacuationProvider.notifier).acknowledge();
    if (mounted) context.go('/evacuate');
  }

  @override
  Widget build(BuildContext context) {
    final evac = ref.watch(evacuationProvider);
    final drill = evac.incident?.isDrill ?? false;
    return PopScope(
      canPop: false,
      child: Scaffold(
        body: Container(
          decoration: const BoxDecoration(gradient: emergencyGradient),
          child: SafeArea(
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                children: [
                  const Spacer(),
                  ScaleTransition(
                    scale: Tween(begin: 0.9, end: 1.15).animate(_pulse),
                    child: const Icon(Icons.local_fire_department, size: 140, color: Colors.white),
                  ),
                  const SizedBox(height: 24),
                  Text(drill ? 'FIRE DRILL' : 'FIRE DETECTED', style: const TextStyle(fontSize: 38, fontWeight: FontWeight.w900, letterSpacing: 2)),
                  const SizedBox(height: 12),
                  Text(
                    drill ? 'This is a drill. Evacuate as you would in a real fire.' : 'Leave the building now. Do not use lifts.',
                    textAlign: TextAlign.center,
                    style: const TextStyle(fontSize: 18, color: Colors.white),
                  ),
                  const SizedBox(height: 8),
                  const Text('Your safest route updates live as conditions change.', textAlign: TextAlign.center, style: TextStyle(color: Colors.white70)),
                  const Spacer(),
                  FilledButton.icon(
                    style: FilledButton.styleFrom(backgroundColor: Colors.white, foregroundColor: AppColors.fireDark, minimumSize: const Size.fromHeight(64)),
                    onPressed: _evacuate,
                    icon: const Icon(Icons.directions_run, size: 28),
                    label: const Text('EVACUATE NOW', style: TextStyle(fontSize: 20)),
                  ),
                  const SizedBox(height: 12),
                  TextButton(
                    onPressed: () async {
                      await ref.read(evacuationProvider.notifier).setStatus('safe');
                      if (context.mounted) context.go('/evacuate');
                    },
                    child: const Text('I am already outside and safe', style: TextStyle(color: Colors.white)),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
