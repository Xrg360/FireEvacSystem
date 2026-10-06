import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geolocator/geolocator.dart';
import 'package:go_router/go_router.dart';
import 'package:permission_handler/permission_handler.dart';

import '../../core/native.dart';
import '../../services/notifications.dart';
import '../../state/session.dart';

/// Explains and requests each permission the alarm + indoor positioning need.
class PermissionsScreen extends ConsumerStatefulWidget {
  const PermissionsScreen({super.key});

  @override
  ConsumerState<PermissionsScreen> createState() => _PermissionsScreenState();
}

class _Item {
  _Item(this.icon, this.title, this.why, this.check, this.request);
  final IconData icon;
  final String title;
  final String why;
  final Future<bool> Function() check;
  final Future<void> Function() request;
}

class _PermissionsScreenState extends ConsumerState<PermissionsScreen> with WidgetsBindingObserver {
  final Map<String, bool> _ok = {};
  String _oem = '';

  late final List<_Item> _items = [
    _Item(Icons.my_location, 'Precise location', 'Android only lets apps read Wi-Fi signal strength with precise location. It is used during incidents and drills only.',
        () => Permission.locationWhenInUse.isGranted, () => Permission.locationWhenInUse.request()),
    _Item(Icons.wifi_find, 'Nearby Wi-Fi devices', 'Needed on Android 13+ to scan Wi-Fi routers for indoor positioning.',
        () async => await Permission.nearbyWifiDevices.isGranted || await Permission.nearbyWifiDevices.isRestricted, () => Permission.nearbyWifiDevices.request()),
    _Item(Icons.location_on_outlined, 'Location services ON', 'Wi-Fi scanning returns nothing while the phone\'s Location switch is off.',
        Geolocator.isLocationServiceEnabled, () async => Geolocator.openLocationSettings()),
    _Item(Icons.notifications_active, 'Notifications', 'So the fire alarm can reach you when the app is closed.',
        () => Permission.notification.isGranted, () async => requestNotificationPermissions()),
    _Item(Icons.fullscreen, 'Full-screen alarm', 'Android 14+ asks before an app may show an alarm over the lock screen.',
        NativeBridge.canUseFullScreenIntent, () async {
      await requestFullScreenIntentPermission();
      if (!await NativeBridge.canUseFullScreenIntent()) await NativeBridge.openFullScreenIntentSettings();
    }),
    _Item(Icons.battery_saver, 'Unrestricted battery', 'Battery savers can delay or block alarms.',
        () => Permission.ignoreBatteryOptimizations.isGranted, () => Permission.ignoreBatteryOptimizations.request()),
  ];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _refresh();
    NativeBridge.manufacturer().then((m) => mounted ? setState(() => _oem = m) : null);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _refresh();
  }

  Future<void> _refresh() async {
    for (final i in _items) {
      _ok[i.title] = await i.check();
    }
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final aggressive = ['xiaomi', 'redmi', 'poco', 'oppo', 'realme', 'vivo', 'oneplus', 'huawei', 'honor', 'tecno', 'infinix'].any(_oem.contains);
    final allOk = _items.take(4).every((i) => _ok[i.title] ?? false);
    return Scaffold(
      appBar: AppBar(title: const Text('Set up alarms & positioning')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            for (final i in _items)
              Card(
                child: ListTile(
                  leading: Icon(i.icon),
                  title: Text(i.title),
                  subtitle: Text(i.why),
                  trailing: (_ok[i.title] ?? false)
                      ? const Icon(Icons.check_circle, color: Colors.greenAccent)
                      : FilledButton.tonal(
                          onPressed: () async {
                            await i.request();
                            await _refresh();
                          },
                          child: const Text('Allow'),
                        ),
                  isThreeLine: true,
                ),
              ),
            if (aggressive)
              Card(
                color: Colors.amber.withValues(alpha: 0.15),
                child: ListTile(
                  leading: const Icon(Icons.warning_amber),
                  title: const Text('Your phone may block alarms in the background'),
                  subtitle: Text('On $_oem phones also enable “Autostart” and set Battery to “No restrictions” for this app in Settings → Apps.'),
                  isThreeLine: true,
                  onTap: openAppSettings,
                ),
              ),
            const SizedBox(height: 12),
            FilledButton(
              onPressed: () async {
                await ref.read(storageProvider).setFlag('permissions_done', true);
                if (context.mounted) context.go('/home');
              },
              child: Text(allOk ? 'Done' : 'Continue anyway'),
            ),
          ],
        ),
      ),
    );
  }
}
