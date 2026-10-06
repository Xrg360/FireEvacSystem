# Fire Evacuation: resident app (Android)

This is the Flutter app for the **AI-Driven Smart Fire Evacuation System** (IEEE ICSCC 2025). It is installed on residents' phones in the housing society. It needs the Flask server in `../fire-backend`.

> **Not a certified life-safety system.** Always follow fire alarms, exit signs and responders.

## What it does

| Feature | Where |
|---|---|
| Join the society with a code or QR, sign up (block, flat, mobility needs), wait for admin approval | `lib/features/onboarding/` |
| Permissions wizard: precise location, nearby Wi-Fi, location services, notifications, full-screen alarm, battery. Warns Xiaomi/Realme/Vivo/Oppo owners to allow autostart | `lib/features/permissions/` |
| **Full-screen alarm** over the lock screen. It comes from FCM push when the app is closed, or from the socket when it is open | `lib/services/notifications.dart`, `lib/features/alarm/` |
| **Wi-Fi scanning** (BSSID + RSSI) during an incident. Readings are sent to the server's particle filter, which implements paper Alg. 1 and eq. 1–5 | `lib/services/scan_service.dart` |
| **Live route**:<ul><li>a map and step-by-step instructions;</li><li>reroute banners that give the reason (fire, crowding);</li><li>step-free refuge routing for residents who can't use stairs;</li><li>a large-text mode.</li></ul> | `lib/features/navigation/evacuate_screen.dart` |
| **Location fallback chain**:<ol><li>the Wi-Fi particle filter;</li><li>GPS, used only for "outside / near the assembly point";</li><li>the **"Where are you?"** picker;</li><li>a **floor-confirm** prompt.</li></ol> | `lib/state/evacuation.dart`, `lib/features/navigation/where_are_you.dart` |
| **I'm safe / Need help (SOS)**. Long-press calls 112. Requests are queued while offline | `evacuate_screen.dart` |
| **Offline fallback.** If the server is unreachable for 10 s, the phone routes by itself: cached graph and hazards, Dart A\* (Alg. 2), and triangulation (Alg. 3). Tests check that these give **exactly** the server's routes | `lib/shared/offline_routing.dart`, `test/offline_routing_test.dart` |
| **Survey mode** (surveyor/admin): record labelled scans per room, register router positions | `lib/features/survey/` |
| **Developer panel** (building in Simulation mode): tap the map to place yourself, see raw scans, the fix and the route | `lib/features/dev/` |

**Privacy.** The phone only scans and shares its position during an incident or drill, or when the building is in simulation mode. The server deletes position history after `POSITION_RETENTION_DAYS`.

## Build and run

```bash
flutter pub get
```

```bash
flutter test
```

`flutter test` includes the parity tests against `../fire-backend/contracts/fixtures`.

```bash
flutter run
```

```bash
flutter build apk --release
```

The release build lands in `build/app/outputs/flutter-apk/app-release.apk`.

On first launch, enter the server address, for example `http://192.168.1.20:5000`, which is the laptop's LAN IP. You can also pre-fill it at build time:

```bash
flutter build apk --release --dart-define=API_URL=http://192.168.1.20:5000
```

The demo accounts come from the backend seed. The password for all of them is `Evacuate@123`:
- `resident.b1@example.com`
- `resident.b2@example.com` (wheelchair user)
- `surveyor@example.com`

### Push notifications (optional)

To enable push, put `google-services.json` from your Firebase project into `android/app/` and rebuild. The build only applies the Google Services plugin when that file exists. Without it the app still works, but alarms only arrive while the app is open.

### Demo phones

- **Developer options → Wi-Fi scan throttling → off.** Android otherwise allows only 4 scans every 2 minutes, and positions update much more slowly.
- Keep Location turned on, and set the app's battery usage to "Unrestricted".

## Stack

- Flutter 3.44 / Dart 3.12, Android only. Kotlin DSL Gradle, AGP 9, Java 17.
- Riverpod 3 (state), go_router (navigation), dio (REST with token refresh), socket_io_client (realtime).
- `wifi_scan`, `geolocator`, `firebase_messaging` + `flutter_local_notifications` (full-screen alarm channel), `mobile_scanner`, `flutter_secure_storage`.
- A small Kotlin bridge in `MainActivity.kt` handles keeping the screen on, the full-screen intent permission (Android 14+) and the device manufacturer.
