import 'dart:async';

import 'package:wifi_scan/wifi_scan.dart';

/// Wi-Fi RSSI collection (paper §III-B input to trilateration / particle filter).
///
/// Android allows a foreground app only 4 active scans per 2 minutes. We request a scan every
/// few seconds (accepted ones go through, throttled ones are refused) and ALSO listen to passive
/// results - scans triggered by the system or other apps - so updates keep coming either way.
/// On demo phones, disabling Developer options > Wi-Fi scan throttling gives a scan every ~3 s.
class ScanService {
  ScanService(this.onReadings);

  final void Function(Map<String, double> readings) onReadings;
  StreamSubscription<List<WiFiAccessPoint>>? _sub;
  Timer? _timer;
  int refusedScans = 0;
  int acceptedScans = 0;
  DateTime? lastResultsAt;
  String? problem;
  bool get running => _sub != null;

  /// Returns null when scanning started, otherwise a user-facing reason.
  Future<String?> start({Duration every = const Duration(seconds: 4)}) async {
    if (running) return null;
    final can = await WiFiScan.instance.canStartScan(askPermissions: true);
    if (can != CanStartScan.yes) {
      problem = _explain(can.name);
      return problem;
    }
    final canGet = await WiFiScan.instance.canGetScannedResults(askPermissions: true);
    if (canGet != CanGetScannedResults.yes) {
      problem = _explain(canGet.name);
      return problem;
    }
    problem = null;
    _sub = WiFiScan.instance.onScannedResultsAvailable.listen(_handle);
    _timer = Timer.periodic(every, (_) => _request());
    unawaited(_request());
    // whatever the system scanned most recently is useful immediately
    _handle(await WiFiScan.instance.getScannedResults());
    return null;
  }

  Future<void> _request() async {
    final ok = await WiFiScan.instance.startScan();
    ok ? acceptedScans++ : refusedScans++;
  }

  void _handle(List<WiFiAccessPoint> results) {
    final readings = <String, double>{};
    for (final ap in results) {
      if (ap.bssid.isEmpty || ap.level >= 0 || ap.level < -100) continue;
      readings[ap.bssid.toLowerCase()] = ap.level.toDouble();
    }
    if (readings.isEmpty) return;
    lastResultsAt = DateTime.now();
    onReadings(readings);
  }

  Future<void> stop() async {
    await _sub?.cancel();
    _sub = null;
    _timer?.cancel();
    _timer = null;
  }

  static String _explain(String code) {
    if (code.contains('Location') && code.contains('Service')) return 'Turn on Location - Android needs it for Wi-Fi scanning.';
    if (code.contains('Permission')) return 'Allow precise location so the app can read Wi-Fi signal strength.';
    if (code == 'notSupported') return 'This device cannot scan Wi-Fi.';
    return 'Wi-Fi scanning unavailable ($code).';
  }
}
