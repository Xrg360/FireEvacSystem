import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme.dart';
import '../../state/session.dart';

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _email = TextEditingController();
  final _password = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _login() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    final err = await ref.read(sessionProvider.notifier).login(_email.text, _password.text);
    if (!mounted) return;
    setState(() {
      _busy = false;
      _error = err;
    });
  }

  @override
  Widget build(BuildContext context) {
    final sessionError = ref.watch(sessionProvider).error;
    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(gradient: emergencyGradient),
        child: SafeArea(
          child: ListView(
            padding: const EdgeInsets.all(24),
            children: [
              const SizedBox(height: 32),
              const Icon(Icons.local_fire_department, size: 72, color: Colors.white),
              const SizedBox(height: 12),
              const Text('Smart Fire Evacuation', textAlign: TextAlign.center, style: TextStyle(fontSize: 26, fontWeight: FontWeight.w800)),
              const SizedBox(height: 6),
              const Text('Your safest way out, in real time.', textAlign: TextAlign.center, style: TextStyle(color: Colors.white70)),
              const SizedBox(height: 32),
              TextField(controller: _email, keyboardType: TextInputType.emailAddress, autofillHints: const [AutofillHints.email], decoration: const InputDecoration(labelText: 'Email')),
              const SizedBox(height: 12),
              TextField(controller: _password, obscureText: true, autofillHints: const [AutofillHints.password], decoration: const InputDecoration(labelText: 'Password'), onSubmitted: (_) => _login()),
              if ((_error ?? sessionError) != null) ...[
                const SizedBox(height: 12),
                Text((_error ?? sessionError)!, style: const TextStyle(color: Colors.amberAccent)),
              ],
              const SizedBox(height: 20),
              FilledButton(onPressed: _busy ? null : _login, child: Text(_busy ? 'Signing in…' : 'Sign in')),
              const SizedBox(height: 12),
              OutlinedButton(onPressed: () => context.push('/join'), child: const Text('New resident? Join your society')),
              TextButton(onPressed: () => context.push('/server'), child: const Text('Change server address')),
              const SizedBox(height: 24),
              const Text(
                'Not a certified life-safety system. Always follow fire alarms, exit signs and responders.',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 11, color: Colors.white54),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
