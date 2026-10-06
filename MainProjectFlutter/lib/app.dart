import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'core/theme.dart';
import 'features/alarm/alarm_screen.dart';
import 'features/dev/dev_panel.dart';
import 'features/home/home_screen.dart';
import 'features/navigation/evacuate_screen.dart';
import 'features/onboarding/join_screen.dart';
import 'features/onboarding/login_screen.dart';
import 'features/onboarding/pending_screen.dart';
import 'features/onboarding/server_screen.dart';
import 'features/permissions/permissions_screen.dart';
import 'features/settings/settings_screen.dart';
import 'features/survey/survey_screen.dart';
import 'services/notifications.dart';
import 'state/evacuation.dart';
import 'state/session.dart';

class _SessionListenable extends ChangeNotifier {
  _SessionListenable(Ref ref) {
    ref.listen(sessionProvider, (_, _) => notifyListeners());
  }
}

final routerProvider = Provider<GoRouter>((ref) {
  final listenable = _SessionListenable(ref);
  const publicPaths = {'/login', '/join', '/server'};
  return GoRouter(
    initialLocation: '/home',
    refreshListenable: listenable,
    redirect: (context, state) {
      final s = ref.read(sessionProvider);
      final loc = state.matchedLocation;
      switch (s.status) {
        case SessionStatus.loading:
          return loc == '/splash' ? null : '/splash';
        case SessionStatus.needsServer:
          return loc == '/server' ? null : '/server';
        case SessionStatus.loggedOut:
          return publicPaths.contains(loc) ? null : '/login';
        case SessionStatus.pending:
          return loc == '/pending' ? null : '/pending';
        case SessionStatus.ready:
          final storage = ref.read(storageProvider);
          if (!storage.flag('permissions_done') && loc != '/permissions') return '/permissions';
          if (publicPaths.contains(loc) && loc != '/server' || loc == '/splash' || loc == '/pending') return '/home';
          return null;
      }
    },
    routes: [
      GoRoute(path: '/splash', builder: (_, _) => const Scaffold(body: Center(child: CircularProgressIndicator()))),
      GoRoute(path: '/server', builder: (_, _) => const ServerScreen()),
      GoRoute(path: '/login', builder: (_, _) => const LoginScreen()),
      GoRoute(path: '/join', builder: (_, _) => const JoinScreen()),
      GoRoute(path: '/pending', builder: (_, _) => const PendingScreen()),
      GoRoute(path: '/permissions', builder: (_, _) => const PermissionsScreen()),
      GoRoute(path: '/home', builder: (_, _) => const HomeScreen()),
      GoRoute(path: '/alarm', builder: (_, _) => const AlarmScreen()),
      GoRoute(path: '/evacuate', builder: (_, _) => const EvacuateScreen()),
      GoRoute(path: '/survey', builder: (_, _) => const SurveyScreen()),
      GoRoute(path: '/dev', builder: (_, _) => const DevPanel()),
      GoRoute(path: '/settings', builder: (_, _) => const SettingsScreen()),
    ],
  );
});

class FireEvacApp extends ConsumerStatefulWidget {
  const FireEvacApp({super.key});

  @override
  ConsumerState<FireEvacApp> createState() => _FireEvacAppState();
}

class _FireEvacAppState extends ConsumerState<FireEvacApp> {
  final List<StreamSubscription<dynamic>> _subs = [];

  @override
  void initState() {
    super.initState();
    // Alarm from the server socket (new incident) or from tapping the push notification.
    _subs.add(alarmSignal.stream.listen((_) => ref.read(routerProvider).go('/alarm')));
    _subs.add(alarmTaps.stream.listen((_) async {
      await ref.read(evacuationProvider.notifier).refreshIncident();
      final s = ref.read(evacuationProvider);
      if (s.incidentActive) ref.read(routerProvider).go(s.acknowledged ? '/evacuate' : '/alarm');
    }));
  }

  @override
  void dispose() {
    for (final s in _subs) {
      s.cancel();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    // keep the evacuation controller alive for the whole app session
    ref.watch(evacuationProvider.select((s) => s.incidentActive));
    return MaterialApp.router(
      title: 'Fire Evacuation',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(),
      routerConfig: ref.watch(routerProvider),
    );
  }
}
