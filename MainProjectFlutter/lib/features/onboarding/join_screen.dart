import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../../core/api.dart';
import '../../state/session.dart';

/// Join flow: society code (typed or scanned from the admin's QR) -> signup form.
class JoinScreen extends ConsumerStatefulWidget {
  const JoinScreen({super.key});

  @override
  ConsumerState<JoinScreen> createState() => _JoinScreenState();
}

class _JoinScreenState extends ConsumerState<JoinScreen> {
  final _code = TextEditingController();
  Map<String, dynamic>? _info;
  bool _busy = false;
  String? _error;
  bool _scanning = false;

  // signup fields
  final _name = TextEditingController();
  final _email = TextEditingController();
  final _phone = TextEditingController();
  final _password = TextEditingController();
  final _flat = TextEditingController();
  final _mobility = TextEditingController();
  int? _buildingId;
  int? _roomId;
  bool _stairsOk = true;

  @override
  void dispose() {
    for (final c in [_code, _name, _email, _phone, _password, _flat, _mobility]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _lookup(String code) async {
    setState(() {
      _busy = true;
      _error = null;
      _scanning = false;
    });
    try {
      final info = await ref.read(apiProvider).get('/join/${Uri.encodeComponent(code.trim().toUpperCase())}');
      setState(() {
        _info = info;
        _code.text = code.trim().toUpperCase();
        final buildings = info['buildings'] as List;
        if (buildings.length == 1) _buildingId = (buildings.first as Map)['id'] as int;
      });
    } on ApiException catch (e) {
      setState(() => _error = e.status == 404 ? 'Unknown join code.' : e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _register() async {
    if (_password.text.length < 8) {
      setState(() => _error = 'Password must be at least 8 characters.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    final err = await ref.read(sessionProvider.notifier).register({
      'join_code': _code.text.trim(),
      'name': _name.text.trim(),
      'email': _email.text.trim(),
      'password': _password.text,
      'phone': _phone.text.trim().isEmpty ? null : _phone.text.trim(),
      'building_id': _buildingId,
      'flat': _flat.text.trim().isEmpty ? null : _flat.text.trim(),
      'home_node_id': _roomId,
      'stairs_ok': _stairsOk,
      'mobility_notes': _mobility.text.trim().isEmpty ? null : _mobility.text.trim(),
    });
    if (!mounted) return;
    setState(() {
      _busy = false;
      _error = err;
    });
    if (err == null && mounted) Navigator.of(context).popUntil((r) => r.isFirst);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(_info == null ? 'Join your society' : (_info!['society'] as Map)['name'] as String)),
      body: SafeArea(child: _info == null ? _codeStep() : _signupStep()),
    );
  }

  Widget _codeStep() {
    if (_scanning) {
      return MobileScanner(
        onDetect: (capture) {
          final raw = capture.barcodes.firstOrNull?.rawValue;
          if (raw == null) return;
          // QR may hold just the code or a URL ending with it
          final code = raw.contains('/') ? raw.split('/').last : raw;
          _lookup(code);
        },
      );
    }
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        const Text('Enter the join code from your society admin, or scan their QR code.'),
        const SizedBox(height: 16),
        TextField(controller: _code, textCapitalization: TextCapitalization.characters, decoration: const InputDecoration(labelText: 'Join code')),
        if (_error != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(_error!, style: const TextStyle(color: Colors.redAccent))),
        const SizedBox(height: 16),
        FilledButton(onPressed: _busy ? null : () => _lookup(_code.text), child: const Text('Continue')),
        const SizedBox(height: 8),
        OutlinedButton.icon(onPressed: () => setState(() => _scanning = true), icon: const Icon(Icons.qr_code_scanner), label: const Text('Scan QR code')),
      ],
    );
  }

  Widget _signupStep() {
    final buildings = (_info!['buildings'] as List).cast<Map<String, dynamic>>();
    final building = buildings.where((b) => b['id'] == _buildingId).firstOrNull;
    final rooms = [
      for (final f in (building?['floors'] as List? ?? const []))
        for (final r in ((f as Map)['rooms'] as List)) (id: (r as Map)['id'] as int, label: '${f['name']} · ${r['name']}'),
    ];
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        TextField(controller: _name, decoration: const InputDecoration(labelText: 'Full name')),
        const SizedBox(height: 10),
        TextField(controller: _email, keyboardType: TextInputType.emailAddress, decoration: const InputDecoration(labelText: 'Email')),
        const SizedBox(height: 10),
        TextField(controller: _phone, keyboardType: TextInputType.phone, decoration: const InputDecoration(labelText: 'Phone (rescuers may call you)')),
        const SizedBox(height: 10),
        TextField(controller: _password, obscureText: true, decoration: const InputDecoration(labelText: 'Password (min 8 characters)')),
        const SizedBox(height: 16),
        DropdownButtonFormField<int>(
          initialValue: _buildingId,
          decoration: const InputDecoration(labelText: 'Block / building'),
          items: [for (final b in buildings) DropdownMenuItem(value: b['id'] as int, child: Text(b['name'] as String))],
          onChanged: (v) => setState(() {
            _buildingId = v;
            _roomId = null;
          }),
        ),
        const SizedBox(height: 10),
        TextField(controller: _flat, decoration: const InputDecoration(labelText: 'Flat number (e.g. B-302)')),
        if (rooms.isNotEmpty) ...[
          const SizedBox(height: 10),
          DropdownButtonFormField<int>(
            initialValue: _roomId,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'Your flat / room on the map (optional)'),
            items: [for (final r in rooms) DropdownMenuItem(value: r.id, child: Text(r.label, overflow: TextOverflow.ellipsis))],
            onChanged: (v) => setState(() => _roomId = v),
          ),
        ],
        const SizedBox(height: 16),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          value: !_stairsOk,
          onChanged: (v) => setState(() => _stairsOk = !v),
          title: const Text('I cannot use stairs'),
          subtitle: const Text('You will be guided to a refuge area and rescuers will be told where you are.'),
        ),
        if (!_stairsOk) TextField(controller: _mobility, decoration: const InputDecoration(labelText: 'Anything rescuers should know (optional)')),
        if (_error != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(_error!, style: const TextStyle(color: Colors.redAccent))),
        const SizedBox(height: 20),
        FilledButton(
          onPressed: _busy ? null : _register,
          child: Text(_busy ? 'Creating account…' : 'Create account'),
        ),
        const SizedBox(height: 8),
        const Text('Your location is only shared during a fire, a drill or a simulation.', style: TextStyle(fontSize: 12, color: Colors.white60)),
      ],
    );
  }
}
