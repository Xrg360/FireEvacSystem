import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../state/session.dart';

/// The evacuation server usually runs on a laptop / building server on the local network,
/// so its address is configurable (e.g. http://192.168.1.20:5000).
class ServerScreen extends ConsumerStatefulWidget {
  const ServerScreen({super.key});

  @override
  ConsumerState<ServerScreen> createState() => _ServerScreenState();
}

class _ServerScreenState extends ConsumerState<ServerScreen> {
  late final TextEditingController _url;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    final current = ref.read(storageProvider).serverUrl;
    _url = TextEditingController(text: current.isEmpty ? 'http://192.168.1.10:5000' : current);
  }

  @override
  void dispose() {
    _url.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    final url = _url.text.trim();
    final ok = await Api.ping(url);
    if (!mounted) return;
    if (!ok) {
      setState(() {
        _busy = false;
        _error = 'No evacuation server answered at $url. Check the address and that the phone is on the same Wi-Fi.';
      });
      return;
    }
    await ref.read(sessionProvider.notifier).setServer(url);
    if (mounted) setState(() => _busy = false);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Evacuation server')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(20),
          children: [
            const Icon(Icons.dns_outlined, size: 56, color: Colors.white70),
            const SizedBox(height: 16),
            const Text('Enter the address your society admin gave you.', textAlign: TextAlign.center, style: TextStyle(fontSize: 16)),
            const SizedBox(height: 20),
            TextField(
              controller: _url,
              keyboardType: TextInputType.url,
              autocorrect: false,
              decoration: const InputDecoration(labelText: 'Server address', hintText: 'http://192.168.1.10:5000'),
              onSubmitted: (_) => _save(),
            ),
            if (_error != null) ...[
              const SizedBox(height: 12),
              Text(_error!, style: const TextStyle(color: Colors.redAccent)),
            ],
            const SizedBox(height: 20),
            FilledButton(onPressed: _busy ? null : _save, child: Text(_busy ? 'Checking…' : 'Connect')),
          ],
        ),
      ),
    );
  }
}
