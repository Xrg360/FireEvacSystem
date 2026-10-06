# Fire Evacuation: resident app (Android)

This is the Flutter app installed on residents' phones for the **AI-Driven Smart Fire Evacuation System** (IEEE ICSCC 2025). When a fire is detected:
1. it rings a **full-screen alarm**;
2. it works out where you are from Wi-Fi;
3. it guides you along **your own safest route**, re-routing live as the fire spreads or corridors fill up;
4. it lets you report **I'm safe** or **Need help**.

It is part of the [FireEvacSystem monorepo](../README.md) and needs the Flask server in [`../fire-backend`](../fire-backend). Technical details are in [DEEP_DIVE.md §16](../DEEP_DIVE.md#16-mobile-app-architecture).

> ⚠️ **Not a certified life-safety system.** Always follow fire alarms, exit signs and responders.

<table>
  <tr>
    <td align="center"><img src="../docs/screenshots/app-alarm.png" width="180" alt="Full-screen alarm"/><br/><sub>Full-screen alarm</sub></td>
    <td align="center"><img src="../docs/screenshots/app-route.png" width="180" alt="Personal route"/><br/><sub>Personal route</sub></td>
    <td align="center"><img src="../docs/screenshots/app-where-are-you.png" width="180" alt="Where are you"/><br/><sub>"Where are you?"</sub></td>
    <td align="center"><img src="../docs/screenshots/app-home.png" width="180" alt="Home during a fire"/><br/><sub>Home during a fire</sub></td>
  </tr>
  <tr>
    <td align="center"><img src="../docs/screenshots/app-home-normal.png" width="180" alt="Home normal"/><br/><sub>Normal state</sub></td>
    <td align="center"><img src="../docs/screenshots/app-permissions.png" width="180" alt="Permissions"/><br/><sub>Setup wizard</sub></td>
    <td align="center"><img src="../docs/screenshots/app-settings.png" width="180" alt="Settings"/><br/><sub>Settings & privacy</sub></td>
    <td align="center"><img src="../docs/screenshots/app-login.png" width="180" alt="Login"/><br/><sub>Sign in</sub></td>
  </tr>
</table>

---

## Features

| Feature | Where |
|---|---|
| **Join the society** with a code or QR, sign up (block, flat, "I can't use stairs"), wait for admin approval | `lib/features/onboarding/` |
| **Setup wizard**: precise location, nearby Wi-Fi, location services, notifications, full-screen alarm (Android 14+), unrestricted battery. Warns Xiaomi/Realme/Vivo/Oppo owners to allow autostart. | `lib/features/permissions/` |
| **Full-screen alarm** over the lock screen: from FCM push when the app is closed, from the socket when it's open. Vibrates and keeps the screen on. | `lib/services/notifications.dart`, `lib/features/alarm/` |
| **Wi-Fi scanning** (BSSID + RSSI) during an incident, within Android's scan limits, sent to the server's particle filter (paper Alg. 1, eq. 1–5) | `lib/services/scan_service.dart` |
| **Live route**:<ul><li>floor map and the next instruction;</li><li>step list with distances;</li><li>reroute banner that gives the reason (fire, crowding, deviation);</li><li>step-free refuge routing;</li><li>large-text mode.</li></ul> | `lib/features/navigation/evacuate_screen.dart` |
| **Location fallback**:<ol><li>Wi-Fi particle filter;</li><li>**"Where are you?"** picker, pre-selecting the last known room;</li><li>**floor-confirm** prompt;</li><li>GPS, only for "outside / near the assembly point";</li><li>last known position.</li></ol> | `lib/state/evacuation.dart`, `lib/features/navigation/where_are_you.dart` |
| **I'm safe / Need help** (help, trapped, medical, with a note). **Long-press NEED HELP calls 112.** Status and SOS are queued while offline. | `evacuate_screen.dart` |
| **Offline fallback**: after 10 s without the server, the phone routes by itself (cached graph and hazards, Dart A\* = paper Alg. 2, triangulation = Alg. 3) | `lib/shared/offline_routing.dart` |
| **Survey mode** (surveyor/admin): record labelled scans per room, register router positions | `lib/features/survey/` |
| **Developer panel** (building in Simulation mode): tap to place yourself, see raw scans, the fix and the route | `lib/features/dev/` |

**Privacy.** The phone only scans and shares its position **during an incident, a drill or a simulation**. The server wipes it at all-clear and deletes history after a few days.

---

## Build and run

You need Flutter 3.44 or later and the Android SDK (platforms 35–37). The app is Android only.

1. Install dependencies:
   ```bash
   flutter pub get
   ```
2. Run the tests:
   ```bash
   flutter test
   ```
3. Run on a connected phone:
   ```bash
   flutter run --release
   ```
4. Build a release APK, which lands in `build/app/outputs/flutter-apk/app-release.apk`:
   ```bash
   flutter build apk --release
   ```

On first launch, enter the server address: the laptop's LAN IP, e.g. `http://192.168.1.20:5000`. To pre-fill it at build time:

```bash
flutter build apk --release --dart-define=API_URL=http://192.168.1.20:5000
```

Demo accounts come from the backend seed. The password is `Evacuate@123`:
- `resident.b1@example.com`: tower, flat B-302;
- `resident.b2@example.com`: wheelchair user, gets a refuge route;
- `surveyor@example.com`: survey mode.

New residents tap **Join your society** and use code **`MITS2025`**.

### Android emulator

Emulator images are **x86-64**. A universal APK can pick the wrong native library there and crash on launch, so build for the emulator's architecture and point it at the host:

```bash
flutter build apk --release --target-platform android-x64 --dart-define=API_URL=http://10.0.2.2:5000
```

```bash
adb install -r build/app/outputs/flutter-apk/app-release.apk
```

To place the emulator's GPS at the demo tower, so it isn't treated as "outside the building":

```bash
adb emu geo fix 76.412302 9.962028
```

An emulator hears only one virtual Wi-Fi network, so it can't be positioned by Wi-Fi. The app opens **"Where are you?"**; pick a room and you'll get a route.

### Push notifications (optional)

To enable push, put `google-services.json` from your Firebase project into `android/app/` and rebuild. The Google Services Gradle plugin is applied only when that file exists. Without it the app still works, but alarms arrive only while the app is open. **Settings → Test the alarm** shows the full-screen alarm locally.

### Demo phones

- Turn off **Developer options → Wi-Fi scan throttling**. Otherwise Android allows only 4 scans per 2 minutes and positions update slowly.
- Keep Location turned on, and set the app's battery usage to **Unrestricted**.

---

## Project structure

```
lib/
  core/        api (dio + token refresh), socket_service, storage (secure tokens, cache), native bridge, theme
  state/       session.dart (login, device id, approval, FCM), evacuation.dart (incident, fix, route, scans, GPS, offline)
  services/    notifications.dart (FCM + full-screen alarm channel), scan_service.dart (Wi-Fi)
  shared/      graph.dart, models.dart, offline_routing.dart (A*, triangulation, hazards)
  features/    onboarding, permissions, home, alarm, navigation, survey, dev, settings
  widgets/     floor_map.dart (CustomPainter)
android/app/src/main/kotlin/.../MainActivity.kt   keep-screen-on, full-screen-intent check, manufacturer
test/          offline A* parity with the server, positioning, model parsing
```

## Stack

- Flutter 3.44 / Dart 3.12, Android only. Kotlin DSL Gradle, AGP 9, Java 17, core library desugaring, `minSdk` 24, `compileSdk` 36.
- Riverpod 3 (state), go_router (navigation), dio (REST), socket_io_client (realtime; a fresh connection per session).
- `wifi_scan`, `geolocator` (plain LocationManager, so no Google Play dialogs mid-evacuation), `firebase_messaging` + `flutter_local_notifications` (alarm channel, full-screen intent), `mobile_scanner`, `flutter_secure_storage`, `permission_handler` 12.
- `wakelock_plus` and `connectivity_plus` were left out because their Linux `dbus` dependency conflicts with the latest notifications plugin. Keep-screen-on is done natively, and offline detection uses the socket state.

## Tests

`flutter test` runs 16 tests:
- **Parity:** the offline A\* reproduces the server's routes and costs for 10 shared cases, read from `../fire-backend/contracts/fixtures/route_cases.json`.
- Eq. 1 and triangulation.
- Payload parsing.
- Stair-run collapsing.
- Step-free routing.

`flutter analyze` is clean.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "No evacuation server answered" | Same Wi-Fi as the server? Firewall rule for port 5000? Use the LAN IP (emulator: `10.0.2.2`). |
| App crashes immediately on an emulator | Build with `--target-platform android-x64` (see above). |
| "Finding your position…" never resolves | The building's routers aren't mapped or surveyed, or scanning is throttled. Use **Set my location** (pin icon), or survey the building. |
| "GPS shows you are outside the building" indoors | Pick your room in "Where are you?". A manual pick overrides GPS. |
| Alarm doesn't show over the lock screen | Settings → Permissions & alarm setup → **Full-screen alarm**. On Xiaomi/Oppo/Vivo also allow autostart. |
| "Your session expired" | The server's database was reset. Sign in again. |
